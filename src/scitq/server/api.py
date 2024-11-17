from flask_restx import Api, Resource, fields
from flask import jsonify
from datetime import datetime
from sqlalchemy import and_, delete, select, func, update
from sqlalchemy.sql.expression import label
import logging as log
import json as json_module

from .model import Task, Execution, Signal, Requirement, Worker,\
    create_worker_destroy_job, Job, Recruiter, delete_batch, \
    find_flavor, execution_update_status, worker_delete, \
    ModelException, create_worker_create_job, worker_handle_eviction
from .db import db
from .config import IS_SQLITE
from ..constants import TASK_STATUS, EXECUTION_STATUS, FLAVOR_DEFAULT_LIMIT, FLAVOR_DEFAULT_EVICTION, WORKER_STATUS, TASK_STATUS_ID, DEFAULT_RCLONE_CONF


api = Api(version='1.2', title='TaskMVC API',
    description='A simple TaskMVC API'
)



def process_filtering_args(ObjectType, args):
    """In list functions it seems natural to filter the results with some attributes
    conditions (such as 'batch="foo"' or 'status="succeeded"') and it makes more 
    efficient queries than listing the lot and filtering the results out or sending
    several individual queries (one per item id).
    However sqlalchemy filtering syntax is not friendly when using typical python
    optional args dictionary, this function does this transformation:
    
    When args maybe something as 'batch="foo"' or 'batch=["foo","bar"]'
    - the function will return 'ObjectType.batch=="foo"'
    - or 'ObjectType.batch.in_(["foo","bar"])' if value is a list

    which can then be passed to sqlalchemy .filter() function
    """
    # 
    # filter expects something as 'ObjectType.batch=="foo"'
    # or 'ObjectType.batch.in_(["foo","bar"])' if value is a list
    new_args = [ getattr(ObjectType,attribute).in_(value) if type(value)==list else \
                 getattr(ObjectType,attribute)==value 
                    for attribute,value in args.items() ]
    return and_(*new_args) if len(new_args)>1 else new_args[0]



class BaseDAO(object):
    ObjectType = None
    authorized_status = []

    def get(self, id):
        object = self.ObjectType.query.get(id)
        if object is None:
            api.abort(404, "{} {} doesn't exist".format(
                    self.ObjectType.__name__,id))
        return object
        
    def create(self, data):
        object = self.ObjectType(**data)
        if 'status' in data and data['status'] not in self.authorized_status:
            api.abort(500,
                f"Status {data['status']} is not possible (only {' '.join(self.authorized_status)})")
        db.session.add(object)
        db.session.commit()
        return object

    def update(self, id, data):
        object = self.get(id)
        modified = False
        for attr, value in data.items():
            if hasattr(object,attr): 
                if getattr(object,attr)!=value:
                    if attr=='status' and value not in self.authorized_status:
                        api.abort(500,
                           f"Status {value} is not possible (only {' '.join(self.authorized_status)})")
                    setattr(object, attr, value)
                    modified = True
            else:
                api.abort(500,f'Error: {object.__name__} has no attribute {attr}')
        if modified:
            if hasattr(object,'modification_date'):
                object.modification_date = datetime.utcnow()
            db.session.commit()
        return object

    def delete(self, id):
        object = self.get(id)
        db.session.delete(object)
        db.session.commit()
        return object
    
    def list(self, sorting_column=None, **args):
        if args:
            final_filter = process_filtering_args(self.ObjectType, args)
            return list(self.ObjectType.query.filter(final_filter).order_by(sorting_column))
        else:
            return list(self.ObjectType.query.order_by(sorting_column).all())
        
        



ns = api.namespace('tasks', description='TASK operations')

class TaskDAO(BaseDAO):
    ObjectType = Task
    authorized_status = TASK_STATUS

    def list(self, **args):
        task_list = []
        for task in super().list(sorting_column='task_id',**args):
            task.required_task_ids = list([r.other_task_id for r in task.requirements])
            task_list.append(task)
        return task_list

    def update(self, id, data):
        task = self.get(id)
        modified = False
        status_changed = False
        for attr, value in data.items():
            if hasattr(task,attr): 
                if getattr(task,attr)!=value:
                    if attr=='status':
                        if value not in self.authorized_status:
                            api.abort(500,
                                f"Status {value} is not possible (only {' '.join(self.authorized_status)})")
                        if task.status=='running':
                            for execution in db.session.query(Execution).filter(
                                    Execution.task_id==id, Execution.status=='running'):
                                db.session.add(Signal(execution.execution_id, execution.worker_id, 9))
                                execution.status='failed'
                                execution.modification_date = datetime.utcnow()
                        if value=='failed':
                            if 'retry' in data:
                                if data['retry']>0:
                                    value='pending'
                                    data['retry'] -= 1
                            elif task.retry>0:
                                value='pending'
                                task.retry -= 1
                        status_changed = True
                        
                    setattr(task, attr, value)
                    modified = True
            else:
                raise Exception('Error: {} has no attribute {}'.format(
                    task.__name__, attr))
        if modified:
            task.modification_date = datetime.utcnow()
            if status_changed:
                task.status_date = datetime.utcnow()
            db.session.commit()
        return task



task_dao = TaskDAO()

class RequirementDAO(BaseDAO):
    ObjectType = Requirement

    def list(self, **args):
        super().list(sorting_column='requirement_id', **args)

requirement_dao = RequirementDAO()


