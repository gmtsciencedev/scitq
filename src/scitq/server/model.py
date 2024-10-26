from datetime import datetime
import json as json_module
from sqlalchemy import DDL, event, func, delete, select, or_, and_, tuple_
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy import func
import hashlib
import os

from .config import DEFAULT_BATCH, WORKER_DESTROY_RETRY, get_quotas, EVICTION_ACTION, EVICTION_COST_MARGIN, PREFERRED_REGIONS
from .db import db
from ..util import to_dict, validate_protofilter, protofilter_syntax, PROTOFILTER_SEPARATOR, is_like, has_tag
from ..constants import FLAVOR_DEFAULT_EVICTION, FLAVOR_DEFAULT_LIMIT, EXECUTION_STATUS, WORKER_STATUS
from ..fetch import list_content, info, FetchError, UnsupportedError

import logging as log

class ModelException(Exception):
    @property
    def message(self):
        return self.args[0]

class Task(db.Model):
    __tablename__ = "task"
    task_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String)
    command = db.Column(db.String, nullable=False)
    status = db.Column(db.String, nullable=False)
    creation_date = db.Column(db.DateTime, nullable=False)
    modification_date = db.Column(db.DateTime)
    batch = db.Column(db.String, nullable=False, default=DEFAULT_BATCH)
    input = db.Column(db.String, nullable=True)
    output = db.Column(db.String, nullable=True)
    container = db.Column(db.String, nullable=True)
    container_options = db.Column(db.String, nullable=True)
    resource = db.Column(db.String, nullable=True)
    retry = db.Column(db.Integer, nullable=False, default=0)
    status_date = db.Column(db.DateTime)
    download_timeout = db.Column(db.Integer, nullable=True)
    run_timeout = db.Column(db.Integer, nullable=True)
    use_cache = db.Column(db.Boolean, default=False)

    def __init__(self, command, name=None, status='pending', batch=None, 
                    input=None, output=None, container=None, 
                    container_options=None, resource=None,
                    download_timeout=None, run_timeout=None,
                    retry=None, use_cache=False):
        self.name = name
        self.command = command
        self.status = status
        self.creation_date = datetime.utcnow()
        self.modification_date = self.creation_date
        self.status_date = self.creation_date
        self.batch = batch if batch is not None else DEFAULT_BATCH
        if '/' in self.batch:
            raise ModelException(f'Cannot accept / in batch name, chose a proper batch name: {self.batch}')
        self.input = input
        self.output = output
        self.container = container
        self.container_options = container_options
        self.resource = resource
        self.retry = retry
        self.download_timeout = download_timeout
        self.run_timeout = run_timeout
        self.use_cache = use_cache


