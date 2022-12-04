from argparse import Namespace
from datetime import datetime
from flask import Flask, render_template, request, g
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, and_, select, delete, true
from sqlalchemy.orm import Session
from flask_restx import Api, Resource, fields
from flask_socketio import SocketIO, emit
from werkzeug.middleware.proxy_fix import ProxyFix
from time import sleep
from threading import Thread
import queue
import logging as log
from logging.config import dictConfig
import os
from subprocess import run
import signal
import json
from sqlalchemy.dialects import sqlite
from .util import PropagatingThread, package_path, package_version
from .default_settings import SQLALCHEMY_POOL_SIZE, SQLALCHEMY_DATABASE_URI
from .ansible.scitq.sqlite_inventory import scitq_inventory


MAIN_THREAD_SLEEP = 5
WORKER_OFFLINE_DELAY = 15
SCITQ_SERVER = os.environ.get('SCITQ_SERVER',None)
WORKER_CREATE = f'cd {package_path("ansible","playbooks")} && ansible-playbook deploy_one_vm.yaml --extra-vars "nodename={{hostname}} concurrency={{concurrency}} status=running flavor={{flavor}} region={{region}}"'
if SCITQ_SERVER is not None:
    WORKER_CREATE = WORKER_CREATE[:-1] + f' target={SCITQ_SERVER}"'
WORKER_DELETE = os.environ.get('WORKER_DELETE',f'cd {package_path("ansible","playbooks")} && ansible-playbook destroy_vm.yaml --extra-vars "nodename={{hostname}}"')
WORKER_IDLE_CALLBACK = os.environ.get('WORKER_IDLE_CALLBACK',WORKER_DELETE)
WORKER_CREATE_CONCURRENCY = 10
WORKER_CREATE_RETRY=2
WORKER_CREATE_RETRY_SLEEP=30
UI_OUTPUT_TRUNC=100
WORKER_DESTROY_RETRY=2

dictConfig({
    'version': 1,
    'formatters': {'default': {
        'format': '[%(asctime)s] %(levelname)s in %(module)s: %(message)s',
    }},
    'handlers': {'wsgi': {
        'class': 'logging.StreamHandler',
        'stream': 'ext://flask.logging.wsgi_errors_stream',
        'formatter': 'default'
    }, "file": {
        "class": "logging.handlers.RotatingFileHandler",
        "formatter": "default",
        "filename": os.environ.get('LOG_FILE',"/tmp/scitq.log"),
        "maxBytes": int(os.environ.get('LOG_FILE_MAX_SIZE',"10000000")),
        "backupCount": int(os.environ.get('LOG_FILE_KEEP',"3"))
    }},
    'root': {
        'level': os.environ.get('LOG_LEVEL',"INFO"),
        'handlers': ['wsgi' if 'DEBUG' in os.environ else 'file']
    }
})

IS_SQLITE = 'sqlite' in SQLALCHEMY_DATABASE_URI


log.info('Starting')
log.warning(f'WORKER_CREATE is {WORKER_CREATE}')

worker_create_queue = queue.Queue()


# via https://github.com/pallets/flask-sqlalchemy/blob/main/examples/hello/hello.py
app = Flask(__name__, instance_relative_config=True)
#app.config['SQLALCHEMY_DATABASE_URI'] = "postgresql://postgres:postgres@localhost:5432/"
app.config.from_object('scitq.default_settings')
#app.config.from_pyfile("scitq.cfg", silent=True)
#app.config.from_prefixed_env()
if SQLALCHEMY_POOL_SIZE is not None:
    db = SQLAlchemy(app, engine_options={'pool_size': int(SQLALCHEMY_POOL_SIZE)})
else:
    db = SQLAlchemy(app)
socketio = SocketIO(app)

class Task(db.Model):
    __tablename__ = "task"
    task_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String)
    command = db.Column(db.String, nullable=False)
    status = db.Column(db.String, nullable=False)
    creation_date = db.Column(db.DateTime, nullable=False)
    modification_date = db.Column(db.DateTime)
    batch = db.Column(db.String, nullable=True)
    input = db.Column(db.String, nullable=True)
    output = db.Column(db.String, nullable=True)
    container = db.Column(db.String, nullable=True)
    container_options = db.Column(db.String, nullable=True)
    resource = db.Column(db.String, nullable=True)

    def __init__(self, command, name=None, status='pending', batch=None, 
                    input=None, output=None, container=None, 
                    container_options=None, resource=None):
        self.name = name
        self.command = command
        self.status = status
        self.creation_date = datetime.utcnow()
        self.modification_date = self.creation_date
        self.batch = batch
        self.input = input
        self.output = output
        self.container = container
        self.container_options = container_options
        self.resource = resource


