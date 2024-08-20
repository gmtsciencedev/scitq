# scitq model and API

## scitq model

scitq is base on a simple database model. At the heart of scitq is the notion of:

- task 
- and worker

and without surprise, you'll find they are the two main tables of the database.

![schema](img/relationships.real.large.svg)

The schema include also three other tables:

- signal: a simple object which is only used to send signal to tasks (like the pause, the stop or the kill signal),
- execution: this is an important object: task can be executed several times and each execution may succeed or fail and have different outputs. Also an execution occurs on a specific worker,
- requirement: a simple task association table to implement dependencies between task, a notion at the heart of scitq.worklow, see below.

Since v1.0rc10, a new table, job, has been added to follow internal tasks (like worker creation and destruction):

![schema_job](img/job.1degree.png)

Since v1.2, a new table, recruiter, has been added to allow dynamic worker allocation for tasks (new deployments and recycling of workers). This component is also used by scitq.workflow

![schema_recruiter](img/recruiter.1degree.png)


Execution are not accessible simply using the [GUI](gui.md) or the [command line utility](manage.md). That is because in the vast majority of cases, the only execution that matters is the last. If a task failed, was re-excuted and succeeded in the second execution, why it failed the first time is now of lesser interest. However it is still in the database and we will learn here how to access that.