task = api.model('Task', {
    'task_id': fields.Integer(readonly=True, description='The task unique identifier'),
    'name': fields.String(required=False, description='The task (optional) name'),
    'status': fields.String(required=False, 
        description=f'The task status: {", ".join(TaskDAO.authorized_status)}'), 
    'command': fields.String(required=True, description='The task command'), 
    'creation_date': fields.DateTime(readonly=True, 
        description='timestamp of task creation in server'),
    'modification_date': fields.DateTime(readonly=True,
        description='timestamp of task last modification'),
    'status_date': fields.DateTime(readonly=True,
        description='timestamp of task last change of status'),
    'batch': fields.String(required=False, 
        description="only workers with the same batch (null or not) will accept the task."),
    'input': fields.String(required=False,
        description="Input data required for task (space separated files URL in s3://...)"),
    'output': fields.String(required=False,
        description="Output data basepath where /output content will be copied (if null, the result transmission is up to the command)"),
    'container': fields.String(required=False,
        description="Container (as for now this is a docker) in which task is launched"),
    'container_options': fields.String(required=False,
        description="Container (extra) option if needed"),
    'resource': fields.String(required=False,
        description="Resource data required for task (much like input except it is shared between tasks) (space separated files URL in s3://...)"),
    'required_task_ids': fields.List(fields.Integer,required=False,
        description="List of task ids required to do this task"),
    'retry': fields.Integer(required=False,
        description="If set, retry the task this number of time if it fails until it succeeds"),
    'download_timeout': fields.Integer(required=False,
        description="If set, the task will timeout and fail if the download time exceeds this number in seconds"),
    'run_timeout': fields.Integer(required=False,
        description="If set, the task will timeout and fail if the run time exceeds this number in seconds"),
    'use_cache': fields.Boolean(required=False,
        description="If set, scitq will try to find an identical task already done and reuse the output if possible"),
})

task_filter = api.model('TaskFilter', {
    'task_id': fields.List(fields.Integer(),required=False,description='A list of ids to restrict listing'),
    'batch': fields.String(required=False, description="Filter with this batch"),
    'status': fields.String(required=False, description="Filter with this status"),
    'name': fields.String(required=False, description="Filter with this name"),
})


@ns.route('/')
class TaskList(Resource):
    '''Shows a list of all tasks, and lets you POST to add new tasks'''
    @ns.doc('list_tasks')
    @ns.expect(task_filter)
    @ns.marshal_list_with(task)
    def get(self):
        '''List all tasks'''
        return task_dao.list(**api.payload) if api.payload else task_dao.list()

    @ns.doc('create_task')
    @ns.expect(task)
    @ns.marshal_with(task, code=201)
    def post(self):
        '''Create a new task'''
        if 'required_task_ids' in api.payload:
            requirements = api.payload['required_task_ids']
            del(api.payload['required_task_ids'])
        else:
            requirements = []
        task = task_dao.create(api.payload)
        for r in requirements:
            requirement_dao.create({'task_id':task.task_id, 'other_task_id':r})
        return task, 201


task_status_filter = api.model('TaskStatusFilter', {
    'task_id': fields.List(fields.Integer(),required=True,description='A list of ids to restrict listing'),
})

@ns.route('/status')
class TaskStatusList(Resource):
    '''Shows a list of all tasks, and lets you POST to add new tasks'''
    @ns.doc('list_task_statuses')
    @ns.expect(task_status_filter)
    def get(self):
        '''List all task status'''
        task_id_list = api.payload['task_id']
        task_status = db.session.query(Task.task_id,Task.status).filter(Task.task_id.in_(task_id_list)).all()
        task_to_status = { task_id:TASK_STATUS_ID[status] for task_id,status in task_status }
        return jsonify([task_to_status[id] for id in task_id_list])



@ns.route("/<id>")
@ns.param("id", "The task identifier")
@ns.response(404, "Task not found")
class WorkerObject(Resource):
    @ns.doc("get_task")
    @ns.marshal_with(task)
    def get(self, id):
        """Fetch a task given its identifier"""
        return task_dao.get(id)

    @ns.doc("update_task")
    @ns.expect(task)
    @ns.marshal_with(task, code=201)
    def put(self, id):
        """Update a task"""
        if 'required_task_ids' in api.payload:
            requirements = api.payload['required_task_ids']
            del(api.payload['required_task_ids'])
            db.session.execute(delete(Requirement).where(Requirement.task_id==id))
            for r in requirements:
                requirement_dao.create({'task_id':id, 'other_task_id':r})
        return task_dao.update(id, api.payload)

    @ns.doc("delete_task")
    @ns.marshal_with(task)
    def delete(self, id):
        """Delete a task"""
        return task_dao.delete(id)

@ns.route("/<id>/freeze/<execution_id>")
@ns.param("id", "The task identifier")
@ns.param("execution_id", "The execution identifier")
@ns.response(404, "Task not found")
class WorkerObjectFreeze(WorkerObject):
    @ns.doc("get_task_and_freeze_execution")
    @ns.marshal_with(task)
    def get(self, id, execution_id):
        """Fetch a task given its identifier"""
        task = db.session.query(Task).get(id)
        execution = db.session.query(Execution).get(execution_id)

        if execution.task_id!=task.task_id:
            api.abort(404, f"Execution {execution_id} is not linked to Task {id}")

        for obj,obj_id in [(task,id), (execution,execution_id)]:
            if obj is None:
                api.abort(404, "{} {} doesn't exist".format(
                        self.obj.__class__.__name__,obj_id))
        
        for attr in ['command','container','container_options','output','input','resource']:
            setattr(execution, 'output_folder' if attr=='output' else attr, 
                    getattr(task, attr))

        execution.input_hash = execution.get_input_hash()

        db.session.commit()
        return task




ns = api.namespace('workers', description='WORKER operations')



