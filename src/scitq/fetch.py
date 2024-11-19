import botocore.exceptions
from ftplib import FTP
import re
import logging as log
from functools import wraps, cached_property
from time import sleep, time
import shutil
import os
import requests
import glob
import hashlib
import subprocess
from .util import PropagatingThread, if_is_not_None, bytes_to_hex, get_md5, split_list, package_version
import concurrent.futures
import argparse
import datetime
import pytz
import io
from azure.storage.blob import BlobServiceClient, BlobBlock, BlobClient, ContentSettings
import uuid
import azure.core.exceptions
from .constants import DEFAULT_WORKER_CONF, DEFAULT_RCLONE_CONF
import dotenv
from tabulate import tabulate 
from fnmatch import fnmatch
import hashlib
import multiprocessing
import json
import tempfile
from rclone_python import rclone
import sys

# how many time do we retry
RETRY_TIME = 3
RETRY_SLEEP_TIME = 10
MAX_SLEEP_TIME = 900
PUBLIC_RETRY_TIME = 20
MAX_PARALLEL_S3 = 5
MAX_PARALLEL_S3_LIST = 30


# position in FTP dir command
# typical output is: '-rw-rw-r--    1 ftp      ftp       1088322 Jul 15  2019 MGYG-HGUT-00001.faa' 
FTP_DIR_SIZE_POSITION = 4
FTP_DIR_MONTH_POSITION = 5
FTP_DIR_DAY_POSITION = 6
FTP_DIR_YEAR_POSITION = 7
FTP_DIR_NAME_POSITION = 8

HTTP_CHUNK_SIZE = 81920

ARIA2_PROCESSES = 5
SRA_AWS_URL = 'https://sra-pub-run-odp.s3.amazonaws.com/sra/{run_accession}/{run_accession}'

# name of Azure variables
AZURE_ACCOUNT='SCITQ_AZURE_ACCOUNT'
AZURE_KEY='SCITQ_AZURE_KEY'
MAX_PARALLEL_AZURE = 5
MAX_CONCURRENCY_AZURE = 10
AZURE_CHUNK_SIZE = 100*1024**2

ASPERA_DOCKER = 'martinlaurent/ascli:4.14.0'

MAX_PARALLEL_SYNC = 10

class FetchError(Exception):
    pass


class FetchErrorNoRepeat(FetchError):
    pass

class UnsupportedError(FetchErrorNoRepeat):
    pass


def pathjoin(*items):
    """Like os.path.join but always with '/' even with Windows and no double '/'
        in the middle of the path 
        (also no funny things if one of the item start with slash)
        (multiple slashes will be kept if at the begining or the end)"""
    last = len(items) - 1 
    joined_path = '/'.join([ item.rstrip('/') if rank==0 else 
                      item.lstrip('/') if rank==last else 
                      item.strip('/') 
                      for rank,item in enumerate(items)])
    # s3 tend to do funny things with that pattern, let us remove that buggy path
    joined_path = joined_path.replace('/./','/')
    return joined_path

# general
def retry_if_it_fails(n):
    """A decorator to retry n time some action"""
    def decorator(function):
        @wraps(function)
        def wrapper(*args, __retry_number__=None, **kwargs):
            iteration=0
            if __retry_number__ is None:
                __retry_number__ = n
            sleep_time=RETRY_SLEEP_TIME
            while iteration<__retry_number__:
                try:
                    retval = function(*args, **kwargs)
                    break
                except FetchErrorNoRepeat:
                    raise
                except Exception:
                    log.exception('Something went bad')
                    iteration += 1
                    if iteration<__retry_number__:
                        log.warning(f'Waiting some time ({sleep_time}s)...')
                        sleep(sleep_time)
                        if sleep_time < MAX_SLEEP_TIME/2:
                            sleep_time *= 2
                        else:
                            sleep_time = MAX_SLEEP_TIME
                        log.warning('Retrying...')
                    else:
                        log.error('Too many failures, giving up')
                        raise
            return retval
        return wrapper
    return decorator    

def complete_if_ends_with_slash(source, destination):
    """This function checks if destination ends with slash in which case it completes
    with the source last item
    """
    if destination.endswith('/'):
        destination += source.split('/')[-1]
    return destination

# actions 

def gunzip(filepath):
    """Stupid gunzipper with gzip"""
    subprocess.run(['pigz','-d',filepath], check=True)
    
def untar(filepath):
    """Untar the tar archive locally where it is and delete the archive.
    (so it behaves like gunzip, and not like tar usually)"""
    path, basename = os.path.split(filepath)
    if basename.endswith('gz'):
        subprocess.run(f'pigz -dc "{basename}"|tar x', cwd=path, shell=True, check=True)
    else:
        subprocess.run(['tar','xf',basename], cwd=path, check=True)
    os.remove(filepath)

def unzip(filepath):
    """Stupid unzipper with unzip (and delete the archive like gunzip does), 
    unzip in place like gunzip does, not the default behaviour of unzip"""
    path,_ = os.path.split(filepath)
    subprocess.run(['unzip',filepath] + ['-d',path] if path else [], check=True)
    os.remove(filepath)

def older_python_fromisoformat(d):
    """This is a script to add minimal support to Z date (eg ISO 8601 strings) that were not supported before 3.11"""
    if '.' in d:
        d,ext=d.split('.')
        if ext.endswith('Z'):
            d+='+00:00'
        elif '+' in ext:
            tz=ext.split('+')[1]
            d=f"{d}+{tz}"
    if d.endswith('Z'):
        d=d.split('.')[0]+'+00:00'
    
    return datetime.datetime.fromisoformat(d)

RCLONE_REGEXP=re.compile(r'^(?P<remote>[^:]*)://(?P<path>.*)$')