class Worker(db.Model):
    __tablename__ = "worker"
    worker_id = db.Column(db.Integer,primary_key=True)
    name = db.Column(db.String, nullable=False)
    hostname = db.Column(db.String)
    status = db.Column(db.String, nullable=False)
    concurrency = db.Column(db.Integer)
    prefetch = db.Column(db.Integer)
    load = db.Column(db.String)
    memory=db.Column(db.String)
    read_bytes=db.Column(db.String)
    written_bytes=db.Column(db.String)
    creation_date = db.Column(db.DateTime)
    modification_date = db.Column(db.DateTime)
    last_contact_date = db.Column(db.DateTime)
    batch = db.Column(db.String,nullable=True)
    idle_callback = db.Column(db.String, nullable=True)

    def __init__(self, name, concurrency, prefetch=0, hostname=None, 
                status='paused', batch=None, idle_callback=None):
        self.name = name
        self.concurrency = concurrency
        self.prefetch = prefetch
        self.status = status
        self.creation_date = datetime.utcnow()
        self.modification_date = self.creation_date
        self.hostname = hostname
        self.batch = batch
        self.idle_callback = idle_callback
    
    def destroy(self):
        """Destroy self (stop in provider renting)"""
        log.warning(f'Worker {self.name} is to be destroyed.')

        for i in range(WORKER_DESTROY_RETRY):
            try:
                run([self.idle_callback.format(**(self.__dict__))],shell=True,check=True)
            except Exception as e:
                log.exception(e)

            worker_check = json.loads(scitq_inventory(host=self.hostname))

            if not worker_check:
                log.warning(f'Worker {self.name} was destroyed.')
                break
            else:
                log.exception(f'Worker {self.name} was not properly destroyed (f{worker_check}), retrying.')

class Execution(db.Model):
    __tablename__ = "execution"
    execution_id = db.Column(db.Integer, primary_key=True)
    worker_id = db.Column(db.Integer, db.ForeignKey("worker.worker_id"), nullable=True)
    worker = db.relationship(
        Worker,
        backref=db.backref('executions',
                         uselist=True,
                         cascade='save-update',
                         order_by='Execution.modification_date.desc()'))
    task_id = db.Column(db.Integer, db.ForeignKey("task.task_id"), nullable=False)
    task = db.relationship(
        Task,
        backref=db.backref('tasks',
                         uselist=True,
                         cascade='delete,all'),
                         order_by='Execution.creation_date')
    status = db.Column(db.String, nullable=False)
    creation_date = db.Column(db.DateTime, nullable=False)
    modification_date = db.Column(db.DateTime)
    output = db.Column(db.Text)
    error = db.Column(db.Text)
    return_code = db.Column(db.Integer)
    pid = db.Column(db.Integer)
    output_files = db.Column(db.String, nullable=True)
    

    def __init__(self, worker_id, task_id, status='pending', pid=None, 
                    return_code=None):
        self.worker_id = worker_id
        self.task_id = task_id
        self.status = status
        self.pid = pid
        self.return_code = return_code
        self.creation_date = datetime.utcnow()
        self.modification_date = self.creation_date

class Signal(db.Model):
    __tablename__ = "signal"
    execution_id = db.Column(db.Integer, db.ForeignKey("execution.execution_id"), primary_key=True)
    worker_id = db.Column(db.Integer, db.ForeignKey("worker.worker_id"), primary_key=True)
    signal = db.Column(db.Integer, nullable=False)    

    def __init__(self, execution_id, worker_id, signal):
        self.execution_id = execution_id
        self.worker_id = worker_id
        self.signal = signal

with app.app_context():
    db.create_all()


# via https://flask-restx.readthedocs.io/en/latest/example.html
app.wsgi_app = ProxyFix(app.wsgi_app)
api = Api(app, version='1.0', title='TaskMVC API',
    description='A simple TaskMVC API'
)


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
    
    def list(self, *args, sorting_column=None):
        if args:
            return list(self.ObjectType.query.filter(*args).order_by(sorting_column))
        else:
            return list(self.ObjectType.query.order_by(sorting_column).all())
        
        



ns = api.namespace('tasks', description='TASK operations')

class TaskDAO(BaseDAO):
    ObjectType = Task
    authorized_status = ['paused','pending','assigned','accepted','running','failed','succeeded']

    def list(self):
        return super().list(sorting_column='task_id')

task_dao = TaskDAO()

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
    'batch': fields.String(required=False, 
        description="only workers with the same batch (null or not) will accept the task."),
    'input': fields.String(required=False,
        decription="Input data required for task (space separated files URL in s3://...)"),
    'output': fields.String(required=False,
        decription="Output data basepath where /output content will be copied (if null, the result transmission is up to the command)"),
    'container': fields.String(required=False,
        decription="Container (as for now this is a docker) in which task is launched"),
    'container_options': fields.String(required=False,
        decription="Container (extra) option if needed"),
    'resource': fields.String(required=False,
        decription="Resource data required for task (much like input except it is shared between tasks) (space separated files URL in s3://...)"),
})


@ns.route('/')
class TaskList(Resource):
    '''Shows a list of all tasks, and lets you POST to add new tasks'''
    @ns.doc('list_tasks')
    @ns.marshal_list_with(task)
    def get(self):
        '''List all tasks'''
        return task_dao.list()

    @ns.doc('create_task')
    @ns.expect(task)
    @ns.marshal_with(task, code=201)
    def post(self):
        '''Create a new task'''
        return task_dao.create(api.payload), 201


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
        return task_dao.update(id, api.payload)

    @ns.doc("delete_task")
    @ns.marshal_with(task)
    def delete(self, id):
        """Delete a task"""
        return task_dao.delete(id)

ns = api.namespace('workers', description='WORKER operations')