class WorkerDAO(BaseDAO):
    ObjectType = Worker
    authorized_status = WORKER_STATUS

    def update_contact(self, id, load,memory,stats):
        db.engine.execute(
            db.update(Worker
                    ).values({'last_contact_date':datetime.utcnow(),
                        'load':load,'memory':memory,'stats':stats}
                    ).where(Worker.worker_id==id)
        )
        db.session.commit()

    def update(self, id, data):
        object = self.get(id)
        modified = False
        for attr, value in data.items():
            if hasattr(object,attr): 
                if getattr(object,attr)!=value:
                    if attr=='status':
                        if value not in self.authorized_status:
                            api.abort(500,
                                f"Status {value} is not possible (only {' '.join(self.authorized_status)})")
                        if object.status=='evicted' and value not in ['running']:
                            log.warning(f'Evicted worker {object.worker_id} can only return to running')
                            continue
                    setattr(object, attr, value)
                    if attr=='status' and value=='evicted':
                        worker_handle_eviction(worker=object,session=db.session, commit=False)
                    modified = True
            else:
                api.abort(500,f'Error: {object.__name__} has no attribute {attr}')
        if modified:
            if hasattr(object,'modification_date'):
                object.modification_date = datetime.utcnow()
            db.session.commit()
        return object

    def delete(self,id,is_destroyed=False, session=db.session):
        """Delete a worker
        """
        worker=self.get(id)
        log.warning(f'Deleting worker {id} ({worker.permanent})')
        return worker_delete(worker, session, is_destroyed=is_destroyed)

    def list(self, **args):
        return super().list(sorting_column='worker_id', **args)

worker_dao = WorkerDAO()

worker = api.model('Worker', {
    'worker_id': fields.Integer(readonly=True, description='The worker unique identifier'),
    'name': fields.String(required=True, description='The worker name'),
    'concurrency': fields.Integer(required=True, 
        description='The worker concurrency (nb of parallel processes)'), 
    'prefetch': fields.Integer(required=False, 
        description='How many jobs should be prefetch so that they can be launched as soon as possible'),     
    'hostname': fields.String(required=False, description='The worker hostname'),
    'status': fields.String(required=False,
         description=f'The worker status: {", ".join(WorkerDAO.authorized_status)}'), 
    'load': fields.String(readonly=True, description='The worker load (in %)'),
    'memory':fields.Float(readonly=True, description='Memory used (in %)'),
    'stats':fields.String(readonly=True,description='Other worker stats'),
    'task_properties':fields.String(required=False,description='Some task properties for batch transitions'),
    'creation_date': fields.DateTime(readonly=True, 
        description='timestamp of worker creation'),
    'modification_date': fields.DateTime(readonly=True, 
        description='timestamp of last worker modification'),
    'last_contact_date': fields.DateTime(readonly=True, 
        description='timestamp of last worker ping (automatically sent by worker'),
    'batch': fields.String(required=False, 
        description="worker accept only tasks with same batch (null or not)."),
    'permanent': fields.Boolean(readonly=False, required=False,
        description="Set to True to create a permanent worker"),
    'flavor': fields.String(required=False, 
        description="flavor (cloud type of instance) of the worker."),
    'region': fields.String(readonly=True, 
        description="region (cloud regional entity of the instance) of the worker."),
    'provider': fields.String(readonly=True, 
        description="provider (cloud provider of the instance) of the worker."),
})

@ns.route('/')
class WorkerList(Resource):
    '''Shows a list of all workers, and lets you POST to add new workers'''
    @ns.doc('list_workers')
    @ns.marshal_list_with(worker)
    def get(self):
        '''List all workers'''
        return worker_dao.list(**api.payload)

    @ns.doc('create_worker')
    @ns.expect(worker)
    @ns.marshal_with(worker, code=201)
    def post(self):
        '''Create a new worker'''
        return worker_dao.create(api.payload), 201


worker_tasks = api.model('WorkerTasks', {
    'worker_id': fields.Integer(readonly=True, description='A worker unique identifier'),
    'status': fields.String(readonly=True, description='The different status of tasks'), 
    'count': fields.Integer(readonly=True, description='How many tasks of this type'),
})

@ns.route("/tasks")
class WorkerTaskList(Resource):
    '''Shows a list of all tasks in all workers, and lets you POST to add new workers'''
    @ns.doc('list_worker_tasks')
    @ns.marshal_list_with(worker_tasks)
    def get(self):
        '''List all workers'''
        return list(db.session.execute("""SELECT w.worker_id, e.status, count(e.task_id) as count 
            FROM worker w
            JOIN execution e ON (e.worker_id=w.worker_id)
            JOIN task t ON (e.task_id=t.task_id 
                AND e.latest)
            GROUP BY w.worker_id,e.status"""))
    

@ns.route("/<id>")
@ns.param("id", "The worker identifier")
@ns.response(404, "Worker not found")
class WorkerObject(Resource):
    @ns.doc("get_worker")
    @ns.marshal_with(worker)
    def get(self, id):
        """Fetch a worker given its identifier"""
        return worker_dao.get(id)

    @ns.doc("update_worker")
    @ns.expect(worker)
    @ns.marshal_with(worker, code=201)
    def put(self, id):
        """Update a worker"""
        #worker_dao.update_contact(id)
        if 'batch' in api.payload and api.payload['batch']=='':
            api.payload['batch']==None
        return worker_dao.update(id, api.payload)

    @ns.doc("delete_worker")
    @ns.marshal_with(worker)
    def delete(self, id):
        """Delete a worker"""
        return worker_dao.delete(id)

ping_parser = api.parser()
ping_parser.add_argument('load', type=str, help='Worker load', location='json')
ping_parser.add_argument('memory', type=float, help='Worker memory', location='json')
ping_parser.add_argument('stats', type=str, help='Worker other stats', location='json')

@ns.route("/<id>/ping")
@ns.param("id", "The worker identifier")
@ns.response(404, "Worker not found")
class WorkerPing(Resource):
    @ns.doc("update_worker_contact")
    @ns.expect(ping_parser)
    @ns.marshal_with(worker)
    def put(self, id):
        """Update a worker last contact"""
        args = ping_parser.parse_args()
        worker_dao.update_contact(id, args.get('load',''),args.get('memory',''),args.get('stats',''))
        return worker_dao.get(id)

callback_parser = api.parser()
callback_parser.add_argument('message', type=str, help='Callback message sent (idle)', location='json')

