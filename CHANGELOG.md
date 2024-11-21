<!-- CHANGELOG SPLIT MARKER -->

# v1.3 (2024-11-21)

This version introduces several enhancements to the v1.2.x series, as well as several important changes in the components used. The storage configuration should be changed as all storage is managed through rclone now:
- the `Workflow` class now has some debug capacity which should make debugging a lot easier (simply specify `debug=True` in the `Workflow`
constructor), and contrarily to the previous `scitq-manage debug run` method, tasks are executed the normal way (not an ad hoc local way) and one can initiate a debug run and switch to the normal run during the debug (the reverse is not possible though),
- `Task`s can be cached, i.e. the results of an identical task will be automatically reused provided:
  - `use_cache` property is set to True in the Workflow constructor (or with `Server.task_create()`) for the new Task,
  - Another Task previously succeeded exists with identical `command`, `container`, `input` and `resource`,
  - both `Task`s `output` are located on the same cloud component (enabling remote copy)
- A new component, `scitq.bio.genetics`, was added with several convenient functions like `ena_get_samples()`, `sra_get_samples()`, and some ad hoc filters like `filter_by_layout()` which are coupled with new enhancements in `scitq.fetch`, see below,
- In `scitq.fetch` there is a major component change, with the integration of [rclone](https://github.com/rclone/rclone): this instantly makes all rclone compatible storage systems available in scitq. Note that the URI (generalized URL) used by scitq are different from the one used by rclone: on rclone URIs are like `<resource name>:path/to/my/file` while scitq uses something like `s3://path/to/my/file`. To mimic previous usage, scitq change `<resource>://path/to/my/file` to `<resource>:path/to/my/file` when calling rclone, thus if you call your main S3 resource s3 and your main Azure resource azure, the change will be entirely transparent. However a lot of additional benefits come with this change:
  - there is now a progress bar when calling `scitq-fetch` from the command line,
  - the performance is increased,
  - remote copy is now possible (azure to azure or s3 to s3 copy without transferring any files locally using either copy or rsync: this was throwing an exception in previous versions) - this function is used in `Task` caching when `output` are different.
  - MD5 support which was introduced in v1.2.4 is now supported through rclone: it is compatible with Azure previous implementation (because Azure has limited internal support for MD5), but not AWS (which has no MD5 support): thus files transferred to AWS with previous scitq versions will lose their MD5 information (you'll need to re-transfer them to recover this info if strictly needed - MD5 value should be optional in nearly all situations, notably in the case of `Task` caching which uses MD5 when available and relies on name/date/size otherwise).
- An unrelated change has also occurred in `scitq.fetch` : protocol options are now more flexible and can be cumulated in several situations. Protocol options like `ftp@aria2://...` or `run+fastq@sra://...` activate specific behavior in different protocols: they were impossible to cumulate and internally `ftp@aria2` was considered a different protocol from `ftp`. It is now possible to use `run+fastq@sra@filter_r1://...` for instance which means, remove R2 reads and use SRA to recover that run. The `filter_r1` protocol option is automatically invoked by ad hoc function `scitq.bio.genetics.filter_by_layout()`.
- `scitq.path.URI` formalizes scitq URI in the same way `libpath.Path` does, for instance you can say `URI('s3://temp') / 'test'` which output `URI('s3://temp/test')`, you can ask a `URI` object if it `exists()` if it `isdir()` or it `isfile()`. You can also `list()` its content (though output is a list of Namespace object with dates, size, and co, and not URIs as one could expect). `Workflow.step()` constructor now accepts URI or list of URIs for input, resource and output (not a list for this last one). 
- a lot of bug fixes were added (see commits for details), including several issues with ansible.

To switch to rclone configuration mode (which is mandatory in v1.3), you need to add the different storage resources through rclone, see https://rclone.org/docs/#configure, and the copy the generated `rclone.conf` file (usually in `~/.config/rclone`) to `/etc/` on the scitq server. Remember to call main resources `s3` for the main S3 or `azure` for the main Azure so that your previous URIs remain the same. Clients can copy the configuration using `scitq-manage rclone config --install`, which enable them to use `scitq-fetch` command locally.

All these changes make `Workflow` creation a lot easier than before.


# v1.2.5 (2024-10-09)

This is a quick fix for v1.2.4, that makes workers deploy more robust:
- recruiters using `auto:...` syntax (protofilters) are more dynamically evaluated which should avoid deployment failures when a single recruitment depletes a region from its instance quota (the previous code had an incorrect method of refreshing the quotas, the new code is a lot more generic and take account of other users concurrent deployments): this impacts in cascade scitq.workflow.Workflow which should now have a much better recruitment strategy.
- notably worker deploy should fail less because of ssh timeout (which was a not so common defect)


# v1.2.4 (2024-10-02)

This is a minor update of v1.2.3, with a series of minor but convenient enhancements:
- UI is now more user-friendly with some field with automated completion when deploying a new worker and a representation of flavor details,
- Downloads can now timeout depending on the size of data (so as to fail when some Azure downloads are stuck or some download from NCBI/EBI get too slow)
- Each file copied with scitq to Azure/AWS now has an MD5 info which can be retrieved with `--md5` using `scitq-fetch [list,nlist,nrlist]` or with `scitq.fetch.list_content()` with `md5=True` option. This is not native (native only for small files), so it is locally estimated and added in optional metadata on those clouds (that is transparent when using scitq), so files transferred with previous versions of scitq (or transferred not by scitq) will lack the info in most cases. The efficient retrieval of the info was touchy for AWS, and use a relatively new multiprocess paradigm in Python, `multiprocessing.Pool.starmap()` (it is reported in several places and was confirmed here that multiprocessing parallelizing is efficient for AWS but not multithread)
- `scitq-fetch` command has a new verb, `ncdu` which generates ncdu data (like NCurse Data Usage, an excellent software in text mode to see how much data is used in different folders). It requires the `ncdu` program to parse the generated data (scitq can even run it directly with the generated data when launched with `ncdu --run`), which is available on all distros. `ncdu` is usually restricted to local data but here it works with any folder on Azure or AWS (or ftp or any scitq acceptable URI). Note that the `delete` operation available locally with `ncdu` does not work in this context.
- Workflow now defaults to `region='auto'` which means that as soon as you specify a provider and a flavor when creating the workflow object, workers are automatically deployed. If flavor is present and provider is None (default), this switch to a 'recycle only' behavior, that is only workers deployed by other people or in other contexts that are currently idle can be recruited. This is particularly adapted when using the protofilters introduced in v1.2.3 version.

Several minor bugs were fixed.



# v1.2.3 (2024-08-17)

This is a somehow important reworking of v1.2.2 which introduces dynamic management of flavors, that is maintain and update the worker instance size list, including availability directly querying providers APIs. This new feature is fully described in the documentation under the term `protofilters`. As a short example, instead of specifying `b3-128` (a well known OVH instance), you may say `auto:cpu>=32:ram>=128:disk>=400` which will find the best available instance sastisfying these criterias. This will enable the deploy mechanism (whereas `scitq-manage worker deploy`, `scitq.lib.recruiter_create` or `scitq.workflow.Workflow`) to pick the next best alternative if you choose another provider or if your OVH preferred region is depleted of that specific instance.

This was required notably to properly handle Azure deallocation event, now called `eviction`. `eviction` events are now properly detected and handled. Eviction is when Azure claim back the worker, which is a risk when using Spot (hence the discount granted for Spot). Under scitq v1.2.3 this risk is minimized as eviction rate are dynamically watched for, and if an evicion/deallocation occurs, the worker is automatically replaced (maybe in a more favorable region) and the few lost tasks (those that were active at eviction time) are redispatched automatically.

Some preliminary support for special flavors is also included, namely the G type instances (GPU, available with Azure and OVH) and the M type instance (Metal, e.g. physical server workers, available only with OVH for now). You can now filter for this type of instance. Metal instances are just plain workers, and should work for any task. For GPU instances to work with Azure, you'll need to accept Nvidia specific plan for the instances to deploy (even if the plan is free), which is done with this command:
```sh
az vm image terms accept --urn nvidia:ngc_azure_17_11:ngc-base-version-24_03_4_gen2:latest
```
NB: this is not required for OVH.

For this early stage support, the image provided for GPU instances is based on Ubuntu 22.04 (whereas non-GPU instances still use Ubuntu 20.04 based images).

GPU tasks requires also two specific settings to run, beside being run on a GPU instance:

- you must use a container adapted to GPU tasks, such as [Nvidia NGC containers](https://catalog.ngc.nvidia.com/containers),
- you must pass a specific option to docker to provide access to the hardware, what has been tested is `--gpus all`.

Here is an example satisfying both points:
```sh
scitq-launch -d nvcr.io/nvidia/pytorch:23.05-py3 -O '--gpus all' nvidia-smi
```

Last but not least, there was an increasing difficulty to co-maintain scitq main code depencies and scitq Ansible code dependencies. scitq Ansible code now lives in its own environment which uncouple dependencies and enable a more flexible dependencies management (using pip-tools pip-compile). **This requires to reinstall Ansible binaries (only one line of the conf is required to change), which is easy and quick, sorry about that, but this is all for the best.** (at least in one of our tests, not using venv for Ansible has lead to some issues with `scitq.fetch`). See Ansible install in the doc.

# v1.2.2 (2024-06-01)

This is a minor reworking of v1.2 which introduces specific options and performance optimizations:

- Several instance types (notably in Standard_L... instances in Azure, and i1-... instances in OVH) are better supported which enable use of the best available disk automatically (or a RAID0 combination of those if multiple NVMe disks are available),
- scitq.fetch URI now accepts some transport options, which are specified right after the protocol, notably for the custom URL `run+fastq` (used in bioinformatics only). Normally this specific URI type chooses the best transport automatically. However you can now force this choice (notably in some cases we discovered that some sources are corrupted in EBI and fine in NCBI or the other way around):
  - `run+fastq@ftp://...` : this forces EBI FTP transport,
  - `run+fastq@aspera://...` : this forces EBI Aspera transport,
  - `run+fastq@sra://...` : this forces NCBI transport (by default `ftp@aria2`, see below, else sratools)
- scitq.fetch `https` and `ftp` transport support `@aria2` option like this, replace `https://...` by `https@aria2://...`  or `ftp://...` by `ftp@aria2://...`. [aria2](https://aria2.github.io/) is a lightweight multi-protocol & multi-source command-line download utility that notably parallelize download tasks by splitting the task in several processes (NB this can cause some ethical dilemma when using public resources as it is very demanding for the resource distribution server, so this option should only be used when the alternative methods have strong issues - which is the case for NCBI sratools which are very slow).
- task resource management switched from a common folder for all tasks on a worker to specific folder per tasks with hard linked files which solves notably the issue that one task's resource could corrupt all other tasks resource (notably if one of its resources contained a file already in another resource), resources are also read-only (in dockerized tasks), it also fix the resource order issue (resource A,B is not the same as resource B,A if A and B have some shared files, so here some tasks may have resources A,B and some other B,A and it will work properly, which was not possible before)
- each worker maintains a resource database in JSON (and enable restarting scitq-worker service without having to redownload all resources),
- scitq.fetch URIs (notably for resources) supports new actions. Previously you could end a resource URI with `|gunzip` like `https://my.resource/package.gz|gunzip` (`|untar` was also available - passing the resource to `tar x` which also handle `tar`, `tar.gz` or `tar.bz2` archives). These actions are added:
  - `|unzip` for ZIP files,
  - `|mv <...>` to move the content of the resource to a subfolder (which enables finer resource management in case of shared files between resources)

Plus several scitq.fetch performance enhancements (notably for Azure storage `azure://...` ), and more robust job management (jobs are worker creation/deletion internal tasks in scitq)

## Known issues with Azure Spot deallocation

Because we use Azure Spot, instances can be deallocated which is part of the deal, but this is not yet automatically managed. Hopefully, this is a rare event **if you choose your instance flavors and regions tactically** (the deallocation stats appear when you manually start to create an instance with the create wizard with spot by checking **Run with Azure Spot discount** button, and then by clicking on **See all sizes** link - you do not have to actually launch the new instance to see the stats, choose only instance types with the lowest deallocation stat, 0-5%). If a deallocation event occurs, you will notice that the worker went offline and if you check in Azure console that the instance is deallocated. 

### What works
You have to do in that order:
- reallocate the tasks,
- recreate and delete the deallocated worker (in that order, yes, see below).

Reallocating the tasks can be done manually (in the UI or with `scitq-manage task relaunch`), but we do that directly in scitq PostgreSQL database:
```sql
-- we check that the only offline workers are the one that are deallocated (you can pause other offline workers in the UI if needed)
SELECT worker_id,name FROM worker WHERE status='offline';

BEGIN;
UPDATE task SET status='pending' WHERE task_id in (SELECT task_id FROM execution WHERE worker_id in (SELECT worker_id FROM worker WHERE status='offline') AND status IN ('accepted','running','assigned'));
UPDATE execution SET status='failed' WHERE worker_id in (SELECT worker_id FROM worker WHERE status='offline') AND status IN ('accepted','running','assigned');
COMMIT;
```

Creating a new worker / deleting the old worker is manual, use the UI or `scitq-manage worker deploy ...` and `scitq-manage worker delete ...` (if you use recruiters, do not let the recruiters recreate for you in the same region, as stated below this is generally not a good idea - this is why we create the new worker **before** deleting the old one)

### What does not work
For now, relaunching the instance from the Azure console won't work: the modification of the file system table (`/etc/fstab`) occuring during the instance preparation prevents the instance to complete its boot if relaunched. This means we should rework our instance Ansible scripts to prevent some modifications specifically in Azure (as it enable reboot with correct behavior in OVH). However this would be moderately useful as immediately relaunching an instance that was just deallocated maximizes the risk of a new deallocation event (which makes sense: Azure needs that kind of instance in this region for customers paying the full price, why would it let you have it at the discount price?). If you really need an extra worker, choose another region/flavor and create a new worker. This is likely what will be done if it is automatically managed.





<!-- CHANGELOG SPLIT MARKER -->

# v1.2 (2024-02-06)

This version introduces a new concept, the workflow library. The workflow library is built upon several functions:

- Tasks dependencies, a.k.a. requirements: a task can now depend on the correct execution of one or several tasks before becoming pending,
- Automatic worker attribution using a rule system (aka recruiters):
  - Workers are automatically deployed when a certain number of pending tasks are present,
  - Workers are dynamically reallocated (recycled) when they are no more needed for their initial task attribution.

Together, and using a new programming style, known as the workflow style, it gives maximal flexibility as tasks become more atomic, thus enabling the use of off-the-shelf dockers, permits more optimization as worker instance types (a.k.a. flavor) can be tuned for each type of task (using very quick disks for IO-intensive tasks, GPU workers for other tasks, etc.).

Look at the new workflow [documentation](https://scitq.readthedocs.io/en/latest/model/#scitq-workflow-scitqworkflow) for details.

Previous styles can still be used and/or complement the new workflow system. 

Under the hood, scitq.server code has been refactored to use the Flask app factory pattern. 

And also:

- UI was enhanced, notably the tasks UI,
- with the workflow style comes a small Text UI in Ncurse style (using URWID),
- Task model was enriched with:
- a retry that gives more flexibility on what kind of step can be retried and how many times,
- some (optional) timeouts that enable automatic failure of tasks running too long.


<!-- CHANGELOG SPLIT MARKER -->

# v1.0 (2023-07-04)

First production ready version:

- full support for OVH/Azure cloud instances,
- support for Azure/S3 storage,
- global enhancement of all performance issues discovered during the (long) rc phase,
- last issue solved: better handling of Aspera

