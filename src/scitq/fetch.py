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
import subprocess
from .util import PropagatingThread, xboto3, if_is_not_None
import concurrent.futures
import argparse
import datetime
import pytz
import io
from azure.storage.blob import BlobServiceClient, BlobBlock, BlobClient
import uuid
import azure.core.exceptions
from .constants import DEFAULT_WORKER_CONF
import dotenv
from tabulate import tabulate 
from fnmatch import fnmatch

# how many time do we retry
RETRY_TIME = 3
RETRY_SLEEP_TIME = 10
MAX_SLEEP_TIME = 900
PUBLIC_RETRY_TIME = 20
MAX_PARALLEL_S3 = 5

# position in FTP dir command
# typical output is: '-rw-rw-r--    1 ftp      ftp       1088322 Jul 15  2019 MGYG-HGUT-00001.faa' 
FTP_DIR_SIZE_POSITION = 4
FTP_DIR_MONTH_POSITION = 5
FTP_DIR_DAY_POSITION = 6
FTP_DIR_YEAR_POSITION = 7
FTP_DIR_NAME_POSITION = 8

HTTP_CHUNK_SIZE = 81920

# name of Azure variables
AZURE_ACCOUNT='SCITQ_AZURE_ACCOUNT'
AZURE_KEY='SCITQ_AZURE_KEY'
MAX_PARALLEL_AZURE = 5
MAX_CONCURRENCY_AZURE = 3
AZURE_CHUNK_SIZE = 50*1024**2

ASPERA_DOCKER = 'martinlaurent/ascli:4.14.0'

MAX_PARALLEL_SYNC = 10

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
    """Stupid unzipper with unzip (and delete the archive like gunzip does)"""
    subprocess.run(['unzip',filepath], check=True)
    os.remove(filepath)

# AWS S3 

S3_REGEXP=re.compile(r'^s3://(?P<bucket>[^/]*)/(?P<path>.*)$')

def get_s3():
    """Replace boto3.resource('s3') using hack suggested in https://github.com/aws/aws-cli/issues/1270"""
    return xboto3().resource('s3')

def _bucket_get(bucket, key, destination):
    """A small helper just to ease boto3 client in thread/process context to download a file"""
    return get_s3().Bucket(bucket).download_file(key, destination)

@retry_if_it_fails(RETRY_TIME)
def s3_get(source, destination):
    """S3 downloader: download source expressed as s3://bucket/path_to_file 
    to destination - a local file path"""
    log.info(f'S3 downloading {source} to {destination}')
    destination=complete_if_ends_with_slash(source, destination)
    uri_match = S3_REGEXP.match(source).groupdict()
    if uri_match['path'].endswith('/'):
        retry = RETRY_TIME
        try:
            bucket=get_s3().Bucket(uri_match['bucket'])
            objects = list(bucket.objects.filter(Prefix=uri_match['path']))
            while retry>0:
                failed_objects = []
                failed = False
                try:
                    jobs = {}
                    with concurrent.futures.ProcessPoolExecutor(max_workers=MAX_PARALLEL_S3) as executor:
                        for obj in objects:
                            destination_name = os.path.relpath(obj.key, uri_match['path'])
                            destination_name = os.path.join(destination, destination_name)
                            destination_path,_ = os.path.split(destination_name)
                            log.info(f'S3 downloading {obj.key} to {destination_name}')
                            if not os.path.exists(destination_path):
                                os.makedirs(destination_path, exist_ok=True)
                            if not os.path.exists(destination_name):
                                jobs[executor.submit(_bucket_get, uri_match['bucket'], obj.key, destination_name)]=obj
                        for job in  concurrent.futures.as_completed(jobs):
                            obj = jobs[job]
                            if job.exception() is None:
                                log.info(f'Done for {obj.key}: {job.result()}')
                            else:
                                log.error(f'Could not download {obj.key}')
                                log.exception(job.exception())
                                failed = True
                                failed_objects.append(obj)
                    if failed:
                        objects = failed_objects
                        retry -= 1
                        continue
                    else:
                        break
                except:
                    pass
        except botocore.exceptions.ClientError as error:
            if 'Not Found' in error.response.get('Error',{}).get('Message',None):
                raise FetchError(f'{source} was not found') from error
            else:
                raise
        
        if failed:
            raise FetchError(f"These objects could not be downloaded: {','.join([obj.key for obj in failed_objects])}")
    else:
        try:
            xboto3().client('s3').download_file(uri_match['bucket'],
                uri_match['path'],destination)
        except botocore.exceptions.ClientError as error:
            if 'Not Found' in error.response.get('Error',{}).get('Message',None):
                log.warning(f'{source} was not found, trying {source}/')
                s3_get(source+'/',destination)
            else:
                raise