@ns.route("/<id>/callback")
@ns.param("id", "The worker identifier")
@ns.response(404, "Worker not found")
class WorkerCallback(Resource):
    @ns.doc("update_worker_contact")
    @ns.expect(callback_parser)
    def put(self, id):
        """Update a worker last contact"""
        message = callback_parser.parse_args().get('message','')
        worker = worker_dao.get(id)
        if message == 'idle': 
            if not worker.permanent:
                if db.session.query(Execution).filter(Execution.status.in_(['running','pending','accepted']),
                        Execution.worker_id==worker.worker_id).count()>0:
                    log.warning(f'Worker {worker.name} called idle callback but some tasks are still running or about to run, refusing...')
                    return {'result':'still have running tasks'}
                if db.session.query(Task).filter(and_(Task.status.in_(['pending']),
                                        Task.batch==worker.batch)).count()>0:
                    log.warning(f'Worker {worker.name} called idle but some tasks are still due...')
                    return {'result':'still some work to do, lazy one!'}
                log.warning(f'Worker {worker.name} ({worker.worker_id}) called idle callback, launching destruction')
                #worker.destroy()
                create_worker_destroy_job(worker, db.session, commit=False)
                #db.session.delete(worker)
            else:
                worker.task_properties = json_module.dumps({})
            db.session.commit()
            return {'result':'ok'}
        else:
            log.warning(f'Worker {worker.name} called idle callback but has no idle command')
            return {'result':'nothing to do'}

deploy_parser = api.parser()
deploy_parser.add_argument('number', type=int, help='How many workers should be deployed', location='json')
deploy_parser.add_argument('region', type=str, help='Which provider region for worker', location='json')
deploy_parser.add_argument('provider', type=str, help='Specify the worker provider', location='json')
deploy_parser.add_argument('flavor', type=str, help='Which provider flavor/model for worker', location='json')
deploy_parser.add_argument('batch', type=str, help='Batch name (that must be shared by tasks) for worker', location='json')
deploy_parser.add_argument('concurrency', type=int, help='How many tasks should be run in parallel', location='json')
deploy_parser.add_argument('prefetch', type=int, help='How many extra tasks should be prefetched', location='json')

@ns.route("/deploy")
class WorkerDeploy(Resource):
    @ns.doc("deploy_worker_vm_and_process")
    @ns.expect(deploy_parser)
    def put(self):
        """Create and deploy one or several workers"""
        deploy_args = deploy_parser.parse_args()
        create_worker_create_job(session=db.session, **deploy_args)
        #for _ in range(deploy_args['number']):
#
        #    db.session.add(
        #        Job(target='', 
        #            action='worker_create', 
        #            args={
        #                'concurrency': deploy_args['concurrency'], 
        #                'prefetch':deploy_args['prefetch'],
        #                'flavor':deploy_args['flavor'],
        #                'region':deploy_args['region'],
        #                'provider':deploy_args['provider'],
        #                'batch':deploy_args['batch']
        #            }
        #        )
        #    )
        #db.session.commit()


        return {'result':'ok'}

class ExecutionDAO(BaseDAO):
    ObjectType = Execution
    authorized_status = EXECUTION_STATUS

    def create(self, data):
        task = task_dao.get(data['task_id'])
        if task.status not in ['pending','paused']:
            api.abort(500, f"A new execution for task {task.task_id} is not possible")
        if 'status' in data:
            if data['status']=='running':
                task.status = 'running'
            elif data['status'] in ['pending','paused']:
                task.status = 'assigned'
            else:
                api.abort(500, f"A new execution cannot be created with a status {data['status']}")
        else:
            task.status='assigned'
        return super().create(data)

    def update(self, id, data):
        execution = self.get(id)
        modified = False
        freeze=False
        for attr, value in data.items():
            if attr=='freeze':
                if value:
                    freeze=True
            elif hasattr(execution,attr): 
                if getattr(execution,attr)!=value:
                    if attr=='status':
                        try:
                            execution_update_status(execution, db.session, value, commit=False)
                            modified = True
                        except ModelException as model_exception:
                            api.abort(500, model_exception.message)
                    else:
                        setattr(execution, attr, value)
                        modified = True
            else:
                raise Exception('Error: {} has no attribute {}'.format(
                    execution.__class__.__name__, attr))
        if freeze and execution.status=='succeeded':
            execution.output_hash = execution.get_output_hash()
            modified=True
        if modified:
            execution.modification_date = datetime.utcnow()
            db.session.commit()
        return execution

    def list(self,no_output=False,limit=None,reverse=False,trunc=None,**args):
        sorting_column=Execution.execution_id
        if reverse:
            sorting_column=sorting_column.desc()
        q=Execution.query
        if args:
            task_args = {}
            if 'task_name' in args:
                task_args['name']=args['task_name']
                del(args['task_name'])
            if 'batch' in args:
                task_args['batch']=args['batch']
                del(args['batch'])
            filter = None
            if args:
                filter=process_filtering_args(Execution, args)
            if task_args:
                q = q.join(Task, Task.task_id==Execution.task_id)
                if filter:
                    filter = and_(filter, process_filtering_args(Task, task_args))
                else:
                    filter = process_filtering_args(Task, task_args)
            q=q.filter(filter)
        if no_output:
            q=q.with_entities(Execution.execution_id,
                              Execution.worker_id,
                              Execution.command, 
                              Execution.status,
                              Execution.task_id,
                              Execution.creation_date,
                              Execution.modification_date,
                              Execution.pid,
                              Execution.output_files,
                              Execution.latest)
        elif trunc:
            if IS_SQLITE:
                trunc_output = func.substr(Execution.output, -trunc, trunc).label('output')
                trunc_error = func.substr(Execution.error, -trunc, trunc).label('error')
            else:
                trunc_output = func.right(Execution.output, trunc).label('output')
                trunc_error = func.right(Execution.error, trunc).label('error')
            q=q.with_entities(Execution.execution_id,
                              Execution.worker_id,
                              Execution.command, 
                              Execution.status,
                              Execution.task_id,
                              Execution.creation_date,
                              Execution.modification_date,
                              Execution.pid,
                              Execution.output_files,
                              Execution.latest,
                              trunc_output,
                              trunc_error)
        q = q.order_by(sorting_column)
        if limit:
            q=q.limit(limit)

        return list(q.all())
 