class WorkerDAO(BaseDAO):
    ObjectType = Worker
    authorized_status = ['paused','running','offline','terminated']

    def update_contact(self, id, load,memory,read_bytes,written_bytes):
        db.engine.execute(
            db.update(Worker
                    ).values({'last_contact_date':datetime.utcnow(),
                        'load':load,'memory':memory,'read_bytes':read_bytes,'written_bytes':written_bytes}
                    ).where(Worker.worker_id==id)
        )
        db.session.commit()

    def delete(self,id):
        """Delete a worker
        """
        worker=self.get(id)
        log.warning(f'Deleting worker {id} ({worker.idle_callback})')
        if worker.idle_callback is not None:
            with app.app_context():
                session = Session(db.engine)
            def _this_worker_destroy():
                worker.destroy()
                session.delete(worker)
                session.commit()
                session.close()
            Thread(target=_this_worker_destroy).start()
            return worker
        else:
            return super().delete(id)

    def list(self):
        return super().list(sorting_column='worker_id')

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
    'memory':fields.Float(readonly=True, description='Memory not use (in %)'),
    'read_bytes':fields.Float(readonly=True,description='read bytes'),
    'written_bytes':fields.Float(readonly=True,description='written bytes'),
    'creation_date': fields.DateTime(readonly=True, 
        description='timestamp of worker creation'),
    'modification_date': fields.DateTime(readonly=True, 
        description='timestamp of last worker modification'),
    'last_contact_date': fields.DateTime(readonly=True, 
        description='timestamp of last worker ping (automatically sent by worker'),
    'batch': fields.String(required=False, 
        description="worker accept only tasks with same batch (null or not)."),
    'idle_callback': fields.String(readonly=True,
        description="A command to be called on scitq server when the worker load *returns* to zero. Typically used to end cloud instances.")
})

@ns.route('/')
class WorkerList(Resource):
    '''Shows a list of all workers, and lets you POST to add new workers'''
    @ns.doc('list_workers')
    @ns.marshal_list_with(worker)
    def get(self):
        '''List all workers'''
        return worker_dao.list()

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
            JOIN task t ON e.task_id=t.task_id 
                AND e.execution_id=
                    (SELECT max(execution_id) FROM execution e2 WHERE e2.task_id=t.task_id)
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
ping_parser.add_argument('memory', type=float, help='Worker load', location='json')
ping_parser.add_argument('read_bytes', type=float, help='Worker load', location='json')
ping_parser.add_argument('written_bytes', type=float, help='Worker load', location='json')

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
        worker_dao.update_contact(id, args.get('load',''),args.get('memory',''),args.get('read_bytes',''),args.get('written_bytes',''))
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
        if message == 'idle' and worker.idle_callback:
            if db.session.query(Execution).filter(Execution.status=='running',
                    Execution.worker_id==worker.worker_id).count()>0:
                log.warning(f'Worker {worker.name} called idle callback but some tasks are still running, refusing...')
                return {'result':'still have running tasks'}
            if db.session.query(Task).filter(and_(Task.status.in_(['pending','accepted']),
                                    Task.batch==worker.batch)).count()>0:
                log.warning(f'Worker {worker.name} called idle but some tasks are still due...')
                return {'result':'still some work to do, lazy one!'}
            log.warning(f'Worker {worker.name} called idle callback, launching: '+worker.idle_callback.format(**(worker.__dict__)))
            worker.destroy()
            db.session.delete(worker)
            db.session.commit()
            return {'result':'ok'}
        else:
            log.warning(f'Worker {worker.name} called idle callback but has no idle command')
            return {'result':'nothing to do'}

deploy_parser = api.parser()
deploy_parser.add_argument('number', type=int, help='How many workers should be deployed', location='json')
deploy_parser.add_argument('region', type=str, help='Which provider region for worker', location='json')
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

        for _ in range(deploy_args['number']):
            worker_create_queue.put(Namespace(concurrency=deploy_args['concurrency'], 
                prefetch=deploy_args['prefetch'],
                flavor=deploy_args['flavor'],
                region=deploy_args['region'],
                batch=deploy_args['batch']))
        
        return {'result':'ok'}

class ExecutionDAO(BaseDAO):
    ObjectType = Execution
    authorized_status = ['pending','accepted','running','failed','succeeded']

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
        for attr, value in data.items():
            if hasattr(execution,attr): 
                if getattr(execution,attr)!=value:
                    if attr=='status':
                        if value not in self.authorized_status:
                            api.abort(500,
                                f"Status {value} is not possible (only {' '.join(self.authorized_status)})")
                        task=task_dao.get(execution.task_id)
                        if execution.status=='pending':
                            if value=='running':
                                task.status = 'running'
                                task.modification_date = datetime.utcnow()
                            elif value=='accepted':
                                task.status = 'accepted'
                                task.modification_date = datetime.utcnow()
                            elif value in ['refused','failed']:
                                task.status = 'pending'
                                task.modification_date = datetime.utcnow()
                            elif value=='succeeded':
                                task.status = 'succeeded'
                                task.modification_date = datetime.utcnow()
                            else:
                                api.abort(500, f"An execution cannot change status from pending to {value}")
                        elif execution.status=='accepted':
                            if value in ['running','failed','succeeded']:
                                task.status = value
                                task.modification_date = datetime.utcnow()
                            else:
                                log.exception(f"An execution cannot change status from accepted to {value}")
                                api.abort(500, f"An execution cannot change status from accepted to {value}")
                        elif execution.status=='running':
                            if value in ['succeeded', 'failed']:
                                task.status=value
                                task.modification_date = datetime.utcnow()
                            else:
                                log.exception(f"An execution cannot change status from running to {value}")
                                api.abort(500, f"An execution cannot change status from running to {value}")
                        else:
                            api.abort(500, f"An execution cannot change status from {execution.status} (only from pending, running or accepted)")
                    setattr(execution, attr, value)
                    modified = True
            else:
                raise Exception('Error: {} has no attribute {}'.format(
                    execution.__name__, attr))
        if modified:
            execution.modification_date = datetime.utcnow()
            db.session.commit()
        return execution

    def list(self,*args):
        return super().list(*args,sorting_column='execution_id')