@retry_if_it_fails(RETRY_TIME)
def s3_put(source, destination):
    """S3 uploader: download a local file path in source to a destination
    expressed as a s3 URI s3://bucket/path_to_file"""
    log.info(f'S3 uploading {source} to {destination}')
    destination=complete_if_ends_with_slash(source, destination)
    uri_match = S3_REGEXP.match(destination).groupdict()
    xboto3().client('s3').upload_file(source,uri_match['bucket'],
        uri_match['path'])

def s3_info(uri):
    """S3 info fetcher: get some info on a blob specified with s3://bucket/path_to_file"""
    log.info(f'S3 getting info for {uri}')
    uri_match = S3_REGEXP.match(uri).groupdict()
    try:
        bucket=get_s3().Bucket(uri_match['bucket'])
        object = next(iter(bucket.objects.filter(Prefix=uri_match['path'])))
        return argparse.Namespace(size=object.size, 
                                  creation_date=object.last_modified,
                                  modification_date=object.last_modified)
    except StopIteration:
        raise FetchError(f'{uri} was not found')

def s3_list(uri, no_rec = False):
    """List content of an s3 folder in the form s3://bucket/path
    if no_rec is True, restrict listing to path (and not recursive) - which may list "folders" with None creation_date"""
    log.info(f'S3 getting listing for {uri}')
    uri_match = S3_REGEXP.match(uri).groupdict()
    if no_rec:
        s3_client=xboto3().client('s3')
        bucket_name=uri_match['bucket']
        query = s3_client.list_objects_v2(
                Bucket=bucket_name,
                Delimiter='/',
                Prefix=uri_match['path'])
        return [argparse.Namespace(name=f's3://{bucket_name}/{prefix["Prefix"]}',
                                   rel_name=os.path.relpath(prefix['Prefix'], uri_match['path'])+'/',
                                   size=0,
                                   creation_date=None,
                                   modification_date=None) for prefix in query['CommonPrefixes']
                ] if 'CommonPrefixes' in query else [] + [
                argparse.Namespace(name=f's3://{bucket_name}/{object["Key"]}',
                            rel_name=os.path.relpath(object['Key'], uri_match['path']),
                            size=object['Size'], 
                            creation_date=object['LastModified'],
                            modification_date=object['LastModified'])
                for object in query['Contents']] if 'Contents' in query else []
    else:
        bucket=get_s3().Bucket(uri_match['bucket'])
        return [argparse.Namespace(name=f's3://{bucket.name}/{object.key}',
                                rel_name=os.path.relpath(object.key, uri_match['path']),
                                size=object.size, 
                                creation_date=object.last_modified,
                                modification_date=object.last_modified)
                for object in bucket.objects.filter(Prefix=uri_match['path'])]

def s3_delete(uri):
    """Delete an s3 blob"""
    log.info(f'S3 deleting {uri}')
    uri_match = S3_REGEXP.match(uri).groupdict()
    xboto3().client('s3').delete_object(Bucket=uri_match['bucket'], Key=uri_match['path'])


# Azure

AZURE_REGEXP=re.compile(r'^azure://(?P<container>[^/]*)/(?P<path>.*)$')


def _container_get(container, blob_name, file_name):
    """A small wrapper to ease azure client in thread/process context to download a file
    container can be either a string or an Azure container client."""
    if type(container)==str:
        #container = AzureClient().client.get_container_client(container)
        blob_client = AzureClient().client.get_blob_client(
                                        container=container,
                                        blob=blob_name)
    else:
        blob_client = container.get_blob_client(blob=blob_name)
    try:
        with open(file=file_name, mode="wb") as download_file:
            #download_file.write(container.download_blob(blob_name).readall())
            download_stream = blob_client.download_blob(max_concurrency=MAX_CONCURRENCY_AZURE)
            download_file.write(download_stream.readall())
    except:
        os.remove(file_name)
        raise
        