execution_dao = ExecutionDAO()

execution = api.model('Execution', {
    'execution_id': fields.Integer(readonly=True, description='The execution unique identifier'), 
    'worker_id': fields.Integer(required=True, description='A worker unique identifier'),
    'task_id': fields.Integer(required=True, description='A task unique identifier'),
    'status': fields.String(readonly=True,
        description=f'The execution status: {", ".join(ExecutionDAO.authorized_status)}'), 
    'return_code': fields.Integer(required=False, description='The return code of the execution (when finished)'),
    'pid': fields.String(required=False, description='The process id (pid) of the execution'),
    'creation_date': fields.DateTime(readonly=True,
        description="timestamp of execution creation (on worker)"),
    'modification_date': fields.DateTime(readonly=True,
        description="timestamp of execution last modification"),
    'output': fields.String(readonly=False, required=False, description='The standard output of the execution'),
    'error': fields.String(readonly=False, required=False, description='The standard error of the execution (if any)'),
    'output_files': fields.String(readonly=True, description='A list of output files transmitted (if any)'),
    'command': fields.String(required=False, description='The command that was really launched for this execution (it case Task.execution is modified)'),
    'freeze': fields.Boolean(required=False, description='Freeze execution to compute output hash'),
    'latest': fields.Boolean(readonly=True, description='Latest or current execution for the related task')
})

execution_plus_batch = api.model('ExecutionPlusBatch', {
    'execution_id': fields.Integer(readonly=True, description='The execution unique identifier'), 
    'command': fields.String(required=False, description='The command that was really launched for this execution (it case Task.execution is modified)'),
    'status': fields.String(readonly=True,
        description=f'The execution status: {", ".join(ExecutionDAO.authorized_status)}'), 
    'task_id': fields.Integer(required=True, description='A task unique identifier'),
    'creation_date': fields.DateTime(readonly=True,
        description="timestamp of execution creation (on worker)"),
    'modification_date': fields.DateTime(readonly=True,
        description="timestamp of execution last modification"),
    'pid': fields.String(required=False, description='The process id (pid) of the execution'),
    'output_files': fields.String(readonly=True, description='A list of output files transmitted (if any)'),
    'latest': fields.Boolean(readonly=True, description='Latest or current execution for the related task'),
    'batch': fields.String(readonly=True, description='The batch of the underlying task'),
    'taskstatus': fields.String(readonly=True, description='The status of the underlying task')
})


@ns.route("/<id>/executions")
@ns.param("id", "The worker identifier")
@ns.response(404, "Worker not found")
class WorkerExecutionObject(Resource):
    @ns.doc("get_worker_executions")
    @ns.marshal_list_with(execution_plus_batch)
    def get(self, id):
        """Fetch a worker executions given the worker identifier"""
        #worker_dao.update_contact(id)
        worker_executions = db.session.query(Execution.execution_id,
                              Execution.command, 
                              Execution.status,
                              Execution.task_id,
                              Execution.creation_date,
                              Execution.modification_date,
                              Execution.pid,
                              Execution.output_files,
                              Execution.latest,
                              Task.batch,
                              label('taskstatus',Task.status)).\
                        join(Execution.task).\
                        filter(and_(Execution.worker_id==id,
                                    Execution.status.not_in(['failed','succeeded','pending'])))
        return list(worker_executions)


@ns.route("/<id>/executions/<status>")
@ns.param("id", "The worker identifier")
@ns.param("status", "Filter only executions with this status")
@ns.response(404, "Worker not found")
class WorkerExecutionFilterObject(Resource):
    @ns.doc("get_worker_executions")
    @ns.marshal_list_with(execution_plus_batch)
    def get(self, id, status):
        """Fetch a worker executions given the worker identifier and the executions status"""
        #worker_dao.update_contact(id)
        #return execution_dao.list(worker_id=id, status=status)
        worker_executions = db.session.query(Execution.execution_id,
                              Execution.command, 
                              Execution.status,
                              Execution.task_id,
                              Execution.creation_date,
                              Execution.modification_date,
                              Execution.pid,
                              Execution.output_files,
                              Execution.latest,
                              Task.batch,
                              label('taskstatus',Task.status)).\
                        join(Execution.task).\
                        filter(and_(Execution.worker_id==id,
                                    Execution.status==status))
        return list(worker_executions)

signal = api.model('Signal', {
    'execution_id': fields.Integer(readonly=True, description='The execution unique identifier'), 
    'worker_id': fields.Integer(readonly=True, description='A worker unique identifier'),
    'signal': fields.Integer(readonly=True, description='The signal to send to the execution (UNIX signal)'),
})

signal_parser = api.parser()
signal_parser.add_argument('execution_id', type=int, help='Execution identifier', location='json')
signal_parser.add_argument('signal', type=int, help='Signal to send', location='json')

@ns.route("/<id>/signals")
@ns.param("id", "The worker identifier")
@ns.response(404, "Worker not found")
class WorkerSignal(Resource):
    @ns.doc("get_worker_signals")
    @ns.marshal_list_with(signal)
    def get(self, id):
        """Fetch a worker executions given the worker identifier and the executions status"""
        signals = list(Signal.query.filter(Signal.worker_id==id))
        for sig in signals:
            db.session.delete(sig)
        db.session.commit()
        return signals
    
    @ns.doc("create_worker_signal")
    @ns.expect(signal_parser)
    def post(self, id):
        """Create a signal for the given worker about a certain execution with a certain signal"""
        args = signal_parser.parse_args()
        db.session.add(Signal(args['execution_id'], id, args['signal']))
        db.session.commit()


ns = api.namespace('executions', description='EXECUTION operations')

