from .lib import Server
from .util import coalesce, colors
from typing import Optional
from time import sleep
import os

DEFAULT_SERVER='127.0.0.1'
DEFAULT_REFRESH=30
TASK_STATUS=['paused','waiting','pending','assigned','accepted','running','failed','succeeded']
WORKER_STATUS=['paused','running','offline','failed']

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
        self.recruiter = self.create_recruiter()

    def create_recruiter(self):
        return self.server.recruiter_create(batch = self.name, tasks_per_worker=self.tasks_per_worker, 
                            flavor=self.flavor, concurrency=self.concurrency, region=self.region, 
                            provider=self.provider, prefetch=self.prefetch,
                            maximum_workers=self.maximum_workers)

class Step:
    """A step in a workflow, a class mixing scitq Task and Batch concepts to help writing in workflow logic"""
    __steps__ = {}

    def __init__(self, task, batch):
        self.task = task
        self.batch = batch
        self.task_id = task.task_id
        if batch.name not in self.__steps__:
            self.__steps__[batch.name] = []
        self.__steps__[batch.name].append(self)

    def gather(self):
        """Return all the steps that belongs to this batch"""
        return self.__steps__[self.batch.name]

class Workflow:
    """A class to write workflow in a way close to Nextflow logic"""
    def __init__(self, name: str, server: str =os.environ.get('SCITQ_SERVER',DEFAULT_SERVER), 
                 provider: Optional[str] =None, region: Optional[str] =None,
                 flavor: Optional[str] =None, shell=False, maximum_workers=None, retry=None, rounds=None,
                 prefetch = None, container_options=''):
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
        self.__tasks__ = []
        self.__batch__ = {}
        self.__input__ = None
    
    def step(self, batch, command, concurrency=None, prefetch=None, provider=None, region=None, flavor=None, name=None, 
             tasks_per_worker=None, rounds=None, shell=None, maximum_workers=None, input=None, output=None, resource=None,
             requires=None, container=None, docker=None, container_options=None, retry=None):
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
                                          server=self.server)
                
        # task part
        task = self.server.task_create(
            command = command,
            name = name,
            batch = self.__batch__[batch].name,
            input = input,
            output = output,
            container = coalesce(container, docker),
            container_options = coalesce(container_options, self.container_options),
            resource = resource,
            shell=coalesce(shell, self.shell),
            retry=coalesce(retry, self.retry),
            required_task_ids = None if requires is None else [t if type(t)==int else t.task_id for t in requires],
        )


        step = Step(task, self.__batch__[batch])
        self.__steps__.append(step)
        return step
    

    
    def run(self, refresh=DEFAULT_REFRESH):
        """This is a monitoring function that display some info and run up to the point all tasks are done"""
        b=colors.bg
        f=colors.fg
        c=colors
        first_time=True
        while True:
            batches = list([batch.name for batch in self.__batch__])
            short_batches = list([batch.short_name for batch in self.__batch__])
            tasks = self.server.tasks(batch=batches)
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
            print(f"{b.lightgrey}{f.black}{'':^20}{b.black}{f.white}{'TASKS':^40}{b.blue}{f.black}{'WORKERS':^20}")
            print(f"{b.lightgrey}{f.black}{'BATCH':^20}\
{b.black}{f.yellow} PSE {f.white} WAI {f.lightblue} PEN {f.cyan} ASG {f.lightcyan} ACC {f.green} RUN {f.red} FAI {f.lightgreen} SUC \
{b.blue}{f.yellow} PAU {f.black} OFF {f.lightgreen} RUN {f.red} FAI {c.reset}")
            
            lines=2
            remaining_tasks = 0
            for short,batch in zip(short_batches,batches):
                ts = dmap(_,task_stats[batch])
                ws = dmap(_,worker_stats[batch])
                print(f"{b.lightgrey}{f.black}{short:<20}\
{b.black}{f.yellow}{ts['paused']:>5}{f.white}{ts['wait']:>5}{f.lightblue}{ts['pending']:>5}{f.cyan}{ts['assigned']:>5}\
{f.lightcyan}{ts['accepted']:>5}{f.green}{ts['running']:>5}{f.red}{ts['failed']:>5}{f.lightgreen}{ts['succeeded']:>5}\
{b.blue}{f.yellow}{ws['paused']:>5}{f.black}{ws['offline']:>5}{f.lightgreen}{ws['running']:>5}{f.red}{ws['running']:>5}{c.reset}")
                lines+=1
                remaining_tasks+=sum([ts[s] for s in TASK_STATUS if s not in ['failed','succeeded']])
            
            if remaining_tasks == 0:
                break
            sleep(refresh)
            first_time = False