class AzureClient:
    """A small wrapper above Azure blob client to integrate with scitq"""
    def __init__(self):
        """This deals with initialization"""
        account_name=os.environ.get(AZURE_ACCOUNT)
        account_key=os.environ.get(AZURE_KEY)
        if account_name is None:
            if os.path.isfile(DEFAULT_WORKER_CONF):
                dotenv.load_dotenv(DEFAULT_WORKER_CONF)
                account_name=os.environ.get(AZURE_ACCOUNT)
                account_key=os.environ.get(AZURE_KEY)
        if account_name is None:
            raise FetchError(f'Azure account is not properly configured: either set {AZURE_ACCOUNT} and {AZURE_KEY} environment variables or adjust {DEFAULT_WORKER_CONF}.')
        connection_string = f"DefaultEndpointsProtocol=https;AccountName={account_name};AccountKey={account_key};EndpointSuffix=core.windows.net"
        self.client = BlobServiceClient.from_connection_string(connection_string,
                                        max_single_get_size=1024*1024*32,
                                        max_chunk_get_size=1024*1024*4)

    @retry_if_it_fails(RETRY_TIME)
    def get(self, source, destination):
        log.info(f'Azure downloading {source} to {destination}')
        destination=complete_if_ends_with_slash(source, destination)
        uri_match = AZURE_REGEXP.match(source).groupdict()
        if uri_match['path'].endswith('/'):
            retry = RETRY_TIME
            try:
                container=self.client.get_container_client(uri_match['container'])
                objects = list(container.list_blobs(name_starts_with=uri_match['path']))
                while retry>0:
                    failed_objects = []
                    failed = False
                    try:
                        jobs = {}
                        with concurrent.futures.ProcessPoolExecutor(max_workers=MAX_PARALLEL_AZURE) as executor:
                            for obj in objects:
                                destination_name = os.path.relpath(obj.name, uri_match['path'])
                                destination_name = os.path.join(destination, destination_name)
                                destination_path,_ = os.path.split(destination_name)
                                log.info(f'Azure downloading {obj.name} to {destination_name}')
                                if not os.path.exists(destination_path):
                                    os.makedirs(destination_path, exist_ok=True)
                                if not os.path.exists(destination_name):
                                    jobs[executor.submit(_container_get, 
                                            container.container_name, 
                                            obj.name, 
                                            destination_name)]=obj
                            for job in  concurrent.futures.as_completed(jobs):
                                obj = jobs[job]
                                if job.exception() is None:
                                    log.info(f'Done for {obj.key}: {job.result()}')
                                else:
                                    log.error(f'Could not download {obj.key}')
                                    log.exception(job.exception())
                                    failed = True
                                    failed_objects.append(obj)
                        if failed:
                            objects = failed_objects
                            retry -= 1
                            continue
                        else:
                            break
                    except:
                        pass
            except azure.core.exceptions.ResourceNotFoundError as error:
                raise FetchError(f'{source} was not found') from error
            
            if failed:
                raise FetchError(f"These objects could not be downloaded: {','.join([obj.key for obj in failed_objects])}")
        else:
            try:
                container=self.client.get_container_client(uri_match['container'])
                _container_get(container, uri_match['path'],destination)
            except azure.core.exceptions.ResourceNotFoundError as error:
                log.warning(f'{source} was not found, trying {source}/')
                self.get(source+'/', destination)

    @retry_if_it_fails(RETRY_TIME)
    def put(self, source, destination):
        """Azure uploader: download a local file path in source to a destination
        expressed as an Azure URI azure://container/path_to_file"""
        log.info(f'Azure uploading {source} to {destination}')
        destination=complete_if_ends_with_slash(source, destination)
        uri_match = AZURE_REGEXP.match(destination).groupdict()
        blob_client = self.client.get_blob_client(container=uri_match['container'],
                                                blob=uri_match['path'])
        with open(file=source, mode="rb") as data:
            if os.path.getsize(source)>=AZURE_CHUNK_SIZE:
                if blob_client.exists():
                    blob_client.delete_blob()
                block_list=[]
                while True:
                    read_data = data.read(AZURE_CHUNK_SIZE)
                    if not read_data:
                        break # done
                    blk_id = str(uuid.uuid4())
                    blob_client.stage_block(block_id=blk_id,data=read_data) 
                    block_list.append(BlobBlock(block_id=blk_id))
                blob_client.commit_block_list(block_list)
            else:
                blob_client.upload_blob(data, overwrite=True,max_concurrency=MAX_CONCURRENCY_AZURE)

    def info(self,uri):
        """Azure info fetcher: get some info on a blob specified with azure://container/path_to_file"""
        log.info(f'Azure getting info for {uri}')
        uri_match = AZURE_REGEXP.match(uri).groupdict()
        try:
            container=self.client.get_container_client(uri_match['container'])
            object = next(iter(container.list_blobs(name_starts_with=uri_match['path'])))
            return argparse.Namespace(size=object.size, 
                                    creation_date=object.creation_time,
                                    modification_date=object.last_modified)
        except StopIteration:
            raise FetchError(f'{uri} was not found')

    def list(self,uri, no_rec=False):
        """List the content of an azure storage folder  azure://container/path
        if no_rec is True, restrict listing to path (and not recursive) - which may list "folders" with None creation_date"""
        log.info(f'Azure getting listing for {uri}')
        uri_match = AZURE_REGEXP.match(uri).groupdict()
        container=self.client.get_container_client(uri_match['container'])
        if no_rec:
            return [argparse.Namespace(name=f"azure://{container.container_name}/{object.name}",
                                    rel_name=os.path.relpath(object.name, uri_match['path'])+('/' if object.name.endswith('/') else ''),
                                    size=object.get('size',0), 
                                    creation_date=object.get('creation_time',None),
                                    modification_date=object.get('last_modified',None))
                    for object in container.walk_blobs(name_starts_with=uri_match['path'],delimiter='/')]
        else:
            return [argparse.Namespace(name=f"azure://{container.container_name}/{object.name}",
                                    rel_name=os.path.relpath(object.name, uri_match['path']),
                                    size=object.size, 
                                    creation_date=object.creation_time,
                                    modification_date=object.last_modified)
                    for object in container.list_blobs(name_starts_with=uri_match['path'])]

    def delete(self, uri):
        """Delete an azure blob"""
        log.info(f'Azure deleting {uri}')
        uri_match = AZURE_REGEXP.match(uri).groupdict()
        container=self.client.get_container_client(uri_match['container'])
        container.delete_blob(uri_match['path'])


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

