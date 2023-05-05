#!/usr/bin/env python
"""This script is designed to store and retrieve host, groups and hostvars in a 
sqlite database. It is simple but designed to be extremely performent
"""
import argparse
import sqlite3
import os
import json
from time import sleep
import shutil


# GLOBAL CONSTANTS
SQLITE_DATABASE = os.environ.get('ANSIBLE_SQLITE','/var/spool/scitq/ansible-scitq.db')
DEFAULT_GROUP = os.environ.get('ANSIBLE_DEFAULT_GROUP','Default')

# INTERNAL CONSTANTS
VERSION=2
# how many times we should try /etc/hosts
RETRY_ETCHOSTS=5
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
    def __init__(self, database_path):
        """Initialize database connection, if empty populate it"""
        if not os.path.exists(database_path):
            database_folder,_ = os.path.split(database_path)
            if not os.path.exists(database_folder):
                os.makedirs(database_folder)
        self.connection = sqlite3.connect(database_path)
        self.connection.row_factory = sqlite3.Row
        self.base_cursor = self.connection.cursor()

        try:
            version = self.query('SELECT version FROM version')
            version = version[0][0]
            if version==1:
                self.do("""CREATE TABLE locks (
    resource VARCHAR(50) NOT NULL,
    pid INTEGER NOT NULL
)""")  
                self.do("UPDATE version SET version=2")
                version = 2
            assert version == VERSION
        except sqlite3.OperationalError:
            self.populate()

    def do(self, sql_query, values=[], nested=False):
        """Do a very basic query in an independant cursor"""
        if nested:
            c = self.connection.cursor()
        else:
            c = self.base_cursor
        c.execute(sql_query, values)
        return c

    def query(self, sql_query, values=[], nested=False):
        """Fetch all result of a basic query returning results - SELECT
        In case of nested query (avoid), nested must be set to true so that
        another cursor is claimed"""
        return self.do(sql_query, values, nested).fetchall()
    
    def populate(self):
        """Create the initial schema of the database"""
        self.do("""CREATE TABLE groups (
    group_id INTEGER NOT NULL,
    group_name VARCHAR(100) NOT NULL UNIQUE,
    PRIMARY KEY (group_id)
)""")
        self.do("""CREATE TABLE hosts (
    host_id INTEGER NOT NULL,
    host_name VARCHAR(100) NOT NULL UNIQUE,
    group_id INTEGER NOT NULL,
    PRIMARY KEY (host_id),
    FOREIGN KEY(group_id) REFERENCES groups (group_id)
)""")
        self.do("""CREATE TABLE hostvars (
    host_id INTEGER NOT NULL,
    variable VARCHAR(50) NOT NULL,
    value VARCHAR(100) NOT NULL,
    UNIQUE (host_id, variable)
)""")
        self.do("""CREATE TABLE locks (
    resource VARCHAR(50) NOT NULL,
    pid INTEGER NOT NULL
)""")
        self.do("""CREATE TABLE version (
    version INTEGER NOT NULL
)""")
        self.do('INSERT INTO version (version) VALUES (?)', [VERSION])

        self.connection.commit()


    def list(self):
        """Main inventory function, list all hosts in all groups with _meta (hostvars)"""
        inventory = {}
        for group_name, host_name in self.query('SELECT group_name, host_name FROM hosts NATURAL JOIN groups'):
            if group_name not in inventory:
                inventory[group_name]=[]
            inventory[group_name].append(host_name)
        inventory['_meta'] = {}
        for host_name, variable, value in self.query('SELECT host_name, variable, value FROM hostvars NATURAL JOIN hosts'):
            if host_name not in inventory['_meta']:
                inventory['_meta'][host_name]={}
            inventory['_meta'][host_name][variable]=value
        return json.dumps(inventory,  indent=4, sort_keys=True)

    def list_host(self, host_name):
        """List all hostvars for a certain host, return an empty json if host has no vars or does not exists"""
        return json.dumps(dict(self.query('SELECT variable, value FROM hostvars NATURAL JOIN hosts WHERE host_name=?',
                                                (host_name,) )),
                        indent=4, sort_keys=True)

    def add_host(self, host_name, group_name):
        """Add a host in the inventory with default group_name - watch out: must
        be committed with self.connection.commit()"""
        ids = self.query('SELECT group_id FROM groups WHERE group_name=?',
                            (group_name,))
        if len(ids)==0:
            self.do('INSERT INTO groups (group_name) VALUES (?)',
                                (group_name,))
            ids = self.query('SELECT group_id FROM groups WHERE group_name=?',
                        (group_name,))   

        group_id = ids[0][0]

        try:
            self.do('INSERT INTO hosts (host_name, group_id) VALUES (?,?)',
                        (host_name, group_id))
        except sqlite3.IntegrityError:
            self.do('UPDATE hosts SET group_id=? WHERE host_name=?',(group_id,host_name))
                

    def get_host_id(self, host_name):
        """Return the host_id matching the host_name - this is safe because host_name are UNIQUE"""
        return self.query('SELECT host_id FROM hosts WHERE host_name=?',
                     (host_name,))[0][0]

    def set_hostvar(self, host_id, variable, value):
        """Insert a new host variable (or update) in table hostvars - value is converted to text"""
        try:
            self.do('INSERT INTO hostvars (host_id,variable,value) VALUES (?,?,?)',
                    (host_id, variable, value))
        except sqlite3.IntegrityError:
            self.do('UPDATE hostvars SET value=? WHERE host_id=? AND variable=?',
                    (value, host_id, variable))
    
    def del_host(self, host_name):
        """Delete a host and its hostvars in database"""
        host_id = self.get_host_id(host_name)
        self.do('DELETE FROM hostvars WHERE host_id=?',(host_id,))
        self.do('DELETE FROM hosts WHERE host_id=?',(host_id,))
        self.connection.commit()
    
    def get_lock(self, resource, pid=os.getpid()):
        """Get a lock (answer true) unless there is an another process that holds it (answer false)."""
        locks=self.query('SELECT pid FROM locks WHERE resource=?',
                     (resource,))
        
        if len(locks)>0:
            other_pid=locks[0][0]
            if not check_pid(other_pid):
                self.do('DELETE FROM locks WHERE pid=?',(other_pid,))
            else:
                return False
        
        self.do('INSERT INTO locks (resource,pid) VALUES (?,?)',(resource,pid))
        self.connection.commit()
        return True
    
    def del_lock(self, resource, pid=os.getpid()):
        """Remove a lock if it exists"""
        self.do('DELETE FROM locks WHERE pid=? AND resource=?',(pid,resource))
        self.connection.commit()

    def get_host_ips(self):
        """Return a dictionnary of hostname:IPv4"""
        return dict(self.query(
            """SELECT 
                    h.host_name,
                    (SELECT 
                            value 
                        FROM hostvars hv 
                        WHERE hv.host_id=h.host_id AND hv.variable='ipv4') 
                FROM hosts h"""))

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
    retry = RETRY_ETCHOSTS
    while retry>0:
        lock=db.get_lock('/etc/hosts')
        if lock:
            break
        sleep(1)
        retry -= 1
    else:
        return False
    
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

    db.del_lock('/etc/hosts')

            


