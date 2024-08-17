import ovh
from getpass import getpass
from argparse import Namespace
import pandas as pd
import requests
import re
from ...server import config, get_session
from ..generic import Flavor, FlavorMetrics, GenericProvider
from ...util import to_obj
import logging as log

# Instantiate an OVH Client.
#print('''If you don't have credentials you can create ones with full access to your account on the token creation page:
#       https://api.ovh.com/createToken/index.cgi?GET=/*&PUT=/*&POST=/*&DELETE=/*
#''')

OVH_ENDPOINT='ovh-eu'

class OVH(GenericProvider):

    def __init__(self, session):
        self.session = session

        if config.OVH_APPLICATIONKEY == '' \
            or config.OVH_APPLICATIONSECRET == '' \
            or config.OVH_CONSUMERKEY == '':
            raise RuntimeError('''OVH_APPLICATIONKEY, OVH_APPLICATIONSECRET and OVH_CONSUMERKEY *must* be set in /etc/scitq.conf 
(or as shell variables) for the updater to work.
You may have to visit the following website to create them:
 https://api.ovh.com/createToken/index.cgi?GET=/* ''')
        
        if config.OVH_REGIONS == '':
            raise RuntimeError('''OVH_REGIONS *must* be set in /etc/scitq.conf for the updater to work.''')

        self.client = ovh.Client(
            endpoint=OVH_ENDPOINT,               # Endpoint of API OVH (List of available endpoints: https://github.com/ovh/python-ovh#2-configure-your-application)
            application_key=config.OVH_APPLICATIONKEY,    # Application Key
            application_secret=config.OVH_APPLICATIONSECRET, # Application Secret
            consumer_key=config.OVH_CONSUMERKEY,       # Consumer Key
        )
        self.provider = 'ovh'
        self.service_name = config.OS_PROJECT_ID
        self.regions = config.OVH_REGIONS.split() if config.OVH_REGIONS else \
            self.client.get(f"/cloud/project/{self.service_name}/region")
        self.flavors = {}
        self.flavor_metrics = {}
        self.live = True

    #result = client.get('/cloud/project')
    #choice = None
    #while choice is None or not(0<choice<=len(result)):
    #    print('Choose your service name between: ')
    #    for i,project in enumerate(result):
    #        print(f'choice {i+1}) {project}')
    #    choice=int(input(f'Answer between 1 and {len(result)}: '))
    #service_name = result[choice-1]

    def get_flavors(self):
        """Update OVH flavors"""
        raw_flavors = self.client.get(f"/cloud/project/{self.service_name}/flavor")
        self.push('Getting flavors')
        for flavor in map(to_obj, raw_flavors):
            if not flavor.available or flavor.osType=='windows' or 'flex' in flavor.name:
                continue
            self.push('.')
            if flavor.name not in self.flavors:
                tags=''
                if flavor.name.startswith('bm'):
                    tags+='M'
                if flavor.name=='t1-90' and flavor.vcpus==16:
                    # for some strange reason OVH API sometimes (but not always) answer wrong here...
                    flavor.vcpus=18
                    self.push('<hack t1-90>')
                try:
                    f=Flavor(
                        name=flavor.name,
                        provider=self.provider,
                        cpu=flavor.vcpus,
                        ram=flavor.ram/1000,
                        disk=flavor.disk,
                        bandwidth=flavor.inboundBandwidth/1000,
                        tags=tags)
                except:
                    log.exception('Flavor ill created')
                    self.push('!')
                self.flavors[flavor.name]=f
            if (flavor.name, flavor.region) not in self.flavor_metrics:
                try:
                    fm=FlavorMetrics(
                        flavor_name=flavor.name,
                        provider=self.provider,
                        region_name=flavor.region,
                        eviction=0)
                except:
                    log.exception('FlavorMetrics ill created')
                    self.push('!')
                self.flavor_metrics[(flavor.name, flavor.region)]=fm
        self.push('\n')

    def get_metrics(self):
        self.push('Getting metrics')
        if not self.flavors:
            raise RuntimeError('Cannot get metrics on an empty flavor set')
        
        r = requests.get('https://www.ovhcloud.com/fr/public-cloud/prices/')
        for table in pd.read_html(r.content):
            for line in table.itertuples():
                if hasattr(line,'Nom') and line.Nom in self.flavors:
                    self.push('.')
                    flavor = line.Nom
                    
                    # cost
                    m=re.match(r'([0-9,]+).€ HT/heure',line.Prix)
                    if m:
                        for region in self.regions:
                            if (flavor,region) in self.flavor_metrics:
                                try:
                                    self.flavor_metrics[(flavor,region)].cost = float(m.groups()[0].replace(',','.'))
                                except:
                                    log.exception('FlavorMetrics cost could not be completed')
                                    self.push('!')
                    else:
                        self.push('!')
                        log.exception(f'Flavor {flavor}, could not understand cost: '+line.Prix)

                    # disk
                    disk_found = False
                    for m in re.finditer(r'.*?((?P<n>[0-9]+).x.)?(?P<value>[0-9.]+).(?P<unit>T|G)o.*?',line.Stockage):
                        disk_found = True
                        dict = m.groupdict()
                        n=dict['n']
                        value=dict['value']
                        unit=dict['unit']
                        n=1 if n is None else int(n)
                        value=float(value)
                        unit=1 if unit=='G' else 1024
                        disk = n*value*unit
                        try:
                            if not self.flavors[flavor].disk or self.flavors[flavor].disk<disk:
                                self.flavors[flavor].disk=disk
                        except:
                            log.exception('Flavor disk could not be completed')
                            self.push('!')
                    if not disk_found:
                        self.push('!')
                        log.exception(f'Flavor {flavor}, could not understand disk: '+line.Stockage)
                    
                    if 'NVMe' in line.Stockage:
                        try:
                            self.flavors[flavor].tags+='N'
                        except:
                            log.exception('Flavor tag could not be completed')
                            self.push('!')
                    
                    if hasattr(line,'GPU'):
                        try:
                            self.flavors[flavor].tags+='G'
                            self.flavors[flavor].gpu=line.GPU
                            m=re.match(r'((?P<n>[0-9]+).)?.+ (?P<value>[0-9]+).Go',line.GPU)
                            if m:
                                dicts=m.groupdict()
                                n=1 if dicts['n'] is None else int(dicts['n'])
                                value=float(dicts['value'].replace(',','.'))
                                self.flavors[flavor].gpumem=n*value
                        except:
                            log.exception('Flavor gpu info could not be completed')
                            self.push('!')

        self.push('\n')
        self.update_flavors(self.flavors.values())
        self.update_flavor_metrics([fm for fm in self.flavor_metrics.values() if fm.cost])
        self.push('done\n')

def run():
    session = get_session()

    updater=OVH(session=session)
    updater.get_flavors()
    updater.get_metrics()