class Worker(db.Model):
    __tablename__ = "worker"
    worker_id = db.Column(db.Integer,primary_key=True)
    name = db.Column(db.String, nullable=False)
    hostname = db.Column(db.String)
    status = db.Column(db.String, nullable=False)
    concurrency = db.Column(db.Integer,nullable=False)
    prefetch = db.Column(db.Integer,default=0)
    load = db.Column(db.String)
    memory=db.Column(db.String)
    stats=db.Column(db.String)
    task_properties=db.Column(db.String, default=json_module.dumps({}))
    creation_date = db.Column(db.DateTime)
    modification_date = db.Column(db.DateTime)
    last_contact_date = db.Column(db.DateTime)
    batch = db.Column(db.String, nullable=False,default=DEFAULT_BATCH)
    permanent = db.Column(db.Boolean, default=True)
    flavor = db.Column(db.String, nullable=True)
    region = db.Column(db.String, nullable=True)
    provider = db.Column(db.String, nullable=True)
    ipv4 = db.Column(db.String, nullable=True)
    ipv6 = db.Column(db.String, nullable=True)
    ansible_host = db.Column(db.String, nullable=True)
    ansible_group = db.Column(db.String, nullable=True)
    ansible_active = db.Column(db.Boolean, default=False)
    signals = db.relationship("Signal", cascade="all,delete")

    def __init__(self, name, concurrency, prefetch=0, hostname=None, 
                status='paused', batch=None, flavor=None, region=None, provider=None, permanent=True):
        self.name = name
        self.concurrency = concurrency
        self.prefetch = prefetch
        self.status = status
        self.creation_date = datetime.utcnow()
        self.modification_date = self.creation_date
        self.hostname = hostname
        self.batch = batch
        self.permanent = permanent
        self.region = region
        self.flavor = flavor
        self.provider = provider
     

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
        backref=db.backref('executions',
                         uselist=True,
                         cascade='delete,all'),
                         order_by='Execution.creation_date')
    status = db.Column(db.String, nullable=False)
    creation_date = db.Column(db.DateTime, nullable=False)
    modification_date = db.Column(db.DateTime)
    output = db.Column(db.Text)
    error = db.Column(db.Text)
    return_code = db.Column(db.Integer)
    pid = db.Column(db.String)
    output_files = db.Column(db.String, nullable=True)
    command = db.Column(db.String, nullable=True)
    container = db.Column(db.String, nullable=True)
    container_options = db.Column(db.String, nullable=True)
    input = db.Column(db.String, nullable=True)
    output_folder = db.Column(db.String, nullable=True)
    resource = db.Column(db.String, nullable=True)
    input_hash = db.Column(db.String, index=True, nullable=True)
    output_hash = db.Column(db.String, nullable=True)
    latest = db.Column(db.Boolean, default=True)


    def __init__(self, worker_id, task_id, status='pending', pid=None, 
                    return_code=None, command=None, container=None, container_options=None,
                    input=None, output_folder=None, resource=None):
        self.worker_id = worker_id
        self.task_id = task_id
        self.status = status
        self.pid = pid
        self.return_code = return_code
        self.creation_date = datetime.utcnow()
        self.modification_date = self.creation_date
        self.command = command
        self.container = container
        self.container_options = container_options
        self.input = input
        self.output_folder = output_folder
        self.resource = resource

    def get_input_hash(self):
        """Return an MD5 that guarrantees that this is a unique Experience"""
        h = hashlib.md5(f"""command:{self.command}
container:{self.container}
container_options:{self.container_options}
""".encode("utf-8"))
        if self.input:
            inputs = []
            for data in self.input.split(' '):
                try:
                    action=''
                    if '|' in data:
                        data,action=data.split('|')
                        action=f'|{action}'
                    l=list([f"{item.rel_name}:{item.md5}{action}" for item in list_content(data, md5=True)])
                    inputs.extend(l)
                except UnsupportedError:
                    inputs.append(data+action)
            h.update(f'input:{",".join(inputs)}\n'.encode('utf-8'))
        if self.resource:
            resources = []
            for data in self.resource.split(' '):
                try:
                    action=''
                    if '|' in data:
                        data,action=data.split('|')
                        action=f'|{action}'
                    l=list([f"{item.rel_name}:{item.md5}{action}" for item in list_content(data, md5=True)])
                    resources.extend(l)
                except UnsupportedError:
                    resources.append(data+action)
            h.update(f'resource:{",".join(resources)}'.encode('utf-8'))
        return h.hexdigest()

    def get_output_hash(self):
        """Return an MD5 that guarrantees that the output of the step is untouched"""
        output_files=[]
        try: 
            if self.output_files:
                for of in self.output_files.split(' '):
                    of_info=info(os.path.join(self.output_folder, of), md5=True)
                    md5=None if of_info is None else of_info.md5
                    output_files.append(f'{of}:{md5}')
            h = hashlib.md5(f'output:{",".join(output_files)}'.encode('utf-8'))
            return h.hexdigest()
        except FetchError:
            return None
    
    def check_output(self):
        """Return True if output_hash is unchanged"""
        if self.output_hash is None:
            return False
        else:
            return self.output_hash==self.get_output_hash()
 
