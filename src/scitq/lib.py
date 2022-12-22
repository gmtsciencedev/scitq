import re
import requests
from requests.exceptions import Timeout, ConnectionError
from datetime import datetime
from time import sleep
import threading
import queue
from argparse import Namespace
import logging as log


PUT_TIMEOUT = 30
GET_TIMEOUT = 150
QUERY_THREAD_TIMEOUT = 10
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
            elif key=='batch' and value is None:
                subitem[key] = 'Default'
        return subitem
    if type(item)==list:
        return list([_sub_parse(subitem) for subitem in item])
    elif type(item)==dict:
        return _sub_parse(item)
    else:
        return item

def _clean(d):
    """filter out null value from a dict as well as key in remove list (default
    to ['id']) plus a ugly hack for default batch"""
    return dict([('batch',None) if (k=='batch' and v=='Default') else (k,v)  
        for k,v in d.items() if v is not None])

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


def query_thread(semaphore,send_queue, put_timeout):
        """A Query-thread which treats all the queries with a while loop until the object is there, then it put the result in the returning queue
        """
        while True :
            while not semaphore.acquire(blocking=False):
                try:
                    self,type,query,return_queue = send_queue.get(timeout=QUERY_THREAD_TIMEOUT)
                    break
                except queue.Empty:
                    continue
            else: 
                #This block is executed when the semaphore is acquired (meaning the Server instance was closed)
                break
            url,data=query
            task_done=False
            if type == 'put':
                while not task_done:
                    try:
                        sleep(put_timeout) 
                        result = self._wrap(requests.put(
                                self.url+url, json=data, timeout=put_timeout))
                        task_done = True
                    except (ConnectionError,Timeout) as e:
                        log.warning(f'Exception when trying to put: {e}')
                return_queue.put(result)
            elif type == 'post':
                while not task_done:
                    try:
                        sleep(put_timeout)
                        result = self._wrap(requests.post(
                                self.url+url, json=data, timeout=put_timeout))
                        task_done = True
                    except (ConnectionError,Timeout) as e:
                        log.warning(f'Exception when trying to post: {e}') 
                return_queue.put(result)
            elif type == 'delete':
                while not task_done:
                    try:
                        sleep(put_timeout)
                        result = self._wrap(requests.delete(
                                self.url+url, timeout=put_timeout))
                        task_done = True
                    except (ConnectionError,Timeout) as e:
                        log.warning(f'Exception when trying to post: {e}') 
                return_queue.put(result)            

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

    def __init__(self, ip, style='dict', asynchronous=True, 
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
        if style=='dict':
            self._wrap = lambda x: _parse_date_andco(_filter_non200(x))
        elif style=='object':
            self._wrap = lambda x: _to_obj(_parse_date_andco(_filter_non200(x)))
        else:
            raise Exception(f'style can only be dict or object not f{style}')
        self.asynchronous = asynchronous
        if self.asynchronous:
            self.query_thread_semaphore = threading.Semaphore()
            self.query_thread_semaphore.acquire(blocking=False)
            self.send_queue= queue.Queue()
            self.query_thread=threading.Thread(target=query_thread,
                args=(self.query_thread_semaphore,self.send_queue,put_timeout))
        self.get_timeout = get_timeout
        self.put_timeout = put_timeout

    def queue_size(self):
        """A method to estimate send queue size"""
        return self.send_queue.qsize()        

    def get(self, url):
        """A wrapper used for all get operations.
        - url: extra string to add after base server URL
        
        return the objects according to Server style (see style in class doc)"""
        try:
            return self._wrap(requests.get(
                self.url+url, timeout=self.get_timeout
            ))
        except (ConnectionError,Timeout) as e:
            log.warning(f'Exception when trying to get: {e}')
            sleep(self.get_timeout)
            return self.get(url)

    def put(self,url, data, asynchronous=None, timeout=None):
        """A wrapper used for all put operations.
        - url: extra string to add after base server URL
        - data: extra data (payload of put operation) represented as dict

        return the objects according to Server style (see style in class doc)
        (in asynchronous mode, return a lazy object)"""
        timeout = self.put_timeout if timeout is None else timeout
        asynchronous = self.asynchronous if asynchronous is None else asynchronous
        try:
            return self._wrap(requests.put(
                self.url+url, json=data, timeout=timeout
            ))
        except (ConnectionError,Timeout) as e:
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
        timeout = self.put_timeout if timeout is None else timeout
        asynchronous = self.asynchronous if asynchronous is None else asynchronous
        try:
            return self._wrap(requests.post(
                url=self.url+url, json=data, timeout=self.put_timeout
            ))
        except (ConnectionError,Timeout) as e:
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
        timeout = self.put_timeout if timeout is None else timeout
        asynchronous = self.asynchronous if asynchronous is None else asynchronous
        try:
            return self._wrap(requests.delete(
                self.url+url, timeout=timeout
            ))
        except (ConnectionError,Timeout) as e:
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


    def workers(self):
        """Get a list of all workers"""
        return self.get('/workers/')

    def worker_update(self, id, name=None, hostname=None, concurrency=None, 
                    status=None,batch=None, idle_callback=None, prefetch=None):
        """Update a specific worker with worker_id equal to id
        return the updated worker (or None if the server timeout)"""
        return self.put(f'/workers/{id}', data=_clean(
            {'name':name, 'hostname':hostname, 'concurrency':concurrency, 
            'status':status, 'batch':batch, 'idle_callback':idle_callback,
            'prefetch':prefetch}
        ))

    def worker_create(self, name, concurrency, hostname=None, status='paused',
                batch=None, idle_callback=None, prefetch=0):
        """Create a new worker
        return the new worker (or None if the server timeout)"""
        return self.post('/workers/', data=_clean(
            {'name':name, 'hostname':hostname, 'concurrency':concurrency, 
            'status':status, 'batch':batch, 'idle_callback':idle_callback,
            'prefetch':prefetch}
        ))

    def worker_get(self, id):
        """get a specific worker with worker_id equal to id
        return the worker"""
        return self.get(f'/workers/{id}')

    def worker_ping(self, id, load, memory, read_bytes, written_bytes):
        """Update a specific worker ping time (heartbit)
        return a updated worker object with attribute or key (depending on style)"""
        return self.put(f'/workers/{id}/ping', data={'load':load,'memory':memory,'read_bytes':read_bytes,'written_bytes':written_bytes})

    def worker_callback(self, id, message):
        """Send a callback message (mainly idle) to trigger action on worker from the server
        return a object with result attribute, equal to ok"""
        return self.put(f'/workers/{id}/callback', data={'message':message},
            asynchronous=False, timeout=GET_TIMEOUT)
    
    def worker_executions(self, id, status=None):
        """Get a list of a worker current assigned executions. 
        If status is used, only executions with this status are shown
        """
        if status is None:
            return self.get(f'/workers/{id}/executions')
        else:
            return self.get(f'/workers/{id}/executions/{status}')

    def worker_delete(self, id):
        """Delete a worker"""
        return self.delete(f'/workers/{id}')

    def workers_tasks(self):
        """Return a list of all the different tasks for a certain worker"""
        return self.get(f'/workers/tasks')
    
    def executions(self):
        """Get a list of all executions. 
        """
        return self.get(f'/executions/')
    
    def execution_create(self, worker_id, task_id, status='pending'):
        """Create a new execution, return the newly created execution
        """
        return self.post('/executions/', data={
            'worker_id':worker_id, 'task_id':task_id, 'status':status
        })

    def execution_update(self, id, status=None, pid=None, return_code=None, 
                        output=None, output_files=None):
        """Update a specific execution, return the updated execution
        """
        return self.put(f'/executions/{id}', data=_clean(
            {'status':status, 'pid':pid, 'return_code':return_code, 
                'output':output, 'output_files':output_files}
        ))

    def execution_output_write(self, id, output):
        """Add some output to a specific execution, return the updated execution
        """
        if output is None:
            return None
        return self.put(f'/executions/{id}/output', data=_clean(
            {'text':output}
        ))

    def execution_error_write(self, id, error):
        """Add some error (stderr) to a specific execution, return the updated execution
        """
        if error is None:
            return None
        return self.put(f'/executions/{id}/error', data=_clean(
            {'text':error}
        ))

    def execution_get(self, id):
        """get a specific execution with execution_id equal to id
        return the execution"""
        return self.get(f'/executions/{id}')

    def task_create(self, command, name=None, status='pending',batch=None, 
            input=None, output=None, container=None, container_options='',
            resource=None):
        """Create a new task, return the newly created task
        """
        return self.post('/tasks/', data=_clean({
            'command':command, 'name':name, 'status':status, 'batch':batch,
            'input':input, 'output':output, 'container':container, 
            'container_options':container_options, 'resource':resource
        }))

    def task_update(self, id, command=None, name=None, status=None, batch=None, 
            input=None, output=None, container=None, container_options=None,
            resource=None):
        """Update a specific execution, return the updated execution
        """
        return self.put(f'/tasks/{id}', data=_clean({
            'command':command, 'name':name, 'status':status, 'batch':batch,
            'input':input, 'output':output, 'container':container, 
            'container_options':container_options, 'resource':resource
        }))

    def task_get(self, id):
        """get a specific task with task_id equal to id
        return the task"""
        return self.get(f'/tasks/{id}')

    def tasks(self):
        """Get a list of all tasks. 
        """
        return self.get(f'/tasks/')

    def task_delete(self,id):
        """delete a specific task"""
        return self.delete(f'/tasks/{id}')

    def worker_signals(self, id):
        """Get a list of signals for this worker"""
        return self.get(f'/workers/{id}/signals')

    def worker_create_signal(self, id, execution_id, signal):
        """Create a signal for this worker"""
        return self.post(f'/workers/{id}/signals', data={
            'execution_id': execution_id,
            'signal': signal
        })
    
    def worker_deploy(self, number, batch, region, flavor, concurrency, prefetch=0):
        """Deploy (and create) some workers"""
        return self.put('/workers/deploy', data={
            'number':int(number),
            'region':region,
            'flavor':flavor,
            'batch':batch,
            'concurrency':concurrency,
            'prefetch': prefetch
        })
    
    def batch_stop(self,batch,signal=0):
        """Pause all workers for this batch"""
        if signal==0:
            return self.put(f'/batch/{batch}/stop',data={})
        return self.put(f'/batch/{batch}/stop',data={'signal':signal})
    
    def batch_go(self,batch,signal=0):
        """(re)set all workers affected to this batch to running"""
        return self.put(f'/batch/{batch}/go',data={'signal':signal})

    def batches(self):
        """List all batches, their tasks and workers"""
        return self.get(f'/batch/')

    def batch_delete(self,batch):
        """List all batches, their tasks and workers"""
        return self.delete(f'/batch/{batch}')

    def join(self, task_list, retry=1, check=False):
        """Wait for a certain list of tasks to succeed. In case of failure, relaunch tasks
        a limited number of time (retry). If check is True, then join will fail if
        one of the task fails (after all retries).
        Return a dictionary of the different status of tasks when tasks were all done
        """
        if not task_list:
            raise RuntimeError('task_list should not be empty')
        task_ids = [task['task_id'] if type(task)==dict else task.task_id for task in task_list]
        task_retries = dict([(task_id,0) for task_id in task_ids])

        all_task_done = False
        tasks = None
        dynamic_sleep_time = True
        sleep_time = JOIN_DYNAMIC_SLEEP_TIME_INCREMENT
        failed_tasks = []
        while not all_task_done:
            all_task_done = True
            old_tasks = tasks
            tasks = {'assigned':0,'failed':0, 'running':0, 'accepted':0, 'pending':0,'succeeded':0}
            for task in self.tasks():
                if type(task)==dict:
                    task = Namespace(**task)
                if task.task_id in task_ids:
                    if task.status=='failed':
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
                    elif task.status in ['running','accepted','pending','assigned']:
                        all_task_done = False
                        tasks[task.status]+=1
                    else:
                        tasks[task.status]+=1
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


if __name__=="__main__":
    s=Server('127.0.0.1',style='object')