execution_filter = api.model('ExecutionFilter', {
    'task_id': fields.Integer(required=False,description='A list of ids to restrict listing'),
    'status': fields.String(required=False, description="Filter with this status"),
    'latest': fields.Boolean(required=False, description="Filter only for latest execution"),
    'task_name': fields.String(required=False, description="Filter with this task name"),
    'batch': fields.String(required=False, description="Filter with this batch"),
    'limit': fields.Integer(required=False, description="Limit results to this number"),
    'reverse': fields.Boolean(required=False, description="Reverse sorting order, most recent executions first"),
    'no_output': fields.Boolean(required=False, description="Do not include output and error for a lighter query"),
    'trunc': fields.Integer(required=False, description="Limit output size to this number"),
})
@ns.route('/')
class ExecutionList(Resource):
    '''Shows a list of all executions, and lets you POST to add new workers'''
    @ns.doc('list_executions')
    @ns.expect(execution_filter)
    @ns.marshal_list_with(execution)
    def get(self):
        '''List all executions'''
        return execution_dao.list(**api.payload) if api.payload else execution_dao.list()

    @ns.doc('create_execution')
    @ns.expect(execution)
    @ns.marshal_with(execution, code=201)
    def post(self):
        '''Create a new execution'''
        return execution_dao.create(api.payload), 201
    

@ns.route("/<id>")
@ns.param("id", "The execution identifier")
@ns.response(404, "Execution not found")
class ExecutionObject(Resource):
    @ns.doc("get_execution")
    @ns.marshal_with(execution)
    def get(self, id):
        """Fetch a execution given its identifier"""
        return execution_dao.get(id)

    @ns.doc("update_execution")
    @ns.expect(execution)
    @ns.marshal_with(execution, code=201)
    def put(self, id):
        """Update an execution"""
        return execution_dao.update(id, api.payload)


parser = api.parser()
parser.add_argument('text', type=str, help='Supplementary text', location='json')

@ns.route("/<id>/delete")
@ns.param("id", "The execution identifier")
@ns.response(404, "Execution not found")
class ExecutionObject(Resource):
    @ns.doc('delete_execution')
    def put(self,id):
        '''Delete an execution for this id'''
        for e in Execution.query.filter(Execution.execution_id==id):
            db.session.delete(e)
        db.session.commit()
        return {'result':'ok'}

execution_output_filter = api.model('ExecutionOutputFilter', {
    'output': fields.Boolean(required=False, default=True, description='Include output flow (stdout)'),
    'error': fields.Boolean(required=False, default=True, description='Include error flow (stderr)'),
    'output_start': fields.Integer(required=False, default=1, description='Provide output (stdout) starting from this position'),
    'error_start': fields.Integer(required=False, default=1, description='Provide error (stderr) starting from this position'),
})

@ns.route("/<id>/output")
@ns.param("id", "The execution identifier")
@ns.response(404, "Execution not found")
class ExecutionOutput(Resource):
    @ns.doc("update_execution_output")
    @ns.expect(parser)
    def put(self, id):
        """Add some data to the execution output"""
        #x = execution_dao.get(id)
        args = parser.parse_args()
        db.session.execute(
                update(Execution).where(Execution.execution_id==id).values(
                    {'output':func.coalesce(Execution.output,'')+args['text']})
            )
        db.session.commit()
        #execution_dao.update(id, 
        #    {'output':('' if x.output is None else x.output) + args['text']})
        return {'result':'Ok'}
    
    @ns.doc("get_task_output_and_or_error_from_a_given_position")
    @ns.expect(execution_output_filter)
    def get(self, id):
        """Fetch an execution output given its identifier"""
        data=api.payload['data']
        output=data.get('output',True)
        error=data.get('error',True)
        output_start=data.get('output_position',1)
        error_start=data.get('error_position',1)

        query_items=[]
        if output:
            if IS_SQLITE:
                query_items.append(f'substr(output,{output_start}) as output')
            else:
                query_items.append(f'substring(output FROM {output_start}) as output')
        if error:
            if IS_SQLITE:
                query_items.append(f'substr(error,{error_start}) as error')        
            else:
                query_items.append(f'substring(error FROM {error_start}) as error')

        return dict(db.session.execute(f'''SELECT {','.join(query_items)} FROM execution WHERE execution_id={id}''').one())



@ns.route("/<id>/error")
@ns.param("id", "The execution identifier")
@ns.response(404, "Execution not found")
class ExecutionOutput(Resource):
    @ns.doc("update_execution_error")
    @ns.expect(parser)
    def put(self, id):
        """Add some data to execution error"""
        #x = execution_dao.get(id)
        args = parser.parse_args()
        db.session.execute(
                update(Execution).where(Execution.execution_id==id).values(
                    {'error':func.coalesce(Execution.error,'')+args['text']})
            )
        db.session.commit()
        #execution_dao.update(id, 
        #    {'error':('' if x.error is None else x.error) + args['text']})
        return {'result':'Ok'}

@ns.route("/<id>/output_files")
@ns.param("id", "The execution identifier")
@ns.response(404, "Execution not found")
class ExecutionOutputFiles(Resource):
    @ns.doc("update_execution_output")
    @ns.expect(parser)
    def put(self, id):
        """Update output files (files transferred from /output, i.e. results) for execution as a space separated file URL list"""
        args = parser.parse_args()
        execution_dao.update(id, 
            {'output_files':args['text']})
        return {'result':'Ok'}


ns = api.namespace('batch', description='BATCH level operations')

batch_parser = api.parser()
batch_parser.add_argument('signal', type=int, help='Optionnaly send signal to all running tasks', 
    required=False, location='json')


custom_batch = api.model('Batch', {
    'batch': fields.String(readonly=True, description='The name of the batch'), 
    'pending': fields.Integer(readonly=True,
        description='The number of task in pending state'), 
    'accepted': fields.Integer(readonly=True,
        description='The number of task in accepted state'), 
    'running': fields.Integer(readonly=True,
        description='The number of task in running state'), 
    'failed': fields.Integer(readonly=True,
        description='The number of task in succeeded state'), 
    'succeeded': fields.Integer(readonly=True,
        description='The number of task in failed state'), 
    'workers': fields.String(readonly=True, description='The workers used in that batch'),
})

