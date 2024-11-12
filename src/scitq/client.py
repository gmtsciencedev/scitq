import argparse
from re import L
from .lib import Server, HTTPException
import socket
from time import sleep, time
import multiprocessing
import threading
import queue
import asyncio
from asyncio.subprocess import PIPE
import logging as log
import os
import psutil 
import platform
import queue
import tempfile
from .fetch import get,put,pathjoin, info, FetchError, UnsupportedError, list_content
import traceback
import shutil
import subprocess
from signal import SIGTERM, SIGKILL, SIGTSTP, SIGCONT
from .constants import SIGNAL_CLEAN, SIGNAL_RESTART, SIGNAL_RESET_RESOURCES, HTTP_ERROR_CODE_NOT_FOUND
import shlex
import concurrent.futures
import json
import datetime
import sys
from uuid import uuid1
from .util import isfifo, force_hard_link, PropagatingProcess
from .client_events import monitor_events
import math

CPU_MAX_VALUE =10
POLLING_TIME = 4
READ_TIMEOUT = 5
QUEUE_SIZE_THRESHOLD = 2
IDLE_TIMEOUT = 600
ZOMBIE_TIMEOUT = 600
WAIT_FOR_FIRST_EXECUTION_TIMEOUT = 3600
DEFAULT_WORKER_STATUS = "running"
BASE_WORKDIR = os.environ.get("BASE_WORKDIR", 
    "/tmp/scitq" if platform.system() in ['Windows','Darwin'] else "/scratch")
if not os.path.exists(BASE_WORKDIR):
    os.makedirs(BASE_WORKDIR)
BASE_RESOURCE_DIR = os.path.join(BASE_WORKDIR,'resource')
RESOURCE_FILES_SUBDIR = 'files'
RESOURCE_FILE = os.path.join(BASE_RESOURCE_DIR, 'resource.json')
MAXIMUM_PARALLEL_UPLOAD = 5
RETRY_UPLOAD = 5
RETRY_DOWNLOAD = 2
DEFAULT_AUTOCLEAN = 95
RESOURCE_VERSION = 2
try:
    SCITQ_PERMANENT_WORKER = bool(int(os.environ.get("SCITQ_PERMANENT_WORKER", '1')))
except:
    SCITQ_PERMANENT_WORKER = True

if not os.path.exists(BASE_RESOURCE_DIR):
    os.mkdir(BASE_RESOURCE_DIR)

DEFAULT_INPUT_DIR = '/input'
DEFAULT_OUTPUT_DIR = '/output'
DEFAULT_RESOURCE_DIR = '/resource'
DEFAULT_TEMP_DIR = '/tmp'
OUTPUT_LIMIT = 1024 * 128


STATUS_LAUNCHING = 0
STATUS_DOWNLOADING = 1
STATUS_WAITING = 2
STATUS_RUNNING = 3
STATUS_UPLOADING = 4
STATUS_FAILED = 5
STATUS_SUCCEEDED = 6
STATUS_TXT = ['LAUNCHING', 'DOWNLOADING', 'WAITING', 'RUNNING', 'UPLOADING', 
    'FAILED', 'SUCCEEDED']

CLIENT_STATUS_RUNNING = 1
CLIENT_STATUS_PAUSED = 2
CLIENT_STATUS_UNKNOWN = 0

DOWNLOAD_TIMEOUT_SEC_PER_GB = 600
DOWNLOAD_TIMEOUT_NO_INFO = 1800
DOWNLOAD_LOOP_TIME = 60

def client_status_code(status):
    """A small wrapper to translate status string to a int code"""
    if status=='running':
        return CLIENT_STATUS_RUNNING
    elif status=='paused':
        return CLIENT_STATUS_PAUSED
    else:
        return CLIENT_STATUS_UNKNOWN

def docker_command(input_dir, output_dir, temp_dir, resource_dir, cpu, extra_options,
        container, command, mode='-d'):
    docker_cmd = ['docker','run', mode]
    if os.path.exists('/data'):
        docker_cmd.extend(['-v', '/data:/data'])
    docker_cmd.extend([
        '-v', f'{input_dir}:{DEFAULT_INPUT_DIR}',
        '-v', f'{output_dir}:{DEFAULT_OUTPUT_DIR}',
        '-v', f'{temp_dir}:{DEFAULT_TEMP_DIR}',
        '-v', f'{resource_dir}:{DEFAULT_RESOURCE_DIR}:ro',
        '-e', f'CPU={str(cpu)}'])
    docker_cmd.extend(shlex.split(extra_options))
    docker_cmd.append(container)
    docker_cmd.extend(shlex.split(command)) 
    log.warning(f'Final docker command: {" ".join(docker_cmd)}')
    return docker_cmd

def docker_inspect(container_id):
    alive_container=None
    try:
        alive_container=subprocess.run(['docker','inspect','--format', "'{{json .}}'",container_id],
            capture_output=True, check=True
            ).stdout.decode('utf-8').strip()
        return json.loads(alive_container[1:-1]) 
    except subprocess.CalledProcessError:
        log.warning('No docker by that ID')
        return None
    except Exception:
        log.exception(f'Docker ps gave an non exploitable output: {alive_container}')
        return None

def docker_logs(container_id):
    process = subprocess.run(['docker','logs',container_id],
            capture_output=True, check=True, encoding='utf-8'
            )
    return process.stdout, process.stderr



def create_dir(base_dir, sub_dir):
    """A small helper function to create a subdirectory and return its name.
    Add a final slash (or backslash with windows) to makes things clear it is a directory"""
    # os.path.join throw away the base dir
    if sub_dir.startswith(os.path.sep) or sub_dir.startswith('/'):
        sub_dir=sub_dir[1:]
    new_dir = os.path.join(base_dir, sub_dir)
    log.warning(f'Creating directory {new_dir}')
    os.mkdir(new_dir)
    # fix permission (this cannot be made with mode option in os.mkdir because 
    # it is restricted by umask which is not the case of os.chmod)
    os.chmod(new_dir, mode=0o777)
    if not new_dir.endswith(os.path.sep) and not new_dir.endswith('/'):
        new_dir += os.path.sep
    return new_dir

def final_slash(path):
    """Return the string with a final slash if it has not already"""
    return path if path.endswith('/') else path+'/'

def no_slash(path):
    """Do the reverse of final_slash, remove the final slash if it had one"""
    return path[:-1] if path.endswith('/') else path


def resource_to_json(resource_db, resource_file=RESOURCE_FILE):
    """Dump resource to a json file"""
    with open(resource_file,'w',encoding='utf-8') as rf:
        resource_image = {'version':RESOURCE_VERSION}
        for data,data_info in resource_db.items():
            new_data_info = {}
            for k,v in data_info.items():
                if k=='date' and v is not None:
                    new_data_info[k]=v.isoformat()
                else:
                    new_data_info[k]=v 
            resource_image[data]=new_data_info            
        json.dump(resource_image, rf)

