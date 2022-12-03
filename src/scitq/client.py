import argparse
from re import L
from .lib import Server, HTTPException
import socket
from time import sleep, time
import multiprocessing
import queue
import asyncio
from asyncio.subprocess import PIPE
import logging as log
import os
import psutil 
import platform
import queue
import tempfile
from .fetch import get,put,pathjoin
import traceback
import shutil
import subprocess
from signal import SIGTERM, SIGKILL, SIGTSTP, SIGCONT
import shlex

CPU_MAX_VALUE =10
POLLING_TIME = 4
READ_TIMEOUT = 5
QUEUE_SIZE_THRESHOLD = 2
IDLE_TIMEOUT = 600
DEFAULT_WORKER_STATUS = "running"
BASE_WORKDIR = os.environ.get("BASE_WORKDIR", 
    "/tmp" if platform.system() in ['Windows','Darwin'] else "/scratch")
BASE_RESOURCE_DIR = os.path.join(BASE_WORKDIR,'resource')

if not os.path.exists(BASE_RESOURCE_DIR):
    os.mkdir(BASE_RESOURCE_DIR)

DEFAULT_INPUT_DIR = '/input'
DEFAULT_OUTPUT_DIR = '/output'
DEFAULT_RESOURCE_DIR = '/resource'
DEFAULT_TEMP_DIR = '/tmp'
OUTPUT_LIMIT = 1024 * 128

def docker_command(input_dir, output_dir, temp_dir, resource_dir, cpu, extra_options,
        container, command):
    docker_cmd = ['docker','run', '--rm', '-d']
    if os.path.exists('/data'):
        docker_cmd.extend(['-v', '/data:/data'])
    docker_cmd.extend([
        '-v', f'{input_dir}:{DEFAULT_INPUT_DIR}',
        '-v', f'{output_dir}:{DEFAULT_OUTPUT_DIR}',
        '-v', f'{temp_dir}:{DEFAULT_TEMP_DIR}',
        '-v', f'{resource_dir}:{DEFAULT_RESOURCE_DIR}',
        '-e', f'CPU={str(cpu)}'])
    docker_cmd.extend(shlex.split(extra_options))
    docker_cmd.append(container)
    docker_cmd.extend(shlex.split(command)) 
    log.warning(f'Final docker command: {" ".join(docker_cmd)}')
    return docker_cmd

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