def inventory(args):
    """Main fonction"""
    
    if args.variable or args.value:
        if len(args.variable)!=len(args.value):
            raise (f"Use exactly the same number of values (value used: {args.value}) and variables (variables used: {args.variable})")
        if args.add_host is None and args.for_host is None:
            raise ("Cannot set some variables with values if host is unknown, use --for-host or --add-host")
        variables = dict(zip(args.variable, args.value))
    else:
        variables = {}

    db = Database(SQLITE_DATABASE)

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
        host_id = db.get_host_id(host)
        for variable, value in variables.items():
            db.set_hostvar(host_id, variable, value)
        db.connection.commit()

    if args.del_host is not None:
        db.del_host(args.del_host)
    
    if args.change_etchosts:
        change_etc_hosts(db)
    

def scitq_inventory(list=False, host=None, add_host=None, in_group=DEFAULT_GROUP, 
        for_host=None, variable=[], value=[], del_host=None, change_etchosts=False):
    """Same command as inventory but adapted for scitq internal use"""
    return inventory(argparse.Namespace(list=list, host=host, add_host=add_host, 
            in_group=in_group, for_host=for_host, variable=variable, 
            value=value, del_host=del_host, change_etchosts=change_etchosts))

if __name__=="__main__":
    parser = argparse.ArgumentParser(description='(yaf) Ansible SQLite inventory script')
    decorate_parser(parser)
    args = parser.parse_args()
    result = inventory(args)
    if result:
        print(result)