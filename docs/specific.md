# Specific configurations

## Data management configuration

### Using NFS

NFS has been used since the beginning of scitq usage, but we tend to not use it anymore as NFS is very likely to create some bandwidth bottlenecks. Yet if you have a very big bandwidth this can still be a very good option. In doubt, look at S3 that will be covered later on.

NFS is hardcoded to be mounted on `/data` and as for now there is no way to change that easily as this directory will be used in the NFS server, in the workers and in the container (dockers) where your tasks are launched.

#### Changes in scitq server ansible configuration (`/etc/ansible/inventory/02-scitq` by default)

If you use NFS just set up `nfs_server` with some short name for your server and `nfs_server_address` with the IP or name with which your workers will see your NFS server. Those variables are in `[scitq:vars]` as explained in [Configure ansible components](install.md#configure-ansible-components).

Your server short name should also be added in a `[managers]` section.


#### Additional steps on scitq server

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

**/etc/exports**:
```fs
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

Just open the scitq ansible configuration file (`/etc/ansible/inventory/02-scitq` by default) and configure s3 variables in `[workers:vars]` section:

```
[workers:vars]
[...]
s3_key_id=xxxxx
s3_access_key=xxxx
s3_region=gra
s3_url=https://s3.gra.perf.cloud.ovh.net
```

You can also put these variables under more specific provider configuration (for instance you could replace `[workers:vars]` by `[ovh:vars]`), so that different provider use different s3 settings.

You must also setup S3 access on your permanent workers for root user.

## Docker private image: registry management

Docker private registry management comes with two options, the authenticated and the insecure option. 
Note that these two options are incompatible.
### authenticated registry
The authenticated option is recommanded, because you can find it off the shelf. The OVH option is very good in our experience, just check "Private Registry" in your public cloud project, it uses Harbor under the hood which is very straight forward. That said, there should not be any major difference between any type of private registry, so feel free.

In case you are unfamiliar with a private registry, this work like that: let us pretend that the URL of your registry is `3jfz86dz8.gra7.container-registry.ovh.net`:

```bash
docker login 3jfz86dz8.gra7.container-registry.ovh.net
```

You will be asked for your login and password, and this will generate an encrypted token from your login/pass which is stored in `~/.docker/config.json`:

```json
{
        "auths": {
                "3jfz86dz8.gra7.container-registry.ovh.net": {
                        "auth": "Wm9tTUtqTllkejo1MzdHNkI4MGtvMVAyNGQ5"
                }
        }
}
```

Now you can replicate this file to any server you wish to open the gates of your registry, and that's it.

To have the configuration deployed automatically with Ansible, in your provider file, like usual, the `/etc/ansible/inventory` file matching your provider, let's say for instance `/etc/ansible/inventory/ovh` and configure docker variables in `[ovh:vars]` section:

```ini
[ovh:vars]
docker_registry=3jfz86dz8.gra7.container-registry.ovh.net
docker_authentication=Wm9tTUtqTllkejo1MzdHNkI4MGtvMVAyNGQ5
[...]
```

### Insecure registry

That is the way to go with the default registry provided by Docker, but it is unadvised, mainly because this will create a bottleneck. 

First, as this is insecure, you should register the server where this registry `[managers]` in `/etc/ansible/inventory/common` (like for the NFS server), include it in the trusted IP list in the `manage-firewall.sh` and apply the security script on it as mentionned in [security](install.md#security).

Second, in your provider configuration, like above, you must add a specific docker variable:

```ini
[ovh:vars]
docker_insecure_registry=myprivateregistry.my.domain:5000
[...]
```


## Providers configuration

### OVH

#### Enabling the connection

For OVH, you must create a public cloud project with a "manager" Horizon account. This correspond to the section `Project Management` : `Users & Roles` in OVH interface. Note the Horizon username and password in a safe place (like a [keepass](https://keepass.info)).

Clicking on `...` on the right of the new user you can export the Openstack RC file. In that RC file, you fill find all the specific OpenStack environment variables starting with `OS_...` that must be added into the service definition of scitq-server (`/etc/system/systemd/scitq.service`). You must add them under the `[Service]` section of this file with `Environment=OS_...=value` lines as shown in [OVH parameters](parameters.md#ovh--openstack-provider-specific-variables).

Do not forget to apply those changes:
```bash
systemctl daemon-reload
systemctl restart scitq
```

#### Other things

##### Regions

By default, OVH allow only a few regions when you open your project, so we advise to open as many as you can (as this is free), notably GRA7, GRA11, UK1, DE1 (these are the best regions with lots of instances). This is done under `Project Management`??: `Quota and Regions`.

Then we recommand to push your quotas, but this may require a cash deposit, just ask OVH support.

##### SSH key

You must deploy the SSH key that was created in [install](install.md#create-ssh-key). For that you will need to use Horizon console, as the SSH key deploy in OVH manager interface won't make the key available in OpenStack API which we use. Just login to your [Horizon console](https://horizon.cloud.ovh.net/) with the User we created before. 

!!! note


    When using OVH Horizon, when you connect you default to a specific region (shown in the top gray line of the console, on the right of your public cloud project id). This is remembered from one login to another but may not be the right one. If you get the wrong one like an non-opened region, you will have inactive interfaces for the `Compute` sections, don't forget to change, just click on the region name and you will be able to choose the right region.


Now go to the `Compute`??: `Key pairs` section on [Horizon](https://horizon.cloud.ovh.net/project/key_pairs), and choose `Import Public Key` and copy paste the content of scitq server `/root/.ssh/id_rsa.pub` file in SSH key, give it a name, the keyname that should be set in Ansible `/etc/ansible/inventory/common` file, as noted [here](install.md#adapt-etcansibleinventorycommon). If you change this parameter it will be automatically applied at next Ansible usage.

This must be done for all the opened regions, so once you've imported the key for one region, change the region as explained in the note above and import the key to this new region, keeping the same key name. Do that iteratively for all the regions - there are not so many of them.