@ns.route("/")
class BatchList(Resource):
    @ns.doc("list_batch")
    @ns.marshal_list_with(custom_batch)
    def get(self):
        """List the batches, their task statuses and workers"""
        if IS_SQLITE:
            worker_query='''SELECT batch,GROUP_CONCAT(name,',') FROM worker GROUP BY batch'''
        else:
            worker_query='''SELECT batch,STRING_AGG(name,',') FROM worker GROUP BY batch'''
        batch_query='''SELECT batch,status,count(task_id) FROM task GROUP BY batch,status ORDER BY batch,status'''
        batches = []
        batches_attributes = {}
        for batch,status,count in db.session.execute(batch_query):
            if batch not in batches:
                batches.append(batch)
                batches_attributes[batch]={'batch':batch}    
            batches_attributes[batch][status]=count
        for batch,workers in db.session.execute(worker_query):
            if batch in batches_attributes:
                batches_attributes[batch]['workers']=workers
        return [batches_attributes[batch] for batch in batches]
@ns.route("/<name>/stop")
@ns.param("name", "The batch name")
@ns.response(404, "Batch not found")
class BatchStop(Resource):
    @ns.doc("stop_a_batch")
    @ns.expect(batch_parser)
    def put(self, name):
        """Pause all workers for this batch - and kill current job if force is set"""
        for w in Worker.query.filter(Worker.batch==name):
            w.status = 'paused'
        args = batch_parser.parse_args()
        if args.get('signal',False):
            log.warning(f'Sending signal {args["signal"]} to executions for batch {name}')
            for e in db.session.scalars(select(Execution).join(Execution.task).where(
                                            Execution.status=='running',
                                            Task.batch==name)):
                log.warning(f'Sending signal {args["signal"]} to execution {e.execution_id}')
                db.session.add(Signal(e.execution_id, e.worker_id, args['signal']))
        db.session.commit()
        return {'result':'Ok'}

@ns.route("/<name>/go")
@ns.param("name", "The batch name")
@ns.response(404, "Batch not found")
class BatchGo(Resource):
    @ns.doc("_re_launch_a_batch")
    @ns.expect(batch_parser)
    def put(self, name):
        """(re)set all workers affected to this batch to running"""
        for w in Worker.query.filter(Worker.batch==name):
            w.status = 'running'
        args = batch_parser.parse_args()
        if args.get('signal',False):
            log.warning(f'Sending signal {args["signal"]} to executions for batch {name}')
            for e in db.session.scalars(select(Execution).join(Execution.task).where(
                                            Execution.status=='running',
                                            Task.batch==name)):
                log.warning(f'Sending signal {args["signal"]} to execution {e.execution_id}')
                db.session.add(Signal(e.execution_id, e.worker_id, args['signal']))
        db.session.commit()
        return {'result':'Ok'}



@ns.route("/<name>")
@ns.param("name", "The batch name")
@ns.response(404, "Batch not found")
class BatchDelete(Resource):
    @ns.doc("delete_a_batch")
    def delete(self, name):
        """Delete all tasks and executions for this batch"""
        log.warning(f'Deleting batch {name}')
        delete_batch(name, session=db.session)
        return {'result':'Ok'}


ns = api.namespace('requirement', description='Task requirements management')


requirement = api.model('Requirement', {
    'requirement_id': fields.Integer(readonly=True, description='The requirement unique identifier'),
    'task_id': fields.Integer(required=True, description='The requiring task id'),
    'other_task_id': fields.Integer(required=True, description='The requirred task id'),
})

@ns.route('/')
class RequirementList(Resource):
    '''Shows a list of all requirements, and lets you POST to add new requirements'''
    @ns.doc('list_requirement')
    @ns.marshal_list_with(requirement)
    def get(self):
        '''List all requirements'''
        return requirement_dao.list()

    @ns.doc('create_requirement')
    @ns.expect(requirement)
    @ns.marshal_with(requirement, code=201)
    def post(self):
        '''Create a new requirement'''
        return requirement_dao.create(api.payload), 201

@ns.route("/<id>")
@ns.param("id", "The requirement identifier")
@ns.response(404, "Requirement not found")
class RequirementObject(Resource):
    @ns.doc("delete_requirement")
    @ns.marshal_with(requirement)
    def delete(self, id):
        """Delete a worker"""
        return requirement_dao.delete(id)



ns = api.namespace('recruiter', description='Recruiter management')

class RecruiterDAO(BaseDAO):
    ObjectType = Recruiter

    def get(self, batch, rank):
        object = Recruiter.query.get({'batch':batch, 'rank':rank})
        if object is None:
            api.abort(404, "{} batch {} rank {} doesn't exist".format(
                    self.ObjectType.__name__,batch,rank))
        return object
        
    def create(self, data):
        object = self.ObjectType(**data)
        db.session.merge(object)
        db.session.commit()
        return object

    def update(self, batch, rank, data):
        object = self.get(batch, rank)
        modified = False
        for attr, value in data.items():
            if hasattr(object,attr): 
                if getattr(object,attr)!=value:
                    setattr(object, attr, value)
                    modified = True
            else:
                api.abort(500,f'Error: {object.__name__} has no attribute {attr}')
        if modified:
            db.session.commit()
        return object

    def delete(self, batch, rank):
        object = self.get(batch,rank)
        db.session.delete(object)
        db.session.commit()
        return object
    
    def list(self, **args):
        return super().list(sorting_column='rank', **args)
    


recruiter_dao = RecruiterDAO()

recruiter = api.model('Recruiter', {
    'batch': fields.String(readonly=True, description='The target batch for recruitment'),
    'rank': fields.Integer(readonly=True, description='The rank of the recruiter for that batch (unique per batch)'),
    'tasks_per_worker': fields.Integer(required=True, description='Each time this number of pending tasks is there, trigger a recruitment'),
    'worker_flavor': fields.String(required=True, description='What flavor of worker to recruit'),
    'worker_provider': fields.String(required=False, description='From what provider the worker should be recruited'),
    'worker_region': fields.String(required=False, description='From what provider region the worker should be recruited'),
    'worker_concurrency': fields.Integer(required=True, description='Set worker concurrency to this when recruited'),
    'worker_prefetch': fields.Integer(required=False, description='Set worker prefetch to this when recruited (0 otherwise)'),
    'minimum_tasks': fields.Integer(required=False, description='Do not trigger until there is this minimum number of task (should be above tasks_per_worker)'),
    'maximum_workers': fields.Integer(required=False, description='Stop to trigger when there is this number of worker for the batch'),
})