trigger_latest_sqlite = DDL("""
        CREATE TRIGGER is_latest BEFORE INSERT ON execution FOR EACH ROW 
        BEGIN
            UPDATE execution SET latest=false WHERE latest AND task_id=NEW.task_id;
        END
        """)

func_latest_postgres = DDL("""
        CREATE OR REPLACE FUNCTION render_obsolete() 
        RETURNS TRIGGER
        LANGUAGE plpgsql
        AS $$
        BEGIN
            UPDATE execution 
            SET latest=false
            WHERE task_id=NEW.task_id
            AND latest;
            RETURN NEW;
        END;
        $$
        """)

trigger_latest_postgres = DDL("""
CREATE TRIGGER is_latest BEFORE INSERT ON execution FOR EACH ROW EXECUTE PROCEDURE render_obsolete()
""")

event.listen(
    Execution.__table__, 'after_create',
    trigger_latest_sqlite.execute_if(dialect="sqlite")    
)
event.listen(
    Execution.__table__, 'after_create',
    func_latest_postgres.execute_if(dialect="postgresql")    
)
event.listen(
    Execution.__table__, 'after_create',
    trigger_latest_postgres.execute_if(dialect="postgresql")    
)

def execution_update_status(execution, session, status, commit=True):
    """Change status of an execution, impacting on task if required"""
    if status not in EXECUTION_STATUS:
        raise ModelException(f"Status {status} is not possible (only {' '.join(EXECUTION_STATUS)})")
    task=execution.task
    now = datetime.utcnow()
    if execution.status=='pending':
        if status=='running':
            task.status = 'running'
            task.modification_date = now
            task.status_date = now
        elif status=='accepted':
            task.status = 'accepted'
            task.modification_date = now
            task.status_date = now
        elif status in ['refused','failed']:
            task.status = 'pending'
            task.modification_date = now
            task.status_date = now
        elif status=='succeeded':
            task.status = 'succeeded'
            task.modification_date = now
            task.status_date = now
        else:
            raise ModelException(f"An execution cannot change status from pending to {status}")
    elif execution.status=='accepted':
        if status=='refused':
            task.stats = 'pending'
            task.modification_date = now
            task.status_date = now
        elif status in ['running','failed','succeeded','pending']:
            task.status = status
            task.modification_date = now
            task.status_date = now
        else:
            log.exception(f"An execution cannot change status from accepted to {status}")
            raise ModelException(f"An execution cannot change status from accepted to {status}")
    elif execution.status=='running':
        if status in ['succeeded', 'failed']:
            task.status=status
            task.modification_date = now
            task.status_date = now
            if status=='failed' and task.retry>0:
                log.warning(f'Failure of execution {execution.execution_id} trigger task {task.task_id} retry ({task.retry-1} retries left)')
                task.retry -= 1
                task.status = 'pending'
        else:
            log.exception(f"An execution cannot change status from running to {status}")
            raise ModelException(f"An execution cannot change status from running to {status}")
    else:
        raise ModelException(f"An execution cannot change status from {execution.status} (only from pending, running or accepted)")
    execution.status=status
    if commit:
        session.commit()


class Signal(db.Model):
    __tablename__ = "signal"
    #execution_id = db.Column(db.Integer, db.ForeignKey("execution.execution_id"), primary_key=True, nullable=True)
    signal_id = db.Column(db.Integer, primary_key=True)
    execution_id = db.Column(db.Integer, db.ForeignKey("execution.execution_id"), nullable=True)
    worker_id = db.Column(db.Integer, db.ForeignKey("worker.worker_id"))
    signal = db.Column(db.Integer, nullable=False)    
    execution = db.relationship(
        Execution,
        backref=db.backref('signals',
                            uselist=True,
                            cascade='delete,all'))

    def __init__(self, execution_id, worker_id, signal):
        self.execution_id = execution_id
        self.worker_id = worker_id
        self.signal = signal