def json_to_resource(resource_db,resource_file=RESOURCE_FILE):
    """Load resource from a json file"""
    if os.path.exists(resource_file):
        try:
            with open(resource_file,'r',encoding='utf-8') as rf:
                resource = json.load(rf)
                if 'version' not in resource or resource['version']<RESOURCE_VERSION:
                    resource_folder,_ = os.path.split(resource_file)
                    log.warning(f'Obsolete resource folder, wiping {resource_folder}')
                    for item in os.listdir(resource_folder):
                        item = os.path.join(resource_folder, item)
                        if os.path.isdir(item):
                            shutil.rmtree(item)
                        else:
                            os.remove(item)
                else:
                    del(resource['version'])
                    for data,data_info in resource.items():
                        resource_db[data]=dict( [(k,datetime.datetime.fromisoformat(v)) if k=='date' else (k,v) 
                                             for k,v in data_info.items()] )
        except Exception as e:
            log.exception(f'Could not import resource from {resource_file}')
            
def bytes2gb(x):
    """Concert bytes to Gb"""
    return str(round(x/1024**3,2)) if type(x) in [int,float] else x

def bytes2mb(x):
    """Concert bytes to Mb"""
    return str(round(x/1024**2,2)) if type(x) in [int,float] else x

def speed(before, after, duration):
    """Compute read/write speed computation over a certain duration in seconds"""
    return ((after[i]-before[i])/duration for i in [0,1]) 

def relative(q, ref):
    """Return a list relative to a list of reference value (zeros)"""
    return [(qx-refx) for qx,refx in zip(q,ref)]

class DownloadTimeoutException(Exception):
    pass

def _get(data, folder, data_info=None, timeout=None, execution_queue=None):
    """A thin wrapper above scitq.fetch.get to handle timeout and task interuption"""
    if timeout is None:
        if data_info is None:
            try:
                data_size = sum([item.size for item in list_content(data)])
            except:
                log.exception(f'Could not estimate data size for {data}')
                timeout = DOWNLOAD_TIMEOUT_NO_INFO
        else:
            data_size=data_info.size
        if timeout is None:                
            timeout = math.ceil(data_size / 1024**3) * DOWNLOAD_TIMEOUT_SEC_PER_GB
    if timeout < DOWNLOAD_TIMEOUT_SEC_PER_GB:
        timeout = DOWNLOAD_TIMEOUT_SEC_PER_GB
    p = PropagatingProcess(target=get, args=[data,folder])
    p.start()
    start_time = time()
    later_signals=[]
    while p.is_alive():
        if execution_queue is not None:
            try:
                signal=execution_queue.get(block=False)
                if signal in [SIGTERM, SIGKILL]:
                    p.kill()
                    break
                else:
                    later_signals.append(signal)
            except queue.Empty:
                pass
        if time()-start_time>timeout:
            p.kill()
            break
        p.join(timeout=DOWNLOAD_LOOP_TIME)
    else:
        later_signals.reverse()
        for signal in later_signals:
            execution_queue.put(signal)
        return True
    raise DownloadTimeoutException(f'Download of {data} took longer than {timeout}, bailing out')

