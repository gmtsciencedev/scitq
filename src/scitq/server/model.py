from datetime import datetime
import json as json_module
from sqlalchemy import DDL, event, func, delete, select, or_, and_
from sqlalchemy import func

from .config import DEFAULT_BATCH, WORKER_DESTROY_RETRY, get_quotas
from .db import db
from ..util import to_dict
from ..constants import FLAVOR_DEFAULT_EVICTION, FLAVOR_DEFAULT_LIMIT

class ModelException(Exception):
    pass

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

    def __init__(self, command, name=None, status='pending', batch=None, 
                    input=None, output=None, container=None, 
                    container_options=None, resource=None,
                    download_timeout=None, run_timeout=None,
                    retry=None):
        self.name = name
        self.command = command
        self.status = status
        self.creation_date = datetime.utcnow()
        self.modification_date = self.creation_date
        self.status_date = self.creation_date
        self.batch = batch
        if '/' in batch:
            raise ModelException(f'Cannot accept / in batch name, chose a proper batch name: {batch}')
        self.input = input
        self.output = output
        self.container = container
        self.container_options = container_options
        self.resource = resource
        self.retry = retry
        self.download_timeout = download_timeout
        self.run_timeout = run_timeout


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
    latest = db.Column(db.Boolean, default=True)
    

    def __init__(self, worker_id, task_id, status='pending', pid=None, 
                    return_code=None, command=None):
        self.worker_id = worker_id
        self.task_id = task_id
        self.status = status
        self.pid = pid
        self.return_code = return_code
        self.creation_date = datetime.utcnow()
        self.modification_date = self.creation_date
        self.command = command

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

class Signal(db.Model):
    __tablename__ = "signal"
    #execution_id = db.Column(db.Integer, db.ForeignKey("execution.execution_id"), primary_key=True, nullable=True)
    signal_id = db.Column(db.Integer, primary_key=True)
    execution_id = db.Column(db.Integer, db.ForeignKey("execution.execution_id"), nullable=True)
    worker_id = db.Column(db.Integer, db.ForeignKey("worker.worker_id"))
    signal = db.Column(db.Integer, nullable=False)    

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
    

    def __init__(self, target, action, args={}, retry=0):
        self.target = target
        self.action = action
        self.args = args
        self.retry = retry


def create_worker_destroy_job(worker, session, commit=True):
    job = Job(target = worker.name,
        action='worker_destroy',
        args=to_dict(worker),
        retry=WORKER_DESTROY_RETRY)
    session.add(job)
    if commit:
        session.commit()

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
        self.worker_flavor = worker_flavor
        self.worker_region = worker_region
        self.worker_provider = worker_provider
        self.worker_concurrency = worker_concurrency
        self.worker_prefetch = worker_prefetch
        self.minimum_tasks = minimum_tasks
        self.maximum_workers = maximum_workers
        
    
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
    ram = db.Column(db.Integer, nullable=False)
    disk = db.Column(db.Integer, nullable=False)
    bandwidth = db.Column(db.Integer, nullable=True)
    gpu = db.Column(db.String, nullable=True)
    gpumem = db.Column(db.Integer, nullable=True)
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
    cost = db.Column(db.Integer, nullable=False)
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
    return quotas    

def find_flavor(session, min_cpu=0, min_ram=0, min_disk=0, max_eviction=FLAVOR_DEFAULT_EVICTION, 
                limit=FLAVOR_DEFAULT_LIMIT, provider=None, region=None):
    """Return a list of Flavor fulfilling specific conditions"""
    filters = [Flavor.cpu>=min_cpu, Flavor.ram>=min_ram, Flavor.disk>=min_disk, FlavorMetrics.eviction<=max_eviction]
    if provider is not None:
        filters.append(Flavor.provider==provider)
    if region is not None:
        filters.append(FlavorMetrics.region==region)
    #return session.query(Flavor,FlavorMetrics
    fields = ['name','provider','region','cpu','ram','tags','gpu','gpumem','disk','cost','eviction']
    flavors = [dict(zip(fields, object)) for object in session.query(
                  Flavor.name, Flavor.provider, FlavorMetrics.region_name, 
                  Flavor.cpu, Flavor.ram, Flavor.tags, Flavor.gpu, Flavor.gpumem, 
                  Flavor.disk, FlavorMetrics.cost, FlavorMetrics.eviction      
            ).select_from(FlavorMetrics).join(FlavorMetrics.flavor)\
                .filter(and_(*filters))\
                .order_by(FlavorMetrics.cost).limit(limit)]
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
