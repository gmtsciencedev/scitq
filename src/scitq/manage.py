#!/usr/bin/env python
from tabulate import tabulate 
from .lib  import Server
from subprocess import run
import argparse
from datetime import datetime
import os 
from .util import package_path, package_version
from .ansible.scitq.sqlite_inventory import inventory, decorate_parser
import shutil
import random
from .debug import Debugger
from .constants import DEFAULT_SERVER_CONF, DEFAULT_WORKER_CONF, TASK_STATUS
from signal import SIGKILL, SIGCONT, SIGQUIT, SIGTSTP
import dotenv

MAX_LENGTH_STR=50
DEFAULT_SERVER = os.getenv('SCITQ_SERVER','127.0.0.1')
DEFAULT_ANSIBLE_INVENTORY = '/etc/ansible/inventory'
DEFAULT_PROVIDER='ovh'

def converter(x,long): 
    """A small conversion function for items in lists"""
    if type(x)==datetime:
        x=str(x)
    elif type(x)==str and not long:
        if len(x)> MAX_LENGTH_STR :
            x=x[:MAX_LENGTH_STR-1] +'...'
    elif type(x)==list:
        x=','.join([str(element) for element in x])
    return x

def __list_print(item_list, retained_columns, headers, long=False):
    """A small internal function to format a list of items (i.e. tasks or workers)"""
    print(
        tabulate(
            [[converter(item.get(key,None),long) for key in retained_columns]
                for item in item_list],
            headers=headers,tablefmt ="plain"
            )
        )

