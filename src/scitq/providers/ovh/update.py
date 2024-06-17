import json
import ovh
from getpass import getpass
from argparse import Namespace
import pandas as pd
import requests
import re


# Instantiate an OVH Client.
print('''If you don't have credentials you can create ones with full access to your account on the token creation page:
       https://api.ovh.com/createToken/index.cgi?GET=/*&PUT=/*&POST=/*&DELETE=/*
''')
client = ovh.Client(
	endpoint='ovh-eu',               # Endpoint of API OVH (List of available endpoints: https://github.com/ovh/python-ovh#2-configure-your-application)
	application_key=input('application key: '),    # Application Key
	application_secret=getpass('application secret: '), # Application Secret
	consumer_key=input('consumer key: '),       # Consumer Key
)

result = client.get('/cloud/project')
choice = None
while choice is None or not(0<choice<=len(result)):
    print('Choose your service name between: ')
    for i,project in enumerate(result):
        print(f'choice {i+1}) {project}')
    choice=int(input(f'Answer between 1 and {len(result)}: '))

service_name = result[choice-1]
regions = client.get(f"/cloud/project/{service_name}/region")
raw_flavors = client.get(f"/cloud/project/{service_name}/flavor")

flavors = {}
for rf in [Namespace(**rf) for rf in raw_flavors]:
    if not rf.available or rf.osType=='windows' or 'flex' in rf.name:
        continue
    if rf.name not in flavors:
        tags=[]
        if rf.name.startswith('bm'):
            tags.append('metal')
        flavors[rf.name]={'cpu':rf.vcpus, 'ram':rf.ram/1000, 'disk': rf.disk, 'bandwidth': rf.inboundBandwidth/1000, 'regions': [rf.region], 'tags': tags}
    elif rf.region not in flavors[rf.name]['regions']:
        flavors[rf.name]['regions'].append(rf.region) 
        flavors[rf.name]['regions'].sort()       

r = requests.get('https://www.ovhcloud.com/fr/public-cloud/prices/')
for table in pd.read_html(r.content):
    for line in table.itertuples():
        if hasattr(line,'Nom') and line.Nom in flavors:
            m=re.match(r'([0-9,]+).€ HT/heure',line.Prix)
            if m:
                flavors[line.Nom]['price']=float(m.groups()[0].replace(',','.'))
            
            m=re.match(r'.*\+ ((?P<n>[0-9]+).x.)(?P<value>[0-9,]+).(?P<unit>T|G)o.*',line.Stockage)
            if m:
                dicts=m.groupdict()
                n=1 if dicts['n'] is None else int(dicts['n'])
                value=float(dicts['value'].replace(',','.'))
                unit=1 if dicts['unit']=='G' else 1024
                flavors[line.Nom]['disk']=n*value*unit
            
            if 'NVMe' in line.Stockage:
                flavors[line.Nom]['tags'].append('nvme')
            
            if hasattr(line,'GPU'):
                flavors[line.Nom]['tags'].append('gpu')
                flavors[line.Nom]['gpu']=line.GPU
                m=re.match(r'((?P<n>[0-9]+).)?.+ (?P<value>[0-9]+).Go',line.GPU)
                if m:
                    dicts=m.groupdict()
                    n=1 if dicts['n'] is None else int(dicts['n'])
                    value=float(dicts['value'].replace(',','.'))
                    flavors[line.Nom]['gpumem']=n*value

# Pretty print
with open('resource.json','w') as f:
    json.dump({'regions':regions, 'flavors':flavors},f)