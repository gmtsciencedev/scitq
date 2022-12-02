import boto3
import botocore.exceptions
from ftplib import FTP
import re
import logging as log
from functools import wraps, cached_property
from time import sleep
import shutil
import os
import requests
import glob
import hashlib
import threading
import subprocess
from .util import PropagatingThread
import concurrent.futures

# how many time do we retry
RETRY_TIME = 3
RETRY_SLEEP_TIME = 10
PUBLIC_RETRY_TIME = 20
MAX_PARALLEL_S3 = 5

class FetchError(Exception):
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
                except Exception:
                    log.exception('Something went bad')
                    iteration += 1
                    if iteration<__retry_number__:
                        log.warning(f'Waiting some time ({sleep_time}s)...')
                        sleep(sleep_time)
                        sleep_time *= 2
                        log.warning('Retrying...')
                    else:
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
        subprocess.run(['tar','xzf',basename], cwd=path, check=True)
    else:
        subprocess.run(['tar','xf',basename], cwd=path, check=True)
    os.remove(filepath)

# AWS S3 

S3_REGEXP=re.compile(r'^s3://(?P<bucket>[^/]*)/(?P<path>.*)$')

# this comes from here : https://github.com/boto/boto3/pull/2746
class BotoSession(boto3.session.Session):
    def client(self, *args, **kwargs):
        if kwargs.get('endpoint_url') is None and os.environ.get("AWS_ENDPOINT_URL"):
            kwargs['endpoint_url'] = os.environ.get("AWS_ENDPOINT_URL")
        return super().client(*args, **kwargs)

def get_s3():
    if os.environ.get("AWS_ENDPOINT_URL"):
        return boto3.resource('s3', 
            endpoint_url=os.environ.get("AWS_ENDPOINT_URL"))
    else:
        return boto3.resource('s3')

@retry_if_it_fails(RETRY_TIME)
def s3_get(source, destination):
    """S3 downloader: download source expressed as s3://bucket/path_to_file 
    to destination - a local file path"""
    log.warning(f'S3 downloading {source} to {destination}')
    destination=complete_if_ends_with_slash(source, destination)
    uri_match = S3_REGEXP.match(source).groupdict()
    try:
        if uri_match['path'].endswith('/'):
            bucket=get_s3().Bucket(uri_match['bucket'])
            jobs = {}
            with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_PARALLEL_S3) as executor:
                for obj in bucket.objects.filter(Prefix=uri_match['path']):
                    destination_name = os.path.relpath(obj.key, uri_match['path'])
                    destination_name = os.path.join(destination, destination_name)
                    destination_path,_ = os.path.split(destination_name)
                    log.warning(f'S3 downloading {obj.key} to {destination_name}')
                    if not os.path.exists(destination_path):
                        os.makedirs(destination_path)
                    if not os.path.exists(destination_name):
                        jobs[executor.submit(bucket.download_file, obj.key, destination_name)]=obj.key
                for job in  concurrent.futures.as_completed(jobs):
                    obj = jobs[job]
                    log.warning(f'Done for {obj}: {job.result()}')
        else:
            BotoSession().client('s3').download_file(uri_match['bucket'],
                uri_match['path'],destination)
    except botocore.exceptions.ClientError as error:
        if 'Not Found' in error.response.get('Error',{}).get('Message',None):
            raise FetchError(f'{source} was not found')
        else:
            raise


@retry_if_it_fails(RETRY_TIME)
def s3_put(source, destination):
    """S3 uploader: download a local file path in source to a destination
    expressed as a s3 URI s3://bucket/path_to_file"""
    log.info(f'S3 uploading {source} to {destination}')
    destination=complete_if_ends_with_slash(source, destination)
    uri_match = S3_REGEXP.match(destination).groupdict()
    BotoSession().client('s3').upload_file(source,uri_match['bucket'],
        uri_match['path'])

# FTP

FTP_REGEXP=re.compile(r'^ftp://(?P<host>[^/]*)/(?P<path>.*)$')