def ftp_info(uri):
    """FTP info: get some information on a FTP object"""
    log.info(f'FTP get info for {uri}')
    uri_match = FTP_REGEXP.match(uri).groupdict()
    with FTP(uri_match['host']) as ftp:
        ftp.login()

        with io.StringIO() as output:
            ftp.dir(uri_match['path'],output.write)
            output.seek(0)
            answer = output.read()
        
        if answer:
            obj = answer.split()
            obj_date = datetime.datetime.strptime(
                ' '.join( (obj[FTP_DIR_MONTH_POSITION],
                           obj[FTP_DIR_DAY_POSITION],
                           obj[FTP_DIR_YEAR_POSITION])
                    ),
                '%b %d %Y').replace(tzinfo=pytz.utc)
            return argparse.Namespace(size=obj[FTP_DIR_SIZE_POSITION],
                                    creation_date=obj_date, 
                                    modification_date=obj_date)
        else:
            raise FetchError(f'{uri} was not found')

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
    log.info(f'Pigziping fastqs ({fastqs})')
    subprocess.run(['pigz','-f']+fastqs,
        check=True)
    if os.path.isdir(os.path.join(destination, run_accession)):
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
def fastq_run_get(source, destination):
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
            return fastq_sra_get(uri_match['run_accession'], destination)
        if run_query.status_code==204:
            log.exception('This does not seem to be available on EBI')
            return fastq_sra_get(uri_match['run_accession'], destination)
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
        return fastq_sra_get(uri_match['run_accession'], destination)
        



    if 'fastq_ftp' or 'fastq_aspera' in run:
        ftp_md5s = run['fastq_md5'].split(';')

        for method in ['fastq_aspera', 'fastq_ftp', 'sra']:
            if method in ['fastq_aspera','sra'] and not docker_available:
                continue
            if method == 'sra':
                return fastq_sra_get(uri_match['run_accession'], destination, 
                    __retry_number__=1)
            elif method in run:
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
                    log.info(f'Download method {method} succeeded')
                    return None
                except:
                    log.exception(f'EBI failed with method {method}')
                    continue
        raise FetchError(f'Could not fetch {source}')
    else:
        log.exception('EBI response does not include a fastq_ftp field')
        return fastq_sra_get(uri_match['run_accession'], destination)


SUBMITTED_RUN_REGEXP=re.compile(r'^run\+submitted://(?P<run_accession>[^/]*)/?$')

