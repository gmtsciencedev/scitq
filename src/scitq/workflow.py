from .lib import Server
from .fetch import get
from typing import Optional
from time import sleep
import os
from signal import SIGTSTP, SIGCONT
import urwid
from threading import Event,Thread
import logging as log

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
    def __init__(self, name, shortname, flavor, concurrency, provider, region, 
                 tasks_per_worker, maximum_workers, prefetch, server, extra_workers=0):
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
        self.extra_workers = extra_workers
        self.__recruiter__ = None
        self.__extra_recruiter__ = None
        self.recruit()

    def recruit(self):
        self.__recruiter__ = self.create_recruiter()
        if self.extra_workers>0:
            self.__extra_recruiter__ = self.create_recruiter(rank=2, maximum_workers=self.extra_workers, provider=None, region=None)

    def create_recruiter(self, rank=1, flavor=Unset, region=Unset, provider=Unset, maximum_workers=Unset):
        maximum_workers = coalesce(maximum_workers,self.maximum_workers)
        if maximum_workers and maximum_workers>0:
            return self.server.recruiter_create(batch = self.name, 
                            rank=rank, 
                            tasks_per_worker=self.tasks_per_worker, 
                            flavor=coalesce(flavor,self.flavor), 
                            concurrency=self.concurrency, 
                            region=coalesce(region,self.region), 
                            provider=coalesce(provider,self.provider), 
                            prefetch=self.prefetch,
                            maximum_workers=coalesce(maximum_workers,self.maximum_workers))
        else:
            return None
    
    def clean(self):
        self.server.recruiter_delete(self.name, rank=1)
        if self.extra_workers>0:
            self.server.recruiter_delete(self.name, rank=2)
    
    def destroy(self):
        self.server.batch_delete(batch=self.name)

    def pause(self, signal=0):
        self.server.batch_stop(self.name, signal=signal)
        if self.__recruiter__ is not None:
            self.server.recruiter_delete(self.name, rank=1)
        if self.__extra_recruiter__ is not None:
            self.server.recruiter_delete(self.name, rank=2)

    def unpause(self, signal=0):
        self.server.batch_go(self.name, signal=signal)
        self.recruit()
    
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

    def download(self, destination=None):
        """Download this step output"""
        if destination is None:
            destination=os.getcwd()
        get(self.output,destination)

palette = [
    ('basic', 'light gray', 'black'),
    ('inverted', 'black', 'light gray'),
    ('blueb', 'black', 'dark blue'),
    ('bluey', 'yellow', 'dark blue'),
    ('blueg', 'light green', 'dark blue'),
    ('bluer', 'light red', 'dark blue'),
    ('y', 'yellow', 'black'),
    ('w', 'white', 'black'),
    ('db', 'dark blue', 'black'),
    ('dc', 'dark cyan', 'black'),
    ('c', 'light cyan', 'black'),
    ('dg', 'dark green', 'black'),
    ('r', 'light red', 'black'),
    ('g', 'light green', 'black'),
    ('purpleb', 'black', 'dark magenta'),
    ('purpley', 'yellow', 'dark magenta'),
]

def cell(txt, size, style='basic'):
    """Small wrapper above urwid.Text"""
    txt = "{{:^{}}}".format(size).format(str(txt)[:size])
    return (size, urwid.Text((style, txt)))

def cell_update(cell, txt):
    """Small function to manipulate Cell content"""
    size,content=cell
    style = content.attrib[0][0]
    txt = "{{:^{}}}".format(size).format(str(txt)[:size])
    content.set_text((style,txt))

def padding_update(padding, widget):
    padding.original_widget = widget