class Executor:
    """Executor represent the process in which the task is launched, it is also
    designed to monitor the task and grab its output to push it regularly to the
    server.
    It performs now preparation tasks and post operation tasks."""

    def __init__(self, server, execution_id, task_id, command, input, output, 
                container, container_options, execution_started, execution_queue,
                cpu, resource_dir, resource, resources_db, run_slots, run_slots_semaphore,
                worker_id):
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
        self.execution_started = execution_started
        self.execution_queue = execution_queue
        self.resource_dir = final_slash(resource_dir)
        self.workdir = tempfile.mkdtemp(dir=BASE_WORKDIR)
        log.warning(f'Workdir is {self.workdir} with base {BASE_WORKDIR}')
        self.input_dir = create_dir(self.workdir, DEFAULT_INPUT_DIR)
        self.output_dir = create_dir(self.workdir, DEFAULT_OUTPUT_DIR)
        self.temp_dir = create_dir(self.workdir, DEFAULT_TEMP_DIR)   
        self.cpu=cpu 
        self.resource=resource
        self.resources_db=resources_db
        self.run_slots=run_slots
        self.run_slots_semaphore=run_slots_semaphore
        self.container_id=None
        self.dynamic_read_timeout = READ_TIMEOUT
        asyncio.run(self.run())

    # via: https://stackoverflow.com/questions/10756383/timeout-on-subprocess-readline-in-python/34114767?noredirect=1#comment55978734_10756738
    async def execute(self, execution_id):
        # Start child process
        # NOTE: universal_newlines parameter is not supported
        log.warning(f'Run slots: {self.run_slots.value}')
        while self.run_slots.value<=0:
            log.warning(f'Overalocation, worker is out of run slot, have to wait...')
            self.run_slots_semaphore.release()
            sleep(POLLING_TIME)
            self.run_slots_semaphore.acquire()

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
                            'RESOURCE': no_slash(self.resource_dir)},
                        limit=OUTPUT_LIMIT)
                self.run_slots.value -= 1
                self.s.execution_update(execution_id, pid=self.process.pid, status='running')
            except Exception as e:
                self.s.execution_error_write(execution_id,
                        traceback.format_exc())
                self.s.execution_update(execution_id, status='failed')
        else:
            # this is the safe way to keep docker process attached while still getting its container id
            try:
                self.container_id = subprocess.run(docker_command(command=self.command, 
                        container=self.container,
                        input_dir=self.input_dir,
                        output_dir=self.output_dir,
                        temp_dir=self.temp_dir,
                        resource_dir=self.resource_dir,
                        cpu=self.cpu,
                        extra_options=self.container_options),
                    shell=False,
                    capture_output=True, check=True).stdout.decode('utf-8').strip()
                self.process = await asyncio.create_subprocess_exec(
                        'docker','attach',self.container_id,
                        stdout=PIPE, stderr=PIPE, limit=OUTPUT_LIMIT)
                self.run_slots.value -= 1
                self.s.execution_update(execution_id, pid=self.process.pid, status='running')
            except subprocess.CalledProcessError as e:
                self.s.execution_error_write(execution_id,e.stderr.decode('utf-8'))
                self.s.execution_update(execution_id, status='failed')
            except Exception as e:
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
                output.append(
                    (await asyncio.wait_for(self.process.stdout.readline(), self.dynamic_read_timeout)).decode('utf-8')
                )
                if time()-now>self.dynamic_read_timeout:
                    break
            except asyncio.TimeoutError:
                break
            except Exception as e:
                error.append(f'During stdout collection this error occured: {traceback.format_exc()}\n' )
                break
        self.s.execution_output_write(execution_id, ''.join(output))

        now = time()
        while True:
            try:
                error.append(
                    (await asyncio.wait_for(self.process.stderr.readline(), self.dynamic_read_timeout)).decode('utf-8')
                )
                if time()-now>self.dynamic_read_timeout:
                    break
            except asyncio.TimeoutError:
                break
            except Exception as e:
                error.append(f'During stderr collection this error occured: {traceback.format_exc()}\n' )
                break
        self.s.execution_error_write(execution_id,''.join(error))

        qsize = self.s.queue_size()
        if qsize > QUEUE_SIZE_THRESHOLD:
            self.dynamic_read_timeout += READ_TIMEOUT
        elif qsize == 0 and self.dynamic_read_timeout > READ_TIMEOUT:
            self.dynamic_read_timeout -= READ_TIMEOUT

        return self.process.returncode

    def download(self):
        """Do the downloading part, before launching, getting all input URIs into input_dir"""
        log.warning('Downloading input data...')
        if self.input:
            for data in self.input.split():
                get(data, self.input_dir)
        if self.resource:
            log.warning('Acquiring resources')
            log.warning(f'Resourcedb:  {self.resources_db}')
            for data in self.resource.split():
                if data not in self.resources_db or self.resources_db[data]=='failed':
                    self.resources_db[data]='lock'
                    try:
                        log.warning(f'Downloading resource {data}...')
                        get(data, self.resource_dir)
                        self.resources_db[data]='loaded'
                        log.warning(f'... resource {data} downloaded')
                    except:
                        self.resources_db[data]='failed'
                        log.warning(f'... resource {data} failed!')
                        raise
                else:
                    log.warning(f'Resource {data} is already there')
            while True:
                for data in self.resource.split():
                    if self.resources_db[data]=='lock':
                        log.warning(f'Waiting for resource {data}...')
                        sleep(POLLING_TIME)
                        break
                else:
                    log.warning(f'All resource seems there')
                    break
            for data in self.resource.split():
                if self.resources_db[data]=='failed':
                    self.resources_db[data]='lock'
                    try:
                        log.warning(f'Trying again to download resource {data}...')
                        get(data, self.resource_dir)
                        self.resources_db[data]='loaded'
                        log.warning(f'... resource {data} finally downloaded')
                    except:
                        self.resources_db[data]='failed'
                        log.warning(f'... resource {data} failed again!')
                        raise

    def upload(self):
        """Do the uploading part at the end, getting all output into output URI"""
        log.warning('Uploading output results...')
        if self.output:
            output_files = []
            for root, _, files in os.walk(self.output_dir):
                rel_path = os.path.relpath(root, self.output_dir)
                for local_data in files:
                    data = os.path.join(root, local_data)
                    put(data, pathjoin(self.output,rel_path,'/'))
                    output_files.append(local_data)
            if output_files:
                return ' '.join(output_files)
    
    def clean(self):
        """Clean working directory (triggered if all went well)"""
        shutil.rmtree(self.workdir)

    async def run(self):
        """Launching part of Executor
        """
        log.warning(f'Running job {self.execution_id}: {self.command}')
        self.execution_started.release()
        try:
            self.download()
        except Exception as e:
            self.s.execution_error_write(self.execution_id,
                traceback.format_exc())
            returncode=-1001
            self.s.execution_update(self.execution_id, 
                status='failed', 
                return_code=returncode, output='')
            return None
        
        self.run_slots_semaphore.acquire()
        while self.s.task_get(self.task_id).status == 'paused' or self.run_slots.value<=0:
            if self.run_slots.value<=0:
                log.warning(f'Task {self.task_id} has been prefetched and is waiting')
            else:
                log.warning(f'Task {self.task_id} is paused, waiting...')
            self.run_slots_semaphore.release()
            sleep(POLLING_TIME)
            self.run_slots_semaphore.acquire()
        # check a last time that this task is for us
        if self.s.execution_get(self.execution_id).status == 'failed':
            # the task is no longer for us so we bail out
            log.error(f'Execution {self.execution_id} was cancelled.')
            self.clean()
            return None
        
        log.warning(f'Launching job {self.execution_id}: {self.command}')
        await self.execute(execution_id=self.execution_id)
        self.run_slots_semaphore.release()

        if not self.process is None:
            log.warning('Launched')
            while True:
                log.warning(f"... {self.execution_id} ...")
                returncode = await self.get_output(self.execution_id)
                log.warning("...")
                if returncode is not None:
                    log.warning('... done')
                    await self.get_output(self.execution_id)
                    try:
                        output_files = self.upload()
                    except Exception as e:
                        output_files = ''
                        self.s.execution_error_write(self.execution_id,
                            traceback.format_exc())
                        returncode=-1000
                    if returncode!=0:
                        log.error(f'... task failed with error code {returncode}')
                    log.warning(f'Run slots: {self.run_slots.value}')

                    self.run_slots_semaphore.acquire()
                    self.s.execution_update(self.execution_id, 
                        status='succeeded' if returncode==0 else 'failed', 
                        return_code=returncode, output_files=output_files)
                    self.run_slots.value += 1
                    self.run_slots_semaphore.release()
                    if returncode==0:
                        self.clean()
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
    def __init__(self, server, concurrency, name, batch):
        self.s = Server(server, style='object')
        self.server = server
        self.concurrency = concurrency
        self.prefetch = 0
        self.hostname = socket.gethostname()
        self.batch = batch
        if name is None:
            self.name = self.hostname
        else:
            self.name = name
        self.process = None
        self.executions = {}
        self.declare()
        self.has_worked = False
        self.idle_time = None
        self.resource_dir = tempfile.mkdtemp(dir=BASE_RESOURCE_DIR)
        self.manager = multiprocessing.Manager()
        self.resources_db = self.manager.dict()
        self.run_slots = multiprocessing.Value('i', concurrency)
        self.run_slots_semaphore = multiprocessing.Semaphore(1)


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
                batch=self.batch)


    def run(self, status=DEFAULT_WORKER_STATUS):
        self.w = self.s.worker_update(self.w.worker_id, status=status)
        cpu_list=[]
        while True:
            try:
                try:
                    memory=round(100-psutil.virtual_memory()[2],1)
                    ##memory=round(VM[4]*100/VM[0],2) 
                    disk=psutil.disk_io_counters(perdisk=False, nowrap=True)
                    read_bytes,written_bytes = round(disk[2]/(1024**3),2),round(disk[3]/(1024**3),2)
                    #CPU1,CPU5,CPU15 = [round((x / psutil.cpu_count()) *100,2) for x in psutil.getloadavg()]
                    cpus = psutil.cpu_times_percent()
                    cpu_list.append(cpus.user)
                    if len(cpu_list)== CPU_MAX_VALUE:
                        del(cpu_list[0])
                    cpu_string = f'{cpus.user}'+ ('↑' if cpus.user >= sum(cpu_list)/len(cpu_list) else '↓')
                    if  platform.system() =='Linux':
                        cpu_string += f' / {cpus.iowait}'
                    log.warning(f'CPU is {cpu_string}')
                    self.w=self.s.worker_ping(self.w.worker_id, cpu_string, memory, read_bytes, written_bytes )
                    ##self.w=self.s.worker_ping(self.w.worker_id, load = ' '.join(map(
                        #lambda x: str(int(x*100)),psutil.getloadavg())))
                    ##
                except HTTPException as e:
                    if e.status_code==404:
                        self.declare()
                        continue
                if self.w.concurrency != self.concurrency:
                    self.run_slots_semaphore.acquire()
                    self.run_slots.value += self.w.concurrency-self.concurrency
                    self.run_slots_semaphore.release()
                    log.warning(f'Concurrency changed from {self.concurrency} to {self.w.concurrency}, adjusting run slots: {self.run_slots.value}')
                    self.concurrency = self.w.concurrency
                if self.prefetch != self.w.prefetch:
                    log.warning(f'Prefetch changed from {self.prefetch} to {self.w.prefetch}')
                    self.prefetch = self.w.prefetch
                if self.w.status=='running':
                    executions=self.s.worker_executions(self.w.worker_id, status='pending')
                    for execution in executions:
                        if execution.execution_id not in self.executions:
                            task = self.s.task_get(execution.task_id)
                            execution_started = multiprocessing.Semaphore(0)
                            execution_queue = multiprocessing.Queue()
                            p=multiprocessing.Process(target=Executor,
                                kwargs={
                                    'server': self.server,
                                    'execution_id': execution.execution_id,
                                    'task_id': task.task_id,
                                    'command': task.command,
                                    'input': task.input,
                                    'output': task.output,
                                    'execution_started': execution_started,
                                    'execution_queue': execution_queue,
                                    'container': task.container,
                                    'container_options': task.container_options,
                                    'cpu': psutil.cpu_count()//self.w.concurrency,
                                    'resource_dir': self.resource_dir,
                                    'resource': task.resource,
                                    'resources_db': self.resources_db,
                                    'run_slots': self.run_slots,
                                    'run_slots_semaphore': self.run_slots_semaphore,
                                    'worker_id': self.w.worker_id
                                })
                            self.s.execution_update(execution.execution_id, status='accepted')
                            p.start()
                            self.executions[execution.execution_id]=(p,execution_queue)
                            self.has_worked = True
                            self.idle_time = None
                            log.info('Waiting for execution to start')
                            execution_started.acquire()
                            log.info('Execution started')
                    if not(self.executions) and self.has_worked:
                        now = time()
                        if self.idle_time is None:
                            self.idle_time=now
                        elif now-self.idle_time > IDLE_TIMEOUT:
                            self.s.worker_callback(self.w.worker_id, message = "idle")
                            self.idle_time = None
                for signal in self.s.worker_signals(self.w.worker_id):
                    if signal.execution_id in self.executions:
                        log.warning(f'Sending signal {signal.signal} to execution {signal.execution_id}')
                        self.executions[signal.execution_id][1].put(signal.signal)
                    else:
                        log.warning(f'Execution {signal.execution_id} is not running in this worker')
                for execution_id in list(self.executions.keys()):
                    if not self.executions[execution_id][0].is_alive():
                        del(self.executions[execution_id])
                if self.run_slots_semaphore.acquire():
                    if self.concurrency-len(self.executions)!=self.run_slots.value:
                        log.warning(f'Race condition detected on process number')
                        # ok time to look what is really going on
                        running = waiting = 0
                        for execution in self.s.worker_executions(self.w.worker_id):
                            if execution.status=='running':
                                running += 1
                            elif execution.status=='accepted':
                                waiting += 1
                        log.warning(f'We are supposed to have {self.concurrency} running processes and we have {running}')
                        log.warning(f'We are supposed to have {self.prefetch} waiting processes and we have {waiting}')    
                        log.warning(f'Overall we should have {self.concurrency+self.prefetch} processes and we have {len(self.executions)}')
                        if self.run_slots.value != self.concurrency - running:
                            log.warning(f'Run slot derived, reseting from {self.run_slots.value} to {self.concurrency-running}')
                            self.run_slots.value = self.concurrency - running
                    self.run_slots_semaphore.release()
                else:
                    log.warning('Cannot estimate process number, giving up.')
            except Exception as e:
                log.exception('An exception occured during worker main loop')
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
    args = parser.parse_args()
    
    Client(
        server=args.server, 
        concurrency=args.concurrency, 
        name=args.name,
        batch=args.batch
    ).run(status=args.status)
    

if __name__=="__main__":
    main()
    