execution_dao = ExecutionDAO()

execution = api.model('Execution', {
    'execution_id': fields.Integer(readonly=True, description='The execution unique identifier'), 
    'worker_id': fields.Integer(required=True, description='A worker unique identifier'),
    'task_id': fields.Integer(required=True, description='A task unique identifier'),
    'status': fields.String(readonly=True,
        description=f'The execution status: {", ".join(ExecutionDAO.authorized_status)}'), 
    'return_code': fields.Integer(required=False, description='The return code of the execution (when finished)'),
    'pid': fields.Integer(required=False, description='The process id (pid) of the execution'),
    'creation_date': fields.DateTime(readonly=True,
        description="timestamp of execution creation (on worker)"),
    'modification_date': fields.DateTime(readonly=True,
        description="timestamp of execution last modification"),
    'output': fields.String(readonly=True, description='The standard output of the execution'),
    'error': fields.String(readonly=True, description='The standard error of the execution (if any)'),
    'output_files': fields.String(readonly=True, description='A list of output files transmitted (if any)'),
})


@ns.route("/<id>/executions")
@ns.param("id", "The worker identifier")
@ns.response(404, "Worker not found")
class WorkerExecutionObject(Resource):
    @ns.doc("get_worker_executions")
    @ns.marshal_list_with(execution)
    def get(self, id):
        """Fetch a worker executions given the worker identifier"""
        #worker_dao.update_contact(id)
        return execution_dao.list(Execution.worker_id==id)


@ns.route("/<id>/executions/<status>")
@ns.param("id", "The worker identifier")
@ns.param("status", "Filter only executions with this status")
@ns.response(404, "Worker not found")
class WorkerExecutionFilterObject(Resource):
    @ns.doc("get_worker_executions")
    @ns.marshal_list_with(execution)
    def get(self, id, status):
        """Fetch a worker executions given the worker identifier and the executions status"""
        #worker_dao.update_contact(id)
        return execution_dao.list(Execution.worker_id==id, Execution.status==status)

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

@ns.route('/')
class ExecutionList(Resource):
    '''Shows a list of all executions, and lets you POST to add new workers'''
    @ns.doc('list_executions')
    @ns.marshal_list_with(execution)
    def get(self):
        '''List all executions'''
        return execution_dao.list()

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

@ns.route("/<id>/output")
@ns.param("id", "The execution identifier")
@ns.response(404, "Execution not found")
class ExecutionOutput(Resource):
    @ns.doc("update_execution_output")
    @ns.expect(parser)
    def put(self, id):
        """Add some data to the execution output"""
        x = execution_dao.get(id)
        args = parser.parse_args()
        execution_dao.update(id, 
            {'output':('' if x.output is None else x.output) + args['text']})
        return {'result':'Ok'}

@ns.route("/<id>/error")
@ns.param("id", "The execution identifier")
@ns.response(404, "Execution not found")
class ExecutionOutput(Resource):
    @ns.doc("update_execution_error")
    @ns.expect(parser)
    def put(self, id):
        """Add some data to execution error"""
        x = execution_dao.get(id)
        args = parser.parse_args()
        execution_dao.update(id, 
            {'error':('' if x.error is None else x.error) + args['text']})
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
        if isinstance(db.session.bind.dialect, sqlite.dialect):
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
        if name=='Default':
            for w in Worker.query.filter(Worker.batch.is_(None)):
                w.status = 'paused'
        else:
            for w in Worker.query.filter(Worker.batch==name):
                w.status = 'paused'
        args = batch_parser.parse_args()
        if args.get('signal',False):
            log.warning(args['signal'])
            log.warning(f'Sending signal {args["signal"]} to executions for batch {name}')
            if name=='Default':
                for e in db.session.scalars(select(Execution).join(Execution.task).where(
                                                Execution.status=='running',
                                                Task.batch.is_(None))):
                    log.warning(f'Sending signal {args["signal"]} to execution {e.execution_id}')
                    db.session.add(Signal(e.execution_id, e.worker_id, args['signal']))
            else:
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
        if name=='Default':
            for w in Worker.query.filter(Worker.batch.is_(None)):
                w.status = 'running'
        else:
            for w in Worker.query.filter(Worker.batch==name):
                w.status = 'running'
        args = batch_parser.parse_args()
        if args.get('signal',False):
            log.warning(args['signal'])
            log.warning(f'Sending signal {args["signal"]} to executions for batch {name}')
            if name=='Default':
                for e in db.session.scalars(select(Execution).join(Execution.task).where(
                                                Execution.status=='running',
                                                Task.batch.is_(None))):
                    log.warning(f'Sending signal {args["signal"]} to execution {e.execution_id}')
                    db.session.add(Signal(e.execution_id, e.worker_id, args['signal']))
            else:
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
        # execution are deleted by cascade
        if name=='Default':
            for t in Task.query.filter(Task.batch.is_(None)):
                db.session.delete(t)
        else:
            for t in Task.query.filter(Task.batch==name):
                db.session.delete(t)
        db.session.commit()
        return {'result':'Ok'}

#     # ### 
#     #  #  
#     #  #  
#     #  #  
#     #  #  
#     #  #  
 #####  ### 


package_version = package_version()
@app.route('/ui/')
def ui(name=None):
    return render_template('ui.html', name=name, package_version=package_version)
@app.route('/ui/task/')
def task():
    return render_template('task.html',package_version=package_version)