class Job(db.Model):
    __tablename__ = "job"
    job_id = db.Column(db.Integer, primary_key=True)
    target = db.Column(db.String)
    action = db.Column(db.String)
    args = db.Column(db.JSON, default={})
    retry =  db.Column(db.Integer, default = 0)
    status = db.Column(db.String, default = 'pending')
    log = db.Column(db.Text, nullable=True)
    creation_date = db.Column(db.DateTime, server_default=func.now())
    modification_date = db.Column(db.DateTime, onupdate=func.now())
    progression = db.Column(db.SmallInteger)
    

    def __init__(self, target, action, args={}, retry=0):
        self.target = target
        self.action = action
        self.args = args
        self.retry = retry

def worker_delete(worker, session, is_destroyed=False, commit=True):
    """Handle worker delete, take care of launching the destroy job if needed."""
    if not worker.permanent and not is_destroyed:
        create_worker_destroy_job(worker, session)
        return worker
    else:
        for execution in session.query(Execution).filter(Execution.worker_id==worker.worker_id, Execution.status=='running'):
            execution_update_status(execution, session, 'failed')
        for execution in session.query(Execution).filter(Execution.worker_id==worker.worker_id, Execution.status.in_(['pending','accepted'])):
            execution_update_status(execution, session, 'refused')
        session.delete(worker)
        session.commit()
        return worker

def create_worker_destroy_job(worker, session, commit=True):
    job = Job(target = worker.name,
        action='worker_destroy',
        args=to_dict(worker),
        retry=WORKER_DESTROY_RETRY)
    session.add(job)
    if commit:
        session.commit()

def create_worker_create_job(concurrency, prefetch, batch, flavor, region, provider, session, number=1, commit=True):
    for _ in range(number):
        session.add(
            Job(target='', 
                action='worker_create', 
                args={
                    'concurrency': concurrency, 
                    'prefetch': prefetch,
                    'flavor': flavor,
                    'region':region,
                    'provider':provider,
                    'batch':batch
                }
            )
        )
    if commit:
        session.commit()

def worker_handle_eviction(worker, session, commit=True):
    "Handle worker eviction"
    # Here we want to make an exception: Execution failure on worker eviction should be 
    # immediately retried whatever the retry status
    # NB could not make the SQLALchemy ORM work in that simple case... NotImplementedError: This backend does not support multiple-table criteria within UPDATE
    session.execute(f"UPDATE task SET status='pending' WHERE task_id IN (SELECT task_id FROM execution WHERE worker_id={worker.worker_id} AND status IN ('running','pending','accepted','assigned'))")
    session.execute(f"UPDATE execution SET status='failed' WHERE worker_id={worker.worker_id} AND status='running'")
    session.execute(f"UPDATE execution SET status='refused' WHERE worker_id={worker.worker_id} AND status IN ('pending','accepted')")
    
    if commit:
        session.commit()
    if EVICTION_ACTION in ['delete', 'replace']:
        create_worker_destroy_job(worker, session, commit=commit)
    if EVICTION_ACTION=='replace':
        pending_tasks=session.query(func.count(Task.task_id)).filter(Task.batch==worker.batch, Task.status=='pending').scalar()
        if pending_tasks > 0:
            flavor = worker.flavor_detail
            try:
                cost = session.query(FlavorMetrics.cost).filter(FlavorMetrics.flavor_name==flavor.name, 
                                                                FlavorMetrics.provider==flavor.provider,
                                                                FlavorMetrics.region_name==worker.region).one()
                cost = cost[0]
            except NoResultFound:
                cost = 0
            for new_flavor in find_flavor(session, 
                                        min_cpu=flavor.cpu, 
                                        min_ram=flavor.ram, 
                                        min_disk=flavor.disk, 
                                        limit=1000):
                if new_flavor["available"]==0:
                    continue
                if cost==0 and new_flavor['cost']==0:
                    break
                elif new_flavor['cost']/cost<EVICTION_COST_MARGIN:
                    break
            else:
                log.warning(f'Could not find any suitable replacement for flavor {flavor.name}')
                return None
            log.warning(f'Found a replacement flavor for {flavor.name}: {new_flavor["name"]} in {new_flavor["provider"]}:{new_flavor["region"]}')
            create_worker_create_job(concurrency=worker.concurrency, prefetch=worker.prefetch,
                                    batch=worker.batch, flavor=new_flavor["name"], region=new_flavor["region"],
                                    provider=new_flavor["provider"], session=session, commit=commit)
        




