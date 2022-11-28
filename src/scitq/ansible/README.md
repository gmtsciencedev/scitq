# Ansible

ANSIBLE is an adminisys automation tool. It can also trigger VM creation in
a number of different systems and make a versatile solution in that field.

## Server preparation
Before installing you should consider your server security. As for now, scitq
operate in a closed environment where all nodes blindly trust the server, and
the server trust the nodes and send them tasks to execute. This may change in
the future.

For this reason, the server should use a firewall. IPtables is suggested and you
will find a script to set some initial rules (manager-firewall.sh). These rules
must be adapted to fit the IP of your VPN or your bastion to reach the controler
server.
To make those rules permanent, you can run this script each time you start the 
server. In Ubuntu, at least, it is easier to run it once and to install 
iptables-persistent:

```bash
apt install iptables-persistent
```
The install will propose to save rules.

## Install

```
apt-add-repository ppa:ansible/ansible
apt-get install -y ansible python3-pip python3-apt
pip3 install openstacksdk==0.61
```
(with older ansible os-server module, pip3 install shade was required, no more 
the case)

/!\ with openstacksdk>0.61 you may get the error :
'volumes is not found. openstack.compute.v2.server.Server objects do not support setting arbitrary keys through the dict interface.'
Which is extremely frustrating as completely meaningless and very poorly 
documented, except here: http://lists.openstack.org/pipermail/openstack-i18n/2022-May.txt

Next copy or link the etc directory of this folder as /etc/ansible, so that 
ansible.cfg is present directly in the later folder.

Next go to /root and link the folder that contain this file at this place like this
(the code just below is correct if you cloned  repos in /root/ directory, so
 that the repos root is /root/). If you want to have the repo somewhere else
you'll have to adapt /etc/ansible/inventory/common variable _src, but make
sure ansible folder can be accessed with `cd /root/ansible`

```bash
cd /root
ln -s /ansible
```



### Install custom ansible collections

For mdadm:
```
ansible-galaxy install rolehippie.mdadm
ansible-galaxy collection install openstack.cloud
```

### Adapt /etc/ansible/inventory/common
As already mentionned `/etc/ansible/inventory/common` contain several variable
of interest including:
- keyname : as root generate your key with ssh-keygen and deploy the public key 
with the name corresponding to "keyname" variable in your provider management,


## Organisation

## Useful adhoc commands

### Look at Ansible internal variables
Here for `node1` but it can be replaced with any host or group.
```
ansible node1 -m debug -a "var=hostvars[inventory_hostname]"
```

### List inventory content
In this example, this is the content of the group `all` which contain all hosts 
but `all` can be replaced by `ovh` or `GRA11` (OVH region are set after OVH
variables and hence in capital letters) 
```
ansible --list-hosts all
```

### Execute an adhoc command a certain group of hosts:
Possibly the group `all`
```
ansible ovh -m shell -a "ip a"
```

## Playbook usage
You must be in the playbook folder to execute the playbooks. They cannot be copy
or moved since they call one another.

### Deploy a VM
This and the next will required that you are authenticated with OVH.

```
ansible-playbook deploy_one_vm.yaml --extra-vars "nodename=mynode region=UK1 flavor=s1-2 concurrency=1 server=.server.com"
```

### Destroy a VM
```
ansible-playbook destroy_vm.yaml --extra-vars "nodename=mynode"
```

