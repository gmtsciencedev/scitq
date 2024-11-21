# scitq workflow (scitq.workflow)

**New in v1.2**

While scitq.lib offers an excellent way of executing a simple command at a large scale, implementing a complete chain of small steps can become tedious. You can of course execute a more elaborate script chaining different commands within a task (workflow within task model) but this has several drawbacks:

- First, this means you will not be able to use ready made dockers, you will have to write (and maintain) your own specific docker,
- Second, you will have two codes to maintain: the script that run within the task, and the code that distribute the tasks,
- Third, some steps within your script may have specific hardware requirements while other may not, which may lead to unoptimal use of worker nodes for certain steps.

scitq.worker aims to solve this 3 issues, it introduces Workflow and Step objects, Worker containing Steps and Steps being linked together by dependency relations:

- Each step use a single docker, maximising reuse opportunities,
- which in turn means the logic of each step is simple enough so as not to require a specific script,
- plus each Step can express specific worker requirements - thus enabling timely and adapted worker usage.

## A Hello World example

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

In this very simple example, we introduce the Workflow object. It's only mandatory attribute is its name. The other attributes (here `shell` and `flavor`) are default values for the contained Steps (which can be overriden at step level, if for instance, one of the step needs a specific option).

Then in the for loop, we instanciate Steps. The Step attributes are the same you would expect for a Task (see `create_task` above in scitq.lib), except for one extra attribute: `maximum_workers`, which will tell scitq to dynamically allocate one worker maximum for this Step. As the workflow object is set with `flavor='local'`, this Step will inherit this attribute, which means that a maximum of one worker with the flavor `'local'` will be recruited for this Step (and thus for the entire Workflow as in this simple example, there is only one step).

## Step: an hybrid object

In above example, there is only one step in the workflow, but in terms of python objects this is not true, there is one instance of Workflow and one hundred instances of Step.

So the `step1` variable is overwritten 99 times, not a very clean code. Step is an hybrid object. By hybrid, we mean that it borrows from the Object Factory pattern: Step is primarily a Factory for Tasks. So we **should** declare one Step object and then 100 Tasks from this single Step. But, as you will see in a more elaborate example below, making Step hybrid provides a natural way of writing things.

So under the hood, Step is attached to a Batch object, which is named after the `batch` attribute, and to several Task objects. Some of the Step attributes apply to this Batch object like `maximum_workers` or `flavor` and are shared between Tasks, while others like `name`, `command` apply to individual Tasks. It may sound awkward, but if we look at Step attributes, guessing which apply to which is pretty obvious.

## Workflow attributes
As said above, only `name` is mandatory, and most other attributes are default for Step attributes. There are however two specific attributes that should be set always at Workflow level:

