from .lib import Server
from .util import colors
from typing import Optional
from time import sleep
import os
from pynput import keyboard
from signal import SIGTSTP, SIGCONT
from threading import Event
from queue import Queue

DEFAULT_SERVER='127.0.0.1'
DEFAULT_REFRESH=30
TASK_STATUS=['paused','waiting','pending','assigned','accepted','running','failed','succeeded']
WORKER_STATUS=['paused','running','offline','failed']

# this simple mechanism enable to override a value including if the new value is None
class Unset:
    pass

def coalesce(a,b):
    """Return a or default to b if a is Unset (like in SQL)"""
    return b if a is Unset else a


def _(x):
    return x if x else ''

def dmap(f,d):
    return {k:f(v) for k,v in d.items()}

class WorkflowException(Exception):
    pass

class Batch:
    """A class to automate batch allocation"""
    def __init__(self, name, shortname, flavor, concurrency, provider, region, tasks_per_worker, maximum_workers, prefetch, server):
        self.name = name
        self.shortname = shortname
        self.flavor = flavor
        self.concurrency = concurrency
        self.provider = provider
        self.region = region
        self.tasks_per_worker = tasks_per_worker
        self.maximum_workers = maximum_workers
        self.prefetch = prefetch
        self.server = server
        self.__recruiter__ = self.create_recruiter()

    def create_recruiter(self):
        return self.server.recruiter_create(batch = self.name, rank=1, tasks_per_worker=self.tasks_per_worker, 
                            flavor=self.flavor, concurrency=self.concurrency, region=self.region, 
                            provider=self.provider, prefetch=self.prefetch,
                            maximum_workers=self.maximum_workers)
    
    def clean(self):
        self.server.recruiter_delete(self.name, rank=1)
        

    def pause(self, signal=0):
        self.server.batch_stop(self.name, signal=signal)

    def unpause(self, signal=0):
        self.server.batch_go(self.name, signal=signal)


class Step:
    """A step in a workflow, a class mixing scitq Task and Batch concepts to help writing in workflow logic"""
    __memory__ = {}

    def __init__(self, task, batch):
        self.__task__ = task
        self.__batch__ = batch
        if batch.name not in self.__memory__:
            self.__memory__[batch.name] = []
        self.__steps__=self.__memory__[batch.name]
        self.__steps__.append(self)
        self.map_attributes()

    def map_attributes(self):
        for k,v in self.__task__.__dict__.items():
            if not k.startswith('_'):
                setattr(self,k,v)
        for k,v in self.__batch__.__dict__.items():
            if k not in ['name','shortname'] and not k.startswith('_'):
                setattr(self,k,v)

    def refresh(self):
        self.__task__ = self.server.task_get(self.__task__.task_id)
        self.map_attributes()

    def gather(self, attribute='step'):
        """Return all the steps that belongs to this batch"""
        if attribute == 'step':
            return self.__steps__
        elif attribute == 'output':
            return [s.output for s in self.__steps__]
    
    def get_output(self):
        """Return task output stream if there is one"""
        executions = self.server.executions(task_id=self.task_id, latest=True)
        try:
            return list(executions)[0].output
        except IndexError:
            return None

    def get_error(self):
        """Return task error stream if there is one"""
        executions = self.server.executions(task_id=self.task_id, latest=True)
        if executions:
            return list(executions)[0].error
        else:
            return None
        
    def clean(self):
        """Clean the underlying task"""
        self.server.task_delete(self.task_id)