class RcloneClient:
    """A small wrapper above rclone client to integrate with scitq"""
    def __init__(self):
        """Just check that rclone is there"""
        os.environ['RCLONE_CONFIG']=DEFAULT_RCLONE_CONF
        self.is_installed=rclone.is_installed()
        if self.is_installed:
            self.remotes=[remote[:-1] for remote in rclone.get_remotes()]
        else:
            self.remotes=[]
        if sys.version_info[:2]>=(3,11):
            self._date = datetime.datetime.fromisoformat
        else:
            self._date = older_python_fromisoformat


    def _uri(self, uri):
        if '://' not in uri:
            # likely a local path
            return uri
        m=RCLONE_REGEXP.match(uri)
        if not m:
            raise FetchErrorNoRepeat(f'{uri} is not adapted to rclone')
        m=m.groupdict()
        if m['remote']=='file':
            return m['path']
        else:
            return f'{m["remote"]}:{m["path"]}'

    def list(self, uri, no_rec=False, md5=False):
        if not self.is_installed:
            raise FetchErrorNoRepeat('rclone is not installed')
        _uri=self._uri(uri)
        args=[]
        if not no_rec:
            args.extend(['-R','--fast-list'])
        if md5:
            args.append('--hash-type MD5')
        _list=rclone.ls(_uri, args=args,)  
        only_one_item=len(_list)==1
        
        answer=[]
        for item in _list:
            rel_name = item['Path']
            if item['IsDir']:
                rel_name+='/'
            name=os.path.join(uri, rel_name)

            if not item['IsDir'] and only_one_item:
                _,local_name=os.path.split(_uri)
                if item['Name']==local_name:
                    # this is an indecision case, impossible to know if it 
                    # is uri://a/a or uri://a
                    original_item=rclone.ls(_uri,args=['--stat'])
                    if not original_item['IsDir']:
                        name=uri
                
            xdate=self._date(item["ModTime"])
            answer.append(argparse.Namespace(name=name,
                                rel_name=rel_name,
                                size=0 if item["IsDir"] else item["Size"],
                                creation_date=xdate,
                                modification_date=xdate,
                                md5=item.get("Hashes",{}).get('md5',None)))

        return answer

    @retry_if_it_fails(RETRY_TIME)
    def info(self,uri,md5=False):
        if not self.is_installed:
            raise FetchErrorNoRepeat('rclone is not installed')
        try:
            args=['--stat']
            if md5:
                args.append('--hash-type MD5')
            item=rclone.ls(self._uri(uri),args=args)            
            xdate=self._date(item["ModTime"])

            return argparse.Namespace(size=0 if item["IsDir"] else item["Size"],
                                creation_date=xdate,
                                modification_date=xdate,
                                md5=item.get("Hashes",{}).get('md5',None),
                                type='dir' if item["IsDir"] else 'file')
        except Exception as e:
            raise FetchErrorNoRepeat(*e.args)
    
    @retry_if_it_fails(RETRY_TIME)
    def copy(self, source, destination, show_progress=False, args=[]):
        if not self.is_installed:
            raise FetchErrorNoRepeat('rclone is not installed')
        destination=self._uri(destination)
        source=self._uri(source)
        if destination.endswith('/'):
            rclone.copy(source, destination, show_progress=show_progress, args=args)
        else:
            rclone.copyto(source, destination, show_progress=show_progress, args=args)


    def delete(self, uri):
        _uri=self._uri(uri)
        rclone.delete(_uri)

    def has_source(self, source):
        return source in self.remotes
    
    def ncdu(self, uri):
        _uri=self._uri(uri)
        os.system(f'rclone ncdu {_uri}')

    def sync(self, source, destination, show_progress=False, args=[]):
        """Small wrapper above rclone.sync"""
        if not self.is_installed:
            raise FetchErrorNoRepeat('rclone is not installed')
        destination=self._uri(destination)
        source=self._uri(source)
        rclone.sync(source, destination, show_progress=show_progress, args=args)

# work as a singleton
rclone_client = RcloneClient()

# FTP


FTP_REGEXP=re.compile(r'^ftp://(?P<host>[^/]*)/(?P<path>.*)$')

@retry_if_it_fails(RETRY_TIME)
def ftp_get(source, destination):
    """FTP downloader: download source expressed as ftp://host/path_to_file 
    to destination - a local file path"""
    log.info(f'FTP downloading {source} to {destination}')
    if source.endswith('/'):
        raise FetchError('Directory fetching is not yet supported for ftp:// URI')
    destination=complete_if_ends_with_slash(source, destination)
    uri_match = FTP_REGEXP.match(source)
    if not uri_match:
        message=f'Source does not seem a proper FTP URL: {source}'
        log.error(message)
        raise FetchError(message)
    uri_match = uri_match.groupdict()
    with open(destination, 'wb') as local_file:
        with FTP(uri_match['host']) as ftp:
            ftp.login()
            ftp.retrbinary(f"RETR {uri_match['path']}", local_file.write)

@retry_if_it_fails(RETRY_TIME)
def ftp_put(source, destination):
    """FTP uploader: upload source expressed as a local file path 
    to destination expressed as a FTP URL: ftp://host/path_to_file """
    log.info(f'FTP uploading {source} to {destination}')
    destination=complete_if_ends_with_slash(source, destination)
    uri_match = FTP_REGEXP.match(destination).groupdict()
    with open(destination, 'rb') as local_file:
        with FTP(uri_match['host']) as ftp:
            ftp.login()
            ftp.storbinary(f"STOR {uri_match['path']}", local_file.read)

@retry_if_it_fails(RETRY_TIME)
def ftp_info(uri, md5=False):
    """FTP info: get some information on a FTP object"""
    log.info(f'FTP get info for {uri}')
    uri_match = FTP_REGEXP.match(uri).groupdict()
    with FTP(uri_match['host']) as ftp:
        ftp.login()

        with io.StringIO() as output:
            ftp.dir('-a',uri_match['path'],output.write)
            output.seek(0)
            answer = output.readline()
        
        if answer:
            obj = answer.split()
            try:
                obj_date = datetime.datetime.strptime(
                    ' '.join( (obj[FTP_DIR_MONTH_POSITION],
                            obj[FTP_DIR_DAY_POSITION],
                            obj[FTP_DIR_YEAR_POSITION])
                        ),
                    '%b %d %Y').replace(tzinfo=pytz.utc)
            except ValueError:
                try:
                    obj_date = datetime.datetime.strptime(
                        ' '.join( (obj[FTP_DIR_MONTH_POSITION],
                                obj[FTP_DIR_DAY_POSITION],
                                str(datetime.datetime.now().year))
                            ),
                        '%b %d %Y').replace(tzinfo=pytz.utc)
                except ValueError:
                    obj_date = None
            if obj[FTP_DIR_NAME_POSITION]=='.':
                obj_type='dir'
            elif obj[FTP_DIR_NAME_POSITION]==uri_match['path'].split('/')[-1]:
                obj_type='file'
            else:
                obj_type='unknown'
            return argparse.Namespace(size=obj[FTP_DIR_SIZE_POSITION],
                                    creation_date=obj_date, 
                                    modification_date=obj_date,
                                    md5=None,
                                    type=obj_type)
        else:
            raise FetchErrorNoRepeat(f'{uri} was not found')

