## Motivation

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
that): initially we had chosen socket.io for the UI however when we decided to deploy
scitq in a serious way (with a wsgi server and not Flask development server), we were
not able not configure socket.io in a multi-worker uwsgi setup, so we went back to 
jQuery which is sufficient in our case.

For now, UI and server live in the same Flask application which makes deploy
very easy.


## History

scitq has been used since 2022 in GMT Science where it began instantly being used in production in the R&D team. Since then, it has been the orchestration tool used for all purposes. Little more than a poor Celery clone with a REST server and a database, it gradually enriched with proper docker integration, then OVH lifecycle, then S3 integration, etc.

Please find here the contributor list:
- Thomas Moncion provided an important piece of data that is internal to GMT Science but enable large scale usage of scitq, with the integration and stratification of all public data,
- Rémi Tan was an early contributor to the UI of scitq, and also on the command line manager (scitq-manage).
- Sibylle de Lahondès, contributed scitq favicon and logo.
- Baptiste Hennecart contributed as a beta tester and primary user,
- GMT Science management, staff and share holders, havee been supportive of the project and the fact that it is an opensource code, not necessarily an easy choice for a startup.

Many thanks also to the OVH startup team who accepted us in their program and
have thus helped this project in a major way.
Thanks also to Microsoft who accepted us in their Startup Founders program.