@retry_if_it_fails(PUBLIC_RETRY_TIME)
def submitted_run_get(source, destination):
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

        for method in ['submitted_aspera', 'submitted_ftp']:
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

def file_info(uri):
    """Same as above except that source is this time a plain local path
    and destination is in the form file://... As above just some plain
    syntaxic sugar above shutil.copyfile """
    log.info(f'FILE getting info for {uri}')
    uri_match = FILE_REGEXP.match(uri).groupdict()
    if uri_match:
        complete_path = uri_match['path']
        stat = os.stat(complete_path)
        return argparse.Namespace(size=stat.st_size, 
                                  creation_date=datetime.datetime.utcfromtimestamp(stat.st_ctime).replace(tzinfo=pytz.utc),
                                  modification_date=datetime.datetime.utcfromtimestamp(stat.st_mtime).replace(tzinfo=pytz.utc))
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
        complete_destination = complete_if_ends_with_slash(source, destination)
        if uri.endswith('/'):
            complete_destination=complete_destination[:-1]
            complete_destination_folder=complete_destination            
        else:
            complete_destination_folder = '/'.join(complete_destination.split('/')[:-1])
        if not os.path.exists(complete_destination_folder):
            os.makedirs(complete_destination_folder, exist_ok=True)
        
        if m['proto']=='s3':
            s3_get(source, destination)
        elif m['proto']=='azure':
            AzureClient().get(source, destination) 
        elif m['proto']=='ftp':
            ftp_get(source, destination)
        elif m['proto']=='file':
            file_get(source, destination) 
        elif m['proto']=='fasp':
            fasp_get(source, destination)
        elif m['proto']=='run+fastq':
            fastq_run_get(source, destination)       
        elif m['proto']=='run+submitted':
            submitted_run_get(source, destination)
        elif m['proto'] in ['http','https']:
            http_get(source, destination)
        else:
            raise FetchError(f"This URI protocol is not supported: {m['proto']}")
        
        if m['action']=='gunzip':
            gunzip(complete_destination)
        elif m['action']=='untar':
            untar(complete_destination)
        elif m['action']=='unzip':
            unzip(complete_destination)
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
    if source.endswith('/'):
        raise FetchError('Recursive put is not yet supported, invalid source: '+source)
    if m:
        m = m.groupdict()
        if m['action']:
            raise FetchError(f'Action are unsupported when putting in {uri}')
        destination = f"{m['proto']}://{m['resource']}"
        destination = complete_if_ends_with_slash(source, destination)
        if m['proto']=='s3':
            s3_put(source, destination)
        elif m['proto']=='azure':
            AzureClient().put(source, destination) 
        elif m['proto']=='ftp':
            ftp_put(source, destination)
        elif m['proto']=='file':
            file_put(source, destination)        
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
        if m['proto']=='s3':
            s3_delete(uri)
        elif m['proto']=='azure':
            AzureClient().delete(uri) 
        elif m['proto']=='file':
            file_delete(uri)        
        else:
            raise FetchError(f"This URI proto is not supported: {m['proto']}")
    else:
        raise FetchError(f'This URI is malformed: {uri}')


def check_uri(uri):
    """A small utility to check URI: return True if URI is valid, raise an exception otherwise"""
    m = GENERIC_REGEXP.match(uri)
    if m:
        m = m.groupdict()
        if m['proto'] not in ['ftp','file','s3','azure','run+fastq','run+submitted','http','https']:
            raise FetchError(f"Unsupported protocol {m['proto']} in URI {uri}")
    else:
        raise FetchError(f"Malformed URI : {uri}")
    return True

def get_file_uri(uri):
    """A small utility to check if this is a file URI (starts with file://... or is a path)
    returns a path or None (if not a file URI)"""
    if uri.startswith('file://'):
        return uri[8:]
    elif ':' not in uri:
        return uri
    else:
        return None

def info(uri):
    """Return an info object from a URI, which should contains at least creation_date, modification_date and size
    WARNING: with s3 or ftp URI, creation_date and modification_date are the same."""
    m = GENERIC_REGEXP.match(uri)
    if m:
        m = m.groupdict()
        source = f"{m['proto']}://{m['resource']}"
        if m['proto']=='s3':
            return s3_info(source)
        elif m['proto']=='azure':
            return AzureClient().info(source) 
        elif m['proto']=='ftp':
            return ftp_info(source)
        elif m['proto']=='file':
            return file_info(source) 
        #elif m['proto']=='fasp':
        #    fasp_get(source, destination)
        #elif m['proto']=='run+fastq':
        #    fastq_run_get(source, destination)       
        else:
            raise FetchError(f"This URI protocol is not supported: {m['proto']}")