@app.route('/ui/batch/')
def batch():
    return render_template('batch.html', package_version=package_version)

#@app.route('/test/')


@socketio.on('get')
def handle_get(json):
    if 'delay' in json:
        sleep(int(json['delay']))
    if json['object']=='workers':
        log.info('sending workers')
        #emit('workers', [(w.name, w.status, len(w.executions)) for w in Worker.query.all()])
        emit('workers', {
            'workers':list([dict(row) for row in db.session.execute(
                '''SELECT 
                    worker_id,
                    name, 
                    batch,
                    status, 
                    concurrency,
                    prefetch,
                    (SELECT count(execution_id) FROM execution WHERE execution.worker_id=worker.worker_id AND
                                                                        execution.status='accepted') as accepted,
                    (SELECT count(execution_id) FROM execution WHERE execution.worker_id=worker.worker_id AND 
                                                                        execution.status='running') as running,
                    (SELECT count(execution_id) FROM execution WHERE execution.worker_id=worker.worker_id AND 
                                                                        execution.status='succeeded') as succeeded,
                    (SELECT count(execution_id) FROM execution WHERE execution.worker_id=worker.worker_id AND 
                                                                        execution.status='failed') as failed,
                    (SELECT count(execution_id) FROM execution WHERE execution.worker_id=worker.worker_id) as total,
                    load,
                    memory,
                    read_bytes,
                    written_bytes 
                FROM worker
                ORDER BY worker.batch,worker.name''')]),
            'totals': list([list(row) for row in db.session.execute(
                '''SELECT
                    (SELECT count(task_id) FROM task WHERE status='pending'),
                    (SELECT count(task_id) FROM task WHERE status IN ('assigned','accepted')),
                    (SELECT count(task_id) FROM task WHERE status='running'),
                    (SELECT count(task_id) FROM task WHERE status='failed'),
                    (SELECT count(task_id) FROM task WHERE status='succeeded')
                '''
            )])[0] })

    if json['object']=='task':
        log.warning(f"sending task ordered by {json['order_by']} filter by {json['filter_by']}")

        if json['order_by'] =='worker':
            sort_clause='ORDER BY worker.name, task.task_id DESC'
        elif json['order_by'] =='batch':
            sort_clause='ORDER BY task.batch, task.task_id DESC'
        else:
            sort_clause='ORDER BY task.task_id DESC'
        
        if json['filter_by']=='terminated':
            where_clause = "WHERE execution.status IN ('succeeded','failed')"
        elif json['filter_by']=='all':
            where_clause = ""
        elif json['filter_by']:
            where_clause = f"WHERE execution.status='{json['filter_by']}'"
        else:
            where_clause = ""

        if IS_SQLITE:
            trunc_output=f'SUBSTR(execution.output,-{UI_OUTPUT_TRUNC},{UI_OUTPUT_TRUNC})'
            trunc_error=f'SUBSTR(execution.error,-{UI_OUTPUT_TRUNC},{UI_OUTPUT_TRUNC})'
        else:
            trunc_output=f'RIGHT(execution.output,{UI_OUTPUT_TRUNC})'
            trunc_error=f'RIGHT(execution.error,{UI_OUTPUT_TRUNC})'
        
        task_list = list([list(map(lambda x : str(x) if type(x)==type(datetime.utcnow()) else x ,row)) for row in db.session.execute(
        f'''SELECT
        task.task_id,
        task.name,
        worker.name,
        task.batch,
        execution.creation_date,
        execution.modification_date,
        execution.execution_id,
        {trunc_output},
        {trunc_error},
        task.command,
        execution.worker_id,
        task.status
        FROM task 
        LEFT JOIN execution ON (task.task_id=execution.task_id 
            AND execution.creation_date=(SELECT MAX(creation_date) FROM execution AS e1 WHERE e1.task_id=task.task_id))
        LEFT JOIN worker ON execution.worker_id=worker.worker_id 
        {where_clause}
        {sort_clause}
        '''
        )])

        if json.get('detailed_tasks',None):
            for detailed_task in db.session.execute(f"""
                SELECT execution_id,output,error FROM execution 
                WHERE execution_id IN ({','.join([str(eid) for eid in json['detailed_tasks']])})"""):
                for task in task_list:
                    if task[6]==detailed_task[0]:
                        task[7]=detailed_task[1]
                        task[8]=detailed_task[2]
                        break

        emit('task',{'tasks':task_list})
        
    #if json['object'] in ['succeeded','failed','running','pending']:
    #    log.info('sending executions')
    #    type_execution = json['object']
    #    emit('execution',{'executions':list([list(row) for row in db.session.execute(
    #    f'''SELECT 
    #    execution_id,
    #    worker_id,
    #    task_id,
    #    status,
    #    return_code,
    #    pid,
    #    output,
    #    error
    #    FROM execution
    #    WHERE execution.status 
    #    LIKE '{type_execution}'

    #   '''
    #    )])})
    if json['object'] == 'batch':
        log.info('sending batch')
        if IS_SQLITE:
            duration_query='(JULIANDAY(e1.modification_date)-JULIANDAY(e1.creation_date))*24'
            worker_query='''SELECT batch,GROUP_CONCAT(name,',') FROM worker GROUP BY batch'''
        else:
            duration_query='EXTRACT ( EPOCH FROM (e1.modification_date-e1.creation_date)/3600 )'
            worker_query='''SELECT batch,STRING_AGG(name,',') FROM worker GROUP BY batch'''
        batch_query=f'''SELECT * FROM (
    SELECT batch,status,COUNT(task_id),MAX(duration),MIN(duration), AVG(duration) FROM (
        SELECT {duration_query} as duration, e1.task_id, e1.status,task.batch FROM execution e1 JOIN task ON (
            task.task_id=e1.task_id AND e1.creation_date=(
                SELECT MAX(creation_date) FROM execution WHERE execution.task_id=task.task_id
            )
        )
    ) AS e2 GROUP BY batch,status
    UNION	 
    SELECT batch,status, COUNT(task_id),NULL,NULL,NULL 
    FROM task WHERE task_id NOT IN (SELECT task_id FROM execution) GROUP BY batch,status
) AS b ORDER BY batch, status'''
        emit('batch',{'batches':list([list(map(lambda x : str(x) if type(x)==type(datetime.utcnow()) else x ,row)) for row in db.session.execute(
        batch_query
        )]),
        'workers': list([list(row) for row in db.session.execute(worker_query)])})
        
