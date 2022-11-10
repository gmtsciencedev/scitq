# Specific configurations

## Data management configuration

### Using NFS

NFS has been used since the beginning of pytq usage, but we tend to not use it anymore as NFS is very likely to create some bandwidth bottlenecks. Yet if you have a very big bandwidth this can still be a very good option. In doubt, look at S3 that will be covered later on.

NFS is hardcoded to be mounted on `/data` and as for now there is no way to change that easily as this directory will be used in the NFS server, in the workers and in the container (dockers) where your tasks are launched.

#### Changes in PYTQ server `/etc/ansible/inventory/common`

If you use NFS just set up `nfs_server` with some short name for your server and `nfs_server_address` with the IP or name with which your workers will see your NFS server. Those variables are in `[all:vars]`.

Your server short name should also be added in `[managers]` section together, a line just before the localhost definition for the PYTQ server itself which looks like that:
`localhost ansible_connection=local keyname=mykeyname`

In the provided file, the exemple server shortname is `mynfsserver` and the long server name is `mynfsserver.my.domain` (but it could be an IP address as well).


#### Additional steps on PYTQ server

You should also add the short name of your nfs in your ssh config file, edit or create `/root/.ssh/config` and add those lines:
```init
Host mynfsserver
Hostname mynfsserver.my.domain
```
(of course adapt mynfsserver and mynfsserver.my.domain to the real name and FQDN name of your NFS server)

Next copy your public ssh key to the server, either using this:
```bash
ssh-copy-id mynfsserver
```
Or if you cannot ssh as root with a password on this server, adding the content of your public key (`/root/.ssh/id_rsa.pub`) in `/root/.ssh/authorized_keys`.

In the end, you should be able to ssh directly to your NFS server with:
```bash
ssh mynfsserver
```
and login without any password.

#### Additionnal steps on NFS server

On the NFS server itself, you should install NFS of course:

```bash
apt install nfs-server
systemctl enable nfs-server
systemctl start nfs-server
```

Next you should change your `/etc/exports` file to add some `/data` export. 
A minimal exports file could be:

```/etc/exports
/data   127.0.0.1(rw,sync,no_subtree_check,no_root_squash) 
```

Also create an `/etc/exports.d` directory. This will be used by ansible code to extend your NFS configuration to new workers automatically.

Don't forget to apply `/etc/exports` changes with:

```bash
exportfs -a
```

### AWS (or other's) S3

S3 is the new *de facto* standard for data exchange. It is recommanded as it can be purchased from a variety of places (AWS obviously, but almost everybody (but Microsoft...) is selling S3 now, notably OVH has much cheaper options than AWS) and it scales remarkably. 

Be careful not to be too cheap, the cheapest providers (e.g. [Wasabi](https://wasabi.com/)) were never tested, they never answered our demands to know if their model fit our usage which is not very clear. They should work for what we know.

Here we will focus on worker access to S3 and we suppose you have already setup some standard access to your S3 on some computers (maybe your own computer), as this will prove useful to finally get the results of your workers or to push some resources or inputs (covered in [usage](usage.md)).


#### With Ansible

Just open the `/etc/ansible/inventory` file matching your provider, let's say for instance `/etc/ansible/inventory/ovh` and configure s3 variables in `[ovh:vars]` section:

```
[ovh:vars]
[...]
s3_key_id=xxxxx
s3_access_key=xxxx
s3_region=gra
s3_url=https://s3.gra.perf.cloud.ovh.net
```

You must also setup S3 access on your permanent workers, and be careful to set your AWS_ENDPOINT_URL variable in pytq-worker service `/etc/systemd/system/pytq-worker.service` definition as stated in [parameters](parameters.md#aws_endpoint_url). If you change this file do not forget to reload and apply:

```bash
systemctl daemon-reload
systemctl restart pytq-worker
```

## Providers configuration

### OVH

#### Enabling the connection

For OVH, you must create a public cloud project with a "manager" Horizon account. This correspond to the section `Project Management` : `Users & Roles` in OVH interface. Note the Horizon username and password in a safe place (like a [keepass](https://keepass.info)).

Clicking on `...` on the right of the new user you can export the Openstack RC file. In that RC file, you fill find all the specific OpenStack environment variables starting with `OS_...` that must be added into the service definition of pytq-server (`/etc/system/systemd/pytq.service`). You must add them under the `[Service]` section of this file with `Environment=OS_...=value` lines as shown in [OVH parameters](parameters.md#ovh--openstack-provider-specific-variables).

Do not forget to apply those changes:
```bash
systemctl daemon-reload
systemctl restart pytq
```

#### Other things

##### Regions

By default, OVH allow only a few regions when you open your project, so we advise to open as many as you can (as this is free), notably GRA7, GRA11, UK1, DE1 (these are the best regions with lots of instances). This is done under `Project Management` : `Quota and Regions`.

Then we recommand to push your quotas, but this may require a cash deposit, just ask OVH support.

##### SSH key

You must deploy the SSH key that was created in [install](install.md#create-ssh-key). For that you will need to use Horizon console, as the SSH key deploy in OVH manager interface won't make the key available in OpenStack API which we use. Just login to your [Horizon console](https://horizon.cloud.ovh.net/) with the User we created before. 

!!! note


    When using OVH Horizon, when you connect you default to a specific region (shown in the top gray line of the console, on the right of your public cloud project id). This is remembered from one login to another but may not be the right one. If you get the wrong one like an non-opened region, you will have inactive interfaces for the `Compute` sections, don't forget to change, just click on the region name and you will be able to choose the right region.


Now go to the `Compute` : `Key pairs` section on [Horizon](https://horizon.cloud.ovh.net/project/key_pairs), and choose `Import Public Key` and copy paste the content of PYTQ server `/root/.ssh/id_rsa.pub` file in SSH key, give it a name, the keyname that should be set in Ansible `/etc/ansible/inventory/common` file, as noted [here](install.md#adapt-etcansibleinventorycommon). If you change this parameter it will be automatically applied at next Ansible usage.

This must be done for all the opened regions, so once you've imported the key for one region, change the region as explained in the note above and import the key to this new region, keeping the same key name. Do that iteratively for all the regions - there are not so many of them.