class Workflow:
    """A class to write workflow in a way close to Nextflow logic"""
    def __init__(self, name: str, server: str =os.environ.get('SCITQ_SERVER',DEFAULT_SERVER), 
                 provider: Optional[str] =None, region: Optional[str] =None,
                 flavor: Optional[str] =None, shell=False, maximum_workers=None, retry=None, rounds=None,
                 prefetch = None, container=None, container_options=''):
        self.name = name
        self.server = Server(server, style='object')
        self.provider = provider
        self.region = region
        self.flavor = flavor
        self.shell = shell
        self.maximum_workers = maximum_workers
        self.rounds = rounds
        self.prefetch = prefetch
        self.container_options = container_options
        self.retry = retry
        self.container = container
        self.__steps__ = []
        self.__batch__ = {}
        self.__input__ = None
        self.__quit__ = False
        self.__is_paused__ = False
        self.__clean__ = False
    
    def step(self, batch, command, concurrency=None, prefetch=Unset, provider=Unset, region=Unset, flavor=Unset, name=None, 
             tasks_per_worker=None, rounds=None, shell=Unset, maximum_workers=Unset, input=None, output=None, resource=None,
             required_tasks=None, container=Unset, container_options=Unset, retry=Unset):
        """Add a step to workflow
        - batch: batch for this step (all the different tasks and workers for this step will be grouped into that batch)
                NB batch is mandatory and is defined by at least concurrency and flavor (either at workflow or step level) 
                region and provider will be mandatory if you autorecruit, in which case adding rounds or tasks_per_worker and
                maximum_workers is strongly suggested.
        - concurrency: """

        # batch part

        provider = coalesce(provider,self.provider)
        region = coalesce(region, self.region)
        flavor = coalesce(flavor, self.flavor)
        rounds = coalesce(rounds, self.rounds)
        maximum_workers = coalesce(maximum_workers, self.maximum_workers)
        prefetch = coalesce(prefetch, self.prefetch)

        
        if tasks_per_worker is None:
            if rounds is None:
                tasks_per_worker = concurrency
            else:
                tasks_per_worker = concurrency * rounds

        # try to see if a batch is designated and we already now it
        if batch not in self.__batch__:
            if flavor is None:
                raise WorkflowException(f'A flavor is mandatory as batch {batch} is not already defined')
            if concurrency is None:
                raise WorkflowException(f'A concurrency is mandatory as batch {batch} is not already defined')
            if provider and region and maximum_workers is None:
                raise WorkflowException(f'A maximum number of worker (maximum_workers) is mandatory at workflow or step level if provider and reagion are set')
            self.__batch__[batch] = Batch(name=f'{self.name}.{batch}',
                                          shortname=batch,
                                          flavor=flavor, concurrency=concurrency, prefetch=prefetch,
                                          provider=provider, region=region,                                          
                                          tasks_per_worker=tasks_per_worker,
                                          server=self.server,
                                          maximum_workers=maximum_workers)
                
        # task part
        task = self.server.task_create(
            command = command,
            name = name,
            batch = self.__batch__[batch].name,
            input = input,
            output = output,
            container = coalesce(container, self.container),
            container_options = coalesce(container_options, self.container_options),
            resource = resource,
            shell=coalesce(shell, self.shell),
            retry=coalesce(retry, self.retry),
            required_task_ids = None if required_tasks is None \
                else [t if type(t)==int else t.task_id for t in required_tasks] if type(required_tasks)==list \
                else [required_tasks] if type(required_tasks)==int else [required_tasks.task_id],
        )


        step = Step(task, self.__batch__[batch])
        self.__steps__.append(step)
        return step
    

    
    def run(self, refresh=DEFAULT_REFRESH, hotkeys=True):
        """This is a monitoring function that display some info and run up to the point all tasks are done"""
        b=colors.bg
        f=colors.fg
        c=colors
        self.__exit_sleep__ = Event()
        first_time=True
        while True:
            self.__exit_sleep__.clear()
            batches = list([batch.name for batch in self.__batch__.values()])
            short_batches = list([batch.shortname for batch in self.__batch__.values()])
            tasks = self.server.tasks(task_id=[s.task_id for s in self.__steps__])
            workers = self.server.workers(batch=batches)

            task_stats = {}
            worker_stats = {}
            for batch in batches:
                task_stats[batch] = {status:0 for status in TASK_STATUS}
                worker_stats[batch] = {status:0 for status in WORKER_STATUS}
            for task in tasks:
                task_stats[task.batch][task.status]+=1
            for worker in workers:
                worker_stats[worker.batch][worker.status]+=1

            if not first_time:
                print(f'\x1b[{lines}A',end='')
            print(f"{b.lightgrey}{f.black}{'BATCH':^20}{b.black}{f.white}{'TASKS':^40}{b.blue}{f.black}{'WORKERS':^20}")
            print(f"{b.lightgrey}{f.black}{self.name[:20]:^20}\
{b.black}{f.yellow} PAU {f.white} WAI {f.lightblue} PEN {f.cyan} ASN {f.lightcyan} ACC {f.green} RUN {f.red} FAI {f.lightgreen} SCS \
{b.blue}{f.yellow} PAU {f.black} OFF {f.lightgreen} RUN {f.red} FAI {c.reset}")
            
            lines=2
            remaining_tasks = 0
            for short,batch in zip(short_batches,batches):
                ts = dmap(_,task_stats[batch])
                ws = dmap(_,worker_stats[batch])
                print(f"{b.lightgrey}{f.black}{short[:20]:^20}\
{b.black}{f.yellow}{ts['paused']:^5}{f.white}{ts['waiting']:^5}{f.lightblue}{ts['pending']:^5}{f.cyan}{ts['assigned']:^5}\
{f.lightcyan}{ts['accepted']:^5}{f.green}{ts['running']:^5}{f.red}{ts['failed']:>5}{f.lightgreen}{ts['succeeded']:^5}\
{b.blue}{f.yellow}{ws['paused']:^5}{f.black}{ws['offline']:^5}{f.lightgreen}{ws['running']:^5}{f.red}{ws['failed']:^5}{c.reset}")
                lines+=1
                remaining_tasks+=sum([ts[s] or 0 for s in TASK_STATUS if s not in ['failed','succeeded']])

            if hotkeys:
                if first_time:
                    self.__listener__= keyboard.Listener(on_press=self.keypressed, suppress=True)
                    self.__listener__.start()
                if self.__listener__.is_alive():
                    if self.__is_paused__:
                        print(f" {f.black}{b.purple}{c.blinking}{'(R)EFRESY':^10}{c.reset} {f.black}{b.purple}{c.blinking}{'(U)NPAUSE':^26}{c.reset} \
{f.black}{b.purple}{'(Q)UIT':^10}{c.reset} {f.black}{b.purple}{'(D)ESTROY':^10}{c.reset} {f.black}{b.purple}{'(H)QUIT HOTKEYS':^10}{c.reset} ")
                    else:
                        print(f" {f.black}{b.purple}{c.blinking}{'(R)EFRESY':^10}{c.reset} {f.black}{b.purple}{'(P)AUSE':^10}{c.reset} {f.black}{b.purple}{'(S)USPEND ALL':^15}{c.reset} \
{f.black}{b.purple}{'(Q)UIT':^10}{c.reset} {f.black}{b.purple}{'(D)ESTROY':^10}{c.reset} {f.black}{b.purple}{'(H)QUIT HOTKEYS':^10}{c.reset} ")
                else:
                    print(f'                                                                            ')
                lines+=1

                    

            if remaining_tasks == 0 or self.__quit__:
                break
            self.__exit_sleep__.wait(refresh)
            first_time = False
        if hotkeys:
            if self.__listener__.is_alive():
                self.__listener__.stop()

    def print_function_line(self):
        b=colors.bg
        f=colors.fg
        c=colors


    def clean(self, force=False):
        """Clean all, except failed tasks if force is not set to True"""
        if not self.__clean__:
            for batch in self.__batch__.values():
                batch.clean()
            for task in self.server.tasks(task_id=[s.task_id for s in self.__steps__]):
                if task.status == 'succeeded' or force:
                    self.server.task_delete(task.task_id)
            self.__clean__ = True

    def quit(self):
        """Quit immediatly without waiting that all tasks are done"""
        self.__quit__=True

    def pause(self, suspend=False):
        """Put all worker to pause"""
        if not self.__is_paused__:
            signal = SIGTSTP if suspend else 0
            self.__is_paused__ = SIGTSTP if suspend else True
            for batch in self.__batch__.values():
                batch.pause(signal)

    def unpause(self):
        """Restore running """
        if self.__is_paused__:
            signal = SIGCONT if self.__is_paused__==SIGTSTP else 0
            for batch in self.__batch__.values():
                batch.unpause(signal)
            self.__is_paused__ = False
    
    def keypressed(self, key):
        other_key = False
        if hasattr(key,'char'):
            if key.char=='q':
                self.quit()
            elif key.char=='p':
                self.pause()
            elif key.char=='s':
                self.pause(suspend=True)
            elif key.char=='u':
                self.unpause()
            elif key.char=='d':
                self.clean(force=True)
                self.quit()
            elif key.char=='h':
                self.__listener__.stop()
            elif key.char=='r':
                pass
            else:
                other_key = True
        else:
            other_key = True
        if not other_key:
            self.__exit_sleep__.set()
        