class Executor:
    """Executor represent the process in which the task is launched, it is also
    designed to monitor the task and grab its output to push it regularly to the
    server.
    It performs now preparation tasks and post operation tasks."""

    def __init__(self, server, execution_id, task_id, command, input, output, 
                container, container_options, execution_queue,
                cpu, resource_dir, resource, resources_db, #run_slots, #run_slots_semaphore,
                worker_id, status, working_dirs, client_status,
                recover=False, input_dir=None, output_dir=None, task_resource_dir=None,
                temp_dir=None, workdir=None, container_id=None, go=None):
        log.warning(f'Starting executor for {execution_id}')
        self.s = Server(server, style='object')
        self.worker_id = worker_id
        self.execution_id = execution_id
        self.task_id = task_id
        self.command = command
        self.input = input
        if output and not output.endswith('/'):
            output+='/'
        self.output = output
        self.container = container
        self.container_options = container_options
        self.execution_queue = execution_queue
        self.resource_dir = final_slash(resource_dir)
        self.recover = recover
        self.cpu=cpu 
        self.resource=resource
        self.resources_db=resources_db
        #self.run_slots=run_slots
        #self.run_slots_semaphore=run_slots_semaphore
        self.dynamic_read_timeout = READ_TIMEOUT
        self.__status__=status
        self.maximum_parallel_upload = MAXIMUM_PARALLEL_UPLOAD
        self.recover=recover
        self.working_dirs=working_dirs
        self.client_status=client_status
        self.docker_attach_failed=False
        self.go = go
        if self.go is None and not self.recover:
            raise RuntimeError(f'Execution {execution_id}: go semaphore must be set when not recovering.')
        if not self.recover:
            self.workdir = tempfile.mkdtemp(dir=BASE_WORKDIR)
            self.s.execution_update(execution_id, status='accepted')
            log.warning(f'Workdir is {self.workdir} with base {BASE_WORKDIR}')
            self.input_dir = create_dir(self.workdir, DEFAULT_INPUT_DIR)
            self.output_dir = create_dir(self.workdir, DEFAULT_OUTPUT_DIR)
            self.temp_dir = create_dir(self.workdir, DEFAULT_TEMP_DIR)  
            self.task_resource_dir = create_dir(self.workdir, DEFAULT_RESOURCE_DIR)
            self.container_id=None 
        else:
            self.workdir = workdir
            self.input_dir = input_dir
            self.output_dir = output_dir
            self.temp_dir = temp_dir
            self.container_id = container_id
            self.task_resource_dir = task_resource_dir
        self.working_dirs[execution_id]=self.workdir
        asyncio.run(self.run())


    @classmethod
    def from_docker_container(cls, server, execution_id, task_id, input, output, command,
                container, container_options, execution_queue,
                cpu, resource_dir, resource, resources_db, #run_slots, #run_slots_semaphore, 
                worker_id, status, working_dirs,
                docker_container, client_status ):
        for mount in docker_container['Mounts']:
            if mount['Destination']==DEFAULT_INPUT_DIR:
                input_dir = final_slash(mount['Source'])
            elif mount['Destination']==DEFAULT_OUTPUT_DIR:
                output_dir = final_slash(mount['Source'])
            elif mount['Destination']==DEFAULT_TEMP_DIR:
                temp_dir = final_slash(mount['Source'])
            elif mount['Destination']==DEFAULT_RESOURCE_DIR:
                task_resource_dir = final_slash(mount['Source'])
        workdir='/'.join(input_dir.split('/')[:-2])
        log.warning(f'Workdir was recovered to {workdir}')        
        container_id=docker_container['Id']
        
        return cls(server=server, execution_id=execution_id, task_id=task_id,
            input=input, output=output, command=command, container=container, 
            container_options=container_options, 
            execution_queue=execution_queue, cpu=cpu, resource_dir=resource_dir, 
            resource=resource, resources_db=resources_db, #run_slots=run_slots, 
            #run_slots_semaphore=run_slots_semaphore,
            worker_id=worker_id,
            status=status, working_dirs=working_dirs, recover=True, input_dir=input_dir, output_dir=output_dir,
            temp_dir=temp_dir, workdir=workdir, task_resource_dir=task_resource_dir,
            container_id=container_id, client_status=client_status)

    @property
    def status(self):
        """A wrapper around status multiprocessing.Value, return STATUS_... value
        for this Executor"""
        return self.__status__.value
    
    @status.setter
    def status(self, status_value):
        """A wrapper around status multiprocessing.Value, set status.value as STATUS_"""
        self.__status__.value = status_value

    def post_process_docker_inspect(self, output_files=None):
        """An emergency process to look into docker if possible for more information
        when a process apparently fails - return True if inpection worked, f"""
        if self.container_id is not None:
            log.warning(f'Docker inspecting task {self.task_id}')
            #TODO : try to grab logs in more case, lots of case when this does not work 
            container_inspection_data = docker_inspect(self.container_id)
            if container_inspection_data is not None:
                try:
                    if container_inspection_data['State']['Status']=='exited':
                        log.warning('Docker process was too quick for us but we can inspect what went on')
                        return_code=container_inspection_data['State']['ExitCode']
                        self.status = STATUS_SUCCEEDED if return_code==0 else STATUS_FAILED
                        output,error = docker_logs(self.container_id)
                        self.s.execution_update(
                            self.execution_id, 
                            status='succeeded' if self.status==STATUS_SUCCEEDED else 'failed',
                            output=output,
                            error=error,
                            return_code=return_code,
                            output_files=output_files,
                            freeze=self.status==STATUS_SUCCEEDED
                        )
                        self.process = None

                        if self.status==STATUS_FAILED:
                            log.error(f'... task failed with error code {return_code}')
                        else:
                            log.warning(f'... task succeeded')
                            self.clean()
                            log.warning('Cleaned')

                        return True
                except Exception as e:
                    log.exception(e)
        return False        
    
    # via: https://stackoverflow.com/questions/10756383/timeout-on-subprocess-readline-in-python/34114767?noredirect=1#comment55978734_10756738
    async def execute(self, execution_id):
        # Start child process
        # NOTE: universal_newlines parameter is not supported
        #log.warning(f'Run slots: {self.run_slots.value}')
        #self.run_slots_semaphore.acquire()
        #while self.run_slots.value<=0 and not self.recover:
        #    log.warning(f'Overalocation, worker is out of run slot, have to wait...')
        #    self.run_slots_semaphore.release()
        #    sleep(POLLING_TIME)
        #    self.run_slots_semaphore.acquire()

        self.process = None
        if not self.container:
            try:
                self.process = await asyncio.create_subprocess_exec(
                        *shlex.split(self.command),
                        stdout=PIPE, stderr=PIPE, env={
                            'CPU':str(self.cpu),
                            'INPUT': no_slash(self.input_dir),
                            'OUTPUT': no_slash(self.output_dir),
                            'TEMP': no_slash(self.temp_dir),
                            'RESOURCE': no_slash(self.task_resource_dir)},
                        limit=OUTPUT_LIMIT)
                #self.run_slots.value -= 1
                #self.status = STATUS_RUNNING
                #self.run_slots_semaphore.release()
                self.s.execution_update(execution_id, pid=self.process.pid, status='running')
            except Exception as e:
                self.status = STATUS_FAILED
                #self.run_slots_semaphore.release()
                self.s.execution_error_write(execution_id,
                        traceback.format_exc())
                self.s.execution_update(execution_id, status='failed')
        else:
            # this is the safe way to keep docker process attached while still getting its container id
            try:
                if not self.recover:
                    self.container_id = subprocess.run(docker_command(command=self.command, 
                            container=self.container,
                            input_dir=self.input_dir,
                            output_dir=self.output_dir,
                            temp_dir=self.temp_dir,
                            resource_dir=self.task_resource_dir,
                            cpu=self.cpu,
                            extra_options=self.container_options),
                        shell=False,
                        capture_output=True, check=True).stdout.decode('utf-8').strip()
                self.process = await asyncio.create_subprocess_exec(
                        'docker','attach',self.container_id,
                        stdout=PIPE, stderr=PIPE, limit=OUTPUT_LIMIT)
                #self.status = STATUS_RUNNING
                #self.run_slots.value -= 1
                #self.run_slots_semaphore.release()
                if not self.recover:
                    self.s.execution_update(execution_id, pid=self.container_id, status='running')
            except subprocess.CalledProcessError as e:
                log.warning('Could not attach docker process')
                #self.run_slots_semaphore.release()

                fix_status = False
                if self.container_id is not None:
                    fix_status=self.post_process_docker_inspect()

                if not fix_status:
                    log.error('Finally there was no clue why the execution failed')
                    self.status = STATUS_FAILED
                    self.s.execution_error_write(execution_id,e.stderr.decode('utf-8'))
                    self.s.execution_update(execution_id, status='failed')

            except Exception as e:
                log.error('Could not launch docker and attach it for some reason')
                log.exception(e)
                self.status = STATUS_FAILED
                #self.run_slots_semaphore.release()
                self.s.execution_error_write(execution_id,
                        traceback.format_exc())
                self.s.execution_update(execution_id, status='failed')

                




    async def get_output(self, execution_id):
        # Read line (sequence of bytes ending with b'\n') asynchronously
        output = []
        error = []

        now = time()
        while True:
            try:
                line = (await asyncio.wait_for(self.process.stdout.readline(), self.dynamic_read_timeout)).decode('utf-8')
                if line:
                    output.append(line)
                if time()-now>self.dynamic_read_timeout:
                    break
            except asyncio.TimeoutError:
                break
            except Exception as e:
                error.append(f'During stdout collection this error occured: {traceback.format_exc()}\n' )
                break
        
        if output:
            retry = 2
            while retry > 0:
                try:
                    self.s.execution_output_write(execution_id, ''.join(output))
                    break
                except HTTPException as http_exception:
                    if http_exception.status_code == HTTP_ERROR_CODE_NOT_FOUND:
                        log.error(f'Execution was deleted, must stop at once')
                        self.terminate()
                    else:
                        log.exception(f'Could not write output for {execution_id}:{output} ({http_exception})')
                        retry -= 1    
                except:
                    log.exception(f'Could not write output for {execution_id}:{output}')
                    retry -= 1                

        now = time()
        while True:
            try:
                line = (await asyncio.wait_for(self.process.stderr.readline(), self.dynamic_read_timeout)).decode('utf-8')
                if line:
                    error.append(line)
                if time()-now>self.dynamic_read_timeout:
                    break
            except asyncio.TimeoutError:
                break
            except Exception as e:
                error.append(f'During stderr collection this error occured: {traceback.format_exc()}\n' )
                break
        
        if error:
            retry = 2
            while retry > 0:
                try:
                    joint_error=''.join(error)
                    if joint_error.startswith('You cannot attach to a stopped container'):
                        log.warning('It seems our container failed to attach')
                        self.docker_attach_failed=True
                    self.s.execution_error_write(execution_id,joint_error)
                    break
                except:
                    log.exception(f'Could not write error for {execution_id}:{error}')
                    retry -= 1

        qsize = self.s.queue_size()
        if qsize > QUEUE_SIZE_THRESHOLD:
            self.dynamic_read_timeout += READ_TIMEOUT
        elif qsize == 0 and self.dynamic_read_timeout > READ_TIMEOUT:
            self.dynamic_read_timeout -= READ_TIMEOUT

        return self.process.returncode

    def download_resource(self, data, data_info):
        """A method to properly download resource"""
        self.resources_db[data]={'status':'lock'}
        current_resource_dir = os.path.join(self.resource_dir, str(uuid1()))+'/'
        retry=RETRY_DOWNLOAD
        while True:
            try:
                log.warning(f'Downloading resource {data}...')
                _get(data, current_resource_dir, data_info=data_info, execution_queue=self.execution_queue)
                if data_info is not None:
                    log.warning(f'Modification date is {repr(data_info.modification_date)}')
                    self.resources_db[data]={'status':'loaded',
                                    'date':data_info.modification_date,
                                    'size':data_info.size,
                                    'path':current_resource_dir}
                else:
                    log.warning(f'Resource has no metadata')
                    self.resources_db[data]={'status':'loaded',
                                    'date':None,
                                    'size':None,
                                    'path':current_resource_dir}
                resource_to_json(self.resources_db)
                log.warning(f'... resource {data} downloaded')
                break
            except Exception as e:
                log.exception(f'Somthing failed with resource {data}')
                retry-=1
                if retry>=0:
                    log.warning('Retrying')
                else:
                    self.resources_db[data]={'status':'failed'}
                    log.warning(f'... resource {data} failed!')
                    raise FetchError(f'Could not download resource {data} because of {e}')


    def link_resource(self, path):
        """Hardlink resource files into task resource dir"""
        shutil.copytree(path, self.task_resource_dir, copy_function=force_hard_link, 
                        dirs_exist_ok=True)
            

    def download(self, input=None, resource=None):
        """Do the downloading part, before launching, getting all input URIs into input_dir"""
        if self.status != STATUS_RUNNING:
            log.warning('Downloading input data...')
            self.status = STATUS_DOWNLOADING
        else:
            log.warning('Checking previous downloads...')
        if input is None:
            input = self.input.split() if self.input else []
        if resource is None:
            resource = self.resource.split() if self.resource else []
        current_input = list(input)
        retry=RETRY_DOWNLOAD
        last_exception = None
        while current_input and retry>0:
            failed_input = []
            for data in current_input:
                try:
                    _get(data, self.input_dir, execution_queue=self.execution_queue)
                except Exception as e:
                    log.exception(e)
                    last_exception=e
                    failed_input.append(data)
            if failed_input:
                current_input=failed_input
                retry -= 1
                if retry>0:
                    continue
                else:
                    if last_exception is not None:
                        raise last_exception
                    else:
                        raise RuntimeError(f'Cannot download these data {failed_input}')
            else:
                break
        if resource:
            log.warning('Acquiring resources')
            log.warning(f'Resourcedb:  {self.resources_db}')
            for data in resource:
                try:
                    data_info = info(data)
                except UnsupportedError:
                    data_info = None
                if data not in self.resources_db or self.resources_db[data]['status']=='failed' or (
                            self.resources_db[data]['status']=='loaded' and 
                            ( data_info is not None and (
                                    self.resources_db[data]['date'] is None or 
                                    data_info.modification_date > self.resources_db[data]['date'] or
                                    data_info.size != self.resources_db[data]['size'] )
                            )
                        ):
                    self.download_resource(data, data_info)
                else:
                    log.warning(f'Resource {data} is already there')
            while True:
                for data in resource:
                    if self.resources_db[data]['status']=='lock':
                        log.warning(f'Waiting for resource {data}...')
                        sleep(POLLING_TIME)
                        break
                else:
                    log.warning(f'All resource seems there')
                    break
            for data in resource:
                if self.resources_db[data]['status']=='failed':
                    self.resources_db[data]={'status':'lock'}
                    log.warning(f'Trying again to download resource {data}...')
                    try:
                        data_info = info(data)
                    except UnsupportedError:
                        data_info = None
                    self.download_resource(data, data_info)
                data_info = self.resources_db[data]
                self.link_resource(data_info['path'])
                

    def upload(self):
        """Do the uploading part at the end, getting all output into output URI"""
        log.warning('Uploading output results...')
        if self.output:
            output_files = []
            retry = RETRY_UPLOAD
            while retry>0:
                try:
                    jobs = {}
                    transfer_failed = False
                    with concurrent.futures.ProcessPoolExecutor(max_workers=self.maximum_parallel_upload) as executor:
                        for root, _, files in os.walk(self.output_dir):
                            rel_path = os.path.relpath(root, self.output_dir)
                            for local_data in files:
                                data = os.path.join(root, local_data)
                                if not os.path.islink(data) and not isfifo(data) and data not in output_files:
                                    jobs[executor.submit(put, data, pathjoin(self.output,rel_path,'/'))]=data
                                else:
                                    if data in output_files:
                                        log.warning(f'Passing {data} as it is already transfered')
                                    elif os.path.islink(data):
                                        log.warning(f'{local_data} is ignored as it is a symbolic link.')
                                    elif isfifo(data):
                                        log.warning(f'{local_data} is ignored as it is a FIFO (named pipe).')
                        for job in concurrent.futures.as_completed(jobs):
                            obj = jobs[job]
                            if job.exception() is not None:
                                transfer_failed = True
                                log.warning(f'Transfer failed for {obj}: {job.exception()}')
                                log.exception(job.exception())
                                latest_exception = job.exception()
                            else:
                                log.warning(f'Transfer done for {obj}: {job.result()}')
                                output_files.append(obj)
                    if transfer_failed:
                        log.error(f'Upload partially failed for task {self.task_id}')
                        if self.maximum_parallel_upload>1:
                            self.maximum_parallel_upload -= 1
                            log.warning(f'Reducing parallel upload to {self.maximum_parallel_upload}')
                        retry -= 1
                        if retry<=0:
                            raise latest_exception
                        else:
                            continue
                    if output_files:
                        return ' '.join(output_files)
                    else:
                        return None
                except Exception as e:
                    log.error(f'Upload failed for task {self.task_id}')
                    if self.maximum_parallel_upload>1:
                        self.maximum_parallel_upload -= 1
                    log.warning(f'Reducing parallel upload to {self.maximum_parallel_upload}')
                    log.exception(e)
                    retry -= 1
                    if retry<=0:
                        raise
    
    def clean(self):
        """Clean working directory (triggered if all went well)"""
        shutil.rmtree(self.workdir)
        del(self.working_dirs[self.execution_id])
        if self.container_id is not None:
            subprocess.run(['docker','container','rm',self.container_id], check=True)


    def terminate(self):
        """End current process as soon as possible - should be only called from the Executor process"""
        if self.status == "running":
            if self.container_id:
                subprocess.run(['docker','kill',self.container_id])
            else:
                self.process.send_signal(SIGKILL)
        killing_time = time()
        while True:
            sleep(POLLING_TIME)
            if self.process.returncode is not None:
                break
            if time() - killing_time > ZOMBIE_TIMEOUT:
                log.exception(f"No I would rather suicide than becoming a zombie...")
                break
        self.clean()
        sys.exit(1)

        
    async def run(self):
        """Launching part of Executor
        """
        log.warning(f'Running job {self.execution_id}: {self.command}')
        #self.execution_started.release()
        
        if not self.recover:
            # initialisation is only done if task is not recovered
            try:
                self.download()
            except Exception as e:
                log.exception(e)
                self.s.execution_error_write(self.execution_id,
                    traceback.format_exc())
                returncode=-1001
                self.status = STATUS_FAILED
                self.s.execution_update(self.execution_id, 
                    status='failed', 
                    return_code=returncode, output='')
                return None
        
            #self.run_slots_semaphore.acquire()
            self.status = STATUS_WAITING
            #self.run_slots_semaphore.release()
            
            try:
                self.go.acquire()
                self.status = STATUS_RUNNING
                log.warning(f'Execution {self.execution_id} is now running')

                task = self.s.task_freeze(self.task_id, self.execution_id)

                # let check our command
                self.command = task.command
                self.output = task.output
                self.container = task.container
                self.container_options = task.container_options
                

            except HTTPException:
                # the task was deleted so we bail out
                log.error(f'Task {self.task_id} was deleted.')
                self.clean()
                #self.run_slots_semaphore.release()
                return None
        
            try:
                # check a last time that this task is for us
                if self.s.execution_get(self.execution_id).status == 'failed':
                    # the task is no longer for us so we bail out
                    log.error(f'Execution {self.execution_id} was cancelled.')
                    self.clean()
                    #self.run_slots_semaphore.release()
                    return None
            except HTTPException as http_exception:
                if http_exception.status_code == HTTP_ERROR_CODE_NOT_FOUND:
                    log.error(f'Execution {self.execution_id} was deleted.')
                    self.clean()
                    #self.run_slots_semaphore.release()
                    return None
                else:
                    log.error(f'Unhandled http exception {http_exception}')
                    self.clean()
                    #self.run_slots_semaphore.release()
                    raise
        
            new_input = []
            if task.input != self.input:
                log.warning(f'Input has changed while waiting for task {self.task_id}, adjusting.')
                if task.input:
                    new_input = task.input.split()
                if self.input:
                    old_input = self.input.split()
                else:
                    old_input = []
                for item in old_input:
                    if item in new_input:
                        new_input.remove(item)
                    else:
                        if '/' in item_file:
                            item_file = item.split('/')[-1]
                        else:
                            item_file = item
                        if os.path.exists(os.path.join(self.input_dir, item_file)):
                            os.remove(os.path.join(self.input_dir, item_file))
                self.input = task.input
            
            self.resource = task.resource                    

            # we systematically check now for resource update 
            self.download(input=new_input)
            log.warning(f'Launching job {self.execution_id}: {self.command}')
        else:
            #self.run_slots_semaphore.acquire()
            log.warning(f'Recovering job {self.execution_id}: {self.command}')
            
        await self.execute(execution_id=self.execution_id)
        #self.run_slots_semaphore.release()

        if not self.process is None:
            log.warning('Launched')
            while True:
                log.warning(f"... {self.execution_id} ...")
                returncode = await self.get_output(self.execution_id)
                log.warning("...")
                if returncode is not None:
                    log.warning('... done')
                    await self.get_output(self.execution_id)

                    log.warning(f'Task {self.execution_id} '+'succeeded' if returncode==0 else 'failed')
                    #self.run_slots_semaphore.acquire()
                    self.__status__.value = STATUS_UPLOADING
                    #self.run_slots.value += 1
                    #self.run_slots_semaphore.release()

                    try:
                        output_files = self.upload()
                    except Exception as e:
                        output_files = ''
                        self.s.execution_error_write(self.execution_id,
                            traceback.format_exc())
                        returncode=-1000
                    
                    self.status = STATUS_SUCCEEDED if returncode==0 else STATUS_FAILED
                    if self.status == STATUS_FAILED and self.docker_attach_failed:
                        log.warning('Trying to see if status can be enhanced with docker')
                        self.post_process_docker_inspect(output_files=output_files)
                    else:
                        self.s.execution_update(self.execution_id, 
                            status='succeeded' if returncode==0 else 'failed', 
                            return_code=returncode, 
                            output_files=None if output_files is None else ' '.join([os.path.relpath(of, self.output_dir) for of in output_files.split(' ')]),
                            freeze=returncode==0)
                    
                        if returncode!=0:
                            log.error(f'... task failed with error code {returncode}')
                        else:
                            log.warning(f'... task succeeded')
                            self.clean()
                            log.warning('Cleaned')
                    #log.warning(f'Run slots: {self.run_slots.value}')

                    break
                else:
                    try:
                        signal=self.execution_queue.get(block=False)
                        if self.container:
                            # sending a signal on the docker run process itself will not have any effect
                            # we must launch another process to send the signal to docker service instead
                            if self.container_id:
                                if signal == SIGTERM:
                                    subprocess.run(['docker','stop',self.container_id])
                                elif signal == SIGKILL:
                                    subprocess.run(['docker','kill',self.container_id])
                                elif signal == SIGTSTP:
                                    subprocess.run(['docker','pause',self.container_id])
                                elif signal == SIGCONT:
                                    subprocess.run(['docker','unpause',self.container_id])
                                else:
                                    log.warning(f'Cannot launch signal {signal} with docker...')
                        else:
                            self.process.send_signal(signal)
                        log.warning(f'...signal {signal} sent')    

                    except queue.Empty:
                        pass