A direct interaction with the database must be used with caution since of course you could do anything. However there are specific cases (notably massive update of commands) where it may be extremely efficient. These are discussed in [Using sql directly](troubleshoot.md#using-sql-directly) chapter of troubleshoot.


## API

The API is a full REST API (operated using the excellent [Flask RESTX](https://github.com/python-restx/flask-restx) package), and it is fully exposed on `http://<your scitq server>:5000/` :

![API home](img/api1.png)

If you deploy any tab you'll be able to see the API details, for instance if you deploy the task tab, you will see the different REST verbs available:

![Task API](img/api-task1.png)

And for instance, you can see what getting the task list will look like:

![Task API list](img/api-task2.png)

And now for something usefull we can list the different executions:

![Execution API](img/api-execution.png)

Note that you have a swagger.json link at the top which can help you create a client for the API. However if you plan to create a Python client, do not bother with that there is one ready made for you, and it is the next and last topic of the documentation.


## scitq client (scitq.lib)

### Basic usage

In the following example, we connect locally to the server (the address is thus '127.0.0.1') but scitq.lib is a REST client so it can work remotely provided the network access is granted (see [security](install.md#security)):
```python
from scitq.lib import Server
from pprint import pprint

s = Server('127.0.0.1')
pprint(s.workers())
```

```python
[{'batch': 'Default',
  'concurrency': 1,
  'creation_date': datetime.datetime(2023, 4, 4, 7, 23, 52, 920295),
  'hostname': 'bioit',
  'idle_callback': None,
  'last_contact_date': datetime.datetime(2023, 5, 16, 20, 6, 35, 62751),
  'load': '0.1↓ / 0.0',
  'memory': 4.0,
  'modification_date': datetime.datetime(2023, 5, 16, 19, 36, 39, 770733),
  'name': 'bioit',
  'prefetch': 0,
  'stats': '{"load": "0.2 0.1 0.1", "disk": {"speed": "0.0/0.02 Mb/s", '
           '"usage": ["/:52", "/home:64", "/var/lib/docker:68", "/data:89", '
           '"/scratch:16", "/data/results:83", "/var/lib/postgresql:82"], '
           '"counter": "0.04/0.05 Gb"}, "network": {"speed": "0.01/0.25 Mb/s", '
           '"counter": "0.01/0.44 Gb"}}',
  'status': 'running',
  'worker_id': 1}]
```

The function are available in a consistent style:

#### Server class functions

`workers`
:   list the workers

`worker_create_signal`
:   send a signal (like pause, term, kill) for a task on this worker

`worker_deploy`
:   deploy a new worker

`worker_get`
:   retrieve a worker detail

`worker_create`
:   low level create worker (used internally, prefer worker_deploy)

`worker_delete`
:   delete a worker

`worker_executions`
:   list executions on a certain worker

`worker_update`
:   modify (update) a worker

`workers_tasks`
:   list tasks for a worker

The different function on other objects use the same consistent logic (`tasks`, `task_update`, `task_create`, etc... for tasks, `executions`, `execution_update`, etc... for executions).
The technical documentation of scitq.lib is [here](lib.md)

#### Server style : object or dict

The server object is a simple proxy to the different REST functions that call the API. The answer is provided as is natural in Python JSON in dictionary objects. However in some cases, object style, that is argparse.Namespace, provides a more natural way of coding:

```python
from scitq.lib import Server
from pprint import pprint

s = Server('127.0.0.1', style='object')
for worker in s.workers():
    print(worker.name)
```
NB: style parameter default to dictionary style, `style='dict'`.

#### Asynchronous 

scitq.lib has several goodies upon a basic REST client, and one of the best is that it is partially asynchronous. If the connection to the server is correct it will work in synchronous mode (and block on each query), but when a timeout occurs it will transparently switch to asynchronous mode (unless the server object was called with `asynchronous=False` option).

Asynchronous mode means that a special query thread will be opened and that all queries sending some information will be sent whenever possible. Queries will be executed in the same order as they were launched but the call instruction, like `s.worker_update(...)` will be non-blocking. Also, the objects or dictionaries (depending on style) returned by such queries will be lazy. Lazy means the object hold no real information, only trying to access to an attribute will trigger the real query - and will be blocking.

The get queries are always synchronous (as it is likely you'll need the information very soon after querying) and will block and retry as much as necessary, but not fail, if the server is down. 

This makes any code using scitq.lib very resilient to a server crash.


There are two parameters to be more or less aggressive, in the Server object creator:

`put_timeout`
: the time in second before switching to asynchronous when sending information (and also how frequently the query should be retried) (default to 30sec)

`get_timeout`
: the time in second before retrying when getting information (default to 150sec)

!!! note
    Lowering those times will make your code more aggressive. It can be counter-productive, notably for gets. The server will gather some resource, begin to compute what is required to answer you and... you're already gone and, worse, you will try again later... If the server is already a bit saturated, this is likely to worsen the problem.

So for instance if you want to have a resilient but very unaggressive code, you could:
```python
from scitq.lib import Server

s = Server('127.0.0.1', put_timeout=60, get_timeout=300)
```

#### Example

This is an almost literal example of a real use case of scitq at GMT Science, using [CAMISIM](https://github.com/CAMI-challenge/CAMISIM).

This suppose that:

- all the input files of CAMISIM were uploaded on `s3://rnd/camisim/camisim1/<samplename>`:
  - config.ini,
  - composition.tsv,
  - metadata.tsv
  - and id_to_genome.tsv
- the genomes (.fa files) were archived with tar and (pi)gzipped and uploaded to `s3://rnd/resource/mygenomes.tgz`,
- a private registry was set up and a docker (mainly CAMISIM public docker but with resources pre-downloaded) was uploaded to it.

We could generate almost 400 2x10M read samples in a few days with that.

Note the `s.join()` instruction at the end of the script. This instruction is reminiscent of `threading.join()` except it takes a list of tasks (such as returned by s.task_create) and can take a retry argument to relanch tasks a certain number of time.

```python
import pandas as pd
from scitq.lib import Server

s=Server('myserver')
name='camisim1'
genome_source='s3://rnd/resource/mygenomes.tgz'
DOCKER_IMAGE='privateregistry01.container-registry.ovh.net/library/camisim-shared:1.3.0.7'

with open('samples.tsv','r') as sample_file:
  samples = pd.read_csv(sample_file, sep='\t', index_col=0)
tasks = []
for sample in samples.columns:
    s3base = f's3://rnd/camisim/{name}/{sample}'
    tasks.append(
        s.task_create(
            command=f"metagenomesimulation.py /input/config.ini",
            name=sample,
            batch=name,
            input=' '.join([f'{s3base}/{item}' for item in [
                    'composition.tsv','metadata.tsv','config.ini','id_to_genome.tsv']]),
            resource=f"{genome_source}|untar",
            output=f's3://rnd/results/camisim/{name}/{sample}/',
            container=DOCKER_IMAGE
        )
    )

s.worker_deploy(number=5,
    batch=name,
    region='UK1',
    flavor='i1-180',
    concurrency=9)

s.join(tasks, retry=2)
```

!!! note
    remember to use `s.task_create(command="sh -c '...'")` (double quote outside) and not `s.task_create(command='sh -c "..."')` (simple quote outside) to prevent intermediary shell interpretation.

Since v1.2, `create_task` accept a `shell` optional argument, which default to `False`. If set to `True`, then the command is executed within a shell (`sh` shell). Shell command will be required:

- if you do anything complex such as chaining two commands with `&&` or piping `|`, 
- but also some simple stuff as shell expansion `ls *.png`, 
- or if you use environment variables `touch $OUTPUT/myemptyoutput`. 

Most of the time, using `shell=True` is harmless if not useful. However, first, we stick to python conventions, notably the behaviour of `subprocess.run`, and second, some dockers may not have a shell, in which case activating shell will trigger an error. What `shell=True` does is that it replace your <command> by `sh -c '<command>'`, but it makes the code look tidier. This also means that if your command contains single quotes `'`, it is quite unlikely to work and it will trigger a warning. You can also specify `shell='bash'` if you want a specific shell program. We recommand not to try fancy stuff such as `shell='python'`, which might work but are prone to errors.

## scitq workflow (scitq.workflow)

**New in v1.2**

While scitq.lib offers an excellent way of executing a simple command at a large scale, implementing a complete chain of small steps can become tedious. You can of course execute a more elaborate script chaining different commands in a task but this has several drawbacks:

- First, this means you will not be able to use ready made dockers, you will have to write (and maintain) your own specific docker,
- Second, you will have two codes to maintain: the script that run within the task, and the code that distribute the tasks,
- Third, some steps within your script may have specific hardware requirements while other may not, which may lead to unoptimal use of worker nodes for certain steps.

scitq.worker aims to solve this 3 issues, it introduces Workflow and Step objects, Worker containing Steps and Steps being linked together by dependency relations:

- Each step use a single docker, maximising reuse opportunities,
- which in turn means the logic of each step is simple enough so as not to require a specific script,
- plus each Step can express specific worker requirements - thus enabling timely and adapted worker usage.

### A Hello World example

```python
from scitq.workflow import Workflow
import os
 
wf = Workflow(name=f'helloworld', shell=True, flavor='local')
 
for i in range(100):
    step1 = wf.step(
        batch='echo',
        name=f'echo #{i}',
        command=f'echo Hello world {i}!',
        concurrency=10,
        maximum_workers=1
    )
 
wf.run(refresh=10)
wf.clean()
```

In this very simple example, we introduce the Workflow object. It's only mandatory attribute is its name. The other attributes (here `shell` and `flavor`) are default values for the contained Steps (which can be overriden at step level, if for instance one of the step needs a specific option).

Then in the for loop, we instanciate Steps. The Step attributes are the same you would expect for a Task (see `create_task` above in scitq.lib), except for one extra attribute: `maximum_workers`, which will tell scitq to dynamically allocate one worker maximum for this Step. As the workflow object is set with `flavor='local'`, this Step will inherit this attribute, which means that a maximum of one worker with the flavor `'local'` will be recruited for this Step (and thus for the entire Workflow as in this simple example, there is only one step).

### Step: an hybrid object

In above example, there is only one step in the workflow, but in terms of python objects this is not true, there is one instance of Workflow and one hundred instances of Step.

So the `step1` variable is overwritten 99 times, not a very clean code. Step is an hybrid object. By hybrid, we mean that it borrows from the Object Factory pattern: Step is primarily a Factory for Tasks. So we **should** declare one Step object and then 100 Tasks from this single Step. But, as you will see in a more elaborate example below, making Step hybrid provides a natural way of writing things.

So under the hood, Step is attached to a Batch object, which is named after the `batch` attribute, and to several Task objects. Some of the Step attributes apply to this Batch object like `maximum_workers` or `flavor` and are shared between Tasks, while others like `name`, `command` apply to individual Tasks. It may sound awkward, but if we look at Step attributes, guessing which apply to which is pretty obvious.

### Step attributes (Worflow.step() constructor arguments)
Some of these arguments are mandatory, other are optional: this will be specified for each argument. Others can be set when creating the Workflow (in which case they become a default value that can be overriden for a specific Step), which will be specified with 'can be set at workflow level'. In one specific case (`maximum_workers`), the attribute name at Workflow level is different (`max_step_workers`), this is because a global workflow maximum can be set with `max_workflow_workers`, and it prevents ambiguity.

Let us dive into Step attributes, first the Batch or shared attributes:

- `batch` (mandatory): This is the name of the Batch object, but it is also used to define the batch to which Tasks will belong, the actual batch of the Tasks is `<Workflow name>.<Step batch>`, so as to avoid any collision with a similar Step from another Workflow,
- `maximum_worker` (mandatory if Workflow `max_step_workers` is unset): this is the maximum number of workers to be allocated for this batch, see the worker recruitment system below,
- `concurrency` (mandatory if Worfkow `concurrency` is unset): this is the concurrency setting for newly recruited workers,
- `provider`, `region`, `flavor` (optional, can be set at Workflow level): these are mandatory if new workers should be deployed, if any of these is unset only recycling of currently idle workers will happen if at least `flavor` is set, see worker recruitment below,
- `prefetch` (optional, default to 0): this is the prefetch setting for newly recruited workers,
- `rounds` (optional): an another setting that can help with worker recruitment: for instance if you have 100 tasks with a concurrency of 10, you expect 10 rounds if there is only one worker. So if you want to be frugal, this setting tells scitq how long you are ready to wait in terms of iterations (useful if there is a variable number of tasks),
- `tasks_per_worker` (optional): another logic for worker recruitment: in above exemple, you have a concurrency of 10, that is your worker launches ten tasks simultaneously, but in the end, you expect your worker to do 100 tasks (in 10 rounds). The following equation should be true: `tasks_per_worker = concurrency * rounds`. It's just another way of specifying your expectations.

Then the Task or individual attributes (they may still get the same value for each individual task):

- `command` (mandatory): the command to launch for this Step,
- `name` (optional, recommanded): the name of the task, it defeats the purpose of this argument to use the same name for each task, as it is meant to distinguish between tasks: think of `batch` as the category of task you're launching and `name` as each individual task's name.
- `shell` (optional, can be set at Workflow level): see shell attribute at task level: if set to True, the command is a shell instruction and not a simple binary call. Very likely to get the same value for all tasks of a kind, but formally not required to.
- `input`,`output` (optional): see the create_task usage above, usual input and output attributes for tasks expressed as URI, inputs are placed in docker `/input` (or non docker `$INPUT` folder) (`input` may be a list), `output` is expected to be folder and will receive the content of the docker `/output` folder (or non docker `$OUTPUT` folder). A very common pattern is to take previous Step `output` as the next Step `input`, something we will see in next more elaborate example.
- `resource` (optional): like `input`, see the create_task usage above, it can be a list of URI or a single URI, resources are placed in docker `/resource` (or non docker `$RESOURCE`). Unlike `input` and `output`, it makes more sense to share this value but it is not required, remember that `/resource` folder is indeed shared among tasks.
- `container`, `container_options` (optional, can be set at workflow level): respectively docker name and additional run options (it makes sense to share those, but yet not required),
- `retry` (optional, can be set at workflow level): how many times should we retry this step (usually shared). This exists also since v1.2 in `create_task`, but with scitq.lib direct use, this is rather set within the `scitq.lib.Server.join()` call. Mixing both styles is not recommanded, so either use `join(retry=...)` without setting individual `Task.retry` or do not set retry in `join()` if individual Tasks have a retry. When using both, they should add up (and not multiply), but again this is not recommanded. In the other direction, it is not recommanded either to `join()` Steps: use `Step().gather()`  instead, see below. 
- `download_timeout`, `run_timeout` (optional, can be set at workflow level): if set, they must be integers and set a time in seconds above which the task will be killed (and will fail, possibly relaunching if retry is set). `download_timeout` is a maximal duration for the `accepted` Task.status (during which `input`s and `resource`s are downloaded), whereas `run_timeout` is a maximal duration for the `running` Task.status, that when the provided `command` is running. By default, there is no timeout.


This specific argument is individual but slightly different from the equivalent argument of `task_create`:

- `required_tasks` (optional): it can be a Step, Task or any object with an integer attribute named `task_id` or an simple integer, or a list of those things. A common pattern is to take the previous Step object of the workflow as a required task for the next. (NB in `task_create`, the equivalent argument is called `required_task_ids` and can only be a list of integers)


#### Recommanded coding style and specific tricks: joining (or gathering)

It is common to have a final analytical step or result consolidation step at the end of a workflow. Usually, Workflow are linear: they have multiple Steps that depend each on the previous one. The workflow is also iterated over multiple instances (typically a list of sample data). The logic is thus:

```python
wf=Workflow('myworkflow')
for sample in my_sample_list:
    step1 = wf.step(command='...', input=f'azure://.../{sample}/', output='...')
    step2 = wf.step(command='...', input=step1.output, output='...', required_tasks=step1)
```

From a reader perspective, it is clear that step2 occurs after step1, however in python code, what happens is that this particular step2 (the step2 for this specific sample) depends on this particular step1.

Now let's say you need a step3 that depends on all the iterations of step2. You could collect all different step2 in a list, and set step3 `required_tasks` argument to this list - which will work, but it can be written in a more natural way:

```python
wf=Workflow('myworkflow')
for sample in my_sample_list:
    step1 = wf.step(command='...', input=f'azure://.../{sample}/', output='...')
    step2 = wf.step(command='...', input=step1.output, output='...', required_tasks=step1)

step3 = wf.step(command='...',input=..., required_tasks=step2.gather())
```

Also, in this common pattern, what happens for the input of the last step is that you'll want all the outputs of all the previous step iterations. Likewise, you could collect all the step2.output attributes in a list and set that at the last step input, which would work, but there is a nicer way to do that with a variant of the `.gather()` method:

```python
wf=Workflow('myworkflow')
for sample in my_sample_list:
    step1 = wf.step(command='...', input=f'azure://.../{sample}/', output='...')
    step2 = wf.step(command='...', input=step1.output, output='...', required_tasks=step1)

step3 = wf.step(command='...',input=step2.gather('output'), required_tasks=step2.gather())
```

### Worker recruitment

One of the benefits of the Workflow system is a more dynamic Worker allocation system. This new system inherits from all v1.0 scitq system and add a new low level object called a Recruiter, but before explaining this low level object, let's keep the big picture and see how it works.

#### Recruitment rules

To recruit, scitq need to know what kind of worker you need, how many of them, and where to recruit them:

- the kind of worker is set by the `flavor` argument available at Workflow or Step level: this is the same argument that is expected in `worker_deploy()` call that we have seen before. There is one novelty in v1.2, now even manually deployed worker have a flavor, which by default is `'local'`, but can be changed notably in `/etc/scitq-worker.conf` with `SCITQ_FLAVOR=...`
(this value is overriden by the one in scitq database if it exists, so to change the flavor of a manually deployed worker, change its /etc/scitq-worker.conf and its scitq database value with `scitq-manage worker update -n ... -f <newflavor>`).
- (new in v1.2.3) `flavor` can also start with `auto:...` and uses the protofilters syntax (see [protofilters](manage.md#using-protofilters-new-in-v123)), which offers more flexibility in terms of recycling, and adapt automatically to availability issues *if region is set to auto*,
- where to recruit is set by the `provider` and `region` parameters. If both of those are set, it triggers the possibility to deploy new workers (but it does not make that automatic), if either is missing, no new deploy will occur, but recycling an already present worker remains possible.
- (new in v1.2.3) if `flavor` uses the new `auto:...` syntax, `region` and `provider` can be set to `auto`. This is strongly recommanded for `region`, as it will enable to adapt to `availability`, and not necessarily for `provider` where specifying `auto` may generate extra costs.

The last thing to know is to specify how many workers are needed, which is computed using the following rules:

* There must be some Tasks with status `pending` for this Step (that is tasks not running yet, but with their requirements (a.k.a. `required_tasks`) fulfilled), also scitq know that each worker can do `Step.concurrency` tasks in parallel so basically `# pending tasks / Step.concurrency` is the right base figure,
* An upper limit is set to avoid renting half Azure or half OVH because the Workflow went berseck, this is the `Step.maximum_workers` attribute.

This is the minimal setup, but there are several refinement:

- First, the `Step.maximum_workers` can be set really high and a lower limit can be set with `rounds` or `tasks_per_worker` Step level attributes. Both attributes are syntaxic sugar to specify how long you would ideally wait, if it remains below the hard limit that is `Step.maximum_workers`: the `rounds` argument is how many time scitq will reuse the worker for this Step. So if `rounds=10` and `concurrency=10`, it means scitq will expect one worker per 100 tasks. In that case, specifying `rounds=10` is the same as `tasks_per_worker=100`.
- Second, scitq will always preferably recycle, that is reuse an available worker of the right kind, provided this worker has some spare possibilities from its previously attributed tasks (e.g. no more pending tasks in its previous batch). However you can force somehow this behaviour:

  - for instance if `Workflow.max_worklow_workers=Sum of Step maximum_workers`, then new worker deploy propability is maximal: as soon as a Task reaches the `pending` status, if a worker of the right `flavor` is not immediately available, a new Worker is deployed,
  - If `Worker.max_workflow_workers` is set to 0, then no new deploy will happen whatsoever, scitq will wait indefinitely that by chance a Worker of the right `flavor` becomes available.
  - An intermediate setup will trigger an initial and progressive recruitment up to `Worker.max_workflow_workers`, and then scitq will recycle these workers between the different Workflow steps (at least, those requiring the same `flavor`).


#### Recruiter objects

Recruiter objects are the low level objects implementing the recruitment rules of Workflow. 

A Recruiter is attached to a `batch` (and thus may operate outside of Workflow use). A batch may have several strictly ranked Recruiters (only one Recruiter of a certain `rank`, starting by 1 and increasing, is allowed per `batch`, creating a new Recruiter for an already existing `rank` for a certain `batch` is the same as updating the old Recruiter if one existed before).

Each Recruiter has some triggering parameters:

- `minimum_tasks` : a minimal pending task number (which default to 0, trigger as soon as one pending task is there),
- `maximum_workers` : a maximum number of workers which is reached for this batch will untrigger the Recruiter.

Recruiters are listed sorted by their rank and apply one after the other if their triggering conditions are met. Thus the higher the rank, the more likely the `maximum_workers` condition is met.

When the Recruiter triggers it applies recruitment criteria:

- `worker_flavor` : (mandatory) flavor of Worker to recruit,
- `worker_provider`, `worker_region`: (optional) both are needed for deploy to occur, otherwise this is a "recycle only" recruiter. Note that setting both parameters will not prevent recycling, but make it considerably unlikely as if a recyclable worker is not immediately available a new deploy will occur,
- `tasks_per_worker`: (mandatory) dividing the pending task number by this figure will set the need number of worker (up to `maximum_workers`),
- `worker_concurrency`,`worker_prefetch`: this are settings for newly recruited workers (deployed or recycled). Contrarily to what happens with the workflow high level system, here `worker_concurrency` is not taken into account to estimate the number of needed workers, only `tasks_per_worker` is used.

Recruiters maybe manually created by `scitq.lib.Server().recruiter_create()` call.

Recruiters are linked to batch, deleting the batch will delete all its Recruiters.

Worker restitution upon idleness occurs independantly of Recruiters, Recruiters just add or update Workers.

### Workflow extra methods

Workflow main use is to add Step with the `Workflow.step()` creator. However you may have noticed in the hello world example two extra methods:

- `Workflow.run()`: Current behaviour is that Tasks start as soon as they are declared (if they have no requirements), so this does not really trigger the workflow (which is consistent with the equivalent `scitq.lib.Server().join()` behaviour), but it displays a nice URWID (built upon NCURSE) text app, that displays what is going on with all your tasks for all batch and how the workers are affected. There are also several possible actions like PAUSE (which prevent new tasks to be launched without touching running tasks), SUSPEND (which does the same, plus it suspend running tasks) and DESTROY (which kill all tasks and batches - and recruiters).
Any abnormal ending of the app will trigger an RuntimeException preventing further execution of the script.

- `Workflow.clean()`: This method delete all batch and tasks that were created and by default download all logs (STDOUT and STDERR of all steps in folder named after the Workflow.name, controlled by `log_destination` optional argument - if this argument is set to None then no logs will be downloaded) 

### A more elaborate example

This is a real life example, a QC workflow for a public study (that is remove low quality sequences and sequences that belong to the host (which is usual in microbiota studies), and normalize (rarefy) samples), using the nice docker collection from StaPH-B group.

To run this script, you'll need to configure scitq with an access to Azure.
You will also need to upload [CHM13v2 catalog](https://genome-idx.s3.amazonaws.com/bt/chm13v2.0.zip), unzip it, tar gz it (so that files are in a chm13v2 folder), and upload it to your favorite cloud storage. Adapt the resulting URI in the step2.

NB: Tt is easy to adapt to OVH just change provider to 'ovh' flavor to 'c2-120' and region to 'GRA11' for instance in Workflow definition, change the URI to use s3:// instead of azure://. 

```python
from scitq.workflow import Workflow
import requests
import sys
 
SEED = 42
 
######################################################
#                                                    #
#    Project specifics                               #
#                                                    #
######################################################
if len(sys.argv)<3:
    print(f'Usage: {sys.argv[0]} <bioproject accession PRJxxxxxxx> <depth>')
    sys.exit(1)

bioproject=sys.argv[1]
depth=sys.argv[2]
ena_query=f"https://www.ebi.ac.uk/ena/portal/api/filereport?accession={bioproject}&\
result=read_run&fields=sample_accession,run_accession,library_strategy,library_layout&format=json&download=true&limit=0"
azure_base = f'azure://rnd/raw/{bioproject}'
 
 
######################################################
#                                                    #
#    Collecting samples                              #
#                                                    #
######################################################
samples = {}
for item in requests.get(ena_query).json():
    if item['library_strategy']=='WGS':
        if item['sample_accession'] not in samples:
            samples[item['sample_accession']]=[]
        samples[item['sample_accession']].append(item['run_accession'])
 
 
######################################################
#                                                    #
#    QC Workflow                                     #
#                                                    #
######################################################
 
wf = Workflow(name=f'QC-{bioproject}', shell=True, 
              max_step_workers=5, retry=2, flavor='Standard_D32ads_v5', 
              provider='azure', region='swedencentral',
              max_workflow_workers=10)
 
for sample,runs in samples.items():
 
    # cleaning step
    step1 = wf.step(
        batch='fastp',
        name=f'fastp:{sample}',
        command=f'zcat /input/*.f*q.gz|fastp \
            --adapter_sequence AGATCGGAAGAGCACACGTCTGAACTCCAGTCA --adapter_sequence_r2 AGATCGGAAGAGCGTCGTGTAGGGAAAGAGTGT \
            --cut_front --cut_tail --n_base_limit 0 --length_required 60 --stdin \
            --json /output/{sample}_fastp.json -z 1 -o /output/{sample}.fastq.gz',
        container='staphb/fastp:0.23.4',
        concurrency=12,
        input=[f'run+fastq://{run}' for run in samples[sample]],
        output=f'{azure_base}/{sample}/fastp/',
    )
 
    # human filtering step (removing human DNA for ethical reasons)
    step2 = wf.step(
        batch='humanfiltering',
        name=f'bowtiehuman:{sample}',
        command=f'bowtie2 -p 4 --mm -x /resource/chm13v2.0/chm13v2.0 -U /input/{sample}.fastq.gz\
|samtools fastq -@ 2 -f 4 -F 256 -0 /output/{sample}.fastq -s /dev/null',
        container='staphb/bowtie2:2.5.1',
        concurrency=6,
        required_tasks=step1,
        input=step1.output,
        output=f'{azure_base}/{sample}/humanfiltering/',
        resource='azure://rnd/resource/chm13v2.0.tgz|untar',
    )
 
    # normalization step
    step3 = wf.step(
        batch='seqtk',
        name=f'seqtk:{sample}',
        command=f'seqtk sample -s{SEED} - {depth} < /input/{sample}.fastq > /output/{sample}.fastq',
        container='staphb/seqtk:1.3',
        concurrency=6,
        required_tasks=step2,
        input=step2.output,
        output=f'{azure_base}/{sample}/seqtk-{depth}/',
    )
 
######################################################
#                                                    #
#    Monitoring and post-treatment                   #
#                                                    #
######################################################

step4 = wf.step(
    batch='stats',
    name=f'stats',
    command='apt update && apt install -y parallel && \
find /input -name *.fastq | parallel -j $CPU --ungroup seqkit -j 1 stats {}',
    container='staphb/seqkit',
    concurrency=1,
    required_tasks=step3.gather(),
    input=step3.gather('output'),
)

wf.run(refresh=10)
wf.clean()
```

The **project specifics** and **collecting samples** parts are just a sample use of python requests and ENA API, nothing related to scitq, and really classic.

Some details about **QC Workflow**

- In the Workflow declaration, you will find the recruitment rules specified as described: 5 worker max for each Step set with `max_step_workers=5` (there are 4 of them), but a maximum of 10 for the whole workflow, `max_workflow_workers=10`, so given that there are lots of samples, there should be 10 workers but changing from the first steps to the last as the samples are progressing into the workflow (logically, there should be relatively quickly 5 workers on step1, 5 on step2, and when all samples went through step1, the step1 workers moving to step3, etc.).
- You see also that the level of concurrency is quite different between step1 and step2/3, which tell us that the workers will spent a significant amount of time for step2/3, compared to step1 (and maybe it would make sense to lower the maximum_worker setting for step1).
- Last, you see that step4 is a single step out of the for loop (1 iteration), that will synthetize all the iterations of step3. This uses the gather method for the step4 requirements: its required_tasks is set to `step3.gather()`, that is all the different iterations of step3. You can also see the use of `step3.gather('output')` for step4 input.

Last while step1/2/3 are iterated a certain number of times (1 of each per sample) and step4 is unique (1 iteration for all the samples), the appearance of the workflow code remains clear and easy to read. When defining step4 requirement, the use of gather() method bypasses the fact that, technically, the `step3` that is designated here out of loop is just the last of all step3: gather() result does not depend on which iteration of the step3 it is called.

Last the result of the step4 is downloaded by the final `wf.clean()` (which download STDOUT for all tasks). 