def ftp_list(uri, no_rec=False):
    """list recursively the content of a FTP folder
    not recursively if no_rec is True"""
    log.info(f'FTP get info for {uri}')
    uri_match = FTP_REGEXP.match(uri).groupdict()
    answer = []
    with FTP(uri_match['host']) as ftp:
        ftp.login()

        with io.StringIO() as output:
            listing = []
            ftp.dir(uri_match['path'],listing.append)
        
        for item in listing:
            obj = item.split()
            is_dir=item[0]=='d'
            if is_dir:
                if no_rec:
                    try:
                        obj_date = datetime.datetime.strptime(
                            ' '.join( (obj[FTP_DIR_MONTH_POSITION],
                                    obj[FTP_DIR_DAY_POSITION],
                                    obj[FTP_DIR_YEAR_POSITION])
                                ),
                            '%b %d %Y').replace(tzinfo=pytz.utc)
                    except ValueError:
                        try:
                            obj_date = datetime.datetime.strptime(
                                ' '.join( (obj[FTP_DIR_MONTH_POSITION],
                                        obj[FTP_DIR_DAY_POSITION],
                                        str(datetime.datetime.now().year))
                                    ),
                                '%b %d %Y').replace(tzinfo=pytz.utc)
                        except ValueError:
                            obj_date = None
                    answer.append(argparse.Namespace(
                        name=f"ftp://{uri_match['host']}/{os.path.join(uri_match['path'],obj[FTP_DIR_NAME_POSITION]+'/')}",
                        rel_name=obj[FTP_DIR_NAME_POSITION]+'/',
                        size=0,
                        creation_date = obj_date,
                        modification_date=obj_date
                    ))
                else:
                    dir_name = obj[FTP_DIR_NAME_POSITION]
                    for item in ftp_list(os.path.join(uri, dir_name)):
                        item.rel_name = f"{dir_name}/{item.rel_name}"
                        answer.append(item)
            else:
                obj_date = datetime.datetime.strptime(
                    ' '.join( (obj[FTP_DIR_MONTH_POSITION],
                            obj[FTP_DIR_DAY_POSITION],
                            obj[FTP_DIR_YEAR_POSITION])
                        ),
                    '%b %d %Y').replace(tzinfo=pytz.utc)
                answer.append(argparse.Namespace(
                    name=f"ftp://{uri_match['host']}/{os.path.join(uri_match['path'],obj[FTP_DIR_NAME_POSITION])}",
                    rel_name=obj[FTP_DIR_NAME_POSITION],
                    size=obj[FTP_DIR_SIZE_POSITION],
                    creation_date=obj_date, 
                    modification_date=obj_date))

    return answer

@cached_property
def docker_available():
    """A property to see if docker is there"""
    return subprocess.run(['docker', '-v'],check=False).returncode==0


# aria2c

@retry_if_it_fails(RETRY_TIME)
def aria2_get(source, destination, processes=ARIA2_PROCESSES):
    """FTP downloader: download source expressed as ftp://host/path_to_file 
    to destination - a local file path"""
    log.info(f'Aria downloading {source} to {destination}')
    if source.endswith('/'):
        raise FetchError('Directory fetching is not yet supported for ftp:// URI')
    destination=complete_if_ends_with_slash(source, destination)
    destination_folder,destination_file = os.path.split(destination)
    subprocess.run(['aria2c','-x',str(processes),'-s',str(processes),source,'-o',destination_file]
                   + ['-d', destination_folder] if destination_folder else [],
                    check=True)

# aspera

ASPERA_REGEXP=re.compile(r'^fasp://(?P<username>.*)@(?P<server>.*):/?(?P<url>.*)$')

@retry_if_it_fails(RETRY_TIME)
def fasp_get(source, destination):
    """Aspera downloader: download source expressed as fasp://user@host/path_to_file
    (NB usually with ENA, user is era-fasp) 
    to destination - a local file path"""
    log.info(f'Aspera downloading {source} to {destination}')
    if not docker_available:
        raise FetchError('Cannot use fasp (aspera) without docker')

    if source.endswith('/'):
        raise FetchError('Directory fetching is not yet supported for fasp:// URI (aspera)')

    # we need destination to be expressed as a directory:
    # (but we remember that the target filename may be different from the source
    # filename)
    if destination.endswith('/'):
        target_filename = None
    else:
        destination, target_filename = os.path.split(destination)
    
    uri_match = ASPERA_REGEXP.match(source).groupdict()
    subprocess.run(f'''docker run --rm -v {destination}:/output \
        {ASPERA_DOCKER} --url=ssh://{uri_match["server"]}:33001 --username={uri_match["username"]} \
        --ssh-keys=@ruby:Fasp::Installation.instance.bypass_keys.first --ts=@json:'{{"target_rate_kbps":300000}}' \
        server download {uri_match["url"]} --to-folder=/output/''', shell=True, check=True)
    
    # if the target filename is really different 
    if target_filename is not None:
        source_filename = uri_match['url'].split('/')[-1]
        if source_filename!=target_filename:
            shutil.move(os.path.join(destination, source_filename),
                os.path.join(destination,target_filename))

# run accessions containing fastq


FASTQ_RUN_REGEXP=re.compile(r'^run\+fastq://(?P<run_accession>[^/]*)/?$')
FASTQ_PARITY = re.compile(r'.*(1|2)\.f.*q(\.gz)?$')

@retry_if_it_fails(RETRY_TIME)
def fastq_sra_get(run_accession, destination, filter_r1=False):
    """This subfunction of runacc_get is only called when EBI's ENA won't
    answer as NCBI's SRA while more complete is quite slow"""
    log.info(f'SRA get run+fastq://{run_accession} to {destination}')
    if not docker_available:
        raise FetchError('Cannot use SRA toolkit without docker')
    if not destination.endswith('/'):
            destination+='/'
    previous_fastq = glob.glob(os.path.join(destination, '*.fastq'))
    try:
        aria2 = True
        aria2_get(SRA_AWS_URL.format(run_accession=run_accession), os.path.join(destination,run_accession+'.sra'))
        log.warning('aria download ok')
        subprocess.run(f"docker run --rm -v {destination}:/destination ncbi/sra-tools \
            sh -c 'cd /destination && vdb-validate {run_accession}.sra && fasterq-dump -f -F --split-files {run_accession}.sra'",
            shell=True,
            check=True)
    except:
        aria2 = False
        log.warning(f'aria2 download of {run_accession} failed, trying with prefetch')
        subprocess.run(f'docker run --rm -v {destination}:/destination ncbi/sra-tools \
            sh -c "cd /destination && prefetch {run_accession} && fasterq-dump -f --split-files {run_accession}"',
            shell=True,
            check=True)
    current_fastq = glob.glob(os.path.join(destination, '*.fastq'))
    fastqs = [fastq for fastq in current_fastq if fastq not in previous_fastq]
    if filter_r1:
        unfiltered_fastqs = fastqs
        fastqs = []
        for fastq in unfiltered_fastqs:
            if fastq.endswith('1.fastq'):
                fastqs.append(fastq)
            else:
                log.info(f'Removing read as it is not r1: {fastq}')
                os.remove(fastq)
    log.info(f'Pigziping fastqs ({fastqs})')
    subprocess.run(['pigz','-f']+fastqs,
        check=True)
    if aria2:
        os.remove(os.path.join(destination, run_accession+'.sra'))
    elif os.path.isdir(os.path.join(destination, run_accession)):
        shutil.rmtree(os.path.join(destination, run_accession))
    