def main():
    parser = argparse.ArgumentParser()
    
    parser.add_argument('-s','--server', help=F"Define a server, by default {DEFAULT_SERVER} this default value comes from the SCITQ_SERVER environment variable",type=str,default=DEFAULT_SERVER)
    parser.add_argument('-t','--timeout', type=int,
            help='Specify the get timeout for complex queries (default to 150s)' )
    parser.add_argument('--version', action='store_true',
            help="Print the version and exit")

    subparser=parser.add_subparsers(help='sub-command help',dest='object')
    worker_parser = subparser.add_parser('worker', help='The following options will only concern workers')
    subsubparser=worker_parser.add_subparsers(dest='action')
    list_worker_parser=subsubparser.add_parser('list', help='List all workers')
    list_worker_parser.add_argument('-b','--batch',help="Give you a list of workers according to his name",type=str,default='')
    list_worker_parser.add_argument('-S','--status',help="give you a list of workers according to his status",type=str,default='',choices=['','running','paused','offline','failed'])
    list_worker_parser.add_argument('-H','--no-header',help='Do not print headers',action='store_true')
    list_worker_parser.add_argument('-L','--long',help='Print the entire command',action='store_true')

    deploy_parser=subsubparser.add_parser('deploy',help="Deploy a new worker")
    deploy_parser.add_argument('-C','--concurrency',help="Define how many tasks the worker can do at once (default to 1)",type=int,default=1)
    deploy_parser.add_argument('-p','--prefetch',help="Define how many tasks should be prefetched (default to 0)",type=int,default=0)
    deploy_parser.add_argument('-f','--flavor',required=True,help="Define which flavor/model should be ordered (MANDATORY)",type=str)
    deploy_parser.add_argument('-r','--region',required=True,help="Define in which provider region to order (MANDATORY)",type=str)
    deploy_parser.add_argument('-P','--provider',required=True,help=f"Define from which provider rent the worker (default to {DEFAULT_PROVIDER})",
                               type=str, default=DEFAULT_PROVIDER)
    deploy_parser.add_argument('-N','--number',help="Define the number of workers you want to create (default to 1)",type=int, default=1)
    deploy_parser.add_argument('-b','--batch',help="Define the batch that should fit the tasks'one (default to None, default batch)",type=str,default=None)

    worker_delete_parser=subsubparser.add_parser('delete',help="Delete a worker, possibly terminating the VM")
    worker_delete_parser.add_argument('-n','--name',help="The name of the worker to delete (MANDATORY if -i not used)",type=str, default=None)
    worker_delete_parser.add_argument('-i','--id',help="The id of the worker to delete (MANDATORY if -n is not used)",type=int, default=None)

    worker_update_subparser = subsubparser.add_parser('update', help='Modify some worker')
    worker_update_subparser.add_argument('-i','--id', help='The ID of the worker to modify (MANDATORY if -n is not used)', type=int, default=None)
    worker_update_subparser.add_argument('-n','--name', help='The name of the worker to modify (MANDATORY if -i is not used)', type=str, default=None)
    worker_update_subparser.add_argument('-S','--status', help='The new status of the worker', type=str, default=None)
    worker_update_subparser.add_argument('-b','--batch', help='The new batch of the worker', type=str, default=None)
    worker_update_subparser.add_argument('-C','--concurrency', help='The new concurrency of the worker', type=str, default=None)
    worker_update_subparser.add_argument('-p','--prefetch',help="Define how many tasks should be prefetched",type=int,default=None)
    worker_update_subparser.add_argument('-f','--flavor',help="Define which flavor/model should be ordered",type=str,default=None)
    

    batch_parser = subparser.add_parser('batch', help='The following options will only concern batches')
    subsubparser=batch_parser.add_subparsers(dest='action')
    list_parser=subsubparser.add_parser('list',help='List batches')

    pause_parser=subsubparser.add_parser('stop',help='Stop (pause) a batch')
    pause_parser.add_argument('-n','--name', help='Target the batch with his name. Accept a name or also a list of name by using -n name1 -n name2',action='append',required=True)
    option_group=pause_parser.add_mutually_exclusive_group()
    option_group.add_argument('-N','--number',help='Create a signal if number equals 3, 9, 20',default=0,type=int,choices=[0,3,9,20])
    option_group.add_argument('--term',help='Send the TERM signal (same as -N 3)',action='store_true')
    option_group.add_argument('--kill',help='Send the KILL signal (same as -N 9)',action='store_true')
    option_group.add_argument('--pause',help='Send the SIGTSTP (pause) signal (same as -N 20)',action='store_true')


    go_parser=subsubparser.add_parser('go',help='Continue (relaunch) the execution of a batch ')
    go_parser.add_argument('-n','--name',help='Target the batch with his name. Accept a name or also a list of name by using -n name1 -n name2',action='append',required=True)
    option_group=go_parser.add_mutually_exclusive_group()
    option_group.add_argument('-N','--number',help='Create a signal if number equals 18',default=0,type=int,choices=[0,18])
    option_group.add_argument('--cont',help='Send the SIGCONT (continue) signal (same as -N 18)',action='store_true')

    clear_parser=subsubparser.add_parser('delete',help='Delete (clear) a batch')
    clear_parser.add_argument('-n','--name', help='Target the batch with his name. Accept a name or also a list of name by using -n name1 -n name2',action='append',required=True)

    task_parser = subparser.add_parser('task', help='The following options will only concern tasks')
    subsubparser=task_parser.add_subparsers(dest='action')
    list_task_parser= subsubparser.add_parser('list',help='List all tasks')
    list_task_parser.add_argument('-S','--status',help='Give you a list of tasks according to his status',type=str,choices=TASK_STATUS,default='')
    list_task_parser.add_argument('-b','--batch',help='Give you a list of tasks according to his batch',type=str,default='')
    list_task_parser.add_argument('-H','--no-header',help='Do not print the headers',action='store_true')
    list_task_parser.add_argument('-L','--long',help='Print the entire command',action='store_true')

    go_task_parser= subsubparser.add_parser('relaunch',help='Relaunch a task')
    option_group=go_task_parser.add_mutually_exclusive_group()
    option_group.add_argument('-i','--id',help='Target a task by his id (MANDATORY if -n is not used)',type=int)
    option_group.add_argument('-n','--name', help='The name of the task to delete (MANDATORY if -i is not used)', type=str)
    
    output_task_parser= subsubparser.add_parser('output',help='Show the output/error for a task')
    option_group=output_task_parser.add_mutually_exclusive_group()
    option_group.add_argument('-i','--id',help='Target a task by his id (MANDATORY if -n is not used)',type=int)
    option_group.add_argument('-n','--name', help='The name of the task to delete (MANDATORY if -i is not used)', type=str)
    option_group=output_task_parser.add_mutually_exclusive_group()
    option_group.add_argument('-o','--output',help='Show only the output for a task',action='store_true')
    option_group.add_argument('-e','--error',help='Show only the error for a task',action='store_true')

    task_delete_subparser = subsubparser.add_parser('delete', help='Delete some task')
    option_group=task_delete_subparser.add_mutually_exclusive_group()
    option_group.add_argument('-i','--id',help='Target a task by his id (MANDATORY if -n is not used)',type=int)
    option_group.add_argument('-n','--name', help='The name of the task to delete (MANDATORY if -i is not used)', type=str)
    
    task_update_subparser = subsubparser.add_parser('update', help='Modify some task')
    option_group=task_update_subparser.add_mutually_exclusive_group()
    option_group.add_argument('-i','--id',help='Target a task by his id (MANDATORY if -n is not used)',type=int)
    option_group.add_argument('-n','--name', help='The name of the task to delete (MANDATORY if -i is not used)', type=str)
    task_update_subparser.add_argument('-N','--new-name', help='The new name of the task', type=str, default=None)
    task_update_subparser.add_argument('-c','--command', help='The new command of the task', type=str, default=None)
    task_update_subparser.add_argument('-S','--status', help='The new status of the task', type=str, default=None)
    task_update_subparser.add_argument('-b','--batch', help='The new batch of the task', type=str, default=None)
    task_update_subparser.add_argument('-d','--docker', help='The new docker for the task', type=str, default=None)
    task_update_subparser.add_argument('-O','--option', help='The new docker option for the task', type=str, default=None)
    task_update_subparser.add_argument('-j','--input', help='The new input for the task', type=str, default=None)
    task_update_subparser.add_argument('-o','--output', help='The new output for the task', type=str, default=None)
    task_update_subparser.add_argument('-R','--requirements', help='A new space separated required task ids', type=str, default=None)
    task_update_subparser.add_argument('--run-timeout', help='Change the run timeout (in seconds) for this task', type=int, default=None)
    task_update_subparser.add_argument('--download-timeout', help='Change the download timeout (in seconds) for this task', type=int, default=None)
    
    ansible_parser = subparser.add_parser('ansible', help='The following options are to work with ansible subcode')
    subsubparser=ansible_parser.add_subparsers(dest='action')
    ansible_path_parser=subsubparser.add_parser('path',help='Return the path of scitq Ansible playbooks')
    ansible_install_parser=subsubparser.add_parser('install',help='Install scitq Ansible inventory files')
    ansible_install_parser.add_argument('-p','--path', help=f'specify install path (default to {DEFAULT_ANSIBLE_INVENTORY})',
         type=str, default=DEFAULT_ANSIBLE_INVENTORY)
    ansible_inventory_parser=subsubparser.add_parser('inventory',help='Execute the internal inventory command')
    decorate_parser(ansible_inventory_parser)

    debug_parser = subparser.add_parser('debug', help='The following options help debuging a new task')
    subsubparser=debug_parser.add_subparsers(dest='action')
    debug_run_parser=subsubparser.add_parser('run',help='Run a debugging task (pick randomly if -i or -n is not specified)')
    debug_run_parser.add_argument('-b','--batch',help='Pick task in this batch',type=str, default=None)
    debug_run_parser.add_argument('-i','--id',help='Use the task with this id',type=int, default=None)
    debug_run_parser.add_argument('-n','--name', help='Use the task with this id', type=str, default=None)
    debug_run_parser.add_argument('-r','--retry', help='Do not re-download input and resources, it is just a retry', action='store_true')
    debug_run_parser.add_argument('--no-resource', help='Do not re-download resources, but re-download inputs', action='store_true')
    debug_run_parser.add_argument('-c','--conf', help=f'Use this environment file to set environment (default to {DEFAULT_SERVER_CONF})', type=str, default=DEFAULT_SERVER_CONF)
    debug_run_parser.add_argument('-w','--worker-conf', help=f'Use this environment file to set extra environment (default to {DEFAULT_WORKER_CONF})', 
                                  type=str, default=DEFAULT_WORKER_CONF)
    
    recruiter_parser = subparser.add_parser('recruiter', help='Do some action about recruiter objects (recruiters automatically deploy workers in a batch when needed)')
    subsubparser=recruiter_parser.add_subparsers(dest='action')

    list_recruiter_parser=subsubparser.add_parser('list', help='List all recruiter')
    list_recruiter_parser.add_argument('-b','--batch',help="Filter recruiter for this batch",type=str,default=None)
    list_recruiter_parser.add_argument('-L','--long',help='Print all recruiter details',action='store_true')
    list_recruiter_parser.add_argument('-H','--no-header',help='Do not print headers',action='store_true')

    recruiter_create_parser = subsubparser.add_parser('create', help='Create a new recruiter (or override a recruiter of the same rank for this batch)')
    recruiter_create_parser.add_argument('-b','--batch',type=str,required=True,help='batch in which workers are deployed')
    recruiter_create_parser.add_argument('-n','--rank',type=int,help='rank in which recruiter is tried (unique per batch), default to 1',default=1)
    recruiter_create_parser.add_argument('-f','--flavor',type=str,required=True,help='flavor (type of instance) of worker needed')
    recruiter_create_parser.add_argument('-r','--region',type=str,help='worker region of provenance',default=None)
    recruiter_create_parser.add_argument('-P','--provider',type=str,help='worker provider',default=None)
    recruiter_create_parser.add_argument('-C','--concurrency',type=int,required=True,help='what should be the concurrency setting of recruited workers')
    recruiter_create_parser.add_argument('-p','--prefetch',type=int,help='what should be the prefetch setting of recruited workers (default to 0)',default=None)
    recruiter_create_parser.add_argument('-T','--tasks-per-worker',type=int,help='how many workers should be recruited (default to concurrency, but if you want each worker to work two rounds, set it to twice the concurrency)',default=None)
    recruiter_create_parser.add_argument('-m','--minimum-tasks',type=int,help='prevent the recruiter from triggering before this minimal number of tasks is reached',default=None)
    recruiter_create_parser.add_argument('-W','--maximum-workers',type=int,help='prevent the recruiter from recruiting more than this number of worker',default=None)
    
    recruiter_modify_parser = subsubparser.add_parser('update', help='Update a recruiter')
    recruiter_modify_parser.add_argument('-b','--batch',type=str,required=True,help='batch in which workers are deployed')
    recruiter_modify_parser.add_argument('-n','--rank',type=int,help='rank in which recruiter is tried (unique per batch), default to 1',default=1)
    recruiter_modify_parser.add_argument('-f','--flavor',type=str,help='flavor (type of instance) of worker needed',default=None)
    recruiter_modify_parser.add_argument('-r','--region',type=str,help='worker region of provenance',default=None)
    recruiter_modify_parser.add_argument('-P','--provider',type=str,help='worker provider',default=None)
    recruiter_modify_parser.add_argument('-C','--concurrency',type=int,help='what should be the concurrency setting of recruited workers',default=None)
    recruiter_modify_parser.add_argument('-p','--prefetch',type=int,help='what should be the prefetch setting of recruited workers (default to 0)',default=None)
    recruiter_modify_parser.add_argument('-T','--tasks-per-worker',type=int,help='how many workers should be recruited (default to concurrency, but if you want each worker to work two rounds, set it to twice the concurrency)',default=None)
    recruiter_modify_parser.add_argument('-m','--minimum-tasks',type=int,help='prevent the recruiter from triggering before this minimal number of tasks is reached',default=None)
    recruiter_modify_parser.add_argument('-W','--maximum-workers',type=int,help='prevent the recruiter from recruiting more than this number of worker',default=None)

    recruiter_delete_parser = subsubparser.add_parser('delete', help='Delete a recruiter')
    recruiter_delete_parser.add_argument('-b','--batch',type=str,required=True,help='batch in which workers are deployed')
    recruiter_delete_parser.add_argument('-n','--rank',type=int,help='rank in which recruiter is tried (unique per batch), default to 1',default=1)
    

    db_parser = subparser.add_parser('db', help='The following options are to work with scitq database')
    db_parser.add_argument('-c','--conf', help=f'Use this environment file to set environment (default to {DEFAULT_SERVER_CONF})', type=str, default=DEFAULT_SERVER_CONF)
    subsubparser=db_parser.add_subparsers(dest='action')
    db_upgrade_parser=subsubparser.add_parser('upgrade',help='Migrate the database to the current version of scitq')
    db_init_parser=subsubparser.add_parser('init',help='Initialize a new database with current version of scitq')
    db_upgrade_parser=subsubparser.add_parser('upgrade-or-init',help='Migrate the database to the current version of scitq if it exists, initialize it otherwise')

    args=parser.parse_args()

    if args.version:
        print(f"Version: {package_version()}")
        return None

    s = Server(args.server, get_timeout=args.timeout)
    if args.object=='worker':
        if args.action =='list':
            info_worker=['worker_id','name','status','concurrency','creation_date','last_contact_date','batch']
            if args.long:
                info_worker+=['provider','region','flavor','prefetch','assigned','accepted','running','failed','succeeded']
            if not args.no_header:
                headers = info_worker
            else:
                headers = []
            filters={}
            if args.batch:
                filters['batch']=args.batch
            if args.status:
                filters['status']=args.status
            worker_list=s.workers(**filters) 
            if args.long:
                worker_dict=dict([(w['worker_id'],w) for w in worker_list])
                worker_tasks=s.workers_tasks()
                for w in worker_tasks:
                    worker_dict[w['worker_id']][w['status']]=w['count']
            
            __list_print(worker_list, info_worker, headers)

        elif args.action =='deploy' :
            s.worker_deploy(number=args.number,batch=args.batch,region=args.region,
                flavor=args.flavor,concurrency=args.concurrency, prefetch=args.prefetch,
                provider=args.provider)

        elif args.action =='delete' :
            if args.id is not None:
                id=args.id
            elif args.name is not None:
                for worker in s.workers():
                    if worker['name']==args.name:
                        id=worker['worker_id']
                        break
                else:
                    raise RuntimeError(f'No such worker {args.name}...')
            else:
                raise RuntimeError('You must specify either name (-n) or id (-i)')
            s.worker_delete(id)

        elif args.action =='update' :
            if args.id is not None:
                id=args.id
            elif args.name is not None:
                for worker in s.workers():
                    if worker['name']==args.name:
                        id=worker['worker_id']
                        break
                else:
                    raise RuntimeError(f'No such worker {args.name}...')
            else:
                raise RuntimeError('You must specify either name (-n) or id (-i)')
            s.worker_update(id, batch=args.batch, status=args.status,
                concurrency=args.concurrency, prefetch=args.prefetch, flavor=args.flavor)
        
    elif args.object == 'batch':
        if args.action =='list':
            info_batch=['batch','pending','accepted','running','failed','succeeded','workers']
            batch_list=s.batches() 
            __list_print(batch_list, info_batch, info_batch)

        if args.action == 'stop':
            signal=0
            if args.number:
                signal = args.number
            elif args.term:
                signal = SIGQUIT
            elif args.kill:
                signal = SIGKILL
            elif args.pause:
                signal = SIGTSTP
            for batch in args.name :
                s.batch_stop(batch,signal)
        
        elif args.action == 'go':
            signal=0
            if args.number:
                signal = args.number
            elif args.cont:
                signal = SIGCONT
            for batch in args.name :
                s.batch_go(batch, signal)

        elif args.action == 'delete':
            for batch in args.name :
                s.batch_delete(batch)
        
        
    elif args.object == 'task':  
        if args.action == 'list':
            info_task=['task_id','name','status','command','creation_date','modification_date','status_date','batch']
            if args.long:
                info_task+=['container','container_options','input','output','resource','required_task_ids','retry','run_timeout','download_timeout']
            if not args.no_header:
                headers = info_task
            else:
                headers = []
            filters={}
            if args.batch:
                filters['batch']=args.batch
            if args.status:
                filters['status']=args.status
            task_list=s.tasks(**filters)
            __list_print(task_list, info_task, headers, long=args.long)

        elif args.action=='relaunch':
            if args.id is not None:
                id=args.id
            elif args.name is not None:
                for task in s.tasks(name=args.name):
                    id=task['task_id']
                    break
                else:
                    raise RuntimeError(f'No such task {args.name}...')       
            if s.task_get(id)['status']=='pending':
                print('This task is already in queue')
            else:
                s.task_update(id=id,status='pending')
        
        elif args.action == 'output':
            if args.id is not None:
                id=args.id
            elif args.name is not None:
                for task in s.tasks(name=args.name):
                    id=task['task_id']
                    break
                else:
                    raise RuntimeError(f'No such task {args.name}...')   
            executions = s.executions(task_id=id, latest=True)
            try:
                execution = next(iter(executions))
            except StopIteration:
                raise RuntimeError(f'No execution for this task {id}')
            if args.output:
                print(execution['output'])
            elif args.error:
                print(execution['error'])
            else:
                print(tabulate([[execution['output'],execution['error']]],headers=["output",],tablefmt ="plain"))
        
        elif args.action == 'update':
            if args.id is not None:
                id=args.id
            elif args.name is not None:
                for task in s.tasks(name=args.name):
                    id=task['task_id']
                    break
                else:
                    raise RuntimeError(f'No such task {args.name}...')  
            if args.requirements is not None:
                try:
                    args.requirements = [int(r) for r in args.requirements.split(' ')]
                except: 
                    try:
                        args.requirements = [int(r) for r in args.requirements.split(',')]
                    except:
                        raise RuntimeError(f'requirements should be a space or comma separated list of integer not {args.requirements}') 
            s.task_update(id, name=args.new_name, status=args.status, batch=args.batch,
                command=args.command, container=args.docker, container_options=args.option,
                input=args.input, output=args.output, required_task_ids=args.requirements, 
                run_timeout=args.run_timeout, download_timeout=args.download_timeout)
        elif args.action == 'delete':
            if args.id is not None:
                id=args.id
            elif args.name is not None:
                for task in s.tasks(name=args.name):
                    id=task['task_id']
                    break
                else:
                    raise RuntimeError(f'No such task {args.name}...')   
            else:
                raise RuntimeError('You must specify either name (-n) or id (-i)')
            s.task_delete(id)
    

    elif args.object=='ansible':

        if args.action=='install':
            if not os.path.exists(args.path):
                print('Creating directory', args.path)
                os.makedirs(args.path)
            print('Installing files')
            shutil.copy(package_path('ansible','scitq','sqlite_inventory.py'), 
                os.path.join(args.path,'sqlite_inventory.py') )
            os.chmod(os.path.join(args.path,'sqlite_inventory.py'), 0o770)
            shutil.copy(package_path('ansible','scitq','01-scitq-default'), 
                os.path.join(args.path,'01-scitq-default') )
        elif args.action=='path':
            print(package_path('ansible','playbooks'))

        #sql_inventory = package_path('ansible','scitq','sqlite_inventory.py')
        elif args.action=='inventory':
            result=inventory(args)
            if result:
                print(result)
    
    elif args.object=='debug':

        if args.action=='run':
            if args.id is not None:
                task = s.task_get(args.id)
            elif args.name is not None:
                for task in s.tasks():
                    if task['name']==args.name:
                        break
                else:
                    raise RuntimeError(f'No such task {args.name}...')       
            elif args.batch is not None:
                try:
                    task = random.choice([task for task in s.tasks() if task['batch']==args.batch and task['status']=='pending'])
                except IndexError:
                    raise RuntimeError(f'No pending task in this batch {args.batch}...')
            else:
                try:
                    task = random.choice([task for task in s.tasks() if task['status']=='pending'])
                except IndexError:
                    raise RuntimeError(f'No pending task...')
            get_input = get_resource = True
            if args.retry:
                get_input = get_resource = False
            if args.no_resource:
                get_resource = False
            Debugger(task, get_input=get_input, get_resource=get_resource, 
                     configuration=args.conf, extra_configuration=args.worker_conf).run()
    

    elif args.object=='recruiter':

        if args.action =='list':
            info_recruiter=['batch','rank','flavor','region','provider','concurrency']
            if args.long:
                info_recruiter+=['prefetch','tasks_per_worker','minimum_tasks','maximum_worker']
            if not args.no_header:
                headers = info_recruiter
            else:
                headers = []
            filters={}
            if args.batch:
                filters['batch']=args.batch
            __list_print(s.recruiters(**filters), info_recruiter, headers)

        elif args.action =='create' :
            if args.tasks_per_worker is None:
                args.tasks_per_worker=args.concurrency
            s.recruiter_create(batch=args.batch,rank=args.rank,region=args.region,
                flavor=args.flavor,concurrency=args.concurrency, prefetch=args.prefetch,
                provider=args.provider, tasks_per_worker=args.tasks_per_worker,
                minimum_tasks=args.minimum_tasks, maximum_workers=args.maximum_workers)
        
        elif args.action == 'update':
            s.recruiter_update(batch=args.batch,rank=args.rank,region=args.region,
                flavor=args.flavor,concurrency=args.concurrency, prefetch=args.prefetch,
                provider=args.provider, tasks_per_worker=args.tasks_per_worker,
                minimum_tasks=args.minimum_tasks, maximum_workers=args.maximum_workers)

        elif args.action =='delete' :
            s.recruiter_delete(batch=args.batch, rank=args.rank)

    elif args.object=='db':

        if args.action=='upgrade-or-init':
            dotenv.load_dotenv(args.conf)
            from .default_settings import SQLALCHEMY_DATABASE_URI
            from sqlalchemy import create_engine
            from sqlalchemy.exc import OperationalError
            engine = create_engine(SQLALCHEMY_DATABASE_URI)
            try:
                engine.connect()
                engine.execute('SELECT * FROM task LIMIT 1')
                args.action='upgrade'
            except OperationalError:
                args.action='init'

        if args.action=='init':
            dotenv.load_dotenv(args.conf)
            # return code of flask db init seems to be random, outputing to 1 with no reason or with a good reason...
            run('SCITQ_PRODUCTION=1 FLASK_APP=server flask db init', shell=True, 
                cwd=package_path(), check=False)
            run('SCITQ_PRODUCTION=1 FLASK_APP=server flask db stamp head', shell=True, 
                cwd=package_path(), check=True)
            print('DB intialized')

        if args.action=='upgrade':
            dotenv.load_dotenv(args.conf)
            run('SCITQ_PRODUCTION=1 FLASK_APP=server flask db upgrade', shell=True, 
                cwd=package_path(), check=True)
            print('DB migrated')


if __name__=="__main__":
    main()