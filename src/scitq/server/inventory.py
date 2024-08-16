import argparse
import os
import json
from time import sleep
import shutil
from .db import db
from .model import Worker, Flavor
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import NoResultFound
import filelock
from .config import SCITQ_SERVER
from ..util import filter_none


# GLOBAL CONSTANTS
DEFAULT_GROUP = os.environ.get('ANSIBLE_DEFAULT_GROUP','Default')

# INTERNAL CONSTANTS
VERSION=2
# how many times we should try /etc/hosts
TIMEOUT_ETCHOSTS=30
ETCHOSTS_MARKER_LINE="# DO NOT CHANGE THIS LINE OR ANY LINE BELOW - SCITQ MANAGED ZONE"

# via https://stackoverflow.com/questions/568271/how-to-check-if-there-exists-a-process-with-a-given-pid-in-python
def check_pid(pid):        
    """ Check For the existence of a unix pid. """
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    else:
        return True

class Database:
    def __init__(self, app):
        """Connect to db"""
        with app.app_context():
            self.session = Session(db.engine)

    def list(self):
        """Main inventory function, list all hosts in all groups with _meta (hostvars)"""
        inventory = {}
        inventory['_meta'] = {}
        for worker,flavor in self.session.query(Worker,Flavor).join(Worker.flavor_detail,isouter=True).filter(Worker.ansible_active==True):
            if worker.ansible_group not in inventory:
                inventory[worker.ansible_group]=[]
            inventory[worker.ansible_group].append(worker.hostname)
            inventory['_meta'][worker.hostname]=filter_none({
                'ipv4': worker.ipv4,
                'ipv6': worker.ipv6,
                'provider': worker.provider,
                'region': worker.region,
                'flavor': worker.flavor,
                'cpu': flavor.cpu if flavor else None,
                'ram': flavor.ram if flavor else None,
                'gpu': flavor.gpu if flavor else None,
                'target': SCITQ_SERVER,
                'tags': flavor.tags if flavor else None,
            })
        return json.dumps(inventory,  indent=4)

    def list_host(self, host_name):
        """List all hostvars for a certain host, return an empty json if host has no vars or does not exists"""
        try:
            worker,flavor = self.session.query(Worker,Flavor).join(Worker.flavor_detail,isouter=True).filter(Worker.ansible_active==True).filter(Worker.hostname==host_name).one()
            return json.dumps(filter_none({
                    'ipv4': worker.ipv4,
                    'ipv6': worker.ipv6,
                    'provider': worker.provider,
                    'region': worker.region,
                    'flavor': worker.flavor,
                    'cpu': flavor.cpu if flavor else None,
                    'ram': flavor.ram if flavor else None,
                    'gpu': flavor.gpu if flavor else None,
                    'target': SCITQ_SERVER,
                    'tags': flavor.tags if flavor else None,
                    }),
                    indent=4)
        except NoResultFound:
            return json.dumps({})

    def add_host(self, host_name, group_name):
        """Add a host in the inventory with default group_name - watch out: must
        be committed with self.session.commit()"""
        worker = self.session.query(Worker).filter(Worker.hostname==host_name).one()
        worker.ansible_group = group_name
        worker.ansible_active = True
            

    def set_hostvar(self, host_name, variable, value):
        """Insert a new host variable (or update) in table hostvars - value is converted to text"""
        worker = self.session.query(Worker).filter(Worker.hostname==host_name).one()
        if hasattr(worker, variable):
            setattr(worker, variable, value)
        else:
            print(f'WARNING: variable {variable} cannot be set, it is read-only, ignoring set to {value}')
    
    def del_host(self, host_name):
        """Delete a host and its hostvars in database"""
        worker = self.session.query(Worker).filter(Worker.hostname==host_name).one()
        worker.ansible_active = False
        
    def get_host_ips(self):
        """Return a dictionnary of hostname:IPv4"""
        return dict(self.session.query(Worker).filter(Worker.ansible_active==True).with_entities(Worker.hostname, Worker.ipv4))
    
    def commit(self):
        """Commit pending changes"""
        self.session.commit()

def decorate_parser(parser):
    """Easing integration: all options to parser added here"""
    parser.add_argument('--list', default=None, action='store_true',
                help="List all hosts")
    parser.add_argument('--host', type=str, action='store', default=None,
                help="List one host in particular")
    parser.add_argument('--add-host', type=str, action='store', default=None,
                help=f"Add a host (in group {DEFAULT_GROUP} unless --in-group is used)")
    parser.add_argument('--in-group', type=str, action='store', default=DEFAULT_GROUP,
                help=f"Specify in which group a host should be added")
    parser.add_argument('--for-host', type=str, default=None,
                help="Specify a host where to add variables")
    parser.add_argument('--variable', type=str, action='append',
                help="Add a host variable (requires the host to be known, either with --add-host or with --for-host, and requires a value set with --value), can be used several times")
    parser.add_argument('--value', type=str, action='append',
                help="Add a host variable value (requires --variable, and thus the host to be known - with --add-host or --for-host), can be used several times")
    parser.add_argument('--del-host', type=str, action='store', default=None,
                help=f"Delete a host")
    parser.add_argument('--change-etchosts', action='store_true',
                help="Modify /etc/hosts so that declared hosts in database are present in /etc/hosts (as ansible is very bad at this task)")


def change_etc_hosts(db):
    """Change /etc/hosts
    """
    try:
        with filelock.FileLock('/etc/hosts.lock', timeout=TIMEOUT_ETCHOSTS):
            host_ips = db.get_host_ips()
            new_hosts = list(host_ips.keys())
            shutil.copy('/etc/hosts','/etc/hosts.back')
            with open('/etc/hosts','r', encoding='utf-8') as f:
                etchost  = f.read().strip().split('\n')
            found_marker = False
            new_etchost = []
            for line in etchost:
                if not found_marker:
                    new_etchost.append(line)
                    if ETCHOSTS_MARKER_LINE in line:
                        found_marker=True
                        continue
                    else:
                        continue
                _,host=line.split()
                if host in new_hosts:
                    new_hosts.remove(host)
                    new_etchost.append(f"{host_ips[host]}\t{host}")
            if not found_marker:
                new_etchost.append(ETCHOSTS_MARKER_LINE)
            for host in new_hosts:
                new_etchost.append(f"{host_ips[host]}\t{host}")
            with open('/etc/hosts','w', encoding='utf-8') as f:
                f.write('\n'.join(new_etchost))
    except filelock.Timeout:
        pass

            


def inventory(app):
    """Main fonction"""
    parser = argparse.ArgumentParser(description='Ansible SQLite inventory script')
    decorate_parser(parser)
    args = parser.parse_args()
    
    if args.variable or args.value:
        if len(args.variable)!=len(args.value):
            raise (f"Use exactly the same number of values (value used: {args.value}) and variables (variables used: {args.variable})")
        if args.add_host is None and args.for_host is None:
            raise ("Cannot set some variables with values if host is unknown, use --for-host or --add-host")
        variables = dict(zip(args.variable, args.value))
    else:
        variables = {}

    db = Database(app)

    if args.list:
        return db.list()
    elif args.host is not None:
        return db.list_host(args.host)
    
    if args.add_host is not None:
        host = args.add_host
        db.add_host(host, args.in_group)
        if 'ansible_host' not in variables:
            variables['ansible_host']=host
    elif args.for_host is not None:
        host = args.for_host
    
    if variables:
        for variable, value in variables.items():
            db.set_hostvar(host, variable, value)

    if args.del_host is not None:
        db.del_host(args.del_host)
    
    db.commit()

    if args.change_etchosts:
        change_etc_hosts(db)
    
