# Parameters

## scitq-server parameters

These parameters are environment variable that should be defined when launching `scitq-server`. Unless a specific install was done, this is done in `/etc/scitq.conf` service file (an exemple is provided is `templates/production` directory), using `KEY=value` so for instance the [PATH](#path) parameter will be defined like this:
```ini
PATH=/usr/bin:/usr/local/bin
[...]
```

!!! note
    Before version 1.0rc7, these parameters were set directly in `/etc/systemd/system/scitq.service` file.

### PATH
The usual PATH setup. Not really important for the server, it must contain the PATH where scitq-server command was deployed with [setup.py install](install.md#install-python-package) and is very likely `/usr/local/bin` which is contained by default.

### FLASK_APP
This is required by Flask itself, it should be `scitq.server`, which is set by default, do not change that.

### SCITQ_PRODUCTION
This is the hack that SCITQ is using to know it is not used with the development server, in short, you should always keep it defined to 1 in that file. Do not change that parameter.

### SQLALCHEMY_DATABASE_URI
This is required by SQLAlchemy (more specifically flask-sqlalchemy), it can be either sqlite or PostgreSQL but sqlite should be avoided except for simple tests. In theory any SQLAlchemy compatible database should work but this has not been tested, and as for now, there is some raw SQL code at several places in the code... Yes we know it is bad... However an effort was made so that this code should work at least for mariadb/mysql but again this has never been tested.

For details look at [https://flask-sqlalchemy.palletsprojects.com/en/2.x/config/]. Default value of `postgresql://root@/scitq` should suit the vast majority.

### SQLALCHEMY_POOL_SIZE
This is optionnally used by SQLAlchemy for performance optimization. Default should be fine for most users. Consider  [SCITQ_SERVER_PROCESS](#scitq_server_process) parameter to increase performance. 

### LOG_FILE
Default to `/var/log/scitq/scitq.log`, it should be a path ending with a file in `.log`. It will be rotated automatically creating some extra files so keeping it in a dedicated directory like here is recommanded.

### LOG_FILE_MAX_SIZE
At which size the log file should be rotated (in bytes).

### LOG_FILE_KEEP
How many rotated log files should we keep.

### SCITQ_SERVER
This is the one parameter that should always be changed and adapted to the IP address or name where the worker will be able to connect to the server.

Note that it is only used if workers are deployed with ansible, through scitq-server. This is covered in [usage](usage.md) and it is the default behaviour so it is recommand to change the default of `127.0.0.1`.

### SCITQ_SERVER_PROCESS
This is the number of uwsgi workers (note that it is completely unrelated to SCITQ workers, this is the way uwsgi calls its acting processes). The default (10) should be fine for most setups but if you have huge computation, you may want to increase the number of worker. Be aware of the total number of connections (see [SQLALCHEMY_POOL_SIZE](#sqlalchemy_pool_size)) and adjust the maximum connections in PostgreSQL setup.

### PYTHONPATH
This is the PYTHONPATH variable we all know. It should not be present in this file but due to a bug in Ubuntu 20.04 default python setup, it must be added so that locally built packages can be used, that is used with [SCITQ_SRC]. It should not be useful in other context of use.
NB this can be removed in Ubuntu 24.04.

### OVH / OpenStack provider specific variables

These variable are only to be set if you use scitq ansible part (i.e. automatic lifecycle management) and you use OVH or another OpenStack provider.

These are not present in template and should added manually in `/etc/scitq.conf`:

```ini
OS_AUTH_URL=https://auth.cloud.ovh.net/v3
OS_PROJECT_ID=0123456789abcdef0123456789abcdef
OS_PROJECT_NAME="123456789012345"
OS_USER_DOMAIN_NAME="Default"
OS_PROJECT_DOMAIN_ID="default"
OS_USERNAME="user-xxxxxxxxxxx"
OS_PASSWORD="SECRETPASSWORD123"
OS_REGION_NAME="GRA7"
OS_INTERFACE=public
OS_IDENTITY_API_VERSION=3
```

These variables are defined in Horizon rc file that is provided by OVH - when you log into Horizon this file can be exported clicking on [this link](https://horizon.cloud.ovh.net/project/api_access/openrc/).

Only the password must be set up manually as it is not included in the file associated to OS_PASSWORD variable.

!!! note

    The Open RC file that is proposed using OVH Manager is incomplete and lack several variable: use the one from the Horizon manager as pecified above.

In order to use dynamic flavor discovery, also known as [protofilters](manage.md#using-protofilters-new-in-v123), some specific variables must be added, notably some specific OVH API variables, see [availability variables](specific.md#ovh-availability), [OVH updater](specific.md#ovh-updater), and optionnally [preferred region](specific.md#ovh-preferred-region).


### Azure provider specific variables

These variable are only to be set if you use scitq ansible part (i.e. automatic lifecycle management) and you use Azure.

These are not present in template and should added manually in `/etc/scitq.conf`:

```ini
AZURE_SUBSCRIPTION_ID=000000-0000-0000-0000-000000000000
AZURE_CLIENT_ID=000000-0000-0000-0000-000000000000
AZURE_SECRET=XXXXXXXXXXXXXXXXX
AZURE_TENANT=000000-0000-0000-0000-000000000000
```

The real values are given in [Azure connection procedure](specific.md#azure).

In order to use dynamic flavor discovery, also known as [protofilters](manage.md#using-protofilters-new-in-v123), some specific variables must be added, see [availability variables](specific.md#azure-availability), [Azure updater](specific.md#azure-updater), and optionnally [preferred region](specific.md#azure-preferred-region).


## scitq-worker parameters

These parameters are environment variable that should be defined when launching `scitq-worker`. Unless a specific install was done, this is done in `/etc/systemd/system/scitq-worker.service` service file (an exemple is provided is `templates` directory) in `[Service]` section, using `Environment=...`.

Note that these parameters are only available when deploying the worker manually, see [installation](install.md#manual-worker-deployment). With Ansible automated deployment, this is set using `add_scitq.j2` template and it should not be modified.

### PATH
see [scitq-server](#path). Do not change that.

### SCITQ_SERVER
The IP address or name (not the URL) where scitq-server can be reached. This is the one parameter that should always be changed. On a permanent server, it is even advised to set SCITQ_SERVER environment variable globally at system level so that all scitq commands executed on the system know where to go.

## Ansible parameters

These parameters are used when you deploy workers automatically using internal SCITQ ansible configuration. Two default files exists which should not be modified: `/etc/ansible/inventory/01-scitq-default` and `/etc/ansible/inventory/scitq-inventory`. These files are copied from internal templates by `scitq-manage ansible install`. It always safe to retype this command when unsure. 
You should only modify another file, `/etc/ansible/inventory/02-scitq`. This organization will enable upgrades in a sage way.

A typical `/etc/ansible/inventory/02-scitq` file could look like this:
```ini
[scitq:vars]
nfs_server=bioit
nfs_server_address=bioit.gmt.bio
keyname=alpha
scitq_src=/home/ubuntu/public-pytq

[managers]
bioit

[workers:vars]
swap_proportion = 0.1
docker_registry=zzzzzzzz.graX.container-registry.ovh.net
docker_authentication=wwwwwwwwwwwwwwwwwwwwww
ssh_public_key=/root/.ssh/id_rsa.pub

```

If you are familiar with Ansible, you may notice this is a static group definition with some variables.

Let's go through the different sections and variables of that file. In what follows mandatory variables will have in asterix between parenthesis added in their paragraph title, obviously you will not add the parenthesis and star in the `/etc/scitq.conf` file.

### Some group definitions

Before diving into the file, you must be aware that several ansible groups exists in SCITQ ansible configuration:

`scitq`
:   this is the top-level group, it includes all the other groups.

`managers`
:   this group includes static SCITQ machines, like SCITQ server and optionnally the NFS server. While S3 is strongly advised, NFS is stille possible and the NFS server should be included in that group (so that workers are granted access to it by iptable)

`workers`
:   this group includes all workers managed by Ansible (static not Ansible managed workers could be defined in a new specific group such as `static-workers` to differentiate them).

`ovh`
:   a subgroup of `workers` consisting in OVH public cloud workers.

`azure`
:   a subgroup of `workers` consisting in Azure cloud workers.


### [scitq:vars]

This is SCITQ top level variables definition section, these variables will apply to all hosts, managers and workers, in SCITQ.

#### nfs_server

This variable is used by scitq Ansible playbooks to reach the server where NFS server is installed, first to add `/etc/exports.d/...conf` files to extend automatically NFS usage to a new worker, second to chage iptable rules and allow the IP of the worker.

In short, you should set it to the name that ssh can use to reach your NFS server from the SCITQ server. You should not set it if you do not use NFS.

nfs_ variables are also explained in [specific](specific.md#using-nfs)

#### nfs_server_address

This variable is used in workers to mount NFS `/data` share. It should be set as the FQDN of your NFS server. It should not be set if you do not use NFS.

#### keyname (*)

This variable is used by Ansible code to deploy you SSH key on new workers. It should be the **public** SSH root key of SCITQ server, and it should be deployed under this name on your provider console, and at least for OVH, deployed for all the different regions you will use.

This is mandatory, you should always have this variable properly set.

At GMT, we use the short server name as the name of the key, as we have several SCITQ servers, but you may use any name.

#### scitq_src

This variable is not mandatory and should only be set if you deploy scitq by source. The only reason why you would like to do that is if you are testing a new feature (like a bug correction) before submitting. In that case, you should add the source somewhere on your SCITQ server, you should deploy on the server with this modified source going into the directory of the source and typing `python3 -m pip install .` (if you use Ubuntu default python3, any python will do provided it is the one used in your services, see [PATH](#path) and [PYTHONPATH](#pythonpath)), and you should set the complete path on SCITQ server to this variable (so that the `src` directory is in the folder designated by this variable), so that the workers are deployed with the same modified source.

#### SSH key (Azure)

This defaults to `/root/.ssh/id_rsa.pub`. Change it only in `/etc/ansible/inventory/O2-scitq` if you have your root SSH key in a non standard place. This is only used by Azure deploy code (you must change Ansible SSH key setting as well using Ansible standard settings). Note that OVH handle SSH key in a entirely different way and is not affected by this.

NB In Ubuntu 24.04, the default SSH public key is changed so this should be set to something like:

```ini
ssh_public_key=/root/.ssh/id_edXXXXXX.pub
```

### [managers]

The only reason you may want to add a new member of the managers group is if you have NFS. So add in here the same name that you entered for nfs_server (just the plain name on a new line, not nfs_server=...), look at the typical `02-scitq` above.

### [workers:vars]

The workers specific section.

!!! note

    previous s3_... variables are no more used as `rclone` is used instead. See [Install](./install.md).

#### swap_proportion

This is non mandatory but highly advised. This setup will be used to use this proportion of /scratch folder (which should be automatically assigned to the largest partition on workers) to set up a swap file. 

Be aware that memory issues are deadly in workers, they endup with the scary OOM (out of memory) error in kernel logs (the kernel just randomly kill a process to prevent the server complete crash), which is currently undetected in scitq-worker code (it would be needed to parse the kernel logs to do so AFAIK), which make debuging them a real pain...

The simple remedy to that is to add swap with this variable, this will turn memory issue into high IOwait %, a lot less deadly, and you can see this in the UI and in the database, and adjust things (by reducing concurrency or renting a bigger instance).

With NVMe instances, as these NVMe harddrives are the quickest on the market, you can even rely on this to run a process with a higher memory need than the current memory of the worker. It may not be extremely efficient, but it works. That is what we do in Kraken2 example in [scitq-examples/kraken2](https://github.com/gmtsciencedev/scitq-examples/tree/main/kraken2).

0.1 is fine for most usage, including the one pointed at just above.

#### docker_ variables

This is only required if you use a Docker private registry. These variables are set in your own `~/.docker/config.json`:

`docker_registry` corresponds to the name of the entry in `auths`,
`docker_authentication` corresponds to the `auth` attribute of this entry.

This is further explained in [specific](specific.md#docker-private-image-registry-management).

### other groups

You may also have variables for subgroup like `[ovh:vars]` for instance if you wanted to have a specific docker or s3 setting for OVH workers, but this is not advised as it will complexify management overall.