class Requirement(db.Model):
    __tablename__="requirement"
    requirement_id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey("task.task_id"), nullable=False)
    task = db.relationship(
        Task,
        foreign_keys=[task_id],
        backref=db.backref('requirements',
                         uselist=True,
                         cascade='delete,all'))
    other_task_id = db.Column(db.Integer, db.ForeignKey("task.task_id"), nullable=False)
    other_task = db.relationship(
        Task,
        foreign_keys=[other_task_id],
        backref=db.backref('required_in',
                         uselist=True,
                         cascade='delete,all'))

    def __init__(self, task_id, other_task_id):
        self.task_id=task_id
        self.other_task_id=other_task_id    
    
class Recruiter(db.Model):
    __tablename__="recruiter"
    batch = db.Column(db.String, default=DEFAULT_BATCH, nullable=False, primary_key=True)
    rank = db.Column(db.Integer, nullable=False, primary_key=True)
    tasks_per_worker = db.Column(db.Integer, nullable=False)
    worker_flavor = db.Column(db.String, nullable=False)
    worker_region = db.Column(db.String, nullable=True)
    worker_provider = db.Column(db.String, nullable=True)
    worker_concurrency = db.Column(db.Integer, nullable=False)
    worker_prefetch = db.Column(db.Integer, nullable=False, default=0)
    minimum_tasks = db.Column(db.Integer, nullable=True)
    maximum_workers = db.Column(db.Integer, nullable=True)

    def __init__(self, batch, rank, tasks_per_worker, 
                 worker_flavor, worker_concurrency,
                 worker_region = None, worker_provider = None, 
                 worker_prefetch = 0,
                 minimum_tasks=None, maximum_workers=None):
        self.batch = batch
        self.rank = rank
        self.tasks_per_worker = tasks_per_worker
        validate_protofilter(worker_flavor)
        self.worker_flavor = worker_flavor
        self.worker_region = worker_region
        self.worker_provider = worker_provider
        self.worker_concurrency = worker_concurrency
        self.worker_prefetch = worker_prefetch
        self.minimum_tasks = minimum_tasks
        self.maximum_workers = maximum_workers

    def match_flavor(self, worker, session):
        """A function that says if protofilters (which may appear as auto:... in Recruiter.worker_flavor) validate a worker.flavor"""
        if self.worker_flavor.startswith('auto'):
            if PROTOFILTER_SEPARATOR in self.worker_flavor:
                if worker.flavor_detail is None:
                    return False
                flavor_detail=worker.flavor_detail 
                env={'cpu':flavor_detail.cpu, 'ram':flavor_detail.ram, 'disk':flavor_detail.disk,'tags':flavor_detail.tags, 
                     'gpumem':flavor_detail.gpumem, 'region':worker.region,'provider':worker.provider}
                if 'cost' in self.worker_flavor or 'eviction' in self.worker_flavor:
                    try:
                        metrics = session.query(FlavorMetrics).filter(FlavorMetrics.flavor_name==worker.flavor,
                                                                    FlavorMetrics.provider==worker.provider,
                                                                    FlavorMetrics.region_name==worker.region).one()
                        env['cost']=metrics.cost
                        env['eviction']=metrics.eviction
                    except NoResultFound:
                        return False
                result = True
                for protofilter in self.worker_flavor.split(PROTOFILTER_SEPARATOR):
                    protofilter_match = protofilter_syntax.match(protofilter)
                    if protofilter_match:
                        protofilter_match = protofilter_match.groupdict()
                        variable = protofilter_match['item']
                        comp = protofilter_match['comparator']
                        value = protofilter_match['value']
                        if value[0] not in '0123456789.':
                            # value is a string
                            value=repr(value)
                        if comp=='~':
                            env['is_like']=is_like
                            eval_protofilter = f"is_like({variable},{value})"
                        elif comp=='#':
                            env['has_tag']=has_tag
                            eval_protofilter = f"has_tag({variable},{value})"
                        elif comp=='!~':
                            env['is_like']=is_like
                            eval_protofilter = f"not(is_like({variable},{value}))"
                        elif comp=='!#':
                            env['has_tag']=has_tag
                            eval_protofilter = f"not(has_tag({variable},{value}))"
                        else:
                            eval_protofilter = f"{variable}{comp}{value}"
                        try:
                            result = result and eval(eval_protofilter,env)
                        except Exception as e:
                            log.exception(f'Could not evaluate protofilter {protofilter} (compiled as {eval_protofilter}), eval to False')
                            return False
                return result
        else:
            return self.worker_flavor==worker.flavor
        
    # NB Session.merge() seems the way to go with this object
    # cf https://docs.sqlalchemy.org/en/14/orm/session_api.html#sqlalchemy.orm.Session.merge

