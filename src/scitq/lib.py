import re
import requests
from requests.exceptions import Timeout, ConnectionError
from datetime import datetime
from time import sleep
import threading
import queue
from argparse import Namespace
import logging as log
import time
import os
from .util import filter_none as _clean, validate_protofilter
from .constants import FLAVOR_DEFAULT_EVICTION, FLAVOR_DEFAULT_LIMIT, TASK_STATUS_ID_REVERSE, TASK_STATUS, DEFAULT_SERVER

PUT_TIMEOUT = 30
GET_TIMEOUT = 150
QUERY_THREAD_TIMEOUT = 10
QUERY_THREAD_IDLE_TIMEOUT = 60
JOIN_DYNAMIC_SLEEP_TIME_INCREMENT = 10

def _parse_date_andco(item):
    """A custom filter to transform JSON date (i.e. date in ISO formated text) 
    in datetime object. JSON object can be list of dicts or a simple dict or
    a simple object directly in some case. Only variable with name ending with 
    _date are converted (thus only within a dictionary, standalone object are
    not converted)
    Perform also misc transformation like batch default"""
    def _sub_parse(subitem):
        for key, value in subitem.items():
            if '_date' in key and value is not None:
                subitem[key] = datetime.fromisoformat(value)
        return subitem
    if type(item)==list:
        return list([_sub_parse(subitem) for subitem in item])
    elif type(item)==dict:
        return _sub_parse(item)
    else:
        return item

def _to_obj(d):
    """A simple recursive wrapper to convert JSON like objects in python objects"""
    if type(d)==list:
        return map(_to_obj, d)
    if type(d)==dict:
        return Namespace(**d)
    return d

class HTTPException(Exception):
    def __init__(self, text, message, status_code):
        self.status_code = status_code
        self.message = message
        super().__init__(text)


def _filter_non200(r):
    if r.status_code//100 != 2:
        try:
            message = r.json()['message']
        except:
            message = 'Unknown server error'
        raise HTTPException(f'Error {r.status_code}: {message}', 
                message=message, 
                status_code=r.status_code)
    return r.json()
class LazyObject:
    """A lazy object or dict initialized with a queue.Queue 
    perform q.get as soon as you try to use it..."""
    def __init__(self, q):
        """Initialize object with queue.Queue q"""
        self._q = q
        self._o = None
    def __getattr__(self, __name):
        """Retrieve real attribute (object style) in real object once it is there"""
        if self._o is None:
            self._o = self._q.get()
        return getattr(self._o, __name)
    def __getitem__(self, __key):
        """Retrieve real key in real object (dict style) once it is there"""
        if self._o is None:
            self._o = self._q.get()
        return self._o[__key]
    def __str__(self):
        """Wait for real object and use real object representation"""
        if self._o is None:
            self._o = self._q.get()
        return str(self._o)


def query_thread(send_queue, put_timeout):
        """A Query-thread which treats all the queries with a while loop until the object is there, then it put the result in the returning queue
        """
        time_point = None
        while True :
            try:
                self,type,query,return_queue = send_queue.get(timeout=QUERY_THREAD_TIMEOUT)
                time_point = None
            except queue.Empty:
                if time_point is None:
                    time_point=time.time()
                elif time.time() - time_point > QUERY_THREAD_IDLE_TIMEOUT:
                    return None
                sleep(put_timeout)
                continue
            url,data=query
            
            task_done=False
            while not task_done:
                try:
                    if type=='put':
                        result = self._wrap(requests.put(
                                self.url+url, json=data, timeout=put_timeout))
                    elif type=='post':
                        result = self._wrap(requests.post(
                                self.url+url, json=data, timeout=put_timeout))
                    elif type=='delete':
                        result = self._wrap(requests.delete(
                                self.url+url, timeout=put_timeout))
                    task_done = True
                except (ConnectionError,Timeout) as e:
                    log.exception(f'Exception when trying to {type}: {e}')
            return_queue.put(result)