@socketio.on('change_batch')
def handle_change_batch(json):
    Worker.query.filter(Worker.worker_id==json['worker_id']).update(
        {Worker.batch:json['batch_name'] or None})
    db.session.commit()


@socketio.on('concurrency_change')
def handle_concurrency_change(json):
    worker_id = json['id']
    change = json['change']
    log.info(f'changing concurrency for worker {worker_id}: {change}')
    if isinstance(db.session.bind.dialect, sqlite.dialect):
        log.info('Using sqlite SQL')
        Worker.query.filter(Worker.worker_id==worker_id).update(
            {Worker.concurrency: func.max(Worker.concurrency+change,0)})
    else:
        log.info('Using standard SQL')
        Worker.query.filter(Worker.worker_id==worker_id).update(
            {Worker.concurrency: func.greatest(Worker.concurrency+change,0)})
    db.session.commit()

@socketio.on('prefetch_change')
def handle_prefetch_change(json):
    worker_id = json['id']
    change = json['change']
    log.info(f'changing prefetch for worker {worker_id}: {change}')
    if isinstance(db.session.bind.dialect, sqlite.dialect):
        log.info('Using sqlite SQL')
        Worker.query.filter(Worker.worker_id==worker_id).update(
            {Worker.prefetch: func.max(Worker.prefetch+change,0)})
    else:
        log.info('Using standard SQL')
        Worker.query.filter(Worker.worker_id==worker_id).update(
            {Worker.prefetch: func.greatest(Worker.prefetch+change,0)})
    db.session.commit()

def get_nodename():
    worker_names = list(map(lambda x: x[0], 
        db.session.execute(select(Worker.name))))
    log.warning(f'Worker names: {worker_names}')
    i=1
    while f'node{i}' in worker_names:
        i+=1
    return f'node{i}'



@socketio.on('create_worker')
def handle_create_worker(json):
    concurrency = int(json['concurrency'])
    flavor = json['flavor']
    if not flavor:
        emit('worker_created', 'Flavor must be specified')
        return None
    region = json['region']
    if not region:
        emit('worker_created', 'Region must be specified')
        return None
    batch = json['batch'] or None
    prefetch = int(json['prefetch'])
    number = int(json['number'])
    global worker_create_queue
    for _ in range(number):
        worker_create_queue.put(Namespace(concurrency=concurrency, 
            prefetch=prefetch,
            flavor=flavor,
            region=region,
            batch=batch))

@socketio.on('batch_action')
def handle_batch_action(json):
    """Gathering all the action dealing with batch like pause, break, stop, clear, go."""
    if json['action'] in ['stop','break','pause','simple pause','pause only batch']:
        #Same function as in the API set all workers affected to this batch to running and can also interrupt the running tasks with signal 3 and 9
        name=json['name']
        if name=='Default':
            name=None
        for w in Worker.query.filter(Worker.batch==name):
                w.status = 'paused'
        if json['action']=='break':
            signal = 9
        elif json['action']=='stop':
            signal = 3
        elif json['action']=='simple pause':
            signal = 0
        elif json['action']=='pause':
            for t in Task.query.filter(and_(
                        Task.batch==name,
                        Task.status.in_(['running','accepted']))):
                t.status = 'paused'
            signal = 20
            db.session.commit()
        log.warning(f'Sending signal {signal} to executions for batch {name}')
        for e in db.session.scalars(select(Execution).join(Execution.task).where(
                                        Execution.status=='running',
                                        Task.batch==name)):
            log.warning(f'Sending signal {signal} to execution {e.execution_id}')
            db.session.add(Signal(e.execution_id, e.worker_id, signal ))
        db.session.commit()
        log.warning('result pause :Ok')
    if json['action'] in ['go','simple go']: 
        #Same function as in the API (re)set all workers affected to this batch to running
        name=json['name']
        """(re)set all workers affected to this batch to running"""
        for w in Worker.query.filter(Worker.batch==name):
            w.status = 'running'
        if json['action']=='go':
            signal=18
            for t in Task.query.filter(Task.batch==name):
                if t.status == 'paused':
                    t.status='running'
            for e in db.session.scalars(select(Execution).join(Execution.task).where(
                                            Execution.status=='running',
                                            Task.batch==name)):
                log.warning(f'Sending signal {signal} to execution {e.execution_id}')
                db.session.add(Signal(e.execution_id, e.worker_id, signal ))
        db.session.commit()
        log.warning('result go : Ok')
    if json['action']=='clear':
        #Same function as in the API clear() Delete all tasks and executions for this batch
        name=json['name']
        """Delete all tasks and executions for this batch"""
        # execution are deleted by cascade
        if name=='Default':
            name=None
        for t in Task.query.filter(Task.batch==name):
            db.session.delete(t)
        db.session.commit()
        log.warning(f'result clear batch {name}: Ok ')