def delete_batch(name, session, commit=True):
    """Delete a batch (all tasks, executions and recruiters associated to that batch), either in API context or in UI context"""
    session.execute(delete(Requirement).where(or_(
        Requirement.task_id.in_(select(Task.task_id).where(Task.batch==name)),
        Requirement.other_task_id.in_(select(Task.task_id).where(Task.batch==name)))),
        execution_options={'synchronize_session':False})
    session.execute(delete(Signal).where(Signal.execution_id.in_(
        select(Execution.execution_id).where(Execution.task_id.in_(
            select(Task.task_id).where(Task.batch==name))
        ))),
        execution_options={'synchronize_session':False})
    session.execute(delete(Execution).where(Execution.task_id.in_(
             select(Task.task_id).where(Task.batch==name))),
             execution_options={'synchronize_session':False})    
    session.execute(delete(Task).where(Task.batch==name),
             execution_options={'synchronize_session':False})
    session.execute(delete(Recruiter).where(Recruiter.batch==name),
             execution_options={'synchronize_session':False})
    if commit:
        session.commit()


class Region(db.Model):
    __tablename__="region"
    name = db.Column(db.String, nullable=False, primary_key=True)
    provider = db.Column(db.String, nullable=False, primary_key=True)
    
class Flavor(db.Model):
    __tablename__="flavor"
    name = db.Column(db.String, nullable=False, primary_key=True)
    provider = db.Column(db.String, nullable=False, primary_key=True)
    cpu = db.Column(db.Integer, nullable=False)
    ram = db.Column(db.Float, nullable=False)
    disk = db.Column(db.Float, nullable=False)
    bandwidth = db.Column(db.Float, nullable=True)
    gpu = db.Column(db.String, nullable=True)
    gpumem = db.Column(db.Float, nullable=True)
    tags = db.Column(db.String, nullable=True)
    workers = db.relationship('Worker', 
            primaryjoin=and_(name==Worker.flavor, provider==Worker.provider),
            foreign_keys=[Worker.flavor,Worker.provider],
            viewonly=True,
            backref='flavor_detail', 
            lazy=True)

