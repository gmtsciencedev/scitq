# PYTQ

## Quick start

### Install

Once you git cloned the code, do in the same directory as this file:
```bash
python ./setup.py install
```

### Lauch the server
```bash
FLASK_APP=pytq.pytq flask run
```
The server can be accessed on port 5000, http://localhost:5000/ gives access to
the swagger interface with all the API exposed. http://localhost:5000/ui/ gives
access to the UI.

PS have a look at template_service.tpl to see all the different options that can
be set with environment variables. 

### Launch some workers
```bash
pytq-worker <IPaddress of server> <concurrency>
```
Concurrency is the default level of parallelism of the worker, but it can be
changed from the UI, and once the server know of the worker, it tells it how 
parallel it must be.

### Launch the tasks

#### Launching with pytq-launch
It is very simple:

```bash
pytq-launch echo 'Hello world!'
```

It is advised however: 
- first to put your job in a batch, so that different task groups can be 
distributed to different worker pools, 
- second to use a docker so that the task environment is perfectly define.

So a more realistic example would be:
```bash
pytq-launch -b test -d alpine:latest echo 'Hello world!'
```

Type `pytq-launch -h` for all the options.

Some production tips for NFS usage (in NFS usage, NFS folder is mounted as /data
in dockers):
NFS usage requires setting up NFS in one server and changing some group vars in
Ansible configuration, see ansible/etc/common, variables nfs_server and 
nfs_server_address.
- use small shell script so that as to make your task relaunchable:
```bash
pytq-launch -b test -d mydocker sh -c "rm -fr /data/work/task1 && \
mkdir -p /data/work/task1 && cd /data/work/task1 && do_mystuff task1"
```
- If you generate a list of task with a shell loop, like this, use double
quotes so that variable are interpreted at command creation, that is when 
pytq-launch is executed, not when your task is executed:
```bash
for i in $(seq 1 100)
do
pytq-launch -b test -d mydocker sh -c "rm -fr /data/work/task$i && \
mkdir -p /data/work/task$i && cd /data/work/task$i && do_mystuff task$i"
done
```
- If you wand to have some variable interpreted within your docker context, 
escape $, like this:
```bash
for i in $(seq 1 100)
do
pytq-launch -b test -d mydocker sh -c "rm -fr /data/work/task$i && \
mkdir -p /data/work/task$i && cd /data/work/task$i && for j in \$(seq 1 5); do \
do_mystuff task$i -try \$j && break; done"
done
```

#### Creating tasks programmatically
```python
from pytq.lib import *
s=Server('127.0.0.1')
s.task_create('<some shell stuff>')
```

pytq.lib provide a simple REST client which can consume all the API. It has a
few goodies of its own:
- it is partially asynchronous: if the server goes down, it will wait (in the
background if it is possible), and maybe provide a lazy object as the answer.
- it fixes the datetime objects (which does not exists in REST).

NB: pytq.client is the worker, don't import that.


#### Using CPU in pytq-launch