- `debug` (new in v1.3): this attribute changes the behavior of `Workflow.run()` method and the behavior of `Task`:
  - if `debug` is False (the default): this is the normal mode, tasks are launched with a certain concurrency level, and all tasks able to be run are triggered, see [Workflow extra methods](#workflow-extra-methods) below.
  - if `debug` is True: tasks are created in a `debug` state and when `Workflow.run()` is launched it will be proposed to launch one of the available tasks (a choice is possible), but only one at a time. It will display as much information as possible for this particular task (how the worker are recruited, how the task change and most importantly a real time log of the task command). When this task is over, scitq will ask what to do next, retry, continue with another task, or switch back to normal mode. Note that once in normal mode, there is no comming back to the debug mode. In debug mode, and contrarilly to what happen in normal mode, killing the python script with CTRL-C will prevent any more task to run.
- `base_storage` : an optional value that enable to specify `Step.output` with `step(rel_output=...)` this is the same thing as specifying `step(output=os.path.join(base_storage,...))`.

## Step attributes (Worflow.step() constructor arguments)
Some of these arguments are mandatory, other are optional: this will be specified for each argument. Others can be set when creating the Workflow (in which case they become a default value that can be overriden for a specific Step), which will be specified with 'can be set at workflow level'. In one specific case (`maximum_workers`), the attribute name at Workflow level is different (`max_step_workers`), this is because a global workflow maximum can be set with `max_workflow_workers`, and it prevents ambiguity.

Let us dive into Step attributes, first the Batch or shared attributes:

- `batch` (mandatory): This is the name of the Batch object, but it is also used to define the batch to which Tasks will belong, the actual batch of the Tasks is `<Workflow name>.<Step batch>`, so as to avoid any collision with a similar Step from another Workflow,
- `maximum_worker` (mandatory if Workflow `max_step_workers` is unset): this is the maximum number of workers to be allocated for this batch, see the worker recruitment system below,
- `concurrency` (mandatory if Worfkow `concurrency` is unset): this is the concurrency setting for newly recruited workers,
- `provider`, `region`, `flavor` (optional, can be set at Workflow level): these are mandatory if new workers should be deployed, if any of these is unset only recycling of currently idle workers will happen if at least `flavor` is set, see worker recruitment below, (`region` defaults now to `'auto'` which enable to use the `PREFERRED_REGIONS` setting and permit to adapt automatically to another region when a region is depleted of its quota of instances, see [Worker recruitment](#worker-recruitment) below)
- `prefetch` (optional, default to 0): this is the prefetch setting for newly recruited workers,
- `rounds` (optional): an another setting that can help with worker recruitment: for instance if you have 100 tasks with a concurrency of 10, you expect 10 rounds if there is only one worker. So if you want to be frugal, this setting tells scitq how long you are ready to wait in terms of iterations (useful if there is a variable number of tasks),
- `tasks_per_worker` (optional): another logic for worker recruitment: in above exemple, you have a concurrency of 10, that is your worker launches ten tasks simultaneously, but in the end, you expect your worker to do 100 tasks (in 10 rounds). The following equation should be true: `tasks_per_worker = concurrency * rounds`. It's just another way of specifying your expectations.
- `use_cache` (optional, new in v1.3): default to False. If set to True, scitq will try to find another task (more exactly another execution) that succeeded before and that uses the same command, container, container_options, input and resource. It will then re-use the output of this task for this new task. If the output is the same in the new task and in the previous, and it has not be altered since then, then nothing is done. If the output is different, but on the same cloud storage component and with files unaltered, files are copied to the new output location. If tasks output is different and use different cloud storage component are used, caching does not occur. In this case and in all case where a difference exists, the task is run as usual.

Then the Task or individual attributes (they may still get the same value for each individual task):

- `command` (mandatory): the command to launch for this Step,
- `name` (optional, recommanded): the name of the task, it defeats the purpose of this argument to use the same name for each task, as it is meant to distinguish between tasks: think of `batch` as the category of task you're launching and `name` as each individual task's name. Since v1.3 `name` default to the `batch #X` where X is a counter of the Xth task in the batch.
- `shell` (optional, can be set at Workflow level): see shell attribute at task level: if set to True, the command is a shell instruction and not a simple binary call. Very likely to get the same value for all tasks of a kind, but formally not required to.
- `input`,`output` (optional): see the create_task usage above, usual input and output attributes for tasks expressed as URI, inputs are placed in docker `/input` (or non docker `$INPUT` folder) (`input` may be a list), `output` is expected to be folder and will receive the content of the docker `/output` folder (or non docker `$OUTPUT` folder). A very common pattern is to take previous Step `output` as the next Step `input`, something we will see in next more elaborate example.
- `resource` (optional): like `input`, see the create_task usage above, it can be a list of URI or a single URI, resources are placed in docker `/resource` (or non docker `$RESOURCE`). Unlike `input` and `output`, it makes more sense to share this value but it is not required, remember that `/resource` folder is indeed shared among tasks.
- `container`, `container_options` (optional, can be set at workflow level): respectively docker name and additional run options (it makes sense to share those, but yet not required),
- `retry` (optional, can be set at workflow level): how many times should we retry this step (usually shared). This exists also since v1.2 in `create_task`, but with scitq.lib direct use, this is rather set within the `scitq.lib.Server.join()` call. Mixing both styles is not recommanded, so either use `join(retry=...)` without setting individual `Task.retry` or do not set retry in `join()` if individual Tasks have a retry. When using both, they should add up (and not multiply), but again this is not recommanded. In the other direction, it is not recommanded either to `join()` Steps: use `Step().gather()`  instead, see below. 
- `download_timeout`, `run_timeout` (optional, can be set at workflow level): if set, they must be integers and set a time in seconds above which the task will be killed (and will fail, possibly relaunching if retry is set). `download_timeout` is a maximal duration for the `accepted` Task.status (during which `input`s and `resource`s are downloaded), whereas `run_timeout` is a maximal duration for the `running` Task.status, that when the provided `command` is running. By default, there is no timeout.


This specific argument is individual but slightly different from the equivalent argument of `task_create`:

- `required_tasks` (optional): it can be a Step, Task or any object with an integer attribute named `task_id` or an simple integer, or a list of those things. A common pattern is to take the previous Step object of the workflow as a required task for the next. (NB in `task_create`, the equivalent argument is called `required_task_ids` and can only be a list of integers)


### Recommanded coding style and specific tricks: joining (or gathering)

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

## Worker recruitment

One of the benefits of the Workflow system is a more dynamic Worker allocation system. This new system inherits from all v1.0 scitq system and add a new low level object called a Recruiter, but before explaining this low level object, let's keep the big picture and see how it works.

### Recruitment rules

To recruit, scitq need to know what kind of worker you need, how many of them, and where to recruit them:

- the kind of worker is set by the `flavor` argument available at Workflow or Step level: this is the same argument that is expected in `worker_deploy()` call that we have seen before. There is one novelty in v1.2, now even manually deployed worker have a flavor, which by default is `'local'`, but can be changed notably in `/etc/scitq-worker.conf` with `SCITQ_FLAVOR=...`
(this value is overriden by the one in scitq database if it exists, so to change the flavor of a manually deployed worker, change its /etc/scitq-worker.conf and its scitq database value with `scitq-manage worker update -n ... -f <newflavor>`).
- (new in v1.2.3) `flavor` can also start with `auto:...` and uses the protofilters syntax (see [protofilters](manage.md#using-protofilters-new-in-v123)), which offers more flexibility in terms of recycling, and adapt automatically to availability issues *if region is set to auto* (which is now the default value in Workflow),
- where to recruit is set by the `provider` and `region` parameters. If both of those are set, it triggers the possibility to deploy new workers (but it does not make that automatic), if either is missing, no new deploy will occur, but recycling an already present worker remains possible. As region is now preset to `auto`, specifying the provider decide wether the recruiter actively deploy or only recycle. 
- like `region`, `provider` can be set to `auto`. This has the benefit of bringing a maximal flexibility, notably when using `auto:...` as a `flavor` (as likely different providers have different names for flavors). Yet it gives less control on the different data flows, and it may generate extra costs due to egress/ingress transfers. In doubt it is recommanded to specify a provider (like ovh or azure) and avoid auto except in specific case (when very sparse instances are needed accross providers).

The last thing to know is the number of needed workers, which is computed using the following rules:

* There must be some Tasks with status `pending` for this Step (i.e. tasks not running yet, but with their requirements (a.k.a. `required_tasks`) fulfilled). Using the `Step.concurrency` which setup how many tasks in parallel are run, an initial (and maximal) number can be proposed: `# pending tasks / Step.concurrency`,
* This value is however capped by several figures:
  - [mandatory] `Step.maximum_workers` is the upper limit to avoid an explosion of costs,
  - [optional] the initial number can be devided with `Step.rounds` (e.g. the number of rounds of `Step.concurrency` tasks that each worker will do),
  - [optional] when specifying `Step.tasks_per_worker` the initial number is replaced by `# pending tasks / tasks_per_worker` (up to `Step.maximum_workers`) (which is the same idea as above but expressed differently: if `concurrency` is 10, then `rounds=10` is equivalent to `tasks_per_worker=100`.
- Second, scitq will always preferably recycle, that is reuse an available worker of the right kind, provided this worker is partly idle. However you can force somehow this behaviour:

  - for instance if `Workflow.max_worklow_workers=Sum of Step maximum_workers`, then new worker deploy propability is maximal: as soon as a Task reaches the `pending` status, if a worker of the right `flavor` is not immediately available, a new Worker is deployed,
  - If `Worker.max_workflow_workers` is set to 0, then no new deploy will happen whatsoever, scitq will wait indefinitely that by chance a Worker of the right `flavor` becomes available.
  - An intermediate setup will trigger an initial and progressive recruitment up to `Worker.max_workflow_workers`, and then scitq will recycle these workers between the different Workflow steps (at least, those requiring the same `flavor`).




## Workflow extra methods

Workflow main use is to add Step with the `Workflow.step()` creator. However you may have noticed in the hello world example two extra methods:

- `Workflow.run()`: Current behaviour is that Tasks start as soon as they are declared (if they have no requirements), so this does not really trigger the workflow (which is consistent with the equivalent `scitq.lib.Server().join()` behaviour), but it displays a nice URWID (built upon NCURSE) text app, that displays what is going on with all your tasks for all batch and how the workers are affected. There are also several possible actions like PAUSE (which prevent new tasks to be launched without touching running tasks), SUSPEND (which does the same, plus it suspend running tasks) and DESTROY (which kill all tasks and batches - and recruiters).
Any abnormal ending of the app will trigger an RuntimeException preventing further execution of the script.

- `Workflow.clean()`: This method delete all batch and tasks that were created and by default download all logs (STDOUT and STDERR of all steps in folder named after the Workflow.name, controlled by `log_destination` optional argument - if this argument is set to None then no logs will be downloaded). With v1.3, doing this will remove possibilities of using cache (with the `use_cache` parameter), and is now discouraged.

## Specific domain library

### scitq.bio.genetics

This library offers convenient functions dedicated to genetics:
- `ena_get_samples()`: a method that takes a bioproject accession (like PRJEBxxxx or PRJNAxxxx) and return a dictionary of sample accession: list of runs. The `run` object is a `argparse.Namespace` objet with the attributes of the EBI ENA run object, plus a specific attribute, `run.uri` which is a URI string that can be used notably in `Step.input`,
- `sra_get_samples()`: a very similar method which use NCBI SRA instead of EBI ENA. NCBI SRA attributes are transformed to be more compatible with EBI ENA and more pythonic:

Original SRA attribute|Modified attribute in scitq
--|--
Run|run
ReleaseDate|release_date
LoadDate|load_date
spots|spots
bases|bases
spots_with_mates|spots_with_mates
avgLength|avg_length
size_MB|size_mb
AssemblyName|assembly_name
download_path|download_path
Experiment|experiment
LibraryName|library_name
LibraryStrategy|library_strategy
LibrarySelection|library_selection
LibrarySource|library_source
LibraryLayout|library_layout
InsertSize|insert_size
InsertDev|insert_dev
Platform|platform
Model|model
SRAStudy|sra_study
BioProject|bio_project
Study_Pubmed_id|study_pubmed_id
ProjectID|project_id
Sample|sample
BioSample|bio_sample
SampleType|sample_type
TaxID|tax_id
ScientificName|scientific_name
SampleName|sample_name
g1k_pop_code|g1k_pop_code
source|source
g1k_analysis_group|g1k_analysis_group
Subject_ID|subject_id
Sex|sex
Disease|disease
Tumor|tumor
Affection_Status|affection_status
Analyte_Type|analyte_type
Histological_Type|histological_type
Body_Site|body_site
CenterName|center_name
Submission|submission
dbgap_study_accession|dbgap_study_accession
Consent|consent
RunHash|run_hash
ReadHash|read_hash

The run objects contain like before a `run.uri` attribute for use in input.

- a `uri_get_samples()` is also provided: it takes a URI in input, a cloud storage folder containing a project (consisting of different FASTQs), and it provides a similar dict of sample accession: runs. The regroupment of runs per sample is guessed using either the one sample per folder approach (the folder containing the diffent runs) or the common prefix approach (where runs for the same samples share a common prefix that is not shared with the other runs). The parity information is also guessed from the ending of FASTQ (i.e. if a folder contains two FASTQs, one ending in `1.fastq.gz` the other with `2.fastq.gz`, the runs will have a `run.library_layout` set to `'PAIRED'`). Like previously `run.uri` attribute is also provided.

- Some other functions are also provided, with effect relatively obvious for the field: 
  - `find_library_layout()` find the dominent library layout in a sample dict such as returned by previous functions.
  - `filter_by_layout()` filter runs matching a specific layout, except that PAIRED run will be transformed into SINGLE run.
  - `filter_by()` enable filtering runs by an arbitrary attribute (for instance, one could say `samples=filter_by(samples, library_strategy='WGS')`)
  - `user_friendly_depth()` enable to use strings representing a number of read, a commun parameter for runs, known as depth, in a common way such as `10M`. It also support `x2` or `x1` suffix to denote the parity information (`10Mx2` means 10000000 of pair of reads). One can use prefix like `2x10M`, the result is identical. The answer of this function is a Depth object containing both information.

## A complete workflow example

This is a real life example, a QC workflow for a public study (that is remove low quality sequences and sequences that belong to the host (which is usual in microbiota studies), and normalize (rarefy) samples), using the nice docker collection from StaPH-B group.

To run this script, you'll need to configure scitq with an access to Azure.
You will also need to upload [CHM13v2 catalog](https://genome-idx.s3.amazonaws.com/bt/chm13v2.0.zip), unzip it, tar gz it (so that files are in a chm13v2 folder), and upload it to your favorite cloud storage. Adapt the resulting URI in the step2.

NB: Tt is easy to adapt to OVH just change provider to 'ovh' flavor to 'c2-120' and region to 'GRA11' for instance in Workflow definition, change the URI to use s3:// instead of azure://. 

```python
from scitq.workflow import Workflow
from bio.genetics import ena_get_samples
import sys
import typer
 
SEED = 42
 

def QC_workflow(bioproject:str, depth:str):
    """Collect samples for a bioproject, filter, clean, and normalize them at a given depth - and provide stats"""
    
    ######################################################
    #                                                    #
    #    Collecting samples                              #
    #                                                    #
    ######################################################
    samples = ena_get_samples(bioproject)
    depth,parity = user_friendly_depth(depth).to_tuple()
    
    ######################################################
    #                                                    #
    #    QC Workflow                                     #
    #                                                    #
    ######################################################
    wf = Workflow(name=f'QC-{bioproject}', shell=True, 
                max_step_workers=5, retry=2, flavor='auto:cpu>=32:ram>=120:disk>=100', 
                provider='azure', region='auto',
                max_workflow_workers=10, 
                base_storage= f'azure://rnd/raw/{bioproject}')
    
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
            input=[run.uri for run in runs],
            rel_output=f'{sample}/fastp/',
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
            rel_output=f'{sample}/humanfiltering/',
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
            rel_output=f'{sample}/seqtk-{depth}/',
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
        input=step3.gather('output')
    )

    wf.run(refresh=10)

if __name__=='__main__':
    typer.run(QC_workflow)
```

The **collecting samples** is just a very basic use of the `scitq.bio.genetics` library.

Some details about **QC Workflow**

- In the Workflow declaration:
  - you can notice the worker.flavor use the `auto:...` syntax, with the `auto:cpu>=32:ram>=120:disk>=100` string: it means at least 32 vCores, at least 120Gb of RAM memory and 100Gb of disk.
  - you will find the recruitment rules specified as described: 5 worker max for each Step set with `max_step_workers=5` (there are 4 of them), but a maximum of 10 for the whole workflow, `max_workflow_workers=10`, 
  - so given that there are lots of samples, there should be 10 workers but changing from the first steps to the last as the samples are progressing into the workflow (logically, there should be relatively quickly 5 workers on step1, 5 on step2, and when all samples went through step1, the step1 workers moving to step3, etc.).
- You see also that the level of concurrency is quite different between step1 and step2/3, which tell us that the workers will spent a significant amount of time for step2/3, compared to step1 (and maybe it would make sense to lower the maximum_worker setting for step1).
- Last, you see that step4 is a single step out of the for loop (1 iteration), that will synthetize all the iterations of step3. This uses the gather method for the step4 requirements: its required_tasks is set to `step3.gather()`, that is all the different iterations of step3. You can also see the use of `step3.gather('output')` for step4 input.

Last while step1/2/3 are iterated a certain number of times (1 of each per sample) and step4 is unique (1 iteration for all the samples), the appearance of the workflow code remains clear and easy to read. When defining step4 requirement, the use of gather() method bypasses the fact that, technically, the `step3` that is designated here out of loop is just the last of all step3: gather() result does not depend on which iteration of the step3 it is called.
