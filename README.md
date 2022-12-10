# scitq : a distributed scientific task queue

Item|Project site
--|--
Source|[https://github.com/gmtsciencedev/scitq](https://github.com/gmtsciencedev/scitq)
Documentation|[https://scitq.readthedocs.io/](https://scitq.readthedocs.io/)
Download|[https://pypi.org/project/scitq/](https://pypi.org/project/scitq/)
Docker images|[worker](https://hub.docker.com/repository/docker/gmtscience/scitq-worker) and [server](https://hub.docker.com/repository/docker/gmtscience/scitq-server)
Keywords|task, queue, job, python, distributed, science


**scitq** is a simple task queue in python. It is a distributed task queue system. While quite generalist, it was primarily designed for scientific jobs, relatively heavy tasks that can be expressed as a Unix shell instruction. It also has a specificity of relatively feebly interdependent tasks.

It has a few added capabilities apart from strict task distribution:

- First it has the capacity to manage cloud instance life cycle (as for now 
OpenStack (OVH), but others to follow shortly) - Note that you can still use 
scitq without using that functionality, and you may use it in a mixed environment
(with one or several static server plus extra temporary servers recruited on the
cloud). 
- next, scitq has the capacity to download and upload specific data (notably 
using s3 buckets as data exchange medium, but simple ftp is also possible,
and even some more exotic stuff like IBM Aspera, last a very specific protocol for 
bioinformatics dedicated to downloading public FASTQs (DNA sequence) from EBI or
 NCBI),
- next, usage of docker is integrated so that data input slots or data output slots 
are always in the same place (/input or /output) (in non-dockerized environment,
shell environment variable INPUT and OUTPUT hold the dedicated directories for
these, so docker remains non-mandatory in scitq).


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

### Special thanks

Special thanks to Rémi Tan who did a great job on the UI of scitq, and also on the command line
manager (scitq-manage) and on the library resilience (scitq.lib).

Special thanks to Sibylle de Lahondès, my daughter, who created scitq favicon and logo.

And also to all people of GMT Science team who believe in this project and have
made it possible: Etienne Formstecher, Edi Prifti, Michel Laborde, Florian Plaza-Oñate,
Vadim Puller, Baptiste Hennecart (our more active user, thank you, Baptiste!) and 
Thomas Moncion. Last and not least big up to Benjamin Duplan who by his enthusiasm 
and commitment has helped us in lots of ways to achieve this project.

Many thanks also to the OVH startup team who accepted us in their program and
have thus helped this project in a major way. Special thanks to Christopher Apédo!
Thanks also to OVH support team for their help.

For GMT Science team, Raynald


### Motivation

Before coming to that we have tried several solutions at GMT Science:

- Nextflow and other BioIT specialized tools : (only Nextflow was tried) while
these tools have a lot of qualities, they have several defaults: they have their
own scripting language (which in the case of Nextflow is Groovy and is clearly
a bad point for us, debugging proved quite difficult). As debugging is difficult, 
one tends to make universal workflows with options (which are a lot easier to 
maintain), but the required flexibility is cumbersome and the result is hard to
read, and then less easy to maintain... Last in the context of Kubernetes (which
is one of two solutions when you are multicloud), Nextflow performs very poorly 
(this is due to the complexity of Kubernetes, and the fact that Kubernetes 
philosophy is rather for continuous web loads than one-shot heavy scientific 
loads)

- slurm : while slurm is certainly the king of open source HPC solutions, it is 
not installed quickly and simply. It makes sense when you buy or rent for long 
some hardware. It has the capability to operate in a mixed environment with extra
workforce on the cloud, so I heard, but it remains a complex system to set up in
my opinion. Disclaimer: we had little apetance to invest real time in slurm so 
it was never production tested by us. The simple size of documentation makes it 
impossible to grasp quickly. I think the main flaw of slurm is the complexity
of the specifications: to be able to execute any tasks based on resource
consumption (which scitq does not do: it has much (too?) simpler model of 
concurrency per worker - see below for details and now if you think this too 
simple for you, look really deeper into slurm).

- Celery : Celery is... almost perfect. It is certainly very simple (the quick
start can really work in a matter of minutes), a polished and neat solution which
has been around for years. Why not Celery then? We tried, we had a lot of successes
with Celery BUT we were disappointed in a particular occasion. But first Celery
qualities:
    - it is based on a simple concurrency model where each worker can perform 
    a fixed number of tasks in parallel. It is remarkably adapted to having 
    relatively similar servers rented on the internet (you tend to rent prototyped machines),
    yet if you have some variations, it handles them nicely. This is much simpler 
    than resource management because sometimes identifying the resource requirements
    of certain tasks may be daunting and only trial and error will tell. Nextflow 
    resource management is simply not rich enough (what if the bottleneck is disk
    speed?) and Slurm is too complex. So a simple model like that is extremely clever.
    Plus you can change each worker concurrency with a nice UI (flower).
    - You can add tasks in different ways, but usually a very simple python script
    can do the job (so no other language to learn),
    - The system is very light, super easy to deploy, and consume very little 
    resources.

Now the defaults:

  - It was invented mainly to do some simple asynchronous background tasks for 
  websites (it is the recommended way to do so with Flask), so maybe it was not 
  thought to monitor heavy scientific load: so it can handle tons of tasks (reason
  why it is very light) but it does not remember details if all went well. It tends
  to forget things (like when you relaunch Flower, you lose a lot of details).
  - It does not show remaining tasks: this seems almost unbelievable, you told the
  system to do 100 precious tasks and you cannot know how much are done, how much 
  remains, how much failed or succeeded. Flower shows part of that (but not 
  remaining tasks), but most of the information is lost if Flower crashes...
  - If you launch the tasks in a python console and keep it open, you can have
  a more stable memory and management tool for your tasks (but again if you lose
  the console, you will lose information), this is in fact the only way to know
  the remaining tasks. But it does not refresh... When you try to refresh, you
  always get the 'Pending' status, which in Celery language means: "I don't know".

Now most Celery flaws source from the fact there is no server, just a message queue. It
is a design choice and I understand it: if you already have a database for your 
website, you don't want to have another database just for your website background
management. And if you have tons of tasks maybe a database is not the right tool.

But, now this is not our problem, we're scientists. We have a reasonable amount
of very precious tasks. We can afford a database, which is less sexy than RabbitMQ
but much easier to access and query, and then we can afford a server that dispatch
the tasks (in Celery being sure that a task was acknowledged, claimed by a specific
worker is really a challenge because there is no server, so a specific algorithm 
is needed to achieve that, it can be specifically tuned but it is the source of
some useless complexity in our case where the server less paradigm is not required)

## Design choice

So we want
- A simple server with a super standard method: a simple REST server with Flask
seems perfectly suited for that, and Flask-RESTX package make the writing of such
a server easy... and autodocumented, which is almost a miracle... (Django-Rest is
not as good, we've tried both)
- The server has a main thread (nb: not a process, Flask is not process friendly)
that distribute the task, so contrarily to Celery, this is not democracy, this is
despotism, the server says, the workers obey.
- A simple database management tool: Flask use SQLAlchemy with a dedicated package,
Flask-SQLAlchemy, one more time, very easy and straight forward. Sqlite is ideal 
as a database: it is instantly created from scratch, you can copy it for later if
you wish, etc. At least that's what we thought, now with heavier loads, PostgreSQL
is recommended (concurrency has its limits with sqlite), and is now the default.
- A simple multiprocess worker (if you read multithread, re-read the sentence), 
with a clever management of output flow. Asyncio was the solution here (process.poll()
with stdout.readline() is not performant enough if you have heavy output).
- A nice UI (like Celery Flower) : now this nice UI must update its display very
often you do not want to reload the page to refresh (Flower is smart enough for 
that): I did write a very small game in Python with Flask and I had had a go with
SocketIO with quite a success, so I tried here and it fits the case. I compared
with basic jQuery and it performed better so scitq uses SocketIO (and a nice
Flask package: Flask-SocketIO)

For now, UI and server live in the same Flask application which makes deploy
very easy.