class FlavorMetrics(db.Model):
    __tablename__='flavormetrics'
    flavor_name = db.Column(db.String, nullable=False, primary_key=True)
    provider = db.Column(db.String, nullable=False, primary_key=True)
    region_name = db.Column(db.String, nullable=False, primary_key=True)
    cost = db.Column(db.Float, nullable=False)
    eviction = db.Column(db.Integer, nullable=True)
    flavor = db.relationship('Flavor', 
            primaryjoin=and_(flavor_name==Flavor.name, provider==Flavor.provider),
            foreign_keys=[Flavor.name, Flavor.provider],
            viewonly=True,
            backref='metrics', 
            lazy=True)
    region = db.relationship('Region', 
            primaryjoin=and_(region_name==Region.name, provider==Flavor.provider), 
            foreign_keys=[Region.name, Region.provider],
            viewonly=True,
            backref='metrics', 
            lazy=True)

def find_remaining_quotas(session):
    """Return a dictionnary of (provider,region):cpus where cpus is the number of CPUs still available because of the quota"""
    quotas = get_quotas()
    if quotas:
        for provider,region,cpus in session.query(Worker.provider, Worker.region, func.sum(Flavor.cpu))\
                .select_from(Worker).join(Flavor,and_(Worker.flavor==Flavor.name,Worker.provider==Flavor.provider))\
                .group_by(Worker.provider, Worker.region):
            if (provider,region) in quotas:
                quotas[(provider,region)]-=cpus
        create_jobs=list(map(lambda x: x[0],session.query(Job.args).select_from(Job).filter(Job.action=='worker_create')))
        if create_jobs:
            flavors=[]
            for job_args in create_jobs:
                if (job_args['flavor'],job_args['provider']) not in flavors:
                    flavors.append((job_args['flavor'],job_args['provider']))
            flavors_cpu = { (name, provider):cpu for name, provider, cpu in
                session.query(Flavor.name, Flavor.provider, Flavor.cpu).select_from(Flavor).filter(
                    tuple_(Flavor.name, Flavor.provider).in_(flavors))
            }
            for job_args in create_jobs:
                if (job_args['provider'],job_args['region']) in quotas:
                    quotas[(job_args['provider'],job_args['region'])]-=flavors_cpu.get((job_args['flavor'],job_args['provider']),0)
    return quotas    

