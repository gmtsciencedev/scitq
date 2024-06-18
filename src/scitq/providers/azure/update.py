from azure.identity import ClientSecretCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.subscription import SubscriptionClient
from azure.mgmt.resourcegraph import ResourceGraphClient
from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions

import os
import requests
import json
import csv

GPU_RESOURCE='gpu.tsv'

subscription_id = os.environ['AZURE_SUBSCRIPTION_ID']
client_id = os.environ['AZURE_CLIENT_ID']
client_secret = os.environ['AZURE_SECRET'] 
tenant_id = os.environ['AZURE_TENANT']

credentials = ClientSecretCredential(  
client_id=client_id,  
client_secret=client_secret,  
tenant_id=tenant_id  
)


subscription_client = SubscriptionClient(credentials)
regions = list([region.name for region in subscription_client.subscriptions.list_locations(subscription_id)])
regions.sort()

print('Finding flavors', end='', flush=True)
compute_client = ComputeManagementClient(credentials, subscription_id)
flavors = {}
excluded_regions=[]
for region in regions:
    print('.', end='', flush=True)
    try:
        for flavor in compute_client.virtual_machine_sizes.list(location=region):
            if flavor.name not in flavors:
                flavors[flavor.name]={
                    'cpu':flavor.number_of_cores,
                    'ram':flavor.memory_in_mb/1024,
                    'disk':max(flavor.os_disk_size_in_mb,flavor.resource_disk_size_in_mb)/1024,
                    'regions':[region],
                    'bandwidth':1,
                    'tag':['gpu'] if flavor.name.startswith('Standard_N') else [],
                    'price':{},
                    'eviction':{}
                }
            else:
                flavors[flavor.name]['regions'].append(region)
    except:
        excluded_regions.append(region)

for region in excluded_regions:
    if region in excluded_regions:
        regions.remove(region)

# add price
print('\nFinding prices', end='', flush=True)
query="https://prices.azure.com/api/retail/prices?currencyCode='EUR'&$filter= serviceName eq 'Virtual Machines' and priceType eq 'Consumption' and contains(meterName, 'Spot')"
while query:
    print('.', end='', flush=True)
    data = requests.get(query).json()
    for item in data['Items']:
        flavor = item['armSkuName']
        region = item['armRegionName']
        price = item['unitPrice']
        if flavor in flavors and region in flavors[flavor]['regions'] and region not in flavors[flavor]['price']:
            flavors[flavor]['price'][region]=price
    query=data.get('NextPageLink',None)
    

flavors_lower = { key.lower():value for key,value in flavors.items() }

# add eviction
print('\nFinding eviction rates', end='', flush=True)
resourcegraph_client = ResourceGraphClient(credential=credentials, subscription_id=subscription_id)

skip_token = True
while skip_token:
    print('.', end='', flush=True)
    if skip_token is True:
        options=None
    else:
        options=QueryRequestOptions(skip_token=skip_token)
    query = QueryRequest(
            query="spotresources \
| where type == 'microsoft.compute/skuspotevictionrate/location' \
| project skuName=tostring(sku.name), location, evictionRate=properties.evictionRate, price=properties.unitPrice \
| order by skuName", options=options
        )
    query_response = resourcegraph_client.resources(query, )

    for item in query_response.data:
        if item['skuName'] in flavors_lower and item['location'] in flavors_lower[item['skuName']]['regions']:
            evictionRate=item['evictionRate'].split('-')[-1].strip('+')
            eviction=int(evictionRate)
            flavors_lower[item['skuName']]['eviction'][item['location']]=eviction

    skip_token=query_response.skip_token

print('\nAdding GPU info')
with open(GPU_RESOURCE,'rt',encoding='utf-8') as f:
    for entry in csv.DictReader(f,delimiter='\t'):
        if entry['flavor'] in flavors:
            flavors[entry['flavor']]['gpu']=entry['gpu']
            flavors[entry['flavor']]['gpumem']=entry['gpumem']


print('\nDumping resources')
# dump resource
with open('resource.json','w') as f:
    json.dump({'regions':regions, 'flavors':flavors},f)