def _my_fastq_download(method, url, md5, destination):
    """A small adhoc function to download and check a fastq through a ftp_url plus a md5"""
    filename = url.split('/')[-1]
    if method in ['fastq_ftp','submitted_ftp']:
        ftp_get('ftp://'+url, destination, __retry_number__=1)
    elif method in ['fastq_aspera','submitted_aspera']:
        fasp_get(f'fasp://era-fasp@{url}', destination, __retry_number__=1)
    else:
        raise FetchError(f'No such method: {method}')
    with open(os.path.join(destination,filename),"rb") as f:
        readable_hash = hashlib.md5(f.read()).hexdigest()
        if readable_hash!=md5:
            raise FetchError(f'{filename} md5: {readable_hash} does not match ENA md5 {md5}')


@retry_if_it_fails(PUBLIC_RETRY_TIME)
def fastq_run_get(source, destination, methods=['fastq_aspera', 'fastq_ftp', 'sra'],filter_r1=False):
    """Fetch some fastq associated to a run accession"""
    log.info(f'Run accession: uploading {source} to {destination}')
    if not destination.endswith('/'):
            destination+='/'
    uri_match = FASTQ_RUN_REGEXP.match(source).groupdict()
    query_try = RETRY_TIME+1
    while query_try>0:
        while query_try>0:
            try:
                run_query = requests.get(f"https://www.ebi.ac.uk/ena/portal/api/filereport?\
accession={uri_match['run_accession']}&result=read_run&fields=fastq_md5,fastq_aspera,\
fastq_ftp,sra_md5,sra_ftp&format=json&download=true&limit=0", timeout=30)
            except requests.Timeout:
                query_try -= 1
                continue
            break
        else:
            log.exception('EBI does not answer our query')
            return fastq_sra_get(uri_match['run_accession'], destination, filter_r1=filter_r1)
        if run_query.status_code==204:
            log.exception('This does not seem to be available on EBI')
            return fastq_sra_get(uri_match['run_accession'], destination, filter_r1=filter_r1)
        runs = run_query.json()
        if len(runs)==0:
            # it seems the new API of EBI tends to answer empty responses
            # hoping this will change in near future
            query_try -= 1
            continue
        else:
            run=runs[0]
            break
    else:
        log.exception('EBI does not answer our query')
        return fastq_sra_get(uri_match['run_accession'], destination, filter_r1=filter_r1)
        



    if 'fastq_ftp' or 'fastq_aspera' in run:
        ftp_md5s = run['fastq_md5'].split(';')

        for method in methods:
            if method in ['fastq_aspera','sra'] and not docker_available:
                log.exception(f'Cannot use {method} as docker is not available.')
                continue
            if method == 'sra':
                return fastq_sra_get(uri_match['run_accession'], destination, filter_r1=filter_r1, 
                    __retry_number__=1)
            elif method in run:
                urls =  run[method].split(';')
                # preparing to download and check all fastqs
                download_threads = []
                for url,md5 in zip(urls, ftp_md5s):
                    if filter_r1:
                        m=FASTQ_PARITY.match(url)
                        if m and m.groups()[0]!='1':
                            continue
                    download_thread=PropagatingThread(target=_my_fastq_download,
                                        args=(method, url, md5, destination))
                    download_thread.start()
                    download_threads.append(download_thread)

                # waiting for all FTP to complete
                try:
                    for download_thread in download_threads:
                        download_thread.join()
                    log.info(f'Download method {method} succeeded')
                    return None
                except:
                    log.exception(f'EBI failed with method {method}')
                    continue
        raise FetchError(f'Could not fetch {source}')
    else:
        log.exception('EBI response does not include a fastq_ftp field')
        return fastq_sra_get(uri_match['run_accession'], destination, filter_r1=filter_r1)


SUBMITTED_RUN_REGEXP=re.compile(r'^run\+submitted://(?P<run_accession>[^/]*)/?$')

@retry_if_it_fails(PUBLIC_RETRY_TIME)
def submitted_run_get(source, destination, methods=['submitted_aspera', 'submitted_ftp']):
    """Fetch some fastq associated to a run accession"""
    log.info(f'Run accession: uploading {source} to {destination}')
    if not destination.endswith('/'):
            destination+='/'
    uri_match = SUBMITTED_RUN_REGEXP.match(source).groupdict()
    query_try = RETRY_TIME+1
    while query_try>0:
        try:
            run_query = requests.get(f"https://www.ebi.ac.uk/ena/portal/api/filereport?\
accession={uri_match['run_accession']}&result=read_run&fields=submitted_md5,submitted_aspera,\
submitted_ftp&format=json&download=true&limit=0", timeout=30)
        except requests.Timeout:
            query_try -= 1
            continue
        break
    else:
        raise FetchError('EBI does not answer our query')
    if run_query.status_code==204:
        raise FetchError('This does not seem to be available on EBI')
    run = run_query.json()[0]



    if 'submitted_ftp' or 'submitted_aspera' in run:
        ftp_md5s = run['submitted_md5'].split(';')

        for method in methods:
            if method in run:
                if method in ['submitted_aspera'] and not docker_available:
                    continue
                urls =  run[method].split(';')

                # preparing to download and check all fastqs
                download_threads = []
                for url,md5 in zip(urls, ftp_md5s):
                    download_thread=PropagatingThread(target=_my_fastq_download,
                                        args=(method, url, md5, destination))
                    download_thread.start()
                    download_threads.append(download_thread)

                # waiting for all FTP to complete
                try:
                    for download_thread in download_threads:
                        download_thread.join()
                    return None
                except:
                    log.exception(f'EBI failed with method {method}')
                    continue
        raise FetchError(f'Could not fetch {source}')
    else:
        raise FetchError(f'Could not fetch {source}')


# plain file

FILE_REGEXP=re.compile(r'^file://(?P<path>.*)$')

