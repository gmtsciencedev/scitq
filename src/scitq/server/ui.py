from flask import render_template, request, jsonify, current_app, Blueprint
from time import sleep
import logging as log
import json as json_module
from sqlalchemy import select, func, and_, delete, distinct, union, alias
from signal import SIGKILL, SIGQUIT, SIGTSTP, SIGCONT
from datetime import datetime

from ..util import package_version, tryupdate, to_dict, flat_list
from .db import db
from .config import IS_SQLITE, UI_OUTPUT_TRUNC, UI_MAX_DISPLAYED_ROW
from ..constants import SIGNAL_CLEAN, SIGNAL_RESTART
from .model import Worker, Signal, Job, Task, Execution, delete_batch
from .api import worker_dao



ui = Blueprint('ui', __name__, url_prefix='/ui')

package_version = package_version()
@ui.route('/')
def index(name=None):
    return render_template('ui.html', name=name, package_version=package_version)

@ui.route('/task/', methods=('GET', 'POST'))
def task():
    if request.method=='POST':
        sortby=request.form.get('sortby','task')
        batch_filter=request.form.get('batch_filter','-')
        worker_filter=request.form.get('worker_filter','-')
        status_filter=request.form.get('status_filter','all')
    else:
        sortby='task'
        batch_filter='-'
        worker_filter='-'
        status_filter='all'
    batch_list = flat_list(db.session.execute(
        select(distinct(alias(union(select(Task.batch),select(Worker.batch)),'batch').table_valued())).order_by('batch')
    ))
    worker_list = flat_list(db.session.query(
        distinct(Worker.name)
    ))
    
    #print('batch_list',repr(batch_list))
    return render_template('task.html',package_version=package_version,
                           sortby=sortby,
                           batch_filter=batch_filter,
                           worker_filter=worker_filter,
                           status_filter=status_filter,
                           batch_list=batch_list,
                           worker_list=worker_list)

@ui.route('/batch/')
def batch():
    return render_template('batch.html', package_version=package_version)



