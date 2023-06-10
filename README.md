# scitq : a distributed scientific task queue

Item|Project site
--|--
Source|[https://github.com/gmtsciencedev/scitq](https://github.com/gmtsciencedev/scitq)
Documentation|[https://scitq.readthedocs.io/](https://scitq.readthedocs.io/)
Download|[https://pypi.org/project/scitq/](https://pypi.org/project/scitq/)
Docker images|[worker](https://hub.docker.com/repository/docker/gmtscience/scitq-worker) and [server](https://hub.docker.com/repository/docker/gmtscience/scitq-server)
Examples|[https://github.com/gmtsciencedev/scitq-examples](https://github.com/gmtsciencedev/scitq-examples)
Keywords|task, queue, job, python, distributed, science


**scitq** is a simple task queue in python. It is a distributed task queue system. While quite generalist, it was primarily designed for scientific jobs, relatively heavy tasks that can be expressed as a Unix shell instruction. It also has a specificity of relatively feebly interdependent tasks.

It has a few added capabilities apart from strict task distribution:

- First it has the capacity to manage cloud instance life cycle (as for now 
OpenStack (OVH), Azure, and others to follow) - Note that you can still use 
scitq without using that functionality, and you may use it in a mixed environment
(with one or several static server plus extra temporary servers recruited on the
cloud). 
- next, scitq has the capacity to download and upload specific data - notably 
using s3 buckets, or Azure containers as data exchange medium, but simple ftp is also possible,
and even some more exotic stuff like IBM Aspera, last a very specific protocol for 
bioinformatics dedicated to downloading public FASTQs (DNA sequence) from EBI or
 NCBI,
- it integrates nicely with docker, providing support for private registries, and wrapping docker executions in a simple yet efficient way,
- next, usage of docker is integrated so that data input slots or data output slots 
are always in the same place (/input or /output) (in non-dockerized environment,
shell environment variable INPUT and OUTPUT hold the dedicated directories for
these, so docker remains non-mandatory in scitq).

## What it does, and what it does not

**scitq** is a practical tool; it is meant as a cloud solution to dispatch a serie of tasks and monitor them. It tries to do just this job in a convenient way, not getting in the middle. In a lot of concurrent tools, once a serie of tasks is launched, there is very little you can do: this is where scitq is at its best: 
- you can pause all the tasks to fix something amiss,
- you can change the command executed for the future tasks whithout relaunching the whole serie,
- you can resume and relauch very easily any failed task (with UI or command line tools, no code needed),
- you can adjust execution parameters (like concurrency or prefetch),
- the system can be patched while a task serie is running,
- it is resilient to network troubles,
- loss of a node or temporary server loss (24 hours) should have very limited impact,
- you can mix different cloud resources in the same serie (using S3, OVH, and Azure together if that is what you want).

It provides convenient utilities such as scitq-fetch which can replace specialised tools like AWS or Azure tool and address the different storages the same way.

It does not provide:
- a workflow solution, as in its usual use case workflows are managed within tasks (notably in bioinformatics, useful programs tends to be provided as packaged workflows - no need to re-implement what is already done),
- an abstract environment: it runs vanilla docker with some mount options (or whatever option you want),
- a custom language to express the orchestration logic, yet it provides a simple python library (`scitq.lib`) which makes orchestration through python an easy task (it can be done with some shell code also)

## Introduction

**scitq** is a Task Queue system based on the following model:

- a server hosts a series of (shell) tasks to be executed,
- some workers connect to the server, fetch some tasks according to their capacity
(which is very simply managed by the maximum number of parallel process they can
handle, a.k.a. "concurrency"),
- The stdout/stderr of the command is regularly (all 5s or so) sent to the
server. A task may be executed several times (for instance if it fails). While
this is not automatic, it is easy to trigger and each execution of the task is
remembered.

### Quick start

Install:
```bash
pip install scitq
```

Now in one shell, run the server:
```
FLASK_APP=scitq.server flask run
```

In a another shell, launch the worker:
```bash
scitq-worker 127.0.0.1 1
```

In a third shell, queue some tasks:
```bash
scitq-launch echo 'Hello world!'
```
You're done!

Optionally look on http://127.0.0.1:5000/ui/ to see what happened.

Look into the [documentation](https://scitq.readthedocs.io/) to learn about the different options.


### A more elaborate example

The example above 