def file_get(source, destination):
    """A plain local copy from a file://... source to a local path
    really just some plain syntaxic sugar above shutil.copyfile"""
    log.info(f'FILE downloading {source} to {destination}')
    if source.endswith('/'):
        raise FetchError('Directory fetching is not yet supported for file:// URI')
    destination=complete_if_ends_with_slash(source, destination)
    uri_match = FILE_REGEXP.match(source).groupdict()
    shutil.copyfile(uri_match['path'], destination)

def file_put(source, destination):
    """Same as above except that source is this time a plain local path
    and destination is in the form file://... As above just some plain
    syntaxic sugar above shutil.copyfile """
    log.info(f'FILE uploading {source} to {destination}')
    destination=complete_if_ends_with_slash(source, destination)
    uri_match = FILE_REGEXP.match(destination).groupdict()
    if uri_match:
        complete_path = uri_match['path']
        path=os.path.dirname(complete_path)
        if not os.path.exists(path):
            os.makedirs(path, exist_ok=True)
        shutil.copyfile(source, complete_path)
    else:
        raise FetchError(f"Local URL did not match file://<path> pattern {destination}")

@retry_if_it_fails(RETRY_TIME)
def file_info(uri, md5=False):
    """Same as above except that source is this time a plain local path
    and destination is in the form file://... As above just some plain
    syntaxic sugar above shutil.copyfile """
    log.info(f'FILE getting info for {uri}')
    uri_match = FILE_REGEXP.match(uri).groupdict()
    if uri_match:
        complete_path = uri_match['path']
        stat = os.stat(complete_path)
        if os.path.isfile(complete_path):
            type='file'
        elif os.path.isdir(complete_path):
            type='dir'
        elif os.path.islink(complete_path):
            type='link'
        else:
            type='unknown'
        return argparse.Namespace(size=stat.st_size, 
                                  creation_date=datetime.datetime.utcfromtimestamp(stat.st_ctime).replace(tzinfo=pytz.utc),
                                  modification_date=datetime.datetime.utcfromtimestamp(stat.st_mtime).replace(tzinfo=pytz.utc),
                                  md5=get_md5(complete_path) if type=='file' and md5 else None,
                                  type=type)
    else:
        raise FetchError(f"Local URL did not match file://<path> pattern {uri}")


def file_list(uri, no_rec=False):
    """List recursively the content of a local folder expressed as file://... 
    Not recursively if no_rec is True"""
    log.info(f'FILE getting info for {uri}')
    uri_match = FILE_REGEXP.match(uri).groupdict()
    if uri_match:
        answer = []
        complete_path = uri_match['path']
        if no_rec:
            for file in os.listdir(complete_path):
                complete_file = os.path.join(complete_path,file)
                if os.path.isdir(complete_file):
                    file+='/'
                    complete_file+='/'
                stat = os.stat(complete_file)
                answer.append(argparse.Namespace(name=f'file://{complete_file}',
                                rel_name=file,
                                size=stat.st_size, 
                                creation_date=datetime.datetime.utcfromtimestamp(stat.st_ctime).replace(tzinfo=pytz.utc),
                                modification_date=datetime.datetime.utcfromtimestamp(stat.st_mtime).replace(tzinfo=pytz.utc)))
        else:
            for dir_path,_,files in os.walk(complete_path):
                for file in files:
                    complete_file = os.path.join(dir_path,file)
                    stat = os.stat(complete_file)
                    answer.append(argparse.Namespace(name=f'file://{complete_file}',
                                    rel_name=os.path.relpath(complete_file,complete_path),
                                    size=stat.st_size, 
                                    creation_date=datetime.datetime.utcfromtimestamp(stat.st_ctime).replace(tzinfo=pytz.utc),
                                    modification_date=datetime.datetime.utcfromtimestamp(stat.st_mtime).replace(tzinfo=pytz.utc)))
        return answer
    else:
        raise FetchError(f"Local URL did not match file://<path> pattern {uri}")

def file_delete(uri):
    """Delete a local file expressed as file://... """
    log.info(f'FILE deliting {uri}')
    uri_match = FILE_REGEXP.match(uri).groupdict()
    if uri_match:
        if os.path.exists(uri_match['path']):
            os.remove(uri_match['path'])
        else:
            raise FetchError(f"Local file {uri} does not seem to exist")
    else:
        raise FetchError(f"Local URL did not match file://<path> pattern {uri}")

@retry_if_it_fails(PUBLIC_RETRY_TIME)
def http_get(url, destination):
    """HTTP downloader: download source expressed as http(s)://host/path_to_file 
    to destination - a local file path"""
    destination=complete_if_ends_with_slash(url, destination)
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        with open(destination, 'wb') as f:
            for chunk in r.iter_content(chunk_size=HTTP_CHUNK_SIZE): 
                # If you have chunk encoded response uncomment if
                # and set chunk_size parameter to None.
                #if chunk: 
                f.write(chunk)



# generic wrapper

GENERIC_REGEXP=re.compile(r'^(?P<proto>[a-z0-9+]*)(@(?P<option>[a-z0-9_@]+))?://(?P<resource>[^|]*)(\|(?P<action>.*))?$')