@socketio.on('task_action')
def handle_task_action(json):
    """Gathering all the action dealing with task like break, stop, delete, modify, restart"""
    #The code essentially is from the API code with a few modifications
    task=json['task_id']
    if json['action'] in ['break','stop','pause','resume']: 
        #A signal 3 or 9 is created and causes only the interruption of the task with id same structure as in the API 
        task=json['task_id']
        for t in Task.query.filter(Task.task_id==task):
            if json['action'] == 'break':
                type='break'
                signal = 9
            elif json['action'] == 'stop':
                signal = 3
                type='stop'
            elif json['action'] == 'pause':
                signal = 20
                type='pause'
                t.status='paused'
            elif json['action'] == 'resume':
                signal = 18
                type='resume'
                t.status='running'
            log.warning(f'Sending signal {signal} to executions for task {task}')
            for e in db.session.scalars(select(Execution).join(Execution.task).where(
                                            Execution.status=='running',
                                            Task.task_id==task)):
                log.warning(f'Sending signal {signal} to execution {e.execution_id}')
                db.session.add(Signal(e.execution_id, e.worker_id, signal ))
        db.session.commit()
        log.warning(f'result {type} : Ok')
    if json['action']=='delete': 
        #Delete the task in the data base
        for t in Task.query.filter(Task.task_id==task):
            db.session.delete(t)
        db.session.commit()
        log.warning('result delete: Ok')
    if json['action']=='modify': 
        #Changing the command for a task in the data base and moving it in the task queue. It doesn't create a new task.
        for t in Task.query.filter(Task.task_id==task):
            t.command =json["modification"]
            t.status='pending'
        db.session.commit()
        log.warning('result modify : Ok')
    if json['action']=='restart': 
        #Relaunching the execution of a task.
        for t in Task.query.filter(Task.task_id==task):
            t.status='pending'
        db.session.commit()
        log.warning('result restart : Ok')

@socketio.on('delete_worker') #Delete a worker.
def delete_worker(json):
    """Delete a worker in db"""
    return worker_dao.delete(json['worker_id'])
    

def create_worker_object(concurrency, flavor, region, batch, prefetch, db_session):
    """Create a worker object in db - this must be called linearly not in async way
    """
    hostname = get_nodename()
    idle_callback = WORKER_IDLE_CALLBACK.format(hostname=hostname)
    log.info(f'Creating a new worker {hostname}: concurrency:{concurrency}, flavor:{flavor}, region:{region}, prefetch:{prefetch}')
    w = Worker(name=hostname, hostname=hostname, concurrency=concurrency, status='offline', 
            batch=batch, idle_callback=idle_callback, prefetch=prefetch)
    db_session.add(w)
    db_session.commit()
    return hostname, w
    
    
def create_worker_process(hostname, concurrency, flavor, region, batch, w, 
        db_session, prefetch=None):
    """Deploy a worker - can be called parallely up to a certain limit
    (WORKER_CREATE_CONCURRENCY)
    """
    try:
        regions = region.split()
        if len(regions)>1:
            region=regions[0]
            len(f'Splitting regions and using region {region}')
        retry=WORKER_CREATE_RETRY
        # be careful with lazy objects in case they got deleted
        worker_id,worker_name = w.worker_id,w.name
        while retry>=0 and worker_exists(worker_id, db_session):
            log.warning(f'''Command is {WORKER_CREATE.format(
                hostname=hostname,
                concurrency=concurrency,
                flavor=flavor,
                region=region
            )}''')
            process = run([WORKER_CREATE.format(
                hostname=hostname,
                concurrency=concurrency,
                flavor=flavor,
                region=region
            )],shell=True, capture_output=True, encoding='utf-8')
            if process.returncode == 0:
                log.warning(f'worker created: done for {hostname}')
                socketio.emit('worker_created', f'done for {hostname}',broadcast=True)
                db_session.close()
                break
            else:
                log.warning(f'worker not created: error for {hostname}: {process.stdout.strip()} {process.stderr.strip()}')
                socketio.emit('worker_created', f'error for {hostname}: {process.stdout.strip()} {process.stderr.strip()}',broadcast=True)
                log.warning(f'Broadcast message sent for {worker_name} failure')
                if retry>=0:
                    log.warning('Retrying...')
                    sleep(WORKER_CREATE_RETRY_SLEEP)
                else:
                    db_session.close()
            #if w.idle_callback:
            #    log.warning(f'Worker {w.name} called idle callback, launching: '+w.idle_callback.format(**(worker.__dict__)))
            #    process = run([w.idle_callback.format(**(w.__dict__))],shell=True,capture_output=True, encoding='utf-8')
            #    if process.returncode != 0:
            #        log.warning(f'worker callback failed: error for {hostname}: {process.stdout.strip()} {process.stderr.strip()}')
            #    else:
            #        log.warning(f'Worker {w.name} was successfully undeployed')
            #        if len(regions)>1:
            #            log.warning("Trying next regions")
            #            create_worker_process(hostname, concurrency, flavor, " ".join(regions[1:]), batch, w)
    except Exception as e:
        socketio.emit('worker_created', f'error for {hostname}: {e}',broadcast=True)
        log.exception(f'Creation failed for {hostname}...')
        raise

