# Installation

scitq is simple system as the [quick start](../#quick-start) shows, however in a production
environment you will want to do a little more than that:

- install scitq-server as a service,
- deploy and configure the ansible code to connect to your provider,
- set up some extra services like an S3 or NFS storage and maybe a docker registry.

This sounds a lot more complex than the quick start, but this is really explained carefully here and together it brings a really efficient setup. None of it is mandatory and you can start very simply.

!!! note

    Unless specifically mentionned, all the following commands must be done *as root*.

## How many servers should you use?

The usual setup is a dedicated server for scitq-server and the use of ansible
to recruit and deploy workers on the cloud. We will cover that in detail just
after.

It is also common to have a permanent worker (like a dedicated server). This is
usually deployed manually and we will cover that as well. You may of course have
several of them.

There are just a few discouraged setup:

* having a worker on the server where scitq-server is running. In case the load become high, this is a recipe for disaster, the controlling server will be unavailable and you will have a hard time to cool down everyone. The good news is that scitq-server is reasonably light and will require a very simple instance (2 vcores, 2GB and a few GB of hard drive is perfectly fine). But we recommand that it should be more or less dedicated to that usage. 
* having an all-in-one server install: this should be used only for tests or debug.
* sqlite should not be used in any serious install - it is intended for test only - use PostgreSQL as we will explain just after.


For what follow and to clarify words, we will design as:

* scitq-server : scitq central service and software,
* scitq server : the instance or physical server on which scitq-server is installed,
* scitq-worker : a scitq service and software that takes its order from scitq-server and execute them,
* worker : the instance(s) or physical server(s) on which scitq-worker is installed,

If you are upgrading, go to [upgrading](#upgrading) chapter.

## scitq-server

### preliminary

You need simply the python setuptools. With a Ubuntu distribution just do that:
```bash
apt install python3 python3-pip rclone
```

#### PostgreSQL

`scitq-server` requires a relational database, sqlite or PostgreSQL are supported
but PostgreSQL is recommanded for production.

```bash
apt install postgresql
sudo -u postgres createuser -d root
createdb scitq
```

#### A directory for logs

By default logs will go into `/var/log/scitq`, just make sure the directory exists:
```bash
mkdir /var/log/scitq
```

### install python package

The now default way to install is by pip:
```bash
pip3 install --upgrade pip setuptools
pip3 install scitq
```

NB on newer Ubuntu, notably 24.04 LTS and above, you'll need to specify `pip install --break-system-packages ...` instead of `pip install ...`. If the server is dedicated, it makes sense to install package out of a virtual environment.

If you want to install by source:
```bash
cd /root/
pip3 install --upgrade pip setuptools
git clone https://github.com/gmtsciencedev/scitq.git
cd scitq
python3 -m pip install .
```

### install the service

Since v1.0rc5, uwsgi is the default deploy mode. If you want to keep old style deploy go to [next chapter](#old-style-deploy). Old style deploy uses Flask development server and is used in debug or simple setups. It does not depends upon uwsgi and is more straight forward to understand but it behaves poorly under heavy load.

Since v1.0rc8 there are two different service for scitq which enable a much better performance under heavy load.

Copy the production template 
```bash
curl https://raw.githubusercontent.com/gmtsciencedev/scitq/main/templates/production/scitq-main.service -o /etc/systemd/system/scitq-main.service
curl https://raw.githubusercontent.com/gmtsciencedev/scitq/main/templates/production/scitq-queue.service -o /etc/systemd/system/scitq-queue.service
curl https://raw.githubusercontent.com/gmtsciencedev/scitq/main/templates/production/scitq.target -o /etc/systemd/system/scitq-target
```
(this template_uwsgi_service.tpl is also in `/root/scitq/templates` it you installed by source)

If this is you first time install you will have to create an `/etc/scitq.conf`:

curl https://raw.githubusercontent.com/gmtsciencedev/scitq/main/templates/production/scitq.conf -o /etc/scitq.conf


Install pyuwsgi:
```bash
python3 -m pip install pyuwsgi
```

Now edit `/etc/scitq.conf` to suit your need. Keeping 
most variables as they are should be fine, *except SCITQ_SERVER variable*:

* SCITQ_SERVER variable is used by workers deployed by ansible to contact the server, so it must be the public name or IP address of the server or at least some network address or name accessible to workers (like a private LAN on the cloud). The default value 127.0.0.1 must be changed. In doubt put the public IP address of scitq-server dedicated server.

Look into [Parameters](parameters.md#scitq-server-parameters) to have more details about the parameters that can be set in this file. Notably you will need to place the cloud provider(s) parameters and secrets that make CLI work (and SCITQ ansible code too).

!!! note 
    if you upgrade from an old style deploy (v1.0rc4 or below - or a newer version in old style deploy), remove scitq.service
    ```bash
    systemctl stop scitq.service
    systemctl disable scitq.service
    mv /etc/systemd/system/scitq.service /root/
    ```
    You may want to recover all your `Environment=` lines to put them in `/etc/scitq.conf` (but removing `Environment=` and keeping only what is next)

```bash
mkdir /var/log/scitq
systemctl daemon-reload
systemctl enable scitq-main
systemctl enable scitq-queue
systemctl start scitq.target
```

Look with `systemctl status scitq` that all is fine and that should be it. In case of trouble, you'll find details in `/var/log/scitq/scitq.log` file or whatever file you have specified in [LOG_FILE](parameters.md#log_file) parameter. 

!!! note
    About workers: in SCITQ documentation what we call a worker is a working node in the pseudo HPC cluster managed by SCITQ. It is not a uwsgi worker, which is a forking subprocess of uwsgi to serve requests. We will always refer to uwsgi workers as uwsgi workers, worker without uwsgi prefixed mean SCITQ node executing the scitq-worker process. The number of uwsgi workers is defined in /etc/scitq.conf, with SCITQ_SERVER_PROCESS paramater (it defaults to 10 which should be enough in most cases).

#### Under the hood in uwsgi configuration

When scitq.server is imported, the default behaviour is to start the background() thread which dispatches tasks to workers. Since v1.0rc8, it is possible to define an environment variable, SCITQ_PRODUCTION, which should be set to 1, so that scitq.server does not launch background() thread when imported. This enable uwsgi to run Flask app without launching the background() thread (which is what occurs in scitq-main service), while in the scitq-queue service, scitq.server is imported but only the background() thread is launched, the Flask app is inactive.

With this system, scitq-queue logs are in `/var/log/scitq/scitq-queue.log` (QUEUE_LOG_FILE paramater in /etc/scitq.conf), and scitq-main logs can be reached by `journalctl -u scitq-main` (which is the same as for the worker service on SCITQ workers, `journalctl -u scitq-worker`). 


## Ansible

!!! note

     Ansible is only needed if you deploy workers on the cloud automatically. If workers are deployed manually you can just bypass entirely Ansible configuration.

If you installed scitq before the `1.0b3` version, this section is very different, see [upgrading](#upgrading) for details (and much cleaner now).

### install ansible itself

It is now recommanded to have ansible in its own virtual environment to prevent package collision with scitq itself. 

For Ubuntu 20.04 LTS:
```bash
apt-get install -y python3-pip python3-venv python3-apt
python3 -m venv /root/ansibleenv
source /root/ansibleenv/bin/activate
pip install ansible
ln -s /root/ansibleenv/bin/ansible* /usr/local/bin/
```

For Ubuntu 24.04 LTS:
```bash
add-apt-repository ppa:deadsnakes/ppa -y
apt install python3.10 python3.10-venv python3.10-dev
python3.10 -m venv /root/ansibleenv
source /root/ansibleenv/bin/activate
pip install ansible
ln -s /root/ansibleenv/bin/ansible* /usr/local/bin/
```
NB:  there are issue with some of the packages we use starting from python 3.11


!!! note

    All ansible collections must be done within the virtualenv.


### Install custom ansible collections

Just type in those two lines to add some required ansible collections and roles (collections and roles are the two form of ansible plugins that exists, we happen to use one of each):

Remember to activate ansible virtualenv before this install, in doubt activate it:
```bash
source /root/ansibleenv/bin/activate
```

```bash
ansible-galaxy install rolehippie.mdadm
pip install openstacksdk==0.61
ansible-galaxy collection install openstack.cloud:1.8.0
```
!!! note


    with openstacksdk>0.61 you may get the error :

    *volumes is not found. openstack.compute.v2.server.Server objects do not support setting arbitrary keys through the dict interface.*

    Which is extremely frustrating as it is almost completely meaningless and very poorly 
    documented, except here: [http://lists.openstack.org/pipermail/openstack-i18n/2022-May.txt](http://lists.openstack.org/pipermail/openstack-i18n/2022-May.txt)



#### Azure ansible collection


Remember to activate ansible virtualenv before this install, in doubt activate it:
```bash
source /root/ansibleenv/bin/activate
```

```bash
ansible-galaxy collection install azure.azcollection:1.19
pip install -r ~/.ansible/collections/ansible_collections/azure/azcollection/requirements-azure.txt
```

#### Other ansible collections

```bash
ansible-galaxy collection install community.general
```

### Create ssh key

Just type in (keep all the default answers everywhere, no password on the key else you will have some trouble later on):
```bash
ssh-keygen
```

This will create `/root/.ssh/id_rsa` and `/root/.ssh/id_rsa.pub` (these are the older SSH file names, on newer distrib, they are named `/root/.ssh/id_edXXXXX` and `/root/.ssh/id_edXXXXX.pub`). If you are unfamiliar with ssh, the first file is your private key and should be kept private and secret.

### Configure ansible components

First, you must attach scitq ansible configuration to ansible. You just need to add a specific inventory source, modifying the `inventory=...` line in `ansible.cfg` in the `[defaults]` section (by default, `/etc/ansible/ansible.cfg`), by adding a specific directory for scitq:
`inventory=...,/etc/ansible/inventory`

In the same `[defaults]` section you need to update the python interpreter to account for the virtual environment of ansible:
`interpreter_python=/root/ansibleenv/bin/python`

Also in `[inventory]` section, it is a good idea to enable the (normaly defaults) inventory plugins in the following order:
```ini
[inventory]
enable_plugins=host_list, script, auto, ini, yaml, toml
...
```

In the end this simple `/etc/ansible/ansible.cfg` should be enough:
```ini
[defaults]
inventory=/etc/ansible/inventory
interpreter_python=/root/ansibleenv/bin/python

[inventory]
enable_plugins=host_list, script, auto, ini, yaml, toml
```


Now copy the default files with:
```bash
scitq-manage ansible install
```

If you have an unusual Ansible configuration or do not wish to use `/etc/ansible/inventory` directory, add a `-p` argument:

```bash
scitq-manage ansible install -p /path/to/my/inventory
```
(simply do not forget to add that specific path in your inventory variable in your ansible configuration)

And create a sample file `/etc/ansible/inventory/02-scitq`:

```ini
[scitq:vars]
keyname=scitq
```

This is the minimal file. 

This `keyname` is linked to the SSH key we just created above. You will need to deploy this key in your cloud provider console, as explained in more detail in [Providers configuration](specific.md#providers-configuration), so as to let Ansible gain access to newly deployed workers. The `keyname` is just some short name under which this key will be called in your cloud provider infrastructure. Replace `scitq` by any value you see fit - we have several scitq servers so we go for each server shortname here. Be sure you match the name of your key under your provider configuration.

If you want to deploy by source, add a scitq_src variable pointing to the path the source live: if you followed this guide and installed scitq source in `/root/scitq`, set it as:

`scitq_src=/root/scitq`

Last, this `[scitq:vars]` section is also where NFS parameters can be set if you plan to use NFS, see [using NFS](specific.md#using-nfs) for details. If that is so, you will also need to add your NFS server to the managers group, creating a subsection `[managers]` with the shortname of your server.



Next you may need a `[workers:vars]` for the `docker_...` variables if you use a private registry, see [docker private registry](specific.md#docker-private-image-registry-management).
 
!!! note

    Up to version `v1.2.x`, the `[workers:vars]` had also to contain some variables for S3 or Azure storage so that workers can access the cloud storage components. This is handle directly by `rclone` now so it is not required anymore. It is recommanded to remove those settings however they do not interfere with rclone, so leaving them will have no consequences (other than inducing some confusion for someone seeing those settings).

So that a final `/etc/ansible/inventory/02-scitq` could look like this:

```ini
[scitq:vars]
keyname=scitq
nfs_server=mynfsserver
nfs_server_address=mynfsserver.mycompany.com
scitq_src=/root/scitq

[managers]
mynfsserver

[workers:vars]
docker_registry=xxxxxxxxxx.container-registry.ovh.net
docker_authentication=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```
NB: remember not to set any variable you do not need, like the scitq_src variable which is only to deploy by source on workers. Also creating a `[managers]` section is not useful here if you do not use NFS.

#### About `scitq-inventory` 

If you are not interested in implementation details, just leave this file here and that will be fine.

When we deploy a new worker there are a lot of information we must remember in Ansible to make a correct install, with some specificity as regards the worker configuration. This is called a `host var` in Ansible language, unfortunately Ansible default solution to store these values is very limited (and discouraged by Ansible itself), these `host var` are supposedly dynamically fetched from some dynamic code (likely from the provider itself), however this is a bit difficult if you have several providers (hence the requirement to have an Ansible host group per provider), and at least for some provider where the API are not so quick (or paid for) you do not wish to query them too frequently. This script use the database to store and manage these values and is simple and quick. It replaces the previous script `sqlite_inventory.py` which was using a separate dedicated sqlite database.

### What's next?

There are four optional tasks which are recommanded and all require some modification of Ansible file `/etc/ansible/inventory/02-scitq`:

- scitq Ansible code is really about deploying in the cloud, so you should set up a [provider](specific.md#providers-configuration).
- You should set up the [security](#security) as it is a reasonable idea when operating in a public cloud.
- You should add some [storage](#define-a-storage-component).
- Unless you use only public docker images, you should deploy a docker [private registry](specific.md#docker-private-image-registry-management).


In this file we will finish with manual worker deployment and security.

## Manual worker deployment

!!! note

    This step is not mandatory, not even particularly recommanded: it all depends on your needs. It may be ignored completely if all your workers are deployed in the cloud using Ansible, it may replace completely Ansible configuration if you deploy completely manually or it may be used aside Ansible to have some permanent work force available and yet recruit additional cloud work force when needed.

### Install scitq package

Just like for scitq-server you need simply the python setuptools. With a Ubuntu distribution just do that:
```bash
apt install python3 python3-pip unzip pigz aria2 rclone
pip3 install --upgrade pip
pip3 install --upgrade setuptools
```

Next download and install scitq package:
```
pip3 install scitq
```

Or via source:
```bash
git clone https://github.com/gmtsciencedev/scitq.git
cd scitq
python -m pip install .
```


### Configure and start scitq-worker service

Next copy the service template to systemd directory:
```bash
curl https://raw.githubusercontent.com/gmtsciencedev/scitq/main/templates/template_worker_service.tpl -o /etc/systemd/system/scitq-worker.service
```

And edit `/etc/systemd/system/scitq-worker.service` to suit your needs.

In this file you will find these lines under the `[Service]` section:
```ini
[Service]
Environment=PATH=/usr/bin:/usr/local/bin
Environment=SCITQ_SERVER=127.0.0.1
```
SCITQ_SERVER *must* be modified to your scitq-server IP address or DNS name (not the URL, the name or address). It may even be a good idea to set this SCITQ_SERVER variable into your /etc/environment global setting so that scitq commands on the system can reach the right scitq server automatically (not mandatory, whereas SCITQ_SERVER is mandatory in `/etc/systemd/system/scitq-worker.service`)

PATH can be safely left as it is (unless you have an alternative PATH when you deployed the scitq package).

See [worker parameters](parameters.md#scitq-worker-parameters) for details.

Next reload and launch the worker:
```bash
systemctl daemon-reload
systemctl enable scitq-worker
systemctl start scitq-worker
```

See how it goes with `systemctl status scitq-worker`. The journal/log can be consulted with `journalctl -u scitq-worker` (better pipe that in a less, it may be quite long).

You'll need also to install rclone configuration from server:
(you need to have SCITQ_SERVER environment variable correctly set to the name or IP of your scitq server)
```sh
scitq-manage config rclone --install
```

## Security

scitq approach to security is very simple. It relies completely on iptables, so it is quite well secured from any outsider and completely trust any insider. An insider is root on all scitq server (at least on any worker he has access to), he may rent any number of instance available in your provider account, etc.

Being secure against outsiders is pretty obvious, but we would like to explain why we did nothing for the insiders:

- first, once you have an install working, cloning an independant setup is very easy, so that is what we do to restrict access: we have data falling under "Health Data Storage" requirement - a French law (Hébergement de Données de Santé -  very much like the future European EHDS regulation) that must have a limited access and we have a separate scitq server, a separate public cloud projet, and a separate S3 storage and that's it. 

- second, most publicly available docker are built thinking root user will be used, changing them is work, sometimes relatively hard work, it is costly and not really interesting if you do not reuse frequently this particular docker. Beeing root into the docker makes you very powerful, and the plasticity requirement for the tasks render user power restrictions in that context exceptionnally difficult to implement.

So much for explanations, let us dive into it.

### initial security setup

The idea is to prevent all access except from fixed IP addresses. Typicalling we use a rerooting OpenVPN setup (an SSH bastion would do the same) and access to this machine grant access to scitq related servers (that is scitq server and NFS server or permanent workers if you have any). All these machines should be included in the list of trusted IPs.  

Once you are clear on this list of trusted IPs, adapt the script `manage-firewall.sh` in the `script` folder.
Once your script is fine, on all the scitq related servers, do:
```bash
sh manage-firewall.sh
apt install iptables-persistent
```

Upon the package install you will be proposed to save current rules, answer yes. You're done.

If you do some manual change later on and you want to resave the rules without reinstalling iptables-persistent, just do:
```bash
iptables-save > /etc/iptables/rules.v4
ip6tables-save > /etc/iptables/rules.v6
```

## Define a storage component

If your tasks generate some kind of data output, which is very likely this is the last mandatory step of the install. With current scitq version, you will need to setup the storage component with `rclone` using `rclone --config /etc/rclone.conf config`, see https://rclone.org/docs/ for details. The `--config /etc/rclone.conf` option which is not standard is because scitq uses a central configuration which is not rclone default (you can otherwise copy rclone generated configuration from the default `~/.config/rclone/rclone.conf` to `/etc/rclone.conf`). [NFS](specific.md#using-nfs) is no more recommanded due to bottleneck issue and permission trouble.

In case you have specific docker images that you would want to use, configure a [private registry](specific.md#docker-private-image-registry-management).


## Upgrading

### Upgrading from 1.0b2 and below

#### Ansible configuration 

In 1.0b2 and below, Ansible configuration was directly inserted in scitq source, it now lives in different files. 

- Copy all of previous ansible configuration in a safe place, with `cp -r /root/scitq/ansible /root/oldansible` (or `cp -r /root/pytq/ansible /root/oldansible` for version versions <1.0b2),
- Install new version `pip install --upgrade scitq pip setuptools`,
- Remove ansible link in `/etc` so that `/etc/ansible` is a plain directory,
- Copy back your ansible base configuration : `cp /root/oldansible/etc/ansible.cfg /etc/ansible/`
- Install the files with `scitq-manage ansible install`
- Create `/etc/ansible/inventory/02-scitq` and report in that file all the specific variables:
    - All the specific variables that were in `/root/oldansible/etc/common` :  `keyname`, and possibly `nfs_server`, `nfs_server_address` should be defined in that file under `[scitq:vars]`. If you still plan to deploy by source code (which may enable testing some code modification), add also the `scitq_src` variable with the path in which lives the code (in the path you set, you must have the `src` directory present as an immediate subdirectory) - not that if you do not do that, deployment will be done by pip, which is now the default.
    - All the specific variables that were in `/root/oldansible/etc/ovh` should now go under `[ovh:vars]` in that file (so just copy paste the existing `[ovh:vars]` paragraph in that file)

#### Service configuration

If you come from a version strictly below 1.0b2:

- Next change the service `/etc/systemd/system/pytq.service`:
    - First stop and remove the service `systemctl stop pytq` and `systemctl disable pytq`,
    - Rename the file to `/etc/systemd/system/scitq.service`,
    - Change the line `Description=pytq` by `Description=scitq`,
    - Replace line `Environment=FLASK_APP=...` by `Environment=FLASK_APP=scitq.server`
    - Replace line `Environment=PYTQ_SERVER=...` by `Environment=SCITQ_SERVER=...`
    - Update by `systemctl daemon-reload` and `systemctl enable scitq` and `systemctl start scitq`
- For any manually deployed worker, it is the same procedure (still if you come from strictly below 1.0b2):
    - First stop and remove the service `systemctl stop pytq-worker` and `systemctl disable pytq-worker`,
    - Rename the file to `/etc/systemd/system/scitq-worker.service`,
    - Change the line `Description=pytq-worker` by `Description=scitq-worker`,
    - Change the line `ExecStart=pytq-worker -s running ...` by `ExecStart=scitq-worker -s running ...`,
    - Update by `systemctl daemon-reload` and `systemctl enable scitq-worker` and `systemctl start scitq-worker`

If you come from 1.0b2 just restart the services `systemctl restart scitq` and `systemctl restart scitq-worker`.

### Upgrading from 1.0b3 and above

With pip (replace `pip3` by the path to your pip, if you are not using Ubuntu plain install):
```bash
pip3 install --upgrade scitq
```

With git (replace `/root/scitq` with the path to your source if you did not keep the standard install path)
```bash
cd /root/scitq
git pull
rm -fr build dist
python3 -m pip install .
```

#### For a server only

Upgrade database (mandatory when upgrading to v1.2 or above):
```
scitq-manage db upgrade
```

Update Ansible base config:
```
scitq-manage ansible install
```
(add with -p paramater if you have used a custom inventory directory)


Relaunch the services:
```
systemctl restart scitq-main scitq-queue
```

#### For a worker

```
systemctl restart scitq-worker
```

## What's next?

Well, juste [use it](usage.md) !