def get(uri, destination, parallel=None, show_progress=False):
    """General downloader source should start with s3://... or ftp://...
    (source should not end with slash unless you know what you are doing if 
    destination ends with slash it will be completed with source end item)
    file://... is also supported but be careful that it is local to worker.
    """
    m = GENERIC_REGEXP.match(uri)
    if m:
        m = m.groupdict()
        
        if m['action'] and m['action'].startswith('mv '):
            destination=os.path.join(destination, m['action'][3:])
        
        source = f"{m['proto']}://{m['resource']}"
        if os.path.isdir(destination) and not destination.endswith('/'):
            log.warning(f'Destination {destination} is a folder, changing for {destination}/')
            destination+='/'
        complete_destination = complete_if_ends_with_slash(source, destination)
        if uri.endswith('/'):
            if complete_destination.endswith('/'):
                complete_destination=complete_destination[:-1]
            complete_destination_folder=complete_destination            
        else:
            complete_destination_folder = '/'.join(complete_destination.split('/')[:-1])
        if not os.path.exists(complete_destination_folder):
            os.makedirs(complete_destination_folder, exist_ok=True)

        if m['option']:
            options=m['option'].split('@')
        else:
            options=[]
        
        if 'aria2' in options:
            aria2_get(source, complete_destination)

        elif m['proto']=='ftp':
            ftp_get(source, destination)
        elif m['proto']=='file':
            file_get(source, destination) 
        elif m['proto']=='fasp':
            fasp_get(source, destination)
        elif m['proto']=='run+fastq':
            filter_r1 = 'filter_r1' in options
            if 'sra' in options or 'aspera' in options or 'ftp' in options:
                methods=[]
                for option in options:
                    if option in ['sra','aspera','ftp']:
                        methods.append(option)
                    elif option!='filter_r1':
                        log.warning(f'Unsupported option {option} in URI {uri}')
                fastq_run_get(source, destination, methods=methods, filter_r1=filter_r1)
            else:
                fastq_run_get(source, destination, filter_r1=filter_r1)       
        elif m['proto']=='run+submitted':
            if 'aspera' in options or 'ftp' in options:
                methods=[]
                for option in options:
                    if option in ['aspera','ftp']:
                        methods.append(f'submitted_{option}')
                    else:
                        log.warning(f'Unsupported option {option} in URI {uri}')
                submitted_run_get(source, destination, methods=methods)
            else:
                submitted_run_get(source, destination)    
        elif m['proto'] in ['http','https']:
            http_get(source, destination)
        else:
            if rclone_client.has_source(m['proto']):
                rclone_client.copy(source, destination, show_progress=show_progress)
            else:
                raise FetchError(f"This URI protocol is not supported: {m['proto']}")        
        if m['action'] and m['action'].startswith('mv '):
            pass
        elif m['action']=='gunzip':
            gunzip(complete_destination)
        elif m['action']=='untar':
            untar(complete_destination)
        elif m['action']=='unzip':
            unzip(complete_destination)
        elif m['action'] not in ['',None]:
            raise FetchError(f"Unsupported action: {m['action']}")
    else:
        raise FetchError(f'This URI is malformed: {uri}')

def put(source, uri, parallel=None, show_progress=False):
    """General uploader destination should start with s3://.... or ftp://...
    (only anonymous ftp is implemented so put is unlikely to work with ftp)
    (source should not end with slash unless you know what you are doing if 
    destination ends with slash it will be completed with source end item)
    file://... is also supported but be careful that it is local to worker."""
    m = GENERIC_REGEXP.match(uri)
    if source.endswith('/'):
        raise FetchError('Recursive put is not yet supported, invalid source: '+source)
    if m:
        m = m.groupdict()
        if m['action']:
            raise FetchError(f'Action are unsupported when putting in {uri}')
        destination = f"{m['proto']}://{m['resource']}"
        destination = complete_if_ends_with_slash(source, destination)
        #if m['proto']=='s3':
        #    s3_put(source, destination)
        #elif m['proto']=='azure':
        #    AzureClient().put(source, destination) 
        if m['proto']=='ftp':
            ftp_put(source, destination)
        elif m['proto']=='file':
            file_put(source, destination)        
        else:
            if rclone_client.has_source(m['proto']):
                rclone_client.copy(source, destination, show_progress=show_progress)
            else:
                raise FetchError(f"This URI proto is not supported: {m['proto']}")
    else:
        raise FetchError(f'This URI is malformed: {uri}')


def delete(uri):
    """General deleter for a URI."""
    m = GENERIC_REGEXP.match(uri)
    if m:
        m = m.groupdict()
        if m['action']:
            raise FetchError(f'Action are unsupported when deleting a {uri}')
        if m['proto']=='file':
            file_delete(uri)       
        else:
            if rclone_client.has_source(m['proto']):
                rclone_client.delete(uri)
            else:
                raise FetchErrorNoRepeat(f"This URI proto is not supported: {m['proto']}")
    else:
        raise FetchErrorNoRepeat(f'This URI is malformed: {uri}')


def check_uri(uri):
    """A small utility to check URI: return True if URI is valid, raise an exception otherwise"""
    m = GENERIC_REGEXP.match(uri)
    if m:
        m = m.groupdict()
        proto = m['proto']
        if '@' in proto:
            proto=proto.split('@')[0]
        if proto not in ['ftp','file','run+fastq','run+submitted','http','https'] and not rclone_client.has_source(proto):
            if proto not in ['ftp','file','run+fastq','run+submitted','http','https']:
                if not rclone_client.is_installed:
                    raise UnsupportedError(f"{m['proto']} is not a base protocol and rclone is not installed")
            raise UnsupportedError(f"Unsupported protocol {m['proto']} in URI {uri}")
    else:
        raise FetchErrorNoRepeat(f"Malformed URI : {uri}")
    return proto

def get_file_uri(uri):
    """A small utility to check if this is a file URI (starts with file://... or is a path)
    returns a path or None (if not a file URI)"""
    if uri.startswith('file://'):
        return uri[7:]
    elif ':' not in uri:
        return uri
    else:
        return None

def info(uri, md5=False):
    """Return an info object from a URI, which should contains at least creation_date, modification_date and size
    WARNING: with s3 or ftp URI, creation_date and modification_date are the same."""
    m = GENERIC_REGEXP.match(uri)
    if m:
        m = m.groupdict()
        source = f"{m['proto']}://{m['resource']}"
        proto = m['proto']
        if '@' in proto:
            # get rid of protocol options like @aria2
            proto = proto.split('@')[0]
        #if proto=='s3':
        #    return s3_info(source, md5=md5)
        #elif proto=='azure':
        #    return AzureClient().info(source, md5=md5) 
        if proto=='ftp':
            return ftp_info(source,md5=md5)
        elif proto=='file':
            return file_info(source, md5=md5) 
        #elif m['proto']=='fasp':
        #    fasp_get(source, destination)
        #elif m['proto']=='run+fastq':
        #    fastq_run_get(source, destination)       
        else:
            if rclone_client.has_source(proto):
                return rclone_client.info(source, md5=md5)
            else:
                raise UnsupportedError(f"This URI protocol is not supported: {m['proto']}")

def list_content(uri, no_rec=False, md5=False):
    """Return the recursive listing of folder specified as a URI
    each item of the list should contains at least name (complete URI), rel_name (the name of the object relative to the provided uri), creation_date, modification_date and size
    if no_rec is True, then the listing is non recursive -> MEANS SOME "FOLDERS" WILL APPEAR IN LISTING, eventually with None attribute (in dates)
    WARNING: with s3 or ftp URI, creation_date and modification_date are the same.
    WARNING: this does not respect the pseudo-relativeness of s3/azure which is relative to the bucket/container, here the relativeness is to the folder URI"""
    m = GENERIC_REGEXP.match(uri)
    if m:
        m = m.groupdict()
        source = f"{m['proto']}://{m['resource']}"
        #if m['proto']=='s3':
        #    return s3_list(source, no_rec=no_rec, md5=md5)
        #elif m['proto']=='azure':
        #    return AzureClient().list(source, no_rec=no_rec, md5=md5) 
        if m['proto']=='ftp':
            return ftp_list(source, no_rec=no_rec)
        elif m['proto']=='file':
            return file_list(source, no_rec=no_rec) 
        #elif m['proto']=='fasp':
        #    fasp_get(source, destination)
        #elif m['proto']=='run+fastq':
        #    fastq_run_get(source, destination)       
        else:
            if rclone_client.has_source(m['proto']):
                return rclone_client.list(source, no_rec=no_rec, md5=md5)
            else:
                raise UnsupportedError(f"This URI protocol is not supported: {m['proto']}")
    else:
        return []