def worker_exists(worker_id, db_session):
    """Return true if this worker_id is in database"""
    return db_session.query(Worker).filter(Worker.worker_id==worker_id).count()>0

#@app.route('/ui/get/')
#def ui_get():
#    object = request.args.get('object','workers')
#    log.info('Return worker list to UI')
#    if object=='workers':
#        log.info('sending workers')
#        return jsonify(workers = list([list(row) for row in db.session.execute(
#            'SELECT name, status, (SELECT count(execution_id) FROM execution WHERE execution.worker_id=worker.worker_id) FROM worker')]))

def background():
    # while some tasks are pending without executions:
    #   look for a running worker:
    #      create a pending execution of this task for this worker
    with app.app_context():
        session = Session(db.engine)
    worker_create_process_waiting_queue = []
    worker_create_process_queue = []
    log.info('Starting thread for {}'.format(os.getpid()))
    while True:
        log.info('Starting main loop')
        try:
            task_list = list(session.query(Task).filter(
                    Task.status=='pending').with_entities(Task.task_id, Task.batch))
            if task_list:
                task_attributions = False
                worker_list = list(session.query(Worker).filter(
                            Worker.status=='running').with_entities(
                            Worker.worker_id,Worker.batch,Worker.concurrency,Worker.prefetch))
                execution_per_worker = {worker_id: count for worker_id,count in 
                                session.query(Execution.worker_id,func.count(Execution.task_id)).filter(and_(
                                    Execution.worker_id.in_(list([w.worker_id for w in worker_list])),
                                    Execution.status.in_(['running','pending','accepted']))
                                ).group_by(
                                    Execution.worker_id
                                )
                }
                
                for task in task_list:
                    for worker in worker_list:
                        if worker.batch != task.batch:
                            continue
                        if execution_per_worker.get(worker.worker_id,0)<(worker.concurrency+worker.prefetch):
                            session.add(Execution(worker_id=worker.worker_id,
                                task_id=task.task_id))
                            session.query(Task).filter(Task.task_id==task.task_id).update(
                                {'status':'assigned'}
                            )
                            execution_per_worker[worker.worker_id] = execution_per_worker.get(worker.worker_id,0)+1
                            log.info(f'Execution of task {task.task_id} proposed to worker {worker.worker_id}')
                            task_attributions = True
                            break
                if task_attributions:
                    session.commit()
            now = datetime.utcnow()
            log.warning('Looking for offline/online workers')
            session.expire_all()
            for worker in session.query(Worker).filter(Worker.status.in_(['offline','running'])):
                change = False
                log.warning(f'Assessing worker {worker.name}')
                if worker.last_contact_date is None or (
                            now - worker.last_contact_date
                        ).total_seconds() > WORKER_OFFLINE_DELAY:
                    log.warning(f'... late: {worker.last_contact_date}')
                    if worker.status=='running':
                        log.warning(f'Worker {worker.name} ({worker.worker_id}) lost, marked as offline')
                        worker.status = 'offline'
                        change = True
                else:
                    log.warning('... good')
                    if worker.status=='offline':
                        log.warning(f'Worker {worker.name} ({worker.worker_id}) recovered, marked as running')
                        worker.status = 'running'
                        change = True
                if change:
                    session.commit()  
            try:
                while True:
                    new_worker = worker_create_queue.get(block=False)
                    new_worker.hostname, new_worker.w = create_worker_object(
                        concurrency=new_worker.concurrency,
                        flavor=new_worker.flavor,
                        region=new_worker.region,
                        batch=new_worker.batch,
                        prefetch=new_worker.prefetch,
                        db_session=session)
                    worker_create_process_waiting_queue.append(
                        new_worker
                    )
            except queue.Empty:
                pass
            while len(worker_create_process_waiting_queue)>0 \
                    and len(worker_create_process_queue)<WORKER_CREATE_CONCURRENCY:
                new_worker = worker_create_process_waiting_queue.pop(0)
                with app.app_context():
                    new_worker.db_session = Session(db.engine)
                # verifying that the object is still in db to prevent recreation
                if worker_exists(new_worker.w.worker_id, session):
                    log.warning(f'Launching creation process for worker {new_worker.hostname}.')
                    worker_create_process = PropagatingThread(
                        target = create_worker_process,
                        kwargs = new_worker.__dict__)
                    worker_create_process.start()
                    worker_create_process_queue.append((new_worker, worker_create_process))
                else:
                    log.warning(f'Not queuing {new_worker.hostname} for creation as it was deleted')
            for new_worker,worker_create_process in list(worker_create_process_queue):
                try:
                    if not worker_create_process.is_alive():
                        worker_create_process_queue.remove((new_worker, worker_create_process))
                        log.warning(f'Creation process over for worker {new_worker.hostname}.')
                except Exception as e:
                    log.exception(f'Creation failed: {e}')
                    worker_create_process_queue.remove((new_worker, worker_create_process))
                    

            



                
        except Exception:
            log.exception('An exception occured during server main loop:')
            while True:
                sleep(MAIN_THREAD_SLEEP)
                try:
                    log.warning('Trying to reconnect...')
                    with app.app_context():
                        session = Session(db.engine)
                    break
                except Exception:
                    pass
        sleep(MAIN_THREAD_SLEEP)


Thread(target=background).start()


def main():
    #app.run(debug=False)
    socketio.run(app)

if __name__ == "__main__":
    raise RuntimeError('Do not launch directly, launch with "FLASK=scitq.server flask run"')