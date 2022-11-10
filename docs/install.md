# Installation

PYTQ is simple system and the [quick start](../#quick-start) can really be used. However in a production
environment you will want to do a little more than that:

- install pytq-server as a service,
- deploy and configure the ansible code to connect to your provider.

!!! note


    Unless specifically mentionned, all the following commands must be done *as root*.

## How many servers should you use?

The usual setup is a dedicated server for pytq-server and the use of ansible
to recruit and deploy workers on the cloud. We will cover that in detail just
after.

It is also common to have a permanent worker (like a dedicated server). This is
usually deployed manually and we will cover that as well. You may of course have
several of them.

There are just a few discouraged setup:

* having a worker on the server where pytq-server is running. In case the load become high, this is a recipe for disaster, the controlling server will be unavailable and you will have a hard time to cool down everyone. The good news is that pytq-server is reasonably light and will require a very simple instance (2 vcores, 2GB and a few GB of hard drive is perfectly fine). But we recommand that it should be more or less dedicated to that usage. 
* having an all-in-one server install: this should be used only for tests or debug.
* sqlite should not be used in any serious install - it is intended for test only - use PostgreSQL as we will explain just after.


For what follow and to clarify words, we will design as:

* pytq-server : PYTQ central service and software,
* PYTQ server : the instance or physical server on which pytq-server is installed,
* pytq-worker : a PYTQ service and software that takes its order from pytq-server and execute them,
* worker : the instance(s) or physical server(s) on which pytq-worker is installed,


## pytq-server

### preliminary

You need simply the python setuptools. With a Ubuntu distribution just do that:
```bash
apt install python3 python3-pip
```

And make sure typing `python` launch python3, may be like this:
```bash
ln -s /usr/bin/python3 /usr/local/bin/python
```
(this is notably required for sqlite_inventory.py script in ansible)

#### PostgreSQL

`pytq-server` requires a relational database, sqlite or PostgreSQL are supported
but PostgreSQL is recommanded for production.

```bash
apt install postgresql
sudo -u postgres createuser -d root
createdb pytq
```

#### A directory for logs

By default logs will go into `/var/log/pytq`, just make sure the directory exists:
```bash
mkdir /var/log/pytq
```

### install python package

Go to the `src` directory of the code and just do *as root*:
```bash
cd /root/
git clone https://github.com/gmtsciencedev/pytq.git
cd pytq/src
pyton ./setup.py install
```

### install the service

Go to the `templates` directory, and copy `template_service.tpl`:

```bash
cp template_service.tpl /etc/systemd/system/pytq.service
```

Now edit `/etc/systemd/system/pytq.service` to suit your need. Keeping 
most variables as they are should be fine, *except PYTQ_SERVER variable*:

* PYTQ_SERVER variable is used by workers deployed by ansible to contact the server, so it must be the public name or IP address of the server or at least some network address or name accessible to workers (like a private LAN on the cloud). The default value 127.0.0.1 must be changed. In doubt put the public IP address of pytq-server dedicated server.

Look into [Parameters](parameters.md#pytq-server-parameters) to have more details about the parameters that can be set in this file.

```bash
systemctl daemon-reload
systemctl enable pytq
systemctl start pytq
```

Look with `systemctl status pytq` that all is fine and that should be it. In case of trouble, you'll find details in `/var/log/pytq/pytq.log` file or whatever file you have specified in [LOG_FILE](parameters.md#log_file) parameter. 

## Ansible

!!! note

     Ansible is only needed if you deploy workers on the cloud automatically. If workers are deployed manually you can just bypass entirely Ansible configuration.

First Ansible code is yet quite simple and has a certain number of hardcoded things, which should not raise any major issue on a dedicated server. There are three of them:

* this repository should be put in `/root/pytq` directory (so that `src` complete path is `/root/pytq/src`),
* the ansible part should be linked (preferably) or copied to `/root/ansible`,
* ansible configuration `/etc/ansible` should be a link to `/root/ansible/etc`.

So if the repository is in `/root` (if not move it now), just do:
```bash
cd /root
ln -s pytq/ansible 
ln -s pytq/ansible/etc /etc/ansible 
```

### install ansible itself

```bash
apt-add-repository ppa:ansible/ansible
apt-get install -y ansible python3-pip python3-apt
pip3 install openstacksdk==0.61
```

!!! note


    with openstacksdk>0.61 you may get the error :

    *volumes is not found. openstack.compute.v2.server.Server objects do not support setting arbitrary keys through the dict interface.*

    Which is extremely frustrating as it is almost completely meaningless and very poorly 
    documented, except here: [http://lists.openstack.org/pipermail/openstack-i18n/2022-May.txt](http://lists.openstack.org/pipermail/openstack-i18n/2022-May.txt)

### Install custom ansible collections

Just type in those two lines to add some required ansible collections and roles (collections and roles are the two form of ansible plugins that exists, we happen to use one of each):

```bash
ansible-galaxy install rolehippie.mdadm
ansible-galaxy collection install openstack.cloud
```

### Create ssh key

Just type in (keep all the default answers everywhere, no password on the key else you will have some trouble later on):
```bash
ssh-keygen
```

This will create `/root/.ssh/id_rsa` and `/root/.ssh/id_rsa.pub`. If you are unfamiliar with ssh, the first file is your private key and should be kept private and secret.

### Configure ansible components

Ansible configurable parts are in `/etc/ansible/inventory` (that should be the same as `/root/pytq/ansible/etc/inventory` if you followed this guide)

#### Adapt /etc/ansible/inventory/common

In `[all:vars]`, you will find `nfs_...` variables and `pytq_src` variable. If you do not plan to setup a common NFS server between your workers, you may safely remove `nfs_...` lines. For some details, please read [Using NFS](specific.md#using-nfs).

`pytq_src` must be set to the path where the repository is setup, it default to `/root/pytq` (so that the `src` directory is in `/root/pytq`). It is advised to let it like that. It will be used by Ansible to distribute the worker package to the different workers.

In `[managers]` section, the PYTQ server definition for Ansible, which looks like that:
`localhost ansible_connection=local keyname=mykeyname` 
should be changed for the `keyname` parameter. This point is covered more in detail in [Providers configuration](specific.md#providers-configuration) but this is simple logic. We need to gain SSH access on our workers for Ansible to be able to reach them, thus the SSH key that we created above must be deployed on our workers when creating a new instance, which is very classic in cloud deploy. This requires that the SSH key is uploaded on the provider console and is given a specific name - likely the shortname of your PYTQ server - which should then be assigned to this keyname variable.

#### Adapt `/etc/ansible/inventory/ovh` and others

Have a quick look at the other files in `/etc/ansible/inventory`. Overall these files are pretty safe to be left unchanged unless you need a specific feature. 

The followin options should not be changed to avoid Python and SSH trouble in Ansible with Ubuntu:

```
[...:vars]
ansible_python_interpreter=/usr/bin/env python3
ansible_user=ubuntu
ansible_ssh_common_args='-o StrictHostKeyChecking=no'
```

#### About `/etc/ansible/inventory/sqlite_inventory.py` 

If you are not interested in implementation details, just leave this file here and that will be fine.

When we deploy a new worker there are a lot of information we must remember in Ansible to make a correct install, with some specificity as regards the worker configuration. This is called a `host var` in Ansible language, unfortunately Ansible default solution to store these values is very limited (and discouraged by Ansible itself), these `host var` are supposedly dynamically fetched from some dynamic code (likely from the provider itself), however this is a bit difficult if you have several providers (hence the requirement to have an Ansible host group per provider), and at least for some provider where the API are not so quick (or paid for) you do not wish to query them too frequently. This file maintains a small sqlite database with all the required information, it is extremely simple and quick.

### What's next?

PYTQ Ansible code is really about deploying in the cloud, so you should set up a [provider](specific.md#providers-configuration).

You should set up the [security](#security): first it is a reasonable idea when operating in a public cloud, second PYTQ Ansible has not been tested *at all* without, so it is very likely to fail at some point: You have been warned.

## Manual worker deployment

!!! note

    As explained for Ansible, this step is not mandatory. It may be ignored completely if all your workers are deployed in the cloud using Ansible, it may replace completely Ansible configuration if you deploy completely manually or it may be used aside Ansible to have some permanent work force available and yet recruit additional work force when needed.

### Install PYTQ package

Just like for pytq-server you need simply the python setuptools. With a Ubuntu distribution just do that:
```bash
apt install python3 python3-pip
```

Next download and install PYTQ package:

```bash
git clone https://github.com/gmtsciencedev/pytq.git
cd pytq/src
pyton ./setup.py install
```

### Configure and start pytq-worker service

Next copy the service template to systemd directory:
```bash
cp templates/template_worker_service.tpl /etc/systemd/system/pytq-worker.service
```

And edit `/etc/systemd/system/pytq-worker.service` to suit your needs.

In this file you will find these lines under the `[Service]` section:
```ini
[Service]
Environment=PATH=/usr/bin:/usr/local/bin
Environment=AWS_ENDPOINT_URL=https://s3.gra.perf.cloud.ovh.net
Environment=PYTQ_SERVER=127.0.0.1
```
PYTQ_SERVER *must* be modified to your pytq-server IP address or DNS name (not the URL, the name or address). It may even be a good idea to set this PYTQ_SERVER variable into your /etc/environment global setting so that PYTQ commands on the system can reach the right PYTQ server automatically (not mandatory, whereas PYTQ_SERVER is mandatory in `/etc/systemd/system/pytq-worker.service`)

PATH can be safely left as it is (unless you have an alternative PATH when you deployed the PYTQ package), AWS_ENDPOINT_URL is only needed if you use [S3](specific.md#aws-or-others-s3).

See [worker parameters](parameters.md#pytq-worker-parameters) for details.

Next reload and launch the worker:
```bash
systemctl daemon-reload
systemctl enable pytq-worker
systemctl start pytq-worker
```

See how it goes with `systemctl status pytq-worker`. The journal/log can be consulted with `journalctl -u pytq-worker` (better pipe that in a less, it may be quite long).

## Security

PYTQ approach to security is very simple. It relies completely on iptables, so it is quite well secured from any outsider and completely trust any insider. An insider is root on all PYTQ server (at least on any worker he has access to), he may rent any number of instance available in your provider account, etc.

Being secure against outsiders is pretty obvious, so we will not explain that, but we would like to explain why we did nothing for the insiders. The reason for that are the following (we did not start like that):
- first, once you have an install working, cloning an independant setup is very easy, so that is what we do to restrict access: for instance we have data falling under "Health Data Storage" requirement - a French law (Hébergement de Données de Santé -  very much like the future European EHDS regulation) that must have a limited access and we have a separate PYTQ server, a separate public cloud projet, and a separate S3 storage and that's it. 
- second, most publicly available docker are built thinking root user will be used, changing them is work, sometimes relatively hard work, it is costly and not really interesting if you do not reuse frequently this particular docker. Beeing root into the docker makes you very powerful, and the plasticity requirement for the tasks render user power restrictions in that context exceptionnally difficult to implement.

So much for explanations, let us dive into it.

### initial security setup

The idea is to prevent all access except from fixed IP addresses. Typicalling we use a rerooting OpenVPN setup (an SSH bastion would do the same) and access to this machine grant access to PYTQ related servers (that is PYTQ server and NFS server or permanent workers if you have any). All these machines should be included in the list of trusted IPs.  

Once you are clear on this list of trusted IPs, adapt the script `manage-firewall.sh` in the `script` folder.
Once your script is fine, on all the PYTQ related servers, do:
```bash
sh manage-firewall.sh
apt install iptables-persistent
```

Upon the package install you will be proposed to save current rules, answer yes. You're done.

If you want to resave the rules after install:
```bash
iptables-save > /etc/iptables/rules.v4
ip6tables-save > /etc/iptables/rules.v6
```

## Define a storage component

If your tasks generate some kind of data output, which is very likely this is the last mandatory step of the install. With current PYTQ version, you have two choices: [S3](specific.md#aws-or-others-s3) or [NFS](specific.md#using-nfs). S3 is recommanded, it is cheaper and does not have NFS bottleneck issue, but if you have a nice NFS (with a generous bandwidth and low latency disks), it is perfectly fine.


## What's next?

Well, juste [use it](usage.md) !