class RestartingThread:
    """This Thread class is a thin wrapper above a threading.Thread that can be 
    restarted, it implements only start() and is_alive() methods
    """
    def __init__(self, target, args):
        self.target = target
        self.args = args
        self.__thread__=None
    
    def is_alive(self):
        return False

    def start(self):
        if self.is_alive():
            print('Thread already alive')
            return
        self.__thread__=threading.Thread(target=self.target, args=self.args)
        self.__thread__.start()
        self.is_alive = self.__thread__.is_alive
        


class Server:
    """A thin wrapper above requests with URLs registered
    and several extrathings:
    - output is JSON de-marshalled,
    - date are converted,
    - if server is not accessible, the lib will retry or do the job later,
    - expected arguments are explicit which makes life easier.
    
    Arguments:
    - ip: the name or IP address of server,
    - style: if 'dict' (default) all the objects are rendered as dict, if 
        'object', dict are passed to Namespace to produce real Python objects.
    """

    def __init__(self, ip=os.environ.get('SCITQ_SERVER',DEFAULT_SERVER), style='dict', asynchronous=True, 
            put_timeout=PUT_TIMEOUT, get_timeout=GET_TIMEOUT):
        """initialise the object with IP or name of the server
        
        Arguments:
        - ip: the name or IP address of server,
        - style: if 'dict' (default) all the objects are rendered as dict, if 
            'object', dict are passed to Namespace to produce real Python objects.
        - asynchronous: if True (default) then put and post operations are 
            asynchronous, if False then all operations will wait (forever) for 
            the server to come back. get operations are always synchronous"""
        
        self.ip=ip
        self.url=f'http://{ip}:5000'
        self.style=style
        if style=='dict':
            self._wrap = lambda x: _parse_date_andco(_filter_non200(x))
        elif style=='object':
            self._wrap = lambda x: _to_obj(_parse_date_andco(_filter_non200(x)))
        else:
            raise Exception(f'style can only be dict or object not f{style}')
        self.asynchronous = asynchronous
        if self.asynchronous:
            self.send_queue= queue.Queue()
            self.query_thread=RestartingThread(target=query_thread,
                args=(self.send_queue,put_timeout))
        self.get_timeout = get_timeout
        self.put_timeout = put_timeout



    def queue_size(self):
        """A method to estimate send queue size"""
        return self.send_queue.qsize()        

    def get(self, url, wrap=None, **args):
        """A wrapper used for all get operations.
        - url: extra string to add after base server URL
        - wrap: an optional argument for use in special case
        
        return the objects according to Server style (see style in class doc)"""
        try:
            return (wrap or self._wrap)(requests.get(
                self.url+url, timeout=self.get_timeout, json=args
            ))
        except (ConnectionError,Timeout,HTTPException) as e:
            if hasattr(e,'status_code') and e.status_code!=403:
                log.exception(f'Unsustainable server error: {e}')
                raise
            log.warning(f'Exception when trying to get: {e}')
            sleep(self.get_timeout)
            return self.get(url, **args)

    def put(self,url, data, asynchronous=None, timeout=None):
        """A wrapper used for all put operations.
        - url: extra string to add after base server URL
        - data: extra data (payload of put operation) represented as dict

        return the objects according to Server style (see style in class doc)
        (in asynchronous mode, return a lazy object)"""
        asynchronous = self.asynchronous if asynchronous is None else asynchronous
        if timeout is None:
            timeout = self.put_timeout if asynchronous else self.get_timeout
        try:
            return self._wrap(requests.put(
                self.url+url, json=data, timeout=timeout
            ))
        except (ConnectionError,Timeout,HTTPException) as e:
            if hasattr(e,'status_code') and e.status_code!=403:
                log.exception(f'Unsustainable server error: {e}')
                timeout = self.get_timeout
                raise
            if asynchronous:
                if not self.query_thread.is_alive():
                    self.query_thread.start()
                log.warning(f'Exception when trying to put: {e}')
                return_queue=queue.Queue()
                self.send_queue.put((self,'put',(url, data),return_queue))
                return LazyObject(return_queue)
            else:
                log.warning(f'Exception when trying to put: {e}')
                sleep(timeout)
                return self.put(url, data, asynchronous, timeout)
        

    def post(self, url, data, asynchronous=None, timeout=None):
        """A wrapper used for all post operations.
        - url: extra string to add after base server URL
        - data: extra data (payload of post operation) represented as dict

        return the objects according to Server style (see style in class doc)"""
        asynchronous = self.asynchronous if asynchronous is None else asynchronous
        if timeout is None:
            timeout = self.put_timeout if asynchronous else self.get_timeout
        try:
            return self._wrap(requests.post(
                url=self.url+url, json=data, timeout=self.put_timeout
            ))
        except (ConnectionError,Timeout,HTTPException) as e:
            if hasattr(e,'status_code') and e.status_code!=403:
                log.exception(f'Unsustainable server error: {e}')
                timeout = self.get_timeout
                raise
            if asynchronous:
                if not self.query_thread.is_alive():
                    self.query_thread.start()
                log.warning(f'Exception when trying to post: {e}')
                return_queue=queue.Queue()
                self.send_queue.put((self,'post',(url, data),return_queue))
                return LazyObject(return_queue)
            else:
                log.warning(f'Exception when trying to post: {e}')
                sleep(timeout)
                return self.post(url, data, asynchronous, timeout)

    def delete(self,url, asynchronous=None, timeout=None):
        """A wrapper used for all put operations.
        - url: extra string to add after base server URL
        - data: extra data (payload of put operation) represented as dict

        return the objects according to Server style (see style in class doc)
        (in asynchronous mode, return a lazy object)"""
        asynchronous = self.asynchronous if asynchronous is None else asynchronous
        if timeout is None:
            timeout = self.put_timeout if asynchronous else self.get_timeout
        try:
            return self._wrap(requests.delete(
                self.url+url, timeout=timeout
            ))
        except (ConnectionError,Timeout,HTTPException) as e:
            if hasattr(e,'status_code') and e.status_code!=403:
                log.exception(f'Unsustainable server error: {e}')
                timeout = self.get_timeout
                raise
            if asynchronous:
                if not self.query_thread.is_alive():
                    self.query_thread.start()
                log.warning(f'Exception when trying to delete: {e}')
                return_queue=queue.Queue()
                self.send_queue.put((self,'delete',(url, None),return_queue))
                return LazyObject(return_queue)
            else:
                log.warning(f'Exception when trying to delete: {e}')
                sleep(timeout)
                return self.delete(url, asynchronous, timeout)


    def workers(self, **args):
        """Get a list of all workers"""
        return self.get('/workers/',**args)

    def worker_update(self, id, name=None, hostname=None, concurrency=None, 
                    status=None,batch=None, permanent=None, prefetch=None,
                    flavor=None,task_properties=None,asynchronous=True):
        """Update a specific worker with worker_id equal to id
        return the updated worker (or None if the server timeout)"""
        return self.put(f'/workers/{id}', data=_clean(
            {'name':name, 'hostname':hostname, 'concurrency':concurrency, 
            'status':status, 'batch':batch, 'permanent':permanent,
            'prefetch':prefetch, 'flavor':flavor, 'task_properties':task_properties}
        ), asynchronous=asynchronous)

    def worker_create(self, name, concurrency, hostname=None, status='paused',
                batch=None, permanent=None, prefetch=0, flavor=None,
                asynchronous=True):
        """Create a new worker
        return the new worker (or None if the server timeout)"""
        return self.post('/workers/', data=_clean(
            {'name':name, 'hostname':hostname, 'concurrency':concurrency, 
            'status':status, 'batch':batch, 'permanent':permanent,
            'prefetch':prefetch, 'flavor':flavor}
        ), asynchronous=asynchronous)

    def worker_get(self, id):
        """get a specific worker with worker_id equal to id
        return the worker"""
        return self.get(f'/workers/{id}')

    def worker_ping(self, id, load, memory, stats, asynchronous=False):
        """Update a specific worker ping time (heartbit)
        return a updated worker object with attribute or key (depending on style)"""
        return self.put(f'/workers/{id}/ping', data={'load':load,'memory':memory,
            'stats':stats}, asynchronous=asynchronous)

    def worker_callback(self, id, message, asynchronous=False):
        """Send a callback message (mainly idle) to trigger action on worker from the server
        return a object with result attribute, equal to ok"""
        return self.put(f'/workers/{id}/callback', data={'message':message},
            asynchronous=asynchronous)
    
    def worker_executions(self, id, status=None):
        """Get a list of a worker current assigned executions. 
        If status is used, only executions with this status are shown
        """
        if status is None:
            return self.get(f'/workers/{id}/executions')
        else:
            return self.get(f'/workers/{id}/executions/{status}')

    def worker_delete(self, id, asynchronous=True):
        """Delete a worker"""
        return self.delete(f'/workers/{id}', asynchronous=asynchronous)

    def workers_tasks(self):
        """Return a list of all the different tasks for a certain worker"""
        return self.get(f'/workers/tasks')
    
    def executions(self, **args):
        """Get a list of all executions. 
        Optional args are optional attributes to filter list with:
        - task_id: int
        - status: str
        - latest: boolean
        - batch: str
        - task_name: str
        - limit: int (limit results to N)
        - reverse: set to true to have most recent executions first (default to False)
        - trunc: trunc output/error to this size (trunc, keeping only this number of last characters)
        """
        return self.get(f'/executions/', **args)
    
    def execution_create(self, worker_id, task_id, status='pending', command=None,
                         asynchronous=True):
        """Create a new execution, return the newly created execution
        """
        return self.post('/executions/', data=_clean(
            {
            'worker_id':worker_id, 'task_id':task_id, 'command':command,
            'status':status
            }
            ), asynchronous=asynchronous)

    def execution_update(self, id, status=None, pid=None, return_code=None, 
                        output=None, error=None, output_files=None, command=None,
                        freeze=False,
                        asynchronous=True):
        """Update a specific execution, return the updated execution
        """
        return self.put(f'/executions/{id}', data=_clean(
            {'status':status, 'pid':pid, 'return_code':return_code, 
                'output':output, 'error':error, 'output_files':output_files, 
                'command':command, 'freeze':freeze}
        ), asynchronous=asynchronous)

    def execution_output_write(self, id, output, asynchronous=True):
        """Add some output to a specific execution, return the updated execution
        """
        if output is None:
            return None
        output = output.replace('\00', '')
        return self.put(f'/executions/{id}/output', data=_clean(
            {'text':output}
        ), asynchronous=asynchronous)

    def execution_error_write(self, id, error, asynchronous=True):
        """Add some error (stderr) to a specific execution, return the updated execution
        """
        if error is None:
            return None
        error = error.replace('\00', '')
        return self.put(f'/executions/{id}/error', data=_clean(
            {'text':error}
        ), asynchronous=asynchronous)

    def execution_get(self, id):
        """get a specific execution with execution_id equal to id
        return the execution"""
        return self.get(f'/executions/{id}')
    
    def execution_output(self, id, output:bool=None, error:bool=None, output_position:int=None, error_position:int=None):
        """get the output and error flow (can be restricted to one or the other specifying error=False or output=False)
        starting from a given position (notably to get only newer output or error flow): first character is position 1"""
        return self.get(f'/executions/{id}/output', data=_clean(
            {'output':output, 'error':error, 'output_position':output_position, 'error_position':error_position}
        ))

    def task_create(self, command, name=None, status=None,batch=None, 
            input=None, output=None, container=None, container_options='',
            resource=None, required_task_ids=None, shell=False, retry=None,
            download_timeout=None, run_timeout=None, use_cache=None,
            asynchronous=True):
        """Create a new task, return the newly created task
        """
        if status is None:
            status = 'waiting' if required_task_ids else 'pending'
        if shell:
            shell='sh' if shell is True else shell
            if "'" in command:
                log.warning(f'''This command ({command}) contains quote(s) (') and is unlikely to work''')
            command = f"{shell} -c '{command}'"
        if type(input)==list:
            input=' '.join(input)
        if type(resource)==list:
            resource=' '.join(resource)
        return self.post('/tasks/', data=_clean({
            'command':command, 'name':name, 'status':status, 'batch':batch,
            'input':input, 'output':output, 'container':container, 
            'container_options':container_options, 'resource':resource, 
            'required_task_ids': required_task_ids, 'retry': retry,
            'download_timeout':download_timeout, 'run_timeout':run_timeout,
            'use_cache':use_cache,
        }), asynchronous=asynchronous)

    def task_update(self, id, command=None, name=None, status=None, batch=None, 
            input=None, output=None, container=None, container_options=None,
            resource=None, required_task_ids=None, retry=None, 
            download_timeout=None, run_timeout=None, use_cache=None,
            asynchronous=True):
        """Update a specific execution, return the updated execution
        """
        if type(input)==list:
            input=' '.join(input)
        if type(resource)==list:
            resource=' '.join(resource)
        return self.put(f'/tasks/{id}', data=_clean({
            'command':command, 'name':name, 'status':status, 'batch':batch,
            'input':input, 'output':output, 'container':container, 
            'container_options':container_options, 'resource':resource, 
            'required_task_ids': required_task_ids, 'retry': retry,
            'download_timeout':download_timeout, 'run_timeout':run_timeout,
            'use_cache':use_cache,
        }), asynchronous=asynchronous)

    def task_get(self, id):
        """get a specific task with task_id equal to id
        return the task"""
        return self.get(f'/tasks/{id}')
    
    def task_freeze(self, id, execution_id):
        """get a specific task with task_id equal to id - and copy values to execution execution_id
        return the task"""
        return self.get(f'/tasks/{id}/freeze/{execution_id}')

    def tasks(self, **args):
        """Get a list of all tasks
        Optional args are optional attributes to filter list with:
        - task_id: list(int)
        - status: str
        - batch: str
        - name: str
        """
        return self.get(f'/tasks/', **args)
    
    def task_status(self, task_id_list):
        """Get a list of tasks'status
        Only one mandatory argument, a list of task.task_id:
        - task_id_list: list(int)
        """
        return [TASK_STATUS_ID_REVERSE[status_id] for status_id in self.get(f'/tasks/status', wrap=_filter_non200, task_id=task_id_list)]

    def task_delete(self,id, asynchronous=True):
        """delete a specific task"""
        return self.delete(f'/tasks/{id}', asynchronous=asynchronous)

    def worker_signals(self, id):
        """Get a list of signals for this worker"""
        return self.get(f'/workers/{id}/signals')

    def worker_create_signal(self, id, execution_id, signal, asynchronous=True):
        """Create a signal for this worker"""
        return self.post(f'/workers/{id}/signals', data={
            'execution_id': execution_id,
            'signal': signal
        }, asynchronous=asynchronous)
    
    def worker_deploy(self, number, batch, region, flavor, concurrency, provider,
                      prefetch=0,
             asynchronous=True):
        """Deploy (and create) some workers"""
        return self.put('/workers/deploy', data={
            'number':int(number),
            'region':region,
            'provider':provider,
            'flavor':flavor,
            'batch':batch,
            'concurrency':concurrency,
            'prefetch': prefetch
        }, asynchronous=asynchronous)
    
    def batch_stop(self,batch,signal=0, asynchronous=True):
        """Pause all workers for this batch"""
        if signal==0:
            return self.put(f'/batch/{batch}/stop',data={})
        return self.put(f'/batch/{batch}/stop',data={'signal':signal}, 
            asynchronous=asynchronous)
    
    def batch_go(self,batch,signal=0, asynchronous=True):
        """(re)set all workers affected to this batch to running"""
        return self.put(f'/batch/{batch}/go',data={'signal':signal},
            asynchronous=asynchronous)

    def batches(self):
        """List all batches, their tasks and workers"""
        return self.get(f'/batch/')

    def batch_delete(self,batch, asynchronous=True):
        """List all batches, their tasks and workers"""
        return self.delete(f'/batch/{batch}', asynchronous=asynchronous)
    
    def recruiters(self, **args):
        """List all recruiters (a recruiter is an automate that deploy workers as needed for a certain batch)
        - args: some filtering option like batch='Default'"""
        return self.get(f'/recruiter/', **args)

    def recruiter_create(self, batch, rank, tasks_per_worker, flavor, concurrency, region=None, provider=None,  
                         prefetch=None, minimum_tasks=None, maximum_workers=None,asynchronous=True):
        """Create a new recruiter (or update an existing recruiter of the same rank)"""
        validate_protofilter(flavor)
        return self.post(f'/recruiter/', data=_clean({
            'batch': batch,'rank':rank,'tasks_per_worker':tasks_per_worker,'worker_flavor':flavor,
            'worker_region':region,'worker_provider':provider,'worker_concurrency':concurrency,
            'worker_prefetch': prefetch,'minimum_tasks':minimum_tasks,'maximum_workers':maximum_workers
        }), asynchronous=asynchronous)
    
    def recruiter_update(self, batch, rank, tasks_per_worker=None, flavor=None, region=None, provider=None, concurrency=None, 
                         prefetch=None, minimum_tasks=None, maximum_workers=None,asynchronous=True):
        """Update an existing recruiter"""
        if flavor is not None:
            validate_protofilter(flavor)
        return self.put(f'/recruiter/{batch}/{rank}', data=_clean({
            'tasks_per_worker':tasks_per_worker,'worker_flavor':flavor,
            'worker_region':region,'worker_provider':provider,'worker_concurrency':concurrency,
            'worker_prefetch': prefetch,'minimum_tasks':minimum_tasks,'maximum_workers':maximum_workers
        }), asynchronous=asynchronous)
    
    def recruiter_delete(self, batch, rank,asynchronous=True):
        """Delete an existing recruiter"""
        return self.delete(f'/recruiter/{batch}/{rank}', asynchronous=asynchronous)
    
    def recruiters_match(self, **args):
        """List all recruiters (a recruiter is an automate that deploy workers as needed for a certain batch)
        - args: some filtering option like batch='Default'"""
        return self.get(f'/recruiter/match', **args)
    
    def config_rclone(self):
        """Provide the content of current rclone file"""
        return self.get(f'/config/rclone')
    
    def join(self, task_list, retry=1, check=False):
        """Wait for a certain list of tasks to succeed. In case of failure, relaunch tasks
        a limited number of time (retry). If check is True, then join will fail if
        one of the task fails (after all retries).
        Return a dictionary of the different status of tasks when tasks were all done
        """
        if not task_list:
            raise RuntimeError('task_list should not be empty')
        if type(task_list[0])==dict:
            task_list = [Namespace(**task) for task in task_list]
        task_ids = [task.task_id for task in task_list]
        task_retries = dict([(task_id,0) for task_id in task_ids])

        all_task_done = False
        tasks = None
        dynamic_sleep_time = True
        sleep_time = JOIN_DYNAMIC_SLEEP_TIME_INCREMENT
        failed_tasks = []
        while not all_task_done:
            all_task_done = True
            old_tasks = tasks
            tasks = {status:0 for status in TASK_STATUS}
            for task,task_status in zip(task_list,self.task_status(task_id_list=task_ids)):
                if task_status=='failed':
                    if task_retries[task.task_id]<retry:
                        print(f'Retrying task {task.name or task.task_id} [{task_retries[task.task_id]+1}/{retry}]...')
                        self.task_update(task.task_id, status='pending')
                        task_retries[task.task_id]+=1
                        tasks['pending']+=1
                        all_task_done = False
                    else:
                        tasks['failed']+=1
                        if task.task_id not in failed_tasks:
                            print(f'Task {task.name or task.task_id} failed too many times giving up')
                            failed_tasks.append(task.task_id)
                elif task_status in ['running','accepted','pending','assigned']:
                    all_task_done = False
                    tasks[task_status]+=1
                else:
                    tasks[task_status]+=1
            print(f"Remaining tasks pending : {tasks['pending']}, assigned: {tasks['assigned']}, accepted: {tasks['accepted']}, running: {tasks['running']}, failed: {tasks['failed']}, succeeded: {tasks['succeeded']}")
            
            # sleeping if needed
            if not all_task_done:
                sleep(sleep_time)

            # adjust sleeping time
            if old_tasks is not None and dynamic_sleep_time:
                if tasks['succeeded']==old_tasks['succeeded'] and tasks['failed']==old_tasks['failed']:
                    # no task has been completed since last iteration so it is likely that the time loop is two short
                    sleep_time += JOIN_DYNAMIC_SLEEP_TIME_INCREMENT
                else:
                    # ok so now some tasks have been completed so it is likely the time loop is correct, no need to move it further
                    dynamic_sleep_time = False
            elif not dynamic_sleep_time and sleep_time>JOIN_DYNAMIC_SLEEP_TIME_INCREMENT:
                if tasks['succeeded']!=old_tasks['succeeded'] or tasks['failed']!=old_tasks['failed']:
                    # after all it seems it is moving quicker than expected, maybe time to shorten the time loop
                    dynamic_sleep_time = True
                    sleep_time -= JOIN_DYNAMIC_SLEEP_TIME_INCREMENT
        if check and tasks['failed']>0:
            raise RuntimeError('Could not complete all the tasks...')
        print('All tasks done!')
        return tasks

    def flavors(self, min_cpu=0, min_ram=0, min_disk=0, max_eviction=FLAVOR_DEFAULT_EVICTION, limit=FLAVOR_DEFAULT_LIMIT,
                provider=None, region=None, protofilters=None):
        """List all available flavors"""
        return self.get(f'/flavor/', min_cpu=min_cpu, min_ram=min_ram, min_disk=min_disk, max_eviction=max_eviction,
                        limit=limit, provider=provider, region=region, protofilters=protofilters)
    
    def flavor_find(self, cpu=0, ram=0, disk=0, max_eviction=FLAVOR_DEFAULT_EVICTION, n=1):
        """Return a flavor or a list of flavor if n>0"""
        flavor_list = self.flavors(min_cpu=cpu, min_ram=ram, min_disk=disk, max_eviction=max_eviction)
        if self.style=='dict':
            flavor_list = map(_to_obj,flavor_list)
        answer = []
        initial_n=n
        while n>0:
            while len(flavor_list)>0 and flavor_list[0].available<=0:
                flavor_list.pop(0)
            if len(flavor_list)>0:
                answer.append(flavor_list[0])
                n-=1
                flavor_list[0].available-=1
            else:
                if answer:
                    log.warning(f'WARNING: shortage of VM only {len(answer)} out of {initial_n} could be found.')
                else:
                    raise RuntimeError('Could not find any suitable instance of that type')
        return answer[0] if initial_n==1 else answer
        
if __name__=="__main__":
    s=Server('127.0.0.1',style='object')