@ns.route('/')
class RecruiterList(Resource):
    '''Shows a list of all recruiters, and lets you POST to add new recruiters'''
    @ns.doc('list_recruiters')
    @ns.marshal_list_with(recruiter)
    def get(self):
        '''List all recruiters'''
        return recruiter_dao.list(**api.payload)

    @ns.doc('create_recruiter')
    @ns.expect(recruiter)
    @ns.marshal_with(recruiter)
    def post(self):
        '''Create or replace a recruiter'''
        return recruiter_dao.create(api.payload), 201


@ns.route('/match')
class RecruiterList(Resource):
    '''Send a list of workers matching recruitment criteria for a list of recruiters'''
    @ns.doc('list_recruiters')
    @ns.marshal_list_with(worker)
    def get(self):
        '''List all workers'''
        recruiters = recruiter_dao.list(**api.payload)
        workers = worker_dao.list()
        recruitable_workers=[]
        for recruiter in recruiters:
            for worker in workers:
                if recruiter.match_flavor(worker=worker, session=db.session):
                    recruitable_workers.append(worker)
        return recruitable_workers

@ns.route("/<batch>/<rank>")
@ns.param("batch", "Target batch for the recruiter")
@ns.param("rank", "Rank of the recruiter")
@ns.response(404, "Recruiter not found")
class RecruiterObject(Resource):
    @ns.doc("get_recruiter")
    @ns.marshal_with(recruiter)
    def get(self, batch, rank):
        """Fetch a execution given its identifier"""
        return recruiter_dao.get(batch, rank)

    @ns.doc("update_recruiter")
    @ns.expect(recruiter)
    @ns.marshal_with(recruiter, code=201)
    def put(self, batch, rank):
        """Update an execution"""
        return recruiter_dao.update(batch, rank, api.payload)

    @ns.doc("delete_recruiter")
    @ns.marshal_with(recruiter)
    def delete(self, batch, rank):
        """Delete a worker"""
        object=recruiter_dao.delete(batch, rank)
        return object 

ns = api.namespace('flavor', description='Flavor querying')

flavor_parser = api.parser()
flavor_parser.add_argument('min_cpu', type=int, help='Minimum number of CPUs', 
    required=False, location='json', default=0)
flavor_parser.add_argument('min_ram', type=int, help='Minimum size of RAM (memory) in Gb', 
    required=False, location='json', default=0)
flavor_parser.add_argument('min_disk', type=int, help='Minimum size of disk (harddrive) in Gb', 
    required=False, location='json', default=0)
flavor_parser.add_argument('max_eviction', type=int, 
    help=f'Maximal risk of eviction (default:{FLAVOR_DEFAULT_EVICTION})', 
    required=False, location='json', default=FLAVOR_DEFAULT_EVICTION)
flavor_parser.add_argument('limit', type=int, 
    help=f'Maximal number or answer (default:{FLAVOR_DEFAULT_LIMIT})', 
    required=False, location='json', default=FLAVOR_DEFAULT_LIMIT)
flavor_parser.add_argument('provider', type=str, 
    help=f'Specify provider', 
    required=False, location='json', default=None)
flavor_parser.add_argument('region', type=str, 
    help=f'Specify region', 
    required=False, location='json', default=None)
flavor_parser.add_argument('protofilters', type=str, 
    help=f'Add some : separated protofilters like cpu>10 or ram>=128', 
    required=False, location='json', default=None)

custom_flavor = api.model('Flavor', {
    'name': fields.String(readonly=True, description='The flavor reference'),
    'provider':  fields.String(readonly=True, description='Provider name'),
    'region':  fields.String(readonly=True, description='Provider region name'),
    'cpu': fields.Integer(readonly=True,
        description='The number of CPUs (vcores) for this flavor'), 
    'ram': fields.Float(readonly=True,
        description='The size of the RAM (memory) in Gb'), 
    'disk': fields.Float(readonly=True,
        description='The size of the disk in Gb'),
    'tags': fields.String(readonly=True, 
        description='A custom string listing some specificity of the flavor (G=GPU, M=Metal, N=NVMe)'),
    'gpu': fields.String(readonly=True,
        description='A description of the GPU (if available)'),
    'gpumem': fields.Float(readonly=True,
        description='The size of the GPU memory in Gb (if available)'),
    'cost': fields.Float(readonly=True, description='An indicative cost per hour in the unit of reference of the provider'),
    'eviction': fields.Integer(readonly=True, description='An estimate of the hourly probability of eviction (VM shut down by provider)'), 
    'available': fields.Integer(readonly=True, 
        description='An estimate of the number of VM of this size one can create in this region and for this provider')
})

@ns.route("/")
class FlavorList(Resource):
    @ns.doc("list_flavor")
    @ns.marshal_list_with(custom_flavor)
    @ns.expect(flavor_parser)
    def get(self):
        """List the batches, their task statuses and workers"""
        args = flavor_parser.parse_args()
        return find_flavor(session=db.session, 
                    min_cpu=args.min_cpu,
                    min_ram=args.min_ram, 
                    min_disk=args.min_disk,
                    max_eviction=args.max_eviction,
                    limit = args.limit,
                    provider = args.provider,
                    region = args.region,
                    protofilters = args.protofilters)

ns = api.namespace('config', description='Get some config parameter from server')

@ns.route("/rclone")
class Rclone(Resource):
    @ns.doc("get_rclone_conf")
    def get(self):
        """Provide rclone conf"""
        with open(DEFAULT_RCLONE_CONF,'rt') as rclone_conf:
            return rclone_conf.read()