@retry_if_it_fails(RETRY_TIME)
def ftp_get(source, destination):
    """FTP downloader: download source expressed as ftp://host/path_to_file 
    to destination - a local file path"""
    log.info(f'FTP downloading {source} to {destination}')
    destination=complete_if_ends_with_slash(source, destination)
    uri_match = FTP_REGEXP.match(source).groupdict()
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

@cached_property
def docker_available():
    """A property to see if docker is there"""
    return subprocess.run(['docker', '-v'],check=False).returncode==0

# aspera

ASPERA_REGEXP=re.compile(r'^fasp://(?P<url>.*)$')

@retry_if_it_fails(RETRY_TIME)
def fasp_get(source, destination):
    """Aspera downloader: download source expressed as fasp://user@host/path_to_file
    (NB usually with ENA, user is era-fasp) 
    to destination - a local file path"""
    log.info(f'Aspera downloading {source} to {destination}')
    if not docker_available:
        raise FetchError('Cannot use fasp (aspera) without docker')

    # we need destination to be expressed as a directory:
    # (but we remember that the target filename may be different from the source
    # filename)
    if destination.endswith('/'):
        target_filename = None
    else:
        destination, target_filename = os.path.split(destination)
    
    uri_match = ASPERA_REGEXP.match(source).groupdict()
    subprocess.run(f'docker run --rm -v {destination}:/output ibmcom/aspera-cli \
ascp -T --policy=high -l 300m -P33001 -m 30m -v \
-i /home/aspera/.aspera/cli/etc/asperaweb_id_dsa.openssh \
{uri_match["url"]} /output/', shell=True, check=True)
    
    # if the target filename is really different 
    if target_filename is not None:
        source_filename = uri_match['url'].split('/')[-1]
        if source_filename!=target_filename:
            shutil.move(os.path.join(destination, source_filename),
                os.path.join(destination,target_filename))

# run accessions containing fastq


FASTQ_RUN_REGEXP=re.compile(r'^run\+fastq://(?P<run_accession>[^/]*)/?$')

@retry_if_it_fails(RETRY_TIME)
def fastq_sra_get(run_accession, destination):
    """This subfunction of runacc_get is only called when EBI's ENA won't
    answer as NCBI's SRA while more complete is quite slow"""
    log.info(f'SRA get run+fastq://{run_accession} to {destination}')
    if not docker_available:
        raise FetchError('Cannot use SRA toolkit without docker')
    if not destination.endswith('/'):
            destination+='/'
    previous_fastq = glob.glob(os.path.join(destination, '*.fastq'))
    subprocess.run(f'docker run --rm -v {destination}:/destination ncbi/sra-tools \
        sh -c "cd /destination && prefetch {run_accession} && fasterq-dump -f --split-files {run_accession}"',
        shell=True,
        check=True)
    current_fastq = glob.glob(os.path.join(destination, '*.fastq'))
    fastqs = [fastq for fastq in current_fastq if fastq not in previous_fastq]
    subprocess.run(f'docker run --rm -v {destination}:{destination} ghcr.io/kasperskytte/docker-pigz:master -- '+
        ' '.join(fastqs),
        shell=True,
        check=True)

def _my_fastq_download(method, url, md5, destination):
    """A small adhoc function to download and check a fastq through a ftp_url plus a md5"""
    filename = url.split('/')[-1]
    if method=='fastq_ftp':
        ftp_get('ftp://'+url, destination, __retry_number__=1)
    elif method=='fastq_aspera':
        fasp_get(f'fasp://era-fasp@{url}', destination, __retry_number__=1)
    else:
        raise FetchError(f'No such method: {method}')
    with open(os.path.join(destination,filename),"rb") as f:
        readable_hash = hashlib.md5(f.read()).hexdigest()
        if readable_hash!=md5:
            raise FetchError(f'{filename} md5: {readable_hash} does not match ENA md5 {md5}')