New: you can use $CPU variable in your tasks, this variable is set in task execution
context (so you'll want to escape the dollar in pytq-launch, like above). The 
$CPU variable is set to the number of CPU (thread) in the worker divided by the
concurrency, rounded down. So for instance if you have a 20 thread worker with
concurrency 6, $CPU will be evaluated as 3. So you could do something like that:

```bash
for i in $(seq 1 100)
do
pytq-launch -b housecleaning -d ghcr.io/kasperskytte/docker-pigz:master -p \$CPU -r /data/work/task$i
done
```

NB [ghcr.io/kasperskytte/docker-pigz:master](https://github.com/KasperSkytte/docker-pigz) is a minimal docker that launch pigz.

#### Launching with pytq-launch when using S3 ressources
S3 ressources usage is newer than NFS. It relies on S3 authentification variable 
set in ansible/etc/ovh (or manual or some other provider you might use) at group 
var level. It requires -i/-o flags with pytq-launch.
- -i is for inputs (a space separated list of input URIs, see below), those will
be downloaded in /input directory in docker context before the command is launched,
or in the directory specified in INPUT environment variable out of docker context,
- -o is for output (a unique URI of a folder), where some results will be uploaded,
after the command is finished. The results must be saved in /output folder in 
docker context or in the folder specified in OUTPUT environment variable out of
docker context.

These folders are unique for each execution, so no need to erase and prepare them
as with NFS.

URIs: several type of URI are available,
- s3://bucker/path : s3 file or folder, requires s3 authentication variables as
explained above (authentication must be deployed in workers so setting up authentication
on the VM where pytq server is running is useless),
- ftp://... : a classical FTP URL, anonymous, so unlikely to work for output,
- file://... : a file path local to the worker, useful if you deployed a specific
file share on worker, that is different from NFS, or you wish to use NFS with -i
and -o options, not often use in production, more for tests and debug,
- run+fastq://.../ : a custom URI dedicated to bioinformatics FASTQ studies on
public data, if you provide a RUN accession number (SRA or ENA), this will 
download the FASTQs associated with the RUN.

This is an actual example from GMT Science:
```bash
for i in $(seq 1 8)
do
pytq-launch -b s5810 -n mgshot_S5810Nr$i \
-i "s3://clinical/S5810/mgshot_S5810Nr$i.1.fastq.gz s3://clinical/S5810/mgshot_S5810Nr$i.2.fastq.gz" \
-o "s3://clinical/results/S5810Nr$i/" \
-d registry.gmt.bio:5000/biomscope-pipeline-oral:0.4 \
sh -c "pipeline_rnd.sh -e -c /input mgshot_S5810Nr$i; returncode=\$?;  cd /input; rm *.fastq.gz; cp * /output/ ; exit \$returncode"
done
```

You can mix also NFS and input/output style (here no S3 so no need for S3 authentication)
```bash
for i in SRR890934 SRR890935 SRR890936 SRR890937 SRR890938 SRR890939
do
pytq-launch -b SRA21 -n $i \
-i "run+fastq/$i/" \
-d registry.gmt.bio:5000/biomscope-pipeline:0.8.1 \
sh -c "pipeline_rnd.sh -e -c /input $i; returncode=\$?;  rm /input/*.fastq.gz; cp /input/* /data/results/SRA21/$i/; exit \$returncode"
done
```



Very similarly to '-i', pytq can now use '-r' to download resources shared 
between all tasks on a worker (contrarily to an input (-i), a resource (-r) will
only be downloaded once per worker):
```bash
for i in $(seq 1 100)
do
pytq-launch -b test -d mydocker -r "s3://database/my.db" \
  -i "s3://data/sample_$i/sample_$i.dat" -o "s3://results/sample_$i/" \
  sh -c "do_mystuff --db /resource/my.db --output /output/ /input/sample_$i.dat"
done
```

NB: there is no resource cleaning now, neither for resources, nor for docker 
images at worker level. It may be implemented later on. Nothing prevents you from
manually cleaning resources, but beware that the worker will still think they are
there unless you restart the pytq worker service (systemctl restart pytq-worker),
which will erase the resource memory.

Alternatively to listing all inputs as a single -i option with a space separated
input list, you can specify multiple -i/-r options to add several inputs or 
resources. -o option must however be unique.

For resources, you can also specify `|gunzip` at the end of the resource URL
so that the resource is unzipped (with pigz -d) after download:
```bash
for i in $(seq 1 100)
do
pytq-launch -b test -d mydocker -r "s3://database/my.db.gz|gunzip" \
  -i "s3://data/sample_$i/sample_$i.dat" -o "s3://results/sample_$i/" \
  sh -c "do_mystuff --db /resource/my.db --output /output/ /input/sample_$i.dat"
done
```

### Swap
Most of the disk space of the worker is allocated to /scratch, by default a
small proportion (default 0.1, that is 10%) will be affected to a swapfile.
This make memory overallocation less dramatic, but unless the instances disk
are very quick (i1-xx instances in OVH for instance), this should be avoided.

Watch for IOwait, if it goes up, it's likely your swapping.

### Prefetch
Prefetch is a simple worker parameter to tune things. It is only useful in case 
some inputs are slow to come: you may want in that case to allow some extra tasks 
to be allocated even when all running slots (concurrency) are full, so that 
download may occur in advance. 

It has a drawback: such allocated tasks are not easily re-allocated
to another worker (this is done by setting the execution as failed and 
relaunching the task), which is not an issue when there are lots of tasks but 
may limit the plasticity of task allocation in other cases. For this reason, 
it is unadvised to push this parameter too high (1 should do just fine). It 
defaults to 0, no prefetch, tasks input are only downloaded just before the task 
is run.

### Installation POSTGRESQL

- To install the package type in the shell:
```bash
sudo apt install postgresql
```

With the installation a new user will be added, called postgres.

- Update postgresql: 
The configuration and the databases will be saved ( the folder Datas/ is saved).
You can delete the old version by using in the folder Postgres :
```bash
sudo ./unistall-postgresql 
```
You can install a new version in the following website
https://www.enterprisedb.com/products-services-training/pgdownload
and run :
```bash
sudo ./postgresql-version-linux-x64.run
```
And you will need to confirm the existence of Datas/ with his path of the folder while the installation.

- Configuration:

Postgresql is a server that allows you to connect to different databases. By default, only the postgres user can connect.
So the administration operations will be done under postgres user. To connect as postgres , you will need to type :
```bash
sudo -i -u postgres
Password:
```

Maybe the authentification will return you an error. Use the command chmod ug+r~/.bashrc before connexion will fix the issue.

To be in the POSTGRESQL Shell, type :
psql

You will obtain something like that:
```bash
psql (13.1-1)
Type "help" for help.

postgres=#
```

Survival guide for psql client:
```bash
\h	print a reminder  of SQL commands 
\?	print a reminder  of psql commands
\g	or semi-colon at the end of an instruction to execute an request
\q	to quit
\l	lists all present databases
\du	lists all roles (user or group)
\c database_name name_uer	to connect at the database of <database_name> with the user <username>
\lt	lists all the tables in the current database
set search_path to <my_schema>;	
\d	lists all the tables  in the current schema
\d table_name_or_view	description of the table <table_name> (columns, type…) or of the the view name_view
\d+ table_name_or_view entire description (with comments!) of the table <table_name> (columns, type…) or of the the view name_view with his source code
\dn	list the entire schema of the current database 
\h ALTER TABLE	print help for the ALTER TABLE command
```
- Create a POSTGRESQL user

Quick version, but not safe :
You can create an user with the following command in psql shell:
```bash
postgres=# CREATE ROLE <username> LOGIN;
```

By default, the new user has no rights. You can allow him to create new database. 
```bash
postgres=# ALTER ROLE <username> CREATEDB;
```

And you can assign a password to the user :
```bash
postgres=# ALTER ROLE <username> WITH ENCRYPTED PASSWORD 'password';
```

You can create a database for an user by typing the following commands:
```bash
postgres=# CREATE DATABASE <database_name> OWNER <username>;
```
Now you can quit
```bash
postgres=# \q
```
And you can reconnect.
```bash
postgres@ubuntu:~$ psql databse_name
```
You will get
```bash
database_name=>
```

- environnement variable:
You can select in your ~/.profile the following connexion parameters : PGUSER and PGHOST. Useful  if your database isn't on an localhost server
```bash
export PGHOST=<hostname>
export PGUSER=<username>
```

Then you connect to your database by using:
```bash
psql <database_name>
```
And if you define PGDATABASE, you connect by using:
```bash 
psql
```


- Graphic clients for postgresql:
The clients allows you to manage yours databases with a graphic and colored tool.
You can download pgadmin4 or pgadmin3.

- To connect python to your database:
You have to go in default_settings.py and modify the SQLALCHEMY_DATABASE_URI
SQLALCHEMY_DATABASE_URI = os.environ.get('SQLALCHEMY_DATABASE_URI','postgresql://<username>:<password>@<server>/<db_name>')



### MIGRATION (https://www.compose.com/articles/schema-migrations-with-alembic-python-and-postgresql/)
You will need to install Alembic.

Alembic is designed to work with SQLAlchemy and provides excellent migration support. Alembic works by managing change management scripts. Whenever you modify your models you create (or let Alembic create for you) a Python script that Alembic can invoke and upgrade your actual database schema.

First verify that alembic is installed properly.

To prepare your project to work with alembic type alembic init alembic in your project's directory.

That will create a sub-directory called alembic that contains the following files and directories:
```bash
(alembic-tour-de-force)(G)/alembic-tour-de-force > tree alembic
alembic  
├── README
├── env.py
├── script.py.mako
└── versions
```
The README file is not very interesting. You can add your own instrutions for how to upgrade. The env.py is a Python script that performas a lot of the heavy lifting and script.py.mako is a template for generating migration scripts. You don't call them directly, but use the alembic command-line tool. Finally, the versions directory is where your migration scripts go. Another important file that is generated is the alembic.ini file in your project's directory. You need to set the sqlalchemy.url to point to your database. You can leave the rest as is or modify to your liking

Generate a baseline script
Let's generate a baseline script for the current state of the database. The baseline script can generate a database schema from scratch by using :
```bash
alembic revision -m "revision_name"
```

This generates an empty script with upgrade() and downgrade() functions.

``` Alembic upgrade head ``` : This command makes sure that the database is up to date with the most recent revision.

Auto-generate a Migration Script:
Alembic's killer feature is its ability to auto-generate the migration scripts. Alembic looks at the current models to compare them with current DB schema and figures out what changed.

Before you can use the auto-generation you need to tell alembic where to find your model's metadata. This is done in the env.py file. Here is the relevant section where I added the last line:
```python
# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = models.Base.metadata  
```
Auto-generating the migration script uses the --autogenerate flag to the alembic revision command:
``` bash 
alembic revision --autogenerate -m "add tablename table"
```
EXample of script on the previous link.

Limitations of Auto-generation
Auto-generation is magical but it has some limits you need to be aware of. First of all if you rename a table or a column alembic will consider it a removal and addition of a new table/column. You will lose all the data. You should manually adjust the aut-generated script and replace the drop/create with an explicit rename operation that will preserve the data.

You should name all your constraints. Alembic can't handle anonymously named constraints.

There are some unimplemented features that auto-generation will detect and handle in the future:

Some free-standing constraint additions and removals, like CHECK, PRIMARY KEY
Sequence additions and removals

SQL Generation
You may not be comfortable directly running a migration script via alembic upgrade or you may not be sure what the impact is going to be on your database. Alembic has for this purpose special offline mode where it generate a SQL file with all the SQL statements that represent the upgrade script instead of executing them. Then, you can observe the SQL file, make sure it doesn't do anything fishy and also perform the migration using the SQL file.

The command is ```alembic upgrade --sql```. You need to provide also a start and end revision.

Multi-Stage Upgrade
Naive schema changes may drop data. For example, if you look at the SQL generated above you'll note that the root_cause column was dropped from the bug table. In order to preserve the data you'll have to perform a multi-stage migration. Here's how it can work for the root_cause case. First step just add the root_cause table and the root_cause_id foreign key, but DON'T remove the root_cause column just yet. Perform the migration and the code will still read the root cause information from the root_cause column in the bug table. Then, the information in the root_cause column of the bug table will be inserted into the new root_cause table. The code will be changed to read from the "root_cause" table. At this point the root_cause column is not used anymore and can be dropped in a second migration.

This approach may be necessary even if there is no concern about data loss. For example, in large distributed systems it is difficult if not impossible to perform synchronized changes to the DB schema and the code on all the servers. In these case every breaking change, must be done in a multi-stage approach (unless the system is designed to handle temporary mismatches and can recover gracefully later).




# Production install

## Procedure

### Install PYTQ service

```bash
cd flask
python ./setup.py install
cp pytq/flaskq/template_service.tpl /etc/systemd/system/pytq.service
```

Edit `/etc/systemd/system/pytq.service`, change the value, and add your provider(s)
identification token.

Then:
```bash
mkdir /var/log/pytq
mkdir /var/lib/pytq
systemctl daemon-reload
systemctl enable pytq.service
systemctl start pytq.service
```

Do not forget to install ansible part (see ansible/README.md) if you want to 
recruit some VM within PYTQ. 

#### OVH (openstack)

You should add these entry:
The values are found in openstack RC file that you can download, plus the 
Openstack password that OVH gave you when you created this user.

```text
Environment=OS_AUTH_URL=https://auth.cloud.ovh.net/v3
Environment=OS_PROJECT_ID=<this is called OS_TENANT_ID in OVH file>
Environment=OS_PROJECT_NAME=<this is called OS_TENANT_NAME in OVH file>
Environment=OS_USER_DOMAIN_NAME="Default"
Environment=OS_PROJECT_DOMAIN_ID="default"
Environment=OS_USERNAME="<this is called OS_USERNAME in OVH file>"
Environment=OS_PASSWORD="<not in the file, you should know this one, else you can regenerate clicking on the three dots right hand of user in OVH management console>"
Environment=OS_REGION_NAME="<see below>"
Environment=OS_INTERFACE=public
Environment=OS_IDENTITY_API_VERSION=3
```

#### Regions
In OVH when you start a project you are assigned to a region. You can in principle
activate any number of regions you want. You have some big regions like GRA11 or
DE1 or UK1, and you have smaller like GRA7 or BHS or SBG. This is important if
you recruit lots of big or specific VMs which won't be available in all regions.
In this case you should open as many region as you can.

As soon as you have several regions, the OS_REGION_NAME parameter is of little 
importance as you will chose at runtime the region where you recruit. Put here
your preferred region, but be relaxed about the choice. In doubt chose GRA11, a
pretty big region with lots of refs.

#### About SSH keys
SSH Keys must be added in Horizon console, not in OVH main management console:
https://horizon.cloud.ovh.net/project/key_pairs

You must also install the keys in all the region that you will use (repeat for
each region).

# History

## versions
- v0.1 initial version, NFS oriented
- v0.2 S3 support added (--input, --output, --resource)
## TODO
- add an offline memory to worker (about running tasks and resource)
- make client.Executor instances resilient to worker crash (not possible AFAIK)