def list_content(uri, no_rec=False):
    """Return the recursive listing of folder specified as a URI
    each item of the list should contains at least name (complete URI), rel_name (the name of the object relative to the provided uri), creation_date, modification_date and size
    if no_rec is True, then the listing is non recursive -> MEANS SOME "FOLDERS" WILL APPEAR IN LISTING, eventually with None attribute (in dates)
    WARNING: with s3 or ftp URI, creation_date and modification_date are the same.
    WARNING: this does not respect the pseudo-relativeness of s3/azure which is relative to the bucket/container, here the relativeness is to the folder URI"""
    m = GENERIC_REGEXP.match(uri)
    if m:
        m = m.groupdict()
        source = f"{m['proto']}://{m['resource']}"
        if m['proto']=='s3':
            return s3_list(source, no_rec=no_rec)
        elif m['proto']=='azure':
            return AzureClient().list(source, no_rec=no_rec) 
        elif m['proto']=='ftp':
            return ftp_list(source, no_rec=no_rec)
        elif m['proto']=='file':
            return file_list(source, no_rec=no_rec) 
        #elif m['proto']=='fasp':
        #    fasp_get(source, destination)
        #elif m['proto']=='run+fastq':
        #    fastq_run_get(source, destination)       
        else:
            raise FetchError(f"This URI protocol is not supported: {m['proto']}")


def sync(uri1, uri2, include=None, process=MAX_PARALLEL_SYNC):
    """Sync two URI, one must be local
    Identity of the files is assessed only with name and size
    """
    local_uri = get_file_uri(uri1)
    if local_uri is not None:
        command = put
        remote = uri2
        try:
            check_uri(uri2)
        except FetchError:
            local_uri=get_file_uri(uri2)
            if local_uri is None:
                raise FetchError(f'uri2 appears to be neither locale nor prope: {uri2}')
            else:
                command=get
                remote=uri1 if ':' in uri1 else f'file://{uri1}'
    else:
        local_uri = get_file_uri(uri2)
        if local_uri is None:
            raise FetchError('Neither URI seems to be local, unsupported yet')
        command=get
        check_uri(uri1)
        remote=uri1
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
    list_parser.add_argument('uri', type=str, help='the remote folder uri')
    
    rlist_parser = subparser.add_parser('rlist', help='List the content of a remote folder (outputs some relative path to the URI)')
    rlist_parser.add_argument('--not-recursive', action="store_true", help="Do not be recursive")
    rlist_parser.add_argument('uri', type=str, help='the remote folder uri')

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

    args = parser.parse_args()

    if args.verbose:
        log.basicConfig(level=log.INFO)

    if args.command=='copy':
        candidate_source = get_file_uri(args.source_uri)
        if candidate_source is not None:
            check_uri(args.destination_uri)
            put(candidate_source, args.destination_uri)
        else:
            candidate_destination = get_file_uri(args.destination_uri)
            if candidate_destination is not None:
                check_uri(args.source_uri)
                get(args.source_uri, candidate_destination)
            else:
                raise RuntimeError('Both source_uri and destination_uri seem non file URI: operation unsupported')
    elif args.command=='list':
        if ':' not in args.uri:
            uri=f'file://{args.uri}'
        else:
            check_uri(args.uri)
            uri=args.uri
        headers=['name','creation_date','modification_date','size']
        print(tabulate(
            [[ if_is_not_None(getattr(item,attribute),'-') for attribute in headers  ] for item in list_content(uri, no_rec=args.not_recursive)],
            headers=headers,
            tablefmt='plain'
        ))
    elif args.command=='rlist':
        if ':' not in args.uri:
            uri=f'file://{args.uri}'
        else:
            check_uri(args.uri)
            uri=args.uri
        headers=['rel_name','creation_date','modification_date','size']
        print(tabulate(
            [[ if_is_not_None(getattr(item,attribute),'-') for attribute in headers  ] for item in list_content(uri, no_rec=args.not_recursive)],
            headers=headers,
            tablefmt='plain'
        ))
    elif args.command=='sync':
        sync(args.source_uri, args.destination_uri, include=args.include, process=args.process)
    elif args.command=='delete':
        recursive_delete(args.uri, include=args.include, dryrun=args.dryrun)

if __name__=='__main__':
    main()