@retry_if_it_fails(PUBLIC_RETRY_TIME)
def fastq_run_get(source, destination):
    """Fetch some fastq associated to a run accession"""
    log.info(f'Run accession: uploading {source} to {destination}')
    if not destination.endswith('/'):
            destination+='/'
    uri_match = FASTQ_RUN_REGEXP.match(source).groupdict()
    query_try = RETRY_TIME+1
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
        return fastq_sra_get(uri_match['run_accession'], destination)
    if run_query.status_code==204:
        log.exception('This does not seem to be available on EBI')
        return fastq_sra_get(uri_match['run_accession'], destination)
    run = run_query.json()[0]



    if 'fastq_ftp' or 'fastq_aspera' in run:
        ftp_md5s = run['fastq_md5'].split(';')

        for method in ['fastq_ftp', 'sra', 'fastq_aspera']:
            if method == 'sra':
                return fastq_sra_get(uri_match['run_accession'], destination, 
                    __retry_number__=1)
            elif method in run:
                if method in ['fastq_aspera','sra'] and not docker_available:
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
        log.exception('EBI response does not include a fastq_ftp field')
        return fastq_sra_get(uri_match['run_accession'], destination)




# plain file

FILE_REGEXP=re.compile(r'^file://(?P<path>.*)$')

def file_get(source, destination):
    """A plain local copy from a file://... source to a local path
    really just some plain syntaxic sugar above shutil.copyfile"""
    log.info(f'FILE downloading {source} to {destination}')
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
            os.makedirs(path)
        shutil.copyfile(source, complete_path)
    else:
        raise FetchError(f"Local URL did not match file://<path> pattern {destination}")


# generic wrapper

GENERIC_REGEXP=re.compile(r'^(?P<proto>[a-z0-9+]*)://(?P<resource>[^|]*)(\|(?P<action>.*))?$')

def get(uri, destination):
    """General downloader source should start with s3://... or ftp://...
    (source should not end with slash unless you know what you are doing if 
    destination ends with slash it will be completed with source end item)
    file://... is also supported but be careful that it is local to worker.
    """
    m = GENERIC_REGEXP.match(uri)
    if m:
        m = m.groupdict()
        source = f"{m['proto']}://{m['resource']}"
        if m['proto']=='s3':
            s3_get(source, destination)
        elif m['proto']=='ftp':
            ftp_get(source, destination)
        elif m['proto']=='file':
            file_get(source, destination) 
        elif m['proto']=='fasp':
            fasp_get(source, destination)
        elif m['proto']=='run+fastq':
            fastq_run_get(source, destination)       
        else:
            raise FetchError(f"This URI protocol is not supported: {m['proto']}")
        complete_destination = complete_if_ends_with_slash(source, destination)
        if m['action']=='gunzip':
            gunzip(complete_destination)
        elif m['action']=='untar':
            untar(complete_destination)
        elif m['action'] not in ['',None]:
            raise FetchError(f"Unsupported action: {m['action']}")
    else:
        raise FetchError(f'This URI is malformed: {uri}')

def put(source, uri):
    """General uploader destination should start with s3://.... or ftp://...
    (only anonymous ftp is implemented so put is unlikely to work with ftp)
    (source should not end with slash unless you know what you are doing if 
    destination ends with slash it will be completed with source end item)
    file://... is also supported but be careful that it is local to worker."""
    m = GENERIC_REGEXP.match(uri)
    if m:
        m = m.groupdict()
        if m['action']:
            raise FetchError(f'Action are unsupported when putting in {uri}')
        destination = f"{m['proto']}://{m['resource']}"
        destination = complete_if_ends_with_slash(source, destination)
        if m['proto']=='s3':
            s3_put(source, destination)
        elif m['proto']=='ftp':
            ftp_put(source, destination)
        elif m['proto']=='file':
            file_put(source, destination)        
        else:
            raise FetchError(f"This URI proto is not supported: {m['proto']}")
    else:
        raise FetchError(f'This URI is malformed: {uri}')

def check_uri(uri):
    """A small utility to check URI: return True if URI is valid, raise an exception otherwise"""
    m = GENERIC_REGEXP.match(uri)
    if m:
        m = m.groupdict()
        if m['proto'] not in ['ftp','file','s3','run+fastq']:
            raise FetchError(f"Unsupported protocol {m['proto']} in URI {uri}")
    else:
        raise FetchError(f"Malformed URI : {uri}")
    return True