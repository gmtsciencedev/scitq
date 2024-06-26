<!-- CHANGELOG SPLIT MARKER -->

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
For now, relaunching the instance from the Azure console won't work: the modification of the file system table (`/etc/fstab`) occuring during the instance preparation prevents the instance to complete its boot if relaunched. This means we should rework our instance Ansible scripts to prevent some modifications specifically in Azure (as it enable reboot with correct behaviour in OVH). However this would be moderately useful as immediately relaunching an instance that was just deallocated maximizes the risk of a new deallocation event (which makes sense: Azure needs that kind of instance in this region for customers paying the full price, why would it let you have it at the discount price?). If you really need an extra worker, choose another region/flavor and create a new worker. This is likely what will be done if it is automatically managed.





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