@ui.route('/get/')
def handle_get():
    json = request.args
    if 'delay' in json:
        sleep(int(json['delay']))
    if json['object']=='workers':
        log.info('sending workers')
        return jsonify({
            'workers':list([tryupdate(dict(row),'stats',json_module.loads,row.stats) for row in db.session.execute(
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
                    stats
                FROM worker
                ORDER BY worker.batch,worker.name''')]),
            'tasks_per_status': dict([row for row in db.session.execute(
                '''SELECT status,count(task_id) as count FROM task GROUP BY status'''
            )]) })

    elif json['object']=='tasks':
        sortby = json.get('sortby', None)
        status = json.get('status', None)
        worker = json.get('worker', None)
        batch = json.get('batch',None)

        log.warning(f"sending task ordered by {sortby} filtered by status {status} for worker {worker}")


        if sortby=='worker':
            sort_clause='ORDER BY worker.name, task.task_id DESC'
        elif sortby=='batch':
            sort_clause='ORDER BY task.batch, task.task_id DESC'
        else:
            sort_clause='ORDER BY task.task_id DESC'
        
        where_clauses = []

        if status is not None:
            where_clauses.append(f"task.status='{status}'")

        if worker is not None:
            where_clauses.append(f"worker.name='{worker}'")

        if batch is not None:
            where_clauses.append(f"task.batch='{batch}'")

        where_clause = f'''WHERE {' AND '.join(where_clauses)}''' if where_clauses else ''

        if IS_SQLITE:
            trunc_output=f'SUBSTR(execution.output,-{UI_OUTPUT_TRUNC},{UI_OUTPUT_TRUNC})'
            trunc_error=f'SUBSTR(execution.error,-{UI_OUTPUT_TRUNC},{UI_OUTPUT_TRUNC})'
        else:
            trunc_output=f'RIGHT(execution.output,{UI_OUTPUT_TRUNC})'
            trunc_error=f'RIGHT(execution.error,{UI_OUTPUT_TRUNC})'
        

        #task_list = list([list(map(lambda x : str(x) if type(x)==type(datetime.utcnow()) else x ,row)) for row in db.session.execute(
        task_list = list([dict(row) for row in db.session.execute(
        f'''SELECT
        task.task_id,
        task.name,
        worker.name as worker_name,
        task.batch,
        execution.creation_date,
        execution.modification_date,
        execution.execution_id,
        {trunc_output} as output,
        {trunc_error} as error,
        task.command,
        execution.worker_id,
        task.status
        FROM task 
        LEFT JOIN execution ON (task.task_id=execution.task_id AND latest)
        LEFT JOIN worker ON execution.worker_id=worker.worker_id 
        {where_clause}
        {sort_clause}
        LIMIT {UI_MAX_DISPLAYED_ROW}
        '''
        )])
        
        detailed_tasks = json.getlist('detailed_tasks[]')
        if detailed_tasks:
            log.warning(f"detailing tasks {detailed_tasks}")
            for detailed_task in db.session.execute(f"""
                SELECT execution_id,output,error FROM execution 
                WHERE execution_id IN ({','.join([str(eid) for eid in detailed_tasks])})"""):
                for task in task_list:
                    if task['execution_id']==detailed_task['execution_id']:
                        task['output']=detailed_task['output']
                        task['error']=detailed_task['error']
                        break

        batch_list = flat_list(db.session.execute(
            select(distinct(alias(union(select(Task.batch),select(Worker.batch)),'batch').table_valued())).order_by('batch')
        ))
        worker_list = flat_list(db.session.query(
            distinct(Worker.name)
        ))

        return jsonify({'tasks':task_list, 'batch_list':batch_list, 'worker_list':worker_list})
        
    elif json['object'] == 'batch':
        log.info('sending batch')
        if IS_SQLITE:
            duration_query='(JULIANDAY(e1.modification_date)-JULIANDAY(e1.creation_date))*24'
            worker_query='''SELECT batch,GROUP_CONCAT(name,',') as workers FROM worker GROUP BY batch ORDER BY name'''
        else:
            duration_query='EXTRACT ( EPOCH FROM (e1.modification_date-e1.creation_date)/3600 )'
            worker_query='''SELECT batch,STRING_AGG(name,',') as workers FROM (SELECT * FROM worker ORDER BY name) w GROUP BY batch'''
        batch_query=f'''SELECT * FROM (
    SELECT batch,status,COUNT(task_id) as count,MAX(duration) as max,MIN(duration) as min, AVG(duration) as avg FROM (
        SELECT {duration_query} as duration, e1.task_id, e1.status,task.batch FROM execution e1 JOIN task ON (
            task.task_id=e1.task_id AND e1.latest
        )
    ) AS e2 GROUP BY batch,status
    UNION	 
    SELECT batch,status, COUNT(task_id),NULL,NULL,NULL 
    FROM task WHERE task_id NOT IN (SELECT task_id FROM execution) GROUP BY batch,status
) AS b ORDER BY batch, status'''
        return jsonify({'batches':list([dict(row) for row in db.session.execute(batch_query)]),
                        'workers': list([dict(row) for row in db.session.execute(worker_query)])})

#@socketio.on('change_batch')
@ui.route('/change_batch')
def handle_change_batch():
    json = request.args
    Worker.query.filter(Worker.worker_id==json['worker_id']).update(
        {Worker.batch:json['batch_name'] or None})
    db.session.commit()
    return '"ok"'


#@socketio.on('concurrency_change')
@ui.route('/concurrency_change')
def handle_concurrency_change():
    json = request.args
    worker_id = json['id']
    change = json['change']
    log.info(f'changing concurrency for worker {worker_id}: {change}')
    if IS_SQLITE:
        log.info('Using sqlite SQL')
        Worker.query.filter(Worker.worker_id==worker_id).update(
            {Worker.concurrency: func.max(Worker.concurrency+change,0)})
    else:
        log.info('Using standard SQL')
        Worker.query.filter(Worker.worker_id==worker_id).update(
            {Worker.concurrency: func.greatest(Worker.concurrency+change,0)})
    db.session.commit()
    return '"ok"'

#@socketio.on('prefetch_change')
@ui.route('/prefetch_change')
def handle_prefetch_change():
    json = request.args
    worker_id = json['id']
    change = json['change']
    log.info(f'changing prefetch for worker {worker_id}: {change}')
    if IS_SQLITE:
        log.info('Using sqlite SQL')
        Worker.query.filter(Worker.worker_id==worker_id).update(
            {Worker.prefetch: func.max(Worker.prefetch+change,0)})
    else:
        log.info('Using standard SQL')
        Worker.query.filter(Worker.worker_id==worker_id).update(
            {Worker.prefetch: func.greatest(Worker.prefetch+change,0)})
    db.session.commit()
    return '"ok"'

@ui.route('/pause_unpause_worker')
def handle_pause_unpause_worker():
    json = request.args
    worker_id = json['id']
    status = json['status']
    Worker.query.filter(Worker.worker_id==worker_id).update({Worker.status:status})
    log.info(f'changing status for worker {worker_id}: {status}')
    db.session.commit()
    return '"ok"'


@ui.route('/clean_worker')
def handle_clean_worker():
    json = request.args
    worker_id = json['worker_id']
    db.session.add(Signal(execution_id=None, worker_id=worker_id, signal=SIGNAL_CLEAN))
    db.session.commit()
    log.info(f'sending clean signal for worker {worker_id}')
    return '"ok"'

@ui.route('/restart_worker')
def handle_restart_worker():
    json = request.args
    worker_id = json['worker_id']
    db.session.add(Signal(execution_id=None, worker_id=worker_id, signal=SIGNAL_RESTART))
    db.session.commit()
    log.info(f'sending restart signal for worker {worker_id}')
    return '"ok"'

#@socketio.on('create_worker')
@ui.route('/create_worker')
def handle_create_worker():
    json = request.args
    concurrency = int(json['concurrency'])
    flavor = json['flavor']
    if not flavor:
        return jsonify(error='Flavor must be specified')
        #return None
    region = json['region']
    provider = json['provider']
    if not region:
        return jsonify(error='Region must be specified')
        #return None
    batch = json['batch'] or None
    prefetch = int(json['prefetch'])
    number = int(json['number'])
    for _ in range(number):
        db.session.add(
            Job(target='', 
                action='worker_create', 
                args={
                    'concurrency': concurrency, 
                    'prefetch':prefetch,
                    'flavor':flavor,
                    'region':region,
                    'provider': provider,
                    'batch':batch
                }
            )
        )
    db.session.commit()
    return '"ok"'

#@socketio.on('batch_action')
@ui.route('/batch/action')
def handle_batch_action():
    """Gathering all the action dealing with batch like pause, break, stop, clear, go."""
    json = request.args
    if json['action'] in ['stop','break','pause','simple pause','pause only batch']:
        #Same function as in the API set all workers affected to this batch to running and can also interrupt the running tasks with signal 3 and 9
        name=json['name']
        for w in Worker.query.filter(Worker.batch==name):
                w.status = 'paused'
        if json['action']=='break':
            signal = SIGKILL
        elif json['action']=='stop':
            signal = SIGQUIT
        elif json['action']=='simple pause':
            signal = 0
        elif json['action']=='pause':
            #TODO: make a more efficient query
            for t in Task.query.filter(and_(
                        Task.batch==name,
                        Task.status.in_(['running','accepted']))):
                t.status = 'paused'
            signal = SIGTSTP
            db.session.commit()
        log.warning(f'Sending signal {signal} to executions for batch {name}')
        for e in db.session.scalars(select(Execution).join(Execution.task).where(
                                        Execution.status=='running',
                                        Task.batch==name)):
            log.warning(f'Sending signal {signal} to execution {e.execution_id}')
            db.session.add(Signal(e.execution_id, e.worker_id, signal ))
        db.session.commit()
        log.warning('result pause :Ok')
    elif json['action'] in ['go','simple go']: 
        #Same function as in the API (re)set all workers affected to this batch to running
        name=json['name']
        """(re)set all workers affected to this batch to running"""
        for w in Worker.query.filter(Worker.batch==name):
            w.status = 'running'
        if json['action']=='go':
            signal=SIGCONT
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
    elif json['action']=='clear':
        #Same function as in the API clear() Delete all tasks and executions and recruiters for this batch
        name=json['name']
        """Delete all tasks and executions for this batch"""
        delete_batch(name, session=db.session)
        log.warning(f'result clear batch {name}: Ok ')
    return '"ok"'

#@socketio.on('task_action')
@ui.route('/task/action')
def handle_task_action():
    """Gathering all the action dealing with task like break, stop, delete, modify, restart"""
    #The code essentially is from the API code with a few modifications
    json = request.args
    task=json['task_id']
    if json['action'] in ['break','stop','pause','resume']: 
        #A signal 3 or 9 is created and causes only the interruption of the task with id same structure as in the API 
        task=json['task_id']
        for t in Task.query.filter(Task.task_id==task):
            if json['action'] == 'break':
                type='break'
                signal = SIGKILL
            elif json['action'] == 'stop':
                signal = SIGQUIT
                type='stop'
            elif json['action'] == 'pause':
                signal = SIGTSTP
                type='pause'
                t.status='paused'
            elif json['action'] == 'resume':
                signal = SIGCONT
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
    elif json['action']=='delete': 
        #Delete the task in the data base
        for t in Task.query.filter(Task.task_id==task):
            db.session.delete(t)
        db.session.commit()
        log.warning('result delete: Ok')
    elif json['action']=='modify': 
        #Changing the command for a task in the data base and moving it in the task queue. It doesn't create a new task.
        now = datetime.utcnow()
        for t in Task.query.filter(Task.task_id==task):
            t.command =json["modification"]
            if t.status not in ['pending','assigned','accepted']:
                for e in t.executions:
                    if e.status=='running':
                        e.status='failed'
                        db.session.add(Signal(e.execution_id, e.worker_id, SIGKILL))
                t.status='pending' 
                t.status_date=now
                t.modification_date=now          
        db.session.commit()
        log.warning('result modify : Ok')
    elif json['action']=='restart': 
        #Relaunching the execution of a task.
        now = datetime.utcnow()
        for t in Task.query.filter(Task.task_id==task):
            t.status='pending'
            t.status_date=now
            t.modification_date=now  
        db.session.commit()
        log.warning('result restart : Ok')
    return '"ok"'

#@socketio.on('delete_worker') #Delete a worker.
@ui.route('/delete_worker')
def delete_worker():
    """Delete a worker in db"""
    json = request.args
    worker_dao.delete(json['worker_id'], session=db.session)
    return '"ok"'
    

#@socketio.on('jobs')
@ui.route('/jobs')
def handle_jobs():
    """Provide UI with job list"""
    return jsonify(jobs = [to_dict(job) for job in db.session.query(Job).order_by(Job.job_id.desc()).all()])

@ui.route('/delete_job')
def delete_job():
    """Delete a job in db"""
    json = request.args
    job = db.session.query(Job).get(json['job_id'])
    if job:
        db.session.delete(job)
        db.session.commit()
    else:
        log.warning(f"Job {json['job_id']} already deleted")
    return '"ok"'

@ui.route('/delete_jobs')
def delete_jobs():
    """Delete terminated jobs"""
    if db.session.execute(
            select(func.count()).select_from(Job).where(Job.status=='succeeded')
            ).scalar_one()>0:
        log.warning('Here')
        db.session.execute(delete(Job).where(Job.status=='succeeded'))
    elif db.session.execute(
            select(func.count()).select_from(Job).where(Job.status=='failed')
            ).scalar_one()>0:
        log.warning('There')
        db.session.execute(delete(Job).where(Job.status=='failed'))
    elif db.session.execute(
            select(func.count()).select_from(Job).where(Job.status=='pending')
            ).scalar_one()>0:
        db.session.execute(delete(Job).where(Job.status=='pending'))
    else:
        return '"nothing to do"'
    db.session.commit()
    return '"ok"'

@ui.route('/restart_job')
def restart_job():
    """Restart a job in db"""
    json = request.args
    job = db.session.query(Job).get(json['job_id'])
    if job:
        job.status = 'pending'
        job.retry = 0
        db.session.commit()
    else:
        log.warning(f"Job {json['job_id']} already deleted")
    return '"ok"'

#ns = api.namespace('live', description='Very basic API for the UI')

@ui.route('/ping')
def live_ping():
    """Simply return ok"""
    return '"ok"'