class Workflow:
    """A class to write workflow in a way close to Nextflow logic"""
    def __init__(self, name: str, max_step_workers=None, 
                 server: str =os.environ.get('SCITQ_SERVER',DEFAULT_SERVER), 
                 provider: Optional[str] =None, region: Optional[str] =None,
                 flavor: Optional[str] =None, shell=False, max_workflow_workers=None, 
                 retry=None, rounds=None, prefetch = None, container=None, container_options='', 
                 download_timeout=None, run_timeout=None):
        """Workflow init:
        Mandatory:
        - name [str]: name of workflow
        - maximum_workers [int]: How many workers will be recruited by default for each step (default to 1)
        - total_workers 
        """
        self.name = name
        self.server = Server(server, style='object')
        self.provider = provider
        self.region = region
        self.flavor = flavor
        self.shell = shell
        self.max_step_workers = max_step_workers
        self.max_workflow_workers = max_workflow_workers
        if max_step_workers and max_workflow_workers and max_step_workers > max_workflow_workers:
            log.warning(f'Inconsistant settings: max_step_workers ({max_step_workers}) is above max_workflow_workers ({max_workflow_workers})')
        self.rounds = rounds
        self.prefetch = prefetch
        self.container_options = container_options
        self.retry = retry
        self.container = container
        self.download_timeout = download_timeout
        self.run_timeout = run_timeout
        self.__steps__ = []
        self.__batch__ = {}
        self.__input__ = None
        self.__quit__ = False
        self.__is_paused__ = False
        self.__clean__ = False
        self.__current_workers__=0
        if region and provider and not max_workflow_workers:
            raise WorkflowException('For security, set the "max_workflow_workers" parameter if provider and region are set')
    
    def step(self, batch, command, concurrency=None, prefetch=Unset, provider=Unset, region=Unset, flavor=Unset, name=None, 
             tasks_per_worker=None, rounds=None, shell=Unset, maximum_workers=Unset, input=None, output=None, resource=None,
             required_tasks=None, container=Unset, container_options=Unset, retry=Unset,
             download_timeout=Unset, run_timeout=Unset):
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
        maximum_workers = coalesce(maximum_workers, self.max_step_workers)
        if maximum_workers is None and batch not in self.__batch__:
            raise WorkflowException(f'maximum_workers is mandatory if workflow.max_step_workers is unset and batch {batch} is not already defined')
        extra_workers=0


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
            if provider and region:
                if maximum_workers+self.__current_workers__ > self.max_workflow_workers:
                    target_maximum_workers = maximum_workers
                    maximum_workers = max(self.max_workflow_workers - self.__current_workers__,0)
                    maximum_workers = min(maximum_workers, target_maximum_workers)
                    extra_workers = max(target_maximum_workers - maximum_workers,0)

            self.__current_workers__ += maximum_workers

            self.__batch__[batch] = Batch(name=f'{self.name}.{batch}',
                                          shortname=batch,
                                          flavor=flavor, concurrency=concurrency, prefetch=prefetch,
                                          provider=provider, region=region,                                          
                                          tasks_per_worker=tasks_per_worker,
                                          server=self.server,
                                          maximum_workers=maximum_workers,
                                          extra_workers=extra_workers)
                            
        # task part

        if type(input)==list:
            input = ' '.join(input)

        if type(resource)==list:
            resource = ' '.join(resource)
        
        if type(output)==list:
            raise WorkflowException(f'Task {name} error: output must be a single path, not a list')

        if output and not output.endswith('/'):
            output += '/'

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
            download_timeout=coalesce(download_timeout, self.download_timeout),
            run_timeout=coalesce(run_timeout, self.run_timeout),
            required_task_ids = None if required_tasks is None \
                else [t if type(t)==int else t.task_id for t in required_tasks] if type(required_tasks)==list \
                else [required_tasks] if type(required_tasks)==int else [required_tasks.task_id],
        )


        step = Step(task, self.__batch__[batch])
        self.__steps__.append(step)
        return step
    

    
    def run(self, refresh=DEFAULT_REFRESH):
        """This is a monitoring function that display some info and run up to the point all tasks are done"""
        # prepare display
        title_line = urwid.Columns([cell('BATCH',20,'inverted'),cell('TASKS',40,'w'),cell('WORKERS',20,'blueb')])
        subtitle_line = urwid.Columns([cell(self.name,20,'inverted'),cell('PAU',5,'y'),cell('WAI',5,'b'),cell('PEN',5,'db'),
                            cell('ASN',5,'dc'),cell('ACC',5,'c'),cell('RUN',5,'dg'),cell('FAI',5,'r'),cell('SCS',5,'g'),
                            cell('PAU',5,'bluey'),cell('OFF',5,'blueb'),cell('RUN',5,'blueg'),cell('FAI',5,'bluer')])
        urwid_table = [title_line,subtitle_line]
        
        cells = {}
        for batch in list([batch.shortname for batch in self.__batch__.values()]):
            cells[batch] = { 'task':{}, 'worker':{} }
            line = [cell(batch,20,'inverted')]
            for status,style in [('paused','y'),('waiting','b'),('pending','db'),('assigned','dc'),
                                 ('accepted','c'),('running','dg'),('failed','r'),('succeeded','g')]:
                c = cell('',5,style)
                line.append(c)
                cells[batch]['task'][status]=c
            for status,style in [('paused','bluey'),('offline','blueb'),('running','blueg'),('failed','bluer')]:
                c = cell('',5,style)
                line.append(c)
                cells[batch]['worker'][status]=c
            urwid_table.append(urwid.Columns(line))
        
        command_bar_base = urwid.Columns([cell('(R)EFRESH',10,'purpleb'), cell('(P)AUSE',10,'purpleb'),
                                      cell('(S)USPEND ALL',15,'purpleb'), cell('(Q)UIT',10,'purpleb'),
                                      cell('(U)NPAUSE',10,'purpleb'),
                                      cell('(D)ESTROY',10,'purpleb') ],dividechars=1)
        command_bar_destroy = urwid.Columns([cell('ARE YOU SURE WANT TO DESTROY EVERYTHING ?',50,'purpley'),cell('(Y)ES',9,'purpley'),cell('(any)NO',9,'purpley')],dividechars=1)
        command_bar_quit = urwid.Columns([cell('ARE YOU SURE WANT TO QUIT ?',50,'purpley'),cell('(Y)ES',9,'purpley'),cell('(any)NO',9,'purpley')],dividechars=1)
        
        command_bar = urwid.Padding(command_bar_base,align='center',width=95)

        urwid_table.append(command_bar)

        table = urwid.Pile(urwid_table)
        fill = urwid.Filler(table)
         
        self.ui_state = 'base'
        def handle_keys(key):
            if self.ui_state=='base':
                if key in ('q', 'Q'):
                    self.ui_state='quit'
                    padding_update(command_bar,command_bar_quit)
                    self.__exit_sleep__.set()                    
                elif key in ('r','R'):
                    self.__exit_sleep__.set()
                elif key in ('d','D'):
                    self.ui_state='destroy'
                    padding_update(command_bar,command_bar_destroy)
                    self.__exit_sleep__.set()
                elif key in ('p','P'):
                    self.pause()
                    self.__exit_sleep__.set()
                elif key in ('s','S'):
                    self.pause(suspend=True)
                    self.__exit_sleep__.set()
                elif key in ('u','U'):
                    self.unpause()
                    self.__exit_sleep__.set()
            else:
                if key in ('y','Y'):
                    if self.ui_state=='destroy':
                        self.clean(force=True)
                        self.__quit_thread__.set()
                        self.__exit_sleep__.set()
                        raise urwid.ExitMainLoop()
                    elif self.ui_state=='quit':
                        self.__quit_thread__.set()
                        self.__exit_sleep__.set()
                        raise urwid.ExitMainLoop()
                else:
                    padding_update(command_bar,command_bar_base)
                    self.ui_state='base'

        loop = urwid.MainLoop(fill, palette=palette, unhandled_input=handle_keys)


        self.__exit_sleep__ = Event()
        self.__quit_thread__ = Event()
        def query_loop(once=False):
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

                remaining_tasks = 0
                for short,batch in zip(short_batches,batches):
                    for status in TASK_STATUS:
                        cell_update(cells[short]['task'][status],_(task_stats[batch][status]))
                        #cell_update(cells[short]['task'][status],'X')
                        pass
                    for status in WORKER_STATUS:
                        cell_update(cells[short]['worker'][status],_(worker_stats[batch][status]))
                        pass

                    remaining_tasks+=sum([task_stats[batch][s] for s in TASK_STATUS if s not in ['failed','succeeded']])

                loop.draw_screen()
                if remaining_tasks == 0:
                    self.__quit_thread__.set()
                    break
                self.__exit_sleep__.wait(refresh)

        def check_quit_thread(loop, *args):
            if self.__quit_thread__.is_set():
                raise urwid.ExitMainLoop()
            else:
                loop.set_alarm_in(
                    sec=0.5,
                    callback=check_quit_thread,
                    )
        
        loop.set_alarm_in(sec=0.5, callback=check_quit_thread)

        query_loop_thread = Thread(target=query_loop)
        query_loop_thread.start()
        loop.run()

        if self.ui_state in ['quit','destroy']:
            raise RuntimeError(f'Workflow.run() was interrupted because of app was in {self.ui_state} state')


    def clean(self, force=False, download_logs=True, log_destination=Unset):
        """Clean all, except failed tasks if force is not set to True"""
        if log_destination is Unset:
            log_destination=self.name
        if not self.__clean__:
            if force:
                for batch in self.__batch__.values():
                    batch.destroy()
            else:
                for task in self.server.tasks(task_id=[s.task_id for s in self.__steps__]):
                    if download_logs and log_destination is not None:
                        if not os.path.exists(log_destination):
                            os.makedirs(log_destination)
                        executions = self.server.executions(task_id=task.task_id, latest=True)
                        try:
                            execution = next(iter(executions))
                            base_log_name = os.path.join(
                                    log_destination,
                                    task.name if task.name else f'task_{task.task_id}'
                            )
                            if execution.output is not None:
                                with open(base_log_name+'_output.log','a+') as f:
                                    f.write(execution.output)
                            if execution.error is not None:
                                with open(base_log_name+'_error.log','a+') as f:
                                    f.write(execution.error)                        
                        except StopIteration:
                            pass
                    if task.status == 'succeeded':
                        self.server.task_delete(task.task_id)
                for batch in self.__batch__.values():
                    batch.clean()
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
        else:
            batches=list([batch.name for batch in self.__batch__.values()])
            workers = self.server.workers(batch=batches, status='paused')
            for worker in workers:
                self.server.worker_update(worker.worker_id,status='running')

    def download(self, uri_list=None, destination=None):
        """Download all step output  - or provide some uri in uri_list"""
        if destination is None:
            destination=os.getcwd()
        if uri_list is None:
            uri_list = []
            for step in self.__steps__:
                os.makedirs(os.path.join(destination,step.name))
                get(step.gather('output'),os.path.join(destination,step.name))
        else:        
            if type(uri_list)!=list:
                uri_list=[uri_list]
            for uri in uri_list:
                get(uri,destination)