class Client:
    def __init__(self, server, concurrency, name, batch, autoclean, flavor):
        self.s = Server(server, style='object')
        self.server = server
        self.concurrency = concurrency
        self.prefetch = 0
        self.hostname = socket.gethostname()
        self.batch = batch
        self.flavor = flavor
        if name is None:
            self.name = self.hostname
        else:
            self.name = name
        self.process = None
        self.executions = {}
        self.declare()
        self.has_worked = False
        self.idle_time = None
        self.manager = multiprocessing.Manager()
        self.resources_db = self.manager.dict()
        self.working_dirs = self.manager.dict()
        json_to_resource(self.resources_db)
        for key,item in self.resources_db.items():
            if item['status']=='lock':
                log.warning(f'{key} is marked as locked in resource, removing')
                del self.resources_db[key]
        self.resource_dir = os.path.join(BASE_RESOURCE_DIR, RESOURCE_FILES_SUBDIR)
        if not os.path.exists(self.resource_dir):
            os.makedirs(self.resource_dir)
        #self.run_slots = multiprocessing.Value('i', concurrency)
        self.shared_status = multiprocessing.Value('i', client_status_code(DEFAULT_WORKER_STATUS))
        #self.run_slots_semaphore = multiprocessing.BoundedSemaphore()
        #self.has_run_slots_semaphore=False
        self.executions_status = {}
        self.ref_disk = self.ref_network = None
        self.autoclean = autoclean
        self.executions_go = {}
        self.zombie_executions = {}


    def declare(self):
        """Declare a new worker or reconnect to the old one."""
        for worker in self.s.workers():
            if worker.name == self.name and worker.hostname == self.hostname:
                self.concurrency = worker.concurrency
                self.prefetch = worker.prefetch
                self.w=worker
                break
        else:
            self.w = self.s.worker_create(name=self.name,
                concurrency=self.concurrency,
                prefetch=self.prefetch,
                hostname=self.hostname,
                batch=self.batch,
                permanent=SCITQ_PERMANENT_WORKER)
        threading.Thread(target=monitor_events, 
                                kwargs={'server': self.server, 
                                        'provider':self.w.provider, 
                                        'worker_id':self.w.worker_id}
                                ).start()

    def clean_all(self):
        """Clean all unused directory"""
        log.warning(f'Working_dirs are {self.working_dirs.values()}')
        for dir in os.listdir(BASE_WORKDIR):
            full_dir = os.path.join(BASE_WORKDIR, dir)
            if full_dir==BASE_RESOURCE_DIR:
                continue
            for working_dir in self.working_dirs.values():
                if full_dir==working_dir:
                    break
            else:
                if os.path.isdir(full_dir):
                    log.warning(f'Removing dir {full_dir}')
                    shutil.rmtree(full_dir)

    def clean_oldest(self):
        """Clean the oldest unused directory"""
        dirs = [(os.stat(dir).st_mtime,dir) for dir in 
            [os.path.join(BASE_WORKDIR, dir) for dir in os.listdir(BASE_WORKDIR)]
        ]
        dirs.sort(reverse=True)
        log.warning(f'Dirs are {dirs}')
        for _,full_dir in dirs:
            if full_dir==BASE_RESOURCE_DIR:
                continue
            for working_dir in self.working_dirs.values():
                if full_dir==working_dir:
                    break
            else:
                if os.path.isdir(full_dir):
                    log.warning(f'Removing dir {full_dir}')
                    shutil.rmtree(full_dir)
                    break

    def clean_execution(self, execution_id):
        """Called when an execution is dead (or has become a zombie)"""
        del(self.executions[execution_id])
        del(self.executions_status[execution_id])
        if execution_id in self.working_dirs:
            del(self.working_dirs[execution_id])

    def run(self, status=DEFAULT_WORKER_STATUS):
        """Main loop of the client"""
        self.w = self.s.worker_update(self.w.worker_id, status=status, flavor=self.flavor)
        self.task_properties = json.loads(self.w.task_properties)
        log.warning(f'Task properties are {repr(self.task_properties)}')
        cpu_list=[]
        previous_disk = previous_network = None
        previous_time = None
        while True:
            try:
                try:
                    current_time = time()
                    memory=psutil.virtual_memory().percent
                    partitions=[part for part in psutil.disk_partitions() 
                                if not part.mountpoint.startswith('/snap/') and
                                  not part.mountpoint.startswith('/boot') and
                                  not part.mountpoint.startswith('/System')]
                    
                    # removes device that we see several times (i.e. bind mount)
                    seen_devices=[]
                    for part in list(partitions):
                        if part.device not in seen_devices:
                            seen_devices.append(part.device)
                        else:
                            partitions.remove(part)
                    
                    disk_usage=[(part.mountpoint,psutil.disk_usage(part.mountpoint).percent) 
                                for part in partitions]
                    scratch_usage = None
                    for disk,usage in disk_usage:
                        if disk=='/' and scratch_usage is None:
                            scratch_usage = usage
                        elif BASE_WORKDIR.startswith(disk):
                            scratch_usage = usage
                    
                    if scratch_usage and scratch_usage >= self.autoclean:
                        log.warning(f'Workdir is full ({scratch_usage}>{self.autoclean}), autocleaning')
                        self.clean_oldest()


                    network = (lambda x: (x.bytes_sent,x.bytes_recv))(
                                    psutil.net_io_counters())
                    if self.ref_network is None:
                        self.ref_network = network
                    disk = (lambda x: (x.read_bytes,x.write_bytes)) (
                        psutil.disk_io_counters(perdisk=False, nowrap=True))
                    if self.ref_disk is None:
                        self.ref_disk = disk
                    load = psutil.getloadavg()

                    if previous_time is not None:
                        duration = current_time - previous_time
                        disk_speed = speed(previous_disk, disk, duration)
                        network_speed = speed(previous_network, network, duration)
                    else:
                        disk_speed = ('-','-')
                        network_speed = ('-', '-')

                    worker_stats = { 
                        'load':' '.join(map(lambda x: str(round(x,1)),load)),
                        'disk': {
                            'speed': '/'.join(map(bytes2mb, disk_speed))
                                        + ' Mb/s',
                            'usage': tuple(map(lambda x: f'{x[0]}:{x[1]:.0f}',disk_usage)),
                            'counter': '/'.join(map(bytes2gb, 
                                        relative(disk,self.ref_disk)))
                                    + ' Gb'
                        },
                        'network': {
                            'speed': '/'.join(map(bytes2mb,network_speed))
                                    + ' Mb/s',
                            'counter': '/'.join(map(bytes2gb,
                                                relative(network,
                                                            self.ref_network)))
                                    + ' Gb'
                        } 
                    }

                    #CPU1,CPU5,CPU15 = [round((x / psutil.cpu_count()) *100,2) for x in psutil.getloadavg()]
                    cpus = psutil.cpu_times_percent()
                    cpu_list.append(cpus.user)
                    while len(cpu_list)>= CPU_MAX_VALUE:
                        cpu_list.pop(0)
                    cpu_string = f'{cpus.user}'+ ('↑' if cpus.user >= sum(cpu_list)/len(cpu_list) else '↓')
                    if  platform.system() =='Linux':
                        cpu_string += f' / {cpus.iowait}'
                    log.warning(f'CPU is {cpu_string}')
                    self.w=self.s.worker_ping(self.w.worker_id, cpu_string, memory, 
                                              json.dumps(worker_stats))
                    self.task_properties = json.loads(self.w.task_properties)
                    if client_status_code(self.w.status)!=self.shared_status.value:
                        log.warning(f'Client status was changed to {self.w.status}')
                        self.shared_status.value = client_status_code(self.w.status)

                    previous_time = current_time
                    previous_disk = disk
                    previous_network = network
                    ##self.w=self.s.worker_ping(self.w.worker_id, load = ' '.join(map(
                        #lambda x: str(int(x*100)),psutil.getloadavg())))
                    ##
                except HTTPException as e:
                    log.exception(e)
                    if e.status_code==404:
                        self.declare()
                        continue
                if self.w.concurrency != self.concurrency:
                    #self.run_slots_semaphore.acquire()
                    #self.has_run_slots_semaphore=True
                    #self.run_slots.value += self.w.concurrency-self.concurrency
                    #self.run_slots_semaphore.release()
                    #self.has_run_slots_semaphore=False
                    #log.warning(f'Concurrency changed from {self.concurrency} to {self.w.concurrency}, adjusting run slots: {self.run_slots.value}')
                    log.warning(f'Concurrency changed from {self.concurrency} to {self.w.concurrency} with task properties {self.task_properties}')
                    self.concurrency = self.w.concurrency
                if self.prefetch != self.w.prefetch:
                    log.warning(f'Prefetch changed from {self.prefetch} to {self.w.prefetch}')
                    self.prefetch = self.w.prefetch
                if self.w.status=='running':
                    executions=self.s.worker_executions(self.w.worker_id, status='pending')
                    for execution in executions:
                        if execution.execution_id not in self.executions:
                            task = self.s.task_get(execution.task_id)
                            #execution_started = multiprocessing.Semaphore(0)
                            self.executions_go[execution.execution_id] = multiprocessing.Semaphore(0)
                            execution_queue = multiprocessing.Queue()
                            self.executions_status[execution.execution_id]=self.manager.Value(
                                                    'I', 
                                                    value=STATUS_LAUNCHING)
                            p=multiprocessing.Process(target=Executor,
                                kwargs={
                                    'server': self.server,
                                    'execution_id': execution.execution_id,
                                    'task_id': task.task_id,
                                    'command': task.command,
                                    'input': task.input,
                                    'output': task.output,
                                    #'execution_started': execution_started,
                                    'execution_queue': execution_queue,
                                    'container': task.container,
                                    'container_options': task.container_options,
                                    'cpu': max(1,
                                               psutil.cpu_count()//self.w.concurrency if self.w.concurrency>0 else psutil.cpu_count()),
                                    'resource_dir': self.resource_dir,
                                    'resource': task.resource,
                                    'resources_db': self.resources_db,
                                    #'run_slots': self.run_slots,
                                    #'run_slots_semaphore': self.run_slots_semaphore,
                                    'worker_id': self.w.worker_id,
                                    'status': self.executions_status[execution.execution_id],
                                    'working_dirs': self.working_dirs,
                                    'client_status': self.shared_status,
                                    'go': self.executions_go[execution.execution_id]
                                })
                            p.start()
                            self.executions[execution.execution_id]=(p,execution_queue)
                            self.has_worked = True
                            self.idle_time = None
                            #log.info('Waiting for execution to start')
                            #execution_started.acquire()
                            log.info('Execution started')
                    if not(self.executions):
                        now = time()
                        if self.idle_time is None:
                            self.idle_time=now
                        elif now-self.idle_time > WAIT_FOR_FIRST_EXECUTION_TIMEOUT or \
                                (now-self.idle_time > IDLE_TIMEOUT and self.has_worked):
                            self.s.worker_callback(self.w.worker_id, message = "idle")
                            self.idle_time = None
                for signal in self.s.worker_signals(self.w.worker_id):
                    if signal.execution_id in self.executions:
                        log.warning(f'Sending signal {signal.signal} to execution {signal.execution_id}')
                        self.executions[signal.execution_id][1].put(signal.signal)
                    elif signal.execution_id is None:
                        if signal.signal == SIGNAL_CLEAN:
                            log.warning('Received cleaning signal, cleaning.')
                            self.clean_all()
                        elif signal.signal == SIGNAL_RESTART:
                            log.warning('Received reloading signal, quitting to reload.')
                            #self.run_slots_semaphore.acquire()
                            #self.has_run_slots_semaphore=True
                            while True:
                                for execution, status in self.executions_status.items():
                                    if status.value == 'UPLOADING':
                                        #self.run_slots_semaphore.release()
                                        #self.has_run_slots_semaphore=False
                                        log.warning('This is not a good time to die, somebody is uploading...')
                                        sleep(POLLING_TIME)
                                        break
                                else:
                                    break
                            os.execv(sys.executable, [sys.executable,'-m', 'scitq.client']+sys.argv[1:])
                        elif signal.signal == SIGNAL_RESET_RESOURCES:
                            log.warning('Received reset resource signal, forgetting resources')
                            for resource in self.resources_db.keys():
                                del(self.resources_db[resource])
                    else:
                        log.warning(f'Execution {signal.execution_id} is not running in this worker')
                for execution_id in list(self.executions.keys()):
                    if not self.executions[execution_id][0].is_alive():
                        self.clean_execution(execution_id)
                #if self.run_slots_semaphore.acquire():
                #    self.has_run_slots_semaphore=True
                #running_executions = [ execution_id 
                #        for execution_id, execution_status in self.executions_status.items()
                #        if execution_status.value==STATUS_RUNNING ]
                log.warning(f'Status are { {execution_id:STATUS_TXT[execution_status.value] for execution_id, execution_status in self.executions_status.items()} }')
                #if self.concurrency-len(running_executions)!=self.run_slots.value:
                    #log.warning(f'Race condition detected on process number')
                    # ok time to look what is really going on
                    
                running = waiting = 0
                executions_from_server = list(self.s.worker_executions(self.w.worker_id))
                executions_ready_to_go = []
                for execution in executions_from_server:
                    if execution.execution_id not in self.executions_status:
                        if execution.status=='accepted':
                            log.error(f'Execution {execution.execution_id} was being downloaded but is gone so I will get it again')
                            self.s.execution_update(execution.execution_id, status='pending')
                        elif execution.status=='running':
                            task = self.s.task_get(execution.task_id)
                            if task.container:
                                container=docker_inspect(execution.pid)
                                if container is not None:
                                    log.warning(f'Execution {execution.execution_id} is still alive')
                                    #execution_started = multiprocessing.Semaphore(0)
                                    execution_queue = multiprocessing.Queue()
                                    self.executions_status[execution.execution_id]=self.manager.Value(
                                                            'I', 
                                                            value=STATUS_RUNNING)
                                    p=multiprocessing.Process(target=Executor.from_docker_container,
                                        kwargs={
                                            'server': self.server,
                                            'execution_id': execution.execution_id,
                                            'task_id': task.task_id,
                                            'command': task.command,
                                            'input': task.input,
                                            'output': task.output,
                                            #'execution_started': execution_started,
                                            'execution_queue': execution_queue,
                                            'container': task.container,
                                            'container_options': task.container_options,
                                            'cpu': max(1,
                                               psutil.cpu_count()//self.w.concurrency if self.w.concurrency>0 else psutil.cpu_count()),
                                            'resource_dir': self.resource_dir,
                                            'resource': task.resource,
                                            'resources_db': self.resources_db,
                                            #'run_slots': self.run_slots,
                                            #'run_slots_semaphore': self.run_slots_semaphore,
                                            'worker_id': self.w.worker_id,
                                            'status': self.executions_status[execution.execution_id],
                                            'working_dirs': self.working_dirs,
                                            'docker_container': container,
                                            'client_status': self.shared_status,
                                        })
                                    p.start()
                                    self.executions[execution.execution_id]=(p,execution_queue)
                                    self.has_worked = True
                                    self.idle_time = None
                                    #log.info('Waiting for execution to recover')
                                    #execution_started.acquire()
                                    log.info('Execution recovered')
                                else:
                                    log.error(f'Execution {execution.execution_id} seems to have gone away...')
                                    self.s.execution_update(execution.execution_id, status='failed')
                            else:
                                log.error(f'Execution {execution.execution_id} seems to have gone away...')
                                self.s.execution_update(execution.execution_id, status='failed')
                        continue

                    status = self.executions_status[execution.execution_id].value
                    weight, priority = self.task_properties.get(execution.batch, (1,0) )
                    if status == STATUS_RUNNING:
                        # here we count not the number of tasks but the weight of tasks
                        running += weight
                    elif status in [STATUS_WAITING, STATUS_LAUNCHING, STATUS_DOWNLOADING]:
                        waiting += 1
                        if status == STATUS_WAITING and execution.taskstatus != 'paused':
                            executions_ready_to_go.append( (priority, weight, execution.execution_id) )
                    if execution.status=='running' and status not in  [STATUS_RUNNING, STATUS_UPLOADING, STATUS_LAUNCHING]:
                        log.warning(f'Execution {execution.execution_id} is supposed to be running and is not ({STATUS_TXT[status]}).')
                    elif execution.status=='accepted' and status not in [STATUS_WAITING, STATUS_LAUNCHING, STATUS_DOWNLOADING]:
                        log.warning(f'Execution {execution.execution_id} is supposed to be accepted and is not ({STATUS_TXT[status]}).')
                if running>self.concurrency:
                    log.warning(f'We are supposed to have {self.concurrency} running processes and we have {running}')
                elif running<self.concurrency and self.w.status=='running':
                    executions_ready_to_go.sort(reverse=True)
                    for _,weight,execution_id in executions_ready_to_go:
                        if self.concurrency - running >= weight:
                            running += weight
                            log.warning(f'Releasing execution {execution_id}')
                            self.executions_go[execution_id].release()
                            #self.executions_status[execution_id].value=STATUS_RUNNING
                            while self.executions_status[execution_id].value == STATUS_WAITING:
                                sleep(0.2)
                                log.warning('Waiting for execution to start')
                            log.warning(f'Execution {execution_id} is now {STATUS_TXT[self.executions_status[execution_id].value]}')
                        else:
                            break
                if waiting>self.prefetch:
                    log.warning(f'We are supposed to have {self.prefetch} waiting processes and we have {waiting}')    
                if running+waiting > self.concurrency+self.prefetch:
                    log.warning(f'Overall we should have at max {self.concurrency+self.prefetch} processes and we have {running+waiting}')
                #if self.run_slots.value != self.concurrency - running:
                #    log.warning(f'Run slot derived, reseting from {self.run_slots.value} to {self.concurrency-running}')
                #    self.run_slots.value = self.concurrency - running
                if self.executions_status:
                    executions_ids = list([execution.execution_id for execution in executions_from_server])
                    for execution_id in self.executions_status.keys():
                        if execution_id not in executions_ids and self.executions_status[execution_id].value == STATUS_RUNNING:
                            log.warning(f'Execution {execution_id} is still running but is no more assigned to us (or likely was deleted), sending SIGTERM signal')
                            self.executions[execution_id][1].put(SIGTERM)
                            if execution_id not in self.zombie_executions:
                                self.zombie_executions[execution_id]=current_time
                            elif current_time - self.zombie_executions[execution_id] > ZOMBIE_TIMEOUT:
                                self.clean_execution(execution_id)
                                log.exception(f'Execution {execution_id} has become a zombie')
                                del(self.zombie_executions[execution_id])
                        if execution_id not in executions_ids and self.executions_status[execution_id].value == STATUS_WAITING:
                            log.warning(f'Execution {execution_id} is waiting but is no more assigned to us (or likely was deleted), releasing it to its death')
                            self.executions_go[execution_id].release()

                #self.run_slots_semaphore.release()
                #self.has_run_slots_semaphore=False
                #else:
                #    log.warning('Cannot estimate process number, giving up.')
            except Exception as e:
                log.exception('An exception occured during worker main loop')
                #if self.has_run_slots_semaphore:
                #    log.warning('Releasing run slots semaphore')
                #    self.run_slots_semaphore.release()
                #    self.has_run_slots_semaphore=False
            sleep(POLLING_TIME)
            
                
                    

def main():
    parser = argparse.ArgumentParser(description='scitq client')
    parser.add_argument('server', type=str,
                    help='IP address of the server')
    parser.add_argument('concurrency', type=int,
                    help='How many processes should be initially started')
    parser.add_argument('-n','--name', type=str, default=None,
                help="Give a name to the worker, default to hostname")
    parser.add_argument('-s','--status', type=str, default=DEFAULT_WORKER_STATUS,
            help=f"Give a name to the worker, default to hostname, default to {DEFAULT_WORKER_STATUS}")
    parser.add_argument('-b','--batch', type=str, default=None,
            help=f"Assign the worker to a default batch (default to None, the default batch)")
    parser.add_argument('-a','--autoclean', type=int, default=DEFAULT_AUTOCLEAN,
            help=f"Clean failures when disk is full up to this %% (default to {DEFAULT_AUTOCLEAN})")
    parser.add_argument('-f','--flavor', type=str, default=None,
            help=f"Update the declared flavor of this client to this value (otherwise keep the default value)")
    args = parser.parse_args()
    
    Client(
        server=args.server, 
        concurrency=args.concurrency, 
        name=args.name,
        batch=args.batch,
        autoclean=args.autoclean,
        flavor=args.flavor,
    ).run(status=args.status)
    

if __name__=="__main__":
    main()
    