def ncdu(uri, output_file):
    """Return a JSON list in the format that ncdu accept with -f"""

    class File:
        def __init__(self, name, size, time):
            self.name = name
            self.size = size
            self.time = time
        def ncdu_object(self):
            return {"name":self.name,"dsize":self.size,"mtime":int(self.time.timestamp())}

    class Folder:
        def __init__(self, name):
            self.name = name
            self.content = {}
        def add_folder(self, name):
            self.content[name]=Folder(name)
        def has(self,name):
            return name in self.content
        def add_file(self, name, size, time):
            self.content[name]=File(name, size, time)
        def ncdu_object(self):
            return [ {'name': self.name} ] + [ c.ncdu_object() for c in self.content.values() ]
        def get(self, name):
            return self.content[name]

    top_folder = Folder(uri)

    for item in list_content(uri):
        folder,file=os.path.split(item.rel_name)
        current_folder=top_folder
        if folder!='':
            for subfolder in folder.split('/'):
                if not current_folder.has(subfolder):
                    current_folder.add_folder(subfolder)
                current_folder=current_folder.get(subfolder)
        current_folder.add_file(file, item.size, item.modification_date)

    json.dump([1,
                0,
                {"progname":"scitq",
                "progver":package_version(),
                "timestamp":int(time())},
                top_folder.ncdu_object()],
              output_file)

def sync(uri1, uri2, include=None, process=MAX_PARALLEL_SYNC, show_progress=False):
    """Sync two URI, one must be local
    Identity of the files is assessed only with name and size
    """
    local_uri = get_file_uri(uri1)
    if local_uri is not None:
        command = put
        remote = uri2
        try:
            proto2=check_uri(uri2)
            remote_proto=proto2
        except FetchError:
            local_uri=get_file_uri(uri2)
            if local_uri is None:
                raise UnsupportedError(f'uri2 appears to be neither locale nor proper: {uri2}')
            else:
                rclone_client.sync(uri1, uri2, show_progress=show_progress)
                #command=get
                #remote=uri1 if ':' in uri1 else f'file://{uri1}'
    else:
        try:
            proto1=check_uri(uri1)
            remote_proto=proto1
        except FetchError:
            raise UnsupportedError(f'Destination URI seems illdefined: {uri1}')
        local_uri=get_file_uri(uri2)
        if local_uri is None:
            try:
                proto2=check_uri(uri2)
            except FetchError:
                raise UnsupportedError(f'Destination URI seems illdefined: {uri2}') 
            if rclone_client.has_source(proto2) and rclone_client.has_source(proto1):
                return rclone_client.sync(uri1, uri2, show_progress=show_progress)                
            else:
                raise UnsupportedError('Neither URI seems to be local nor supported remotes, unsupported yet')
        else:
            return rclone_client.sync(uri1, uri2, show_progress=show_progress)
        #command=get
        #remote=uri1
    
    if rclone_client.has_source(remote_proto):
        return rclone_client.sync(uri1, uri2, show_progress=show_progress)
    else:
        full_local_uri=f"file://{local_uri}"
        if not os.path.exists(local_uri):
            os.makedirs(local_uri, exist_ok=True)
        

        local_list = dict([(item.rel_name,item) for item in list_content(full_local_uri)])
        remote_list = dict([(item.rel_name,item) for item in list_content(remote)])

        if command==get:
            source_list=remote_list
            dest_list=local_list
            source_uri=remote
            dest_uri=local_uri
        else:
            source_list=local_list
            dest_list=remote_list
            source_uri=local_uri
            dest_uri=remote

        jobs = {}
        with concurrent.futures.ProcessPoolExecutor(max_workers=process) as executor:
            for item_name, item in source_list.items():
                if item_name not in dest_list or \
                        dest_list[item_name].size!=item.size:
                    if include:
                        for inc in include:
                            if fnmatch(item_name, inc):
                                break
                        else:
                            continue
                    log.warning(f'Copying {os.path.join(source_uri, item_name)} to {os.path.join(dest_uri, item_name)}')
                    jobs[executor.submit(command, 
                                    os.path.join(source_uri, item_name),
                                    os.path.join(dest_uri, item_name))]=item_name
        
        failed = False
        for job in concurrent.futures.as_completed(jobs):
            item_name = jobs[job]
            if job.exception() is None:
                log.info(f'Done for {item_name}: {job.result()}')
            else:
                log.error(f'Could not download {item_name}')
                log.exception(job.exception())
                failed = True
        
        if failed:
            raise FetchError('At least some objects could not be synchronized')

def recursive_delete(uri, include=None, dryrun=False):
    """Works the same way than sync, recursively deleting some objects from uri"""
    try:
        proto=check_uri(uri)
    except FetchError:
        if get_file_uri(uri) is None:
            raise UnsupportedError(f'Malformed URI for deletion {uri}')
        else:
            proto='file'
    if proto=='file' or rclone_client.has_source(proto):
        rclone_client.delete(uri)
    else:
        jobs = {}
        with concurrent.futures.ProcessPoolExecutor(max_workers=MAX_PARALLEL_SYNC) as executor:
            for item in list_content(uri):
                item_name=item.rel_name.split('/')[-1]
                if include:
                    for inc in include:
                        if fnmatch(item_name, inc):
                            break
                    else:
                        continue
                log.warning(f'Deleting {item.name}')
                if not dryrun:
                    jobs[executor.submit(delete, 
                                item.name)]=item.name
        
        failed = False
        for job in concurrent.futures.as_completed(jobs):
            item_name = jobs[job]
            if job.exception() is None:
                log.info(f'Done for {item_name}: {job.result()}')
            else:
                log.error(f'Could not delete {item_name}')
                log.exception(job.exception())
                failed = True

        if failed:
            raise FetchError('At least some objects could not be deleted')