def find_flavor(session, protofilters='', min_cpu=None, min_ram=None, min_disk=None, 
                max_eviction=FLAVOR_DEFAULT_EVICTION, 
                limit=FLAVOR_DEFAULT_LIMIT, provider=None, region=None, flavor=None):
    """Return a list of Flavor fulfilling specific conditions

    protofilters should be a string of PROTOFILTER_SEPARATOR (e.g. :) separated strings passing validate_protofilter() function
    """
    # WATCH OUT When modifying this function, Recruiter.match_flavor() function (used for recycling) should be updated too
    filters = []
    order_by = (FlavorMetrics.cost,)
    if max_eviction is not None and not (protofilters and 'eviction' in protofilters):
        filters.append(FlavorMetrics.eviction<=max_eviction)
    if not (protofilters and 'tags' in protofilters):
        filters.append(~Flavor.tags.like('%M%'))
    if min_cpu is not None:
        filters.append(Flavor.cpu>=min_cpu)
    if min_ram is not None:
        filters.append(Flavor.ram>=min_ram)
    if min_disk is not None:
        filters.append(Flavor.disk>=min_disk)
    if provider is not None:
        filters.append(Flavor.provider==provider)
        if provider in PREFERRED_REGIONS and PREFERRED_REGIONS[provider]:
            order_by = (FlavorMetrics.region_name.like(PREFERRED_REGIONS[provider])).desc(),*order_by
    if region is not None:
        filters.append(FlavorMetrics.region_name==region)
    if flavor is not None:
        filters.append(Flavor.name.like(flavor))
    if protofilters:
        for protofilter_string in protofilters.split(PROTOFILTER_SEPARATOR):
            protofilter = protofilter_syntax.match(protofilter_string)
            if protofilter:
                protofilter=protofilter.groupdict()
                protofilter_item = getattr(FlavorMetrics, 'region_name' if protofilter['item']=='region' else protofilter['item']) \
                    if protofilter['item'] in ['region','cost','eviction'] else \
                    getattr(Flavor, protofilter['item'])
                comp = protofilter['comparator']
                if comp=='==':
                    filters.append(protofilter_item==protofilter['value'])
                elif comp=='!=':
                    filters.append(protofilter_item!=protofilter['value'])
                elif comp=='>':
                    filters.append(protofilter_item>protofilter['value'])
                elif comp=='<':
                    filters.append(protofilter_item<protofilter['value'])
                elif comp=='>=':
                    filters.append(protofilter_item>=protofilter['value'])
                elif comp=='<=':
                    filters.append(protofilter_item<=protofilter['value'])
                elif comp=='~':
                    filters.append(protofilter_item.like(protofilter['value']))
                elif comp=='!~':
                    filters.append(~protofilter_item.like(protofilter['value']))
                elif comp=='#':
                    for letter in protofilter['value']:
                        filters.append(protofilter_item.like(f'%{letter}%'))
                elif comp=='!#':
                    for letter in protofilter['value']:
                        filters.append(~protofilter_item.like(f'%{letter}%'))
            else:
                log.warning(f'Unknown protofilter {protofilter_string}')
    #return session.query(Flavor,FlavorMetrics
    fields = ['name','provider','region','cpu','ram','tags','gpu','gpumem','disk','cost','eviction']
    flavors = [dict(zip(fields, object)) for object in session.query(
                  Flavor.name, Flavor.provider, FlavorMetrics.region_name, 
                  Flavor.cpu, Flavor.ram, Flavor.tags, Flavor.gpu, Flavor.gpumem, 
                  Flavor.disk, FlavorMetrics.cost, FlavorMetrics.eviction      
            ).select_from(FlavorMetrics).join(FlavorMetrics.flavor)\
                .filter(*filters)\
                .order_by(*order_by).limit(limit)]
    quotas = find_remaining_quotas(session)
    for flavor in flavors:
        if (flavor['provider'], flavor['region']) in quotas:
            flavor['available']=quotas[(flavor['provider'], flavor['region'])]//flavor['cpu']
        else:
            flavor['available']=None
    return flavors

class FlavorStats(db.Model):
    __tablename__='flavorstats'
    flavor_name = db.Column(db.String, nullable=False, primary_key=True)
    provider = db.Column(db.String, nullable=False, primary_key=True)
    region_name = db.Column(db.String, nullable=False, primary_key=True)
    rank = db.Column(db.Integer, nullable=False, primary_key=True)
    failure_rate = db.Column(db.Float, default=0)
    eviction_rate = db.Column(db.Float, default=0)
    event_number = db.Column(db.Integer, default=0)
    flavor = db.relationship('Flavor', 
            primaryjoin=and_(flavor_name==Flavor.name, provider==Flavor.provider),
            foreign_keys=[Flavor.name, Flavor.provider],
            viewonly=True,
            backref='stats', 
            lazy=True)
    region = db.relationship('Region', 
            primaryjoin=and_(region_name==Region.name, provider==Flavor.provider), 
            foreign_keys=[Region.name, Region.provider],
            viewonly=True,
            backref='stats', 
            lazy=True)

    def deploy_success(self):
        self.failure_rate = self.failure_rate * self.event_number / (self.event_number + 1)
        self.event_number+=1

    def deploy_failure(self):
        self.failure_rate = (self.failure_rate * self.event_number + 1) / (self.event_number + 1)
        self.event_number+=1

    def eviction_event(self):
        self.eviction_rate = (self.eviction_rate * (self.event_number-1) + 1) / self.event_number

    def destroy_success(self):
        self.eviction_rate = (self.eviction_rate * (self.event_number-1) ) / self.event_number