def copy(source_uri, destination_uri, show_progress=False, file_list=None):
        candidate_source = get_file_uri(source_uri)
        candidate_destination = get_file_uri(destination_uri)
        proto_source = None if candidate_source else check_uri(source_uri)
        proto_destination = None if candidate_destination else check_uri(destination_uri)

        if candidate_destination is None and candidate_source is None:
            # neither source nor destination is local, this is a remote copy only rclone can do that
            if rclone_client.has_source(proto_destination) and rclone_client.has_source(proto_source) and proto_destination==proto_source:
                if file_list:
                    args=[f"--include \"{{{','.join(file_list)}}}\""]
                else:
                    args=[]
                rclone_client.copy(source_uri, destination_uri, show_progress=show_progress, args=args)
            else:
                raise UnsupportedError(f'Cannot copy from protocol {proto_source} to {proto_destination}')
        else:
            if file_list:
                raise UnsupportedError(f'file_list option is only supported with rclone/rclone')
            if candidate_source is not None:
                put(candidate_source, destination_uri, show_progress=show_progress)
            else:
                candidate_destination = get_file_uri(destination_uri)
                get(source_uri, candidate_destination, show_progress=show_progress)


def main():
    parser = argparse.ArgumentParser(
                    prog = 'scitq.fetch module utility mode',
                    description = '''Enable direct download or upload without python code.
Takes a command with one or two URI (generalised URL, including file://... and s3://... or ftp://...) 
one of them must be a file URI (starts with file://... or be a simple path)''')
    parser.add_argument('-v','--verbose',action='store_true',help='Turn log level to info')
    parser.add_argument('-p','--process',type=int,default=MAX_PARALLEL_SYNC,
                        help=f'Number of parallel process (default to {MAX_PARALLEL_SYNC})')
    subparser=parser.add_subparsers(help='sub-command help',dest='command')

    get_parser = subparser.add_parser('copy', help='Copy some file or folder to some folder (one of them must be local)')
    get_parser.add_argument('source_uri', type=str, help='the uri (can be a local file or a remote URI)')
    get_parser.add_argument('destination_uri', type=str, nargs='?',
                        help='the destination uri (same as above, default to ., means download locally)', default=os.getcwd())
    
    list_parser = subparser.add_parser('list', help='List the content of a remote folder (outputs some absolute URI)')
    list_parser.add_argument('--not-recursive', action="store_true", help="Do not be recursive")
    list_parser.add_argument('--md5', action="store_true", help="Fetch also md5")
    list_parser.add_argument('uri', type=str, help='the remote folder uri')
    
    rlist_parser = subparser.add_parser('rlist', help='List the content of a remote folder (outputs some relative path to the URI)')
    rlist_parser.add_argument('--not-recursive', action="store_true", help="Do not be recursive")
    rlist_parser.add_argument('--md5', action="store_true", help="Fetch also md5")
    rlist_parser.add_argument('uri', type=str, help='the remote folder uri')

    nrlist_parser = subparser.add_parser('nrlist', help='List the content of a remote folder, like rlist but with --not-recursive as default')
    nrlist_parser.add_argument('--md5', action="store_true", help="Fetch also md5")
    nrlist_parser.add_argument('uri', type=str, help='the remote folder uri')

    sync_parser = subparser.add_parser('sync', help='Sync some file or folder to some folder (one of them must be local) (identity is checked using name and size)')
    sync_parser.add_argument('source_uri', type=str, help='the uri (can be a local file or a remote URI)')
    sync_parser.add_argument('destination_uri', type=str,
                        help='the destination uri (same as above, default to ., means download locally)', default=os.getcwd())
    sync_parser.add_argument('--include',action='append',type=str,
                        help="A pattern that should be included (only those will be synced) (can be specified several times)")
    

    delete_parser = subparser.add_parser('delete', help='Delete some file or folder expressed as a URI')
    delete_parser.add_argument('uri', type=str, help='the uri (can be a local file or a remote URI)')
    delete_parser.add_argument('--include',action='append',type=str,
                        help="A pattern that should be included (only those will be synced) (can be specified several times)")
    delete_parser.add_argument('--dryrun',action='store_true',
                        help="Do not really delete, just print what it would delete")

    ncdu_parser = subparser.add_parser('ncdu', help='Create an ncdu output to audit data volume comsumption in a folder arborescence')
    ncdu_parser.add_argument('uri', type=str, help='the uri (can be a local file or a remote URI)')
    ncdu_parser.add_argument('--only-file', action='store_true', help='only generate an ncdu file, do not launch ncdu with the results')
    
    
    args = parser.parse_args()

    if args.verbose:
        log.basicConfig(level=log.INFO)

    if args.command=='copy':
        copy(args.source_uri, args.destination_uri, show_progress=True)
    elif args.command=='list':
        if ':' not in args.uri:
            uri=f'file://{args.uri}'
        else:
            check_uri(args.uri)
            uri=args.uri
        headers=['name','creation_date','modification_date','size']
        if args.md5:
            headers.append('md5')
        print(tabulate(
            [[ if_is_not_None(getattr(item,attribute),'-') for attribute in headers  ] for item in list_content(uri, 
                                                                                                        no_rec=args.not_recursive,
                                                                                                        md5=args.md5)],
            headers=headers,
            tablefmt='plain'
        ))
    elif args.command=='rlist' or args.command=='nrlist':
        if args.command=='nrlist':
            args.not_recursive=True
        if ':' not in args.uri:
            uri=f'file://{args.uri}'
        else:
            check_uri(args.uri)
            uri=args.uri
        headers=['rel_name','creation_date','modification_date','size']
        if args.md5:
            headers.append('md5')
        print(tabulate(
            [[ if_is_not_None(getattr(item,attribute),'-') for attribute in headers  ] for item in list_content(uri,
                                                                                                                no_rec=args.not_recursive,
                                                                                                                md5=args.md5)],
            headers=headers,
            tablefmt='plain'
        ))
    elif args.command=='sync':
        sync(args.source_uri, args.destination_uri, include=args.include, process=args.process, show_progress=True)
    elif args.command=='delete':
        recursive_delete(args.uri, include=args.include, dryrun=args.dryrun)
    elif args.command=='ncdu':
        if ':' not in args.uri:
            uri=f'file://{args.uri}'
            proto='file'
        else:
            proto=check_uri(args.uri)
            uri=args.uri
        if not args.only_file and rclone_client.has_source(proto):
            rclone_client.ncdu(uri)
        else:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', delete=False) as output_file:
                ncdu(uri=uri, output_file=output_file)
                output_file.close()
                if not args.only_file:
                    os.system(f'ncdu -f "{output_file.name}"')
                    os.remove(output_file.name)
                else:
                    print(f'ncdu json file was stored in {output_file.name}')

if __name__=='__main__':
    main()