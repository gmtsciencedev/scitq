from azure.identity import ClientSecretCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.subscription import SubscriptionClient
from azure.mgmt.resourcegraph import ResourceGraphClient
from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions

import os
import requests
import json
import csv
from io import StringIO
import logging as log
from ...server import get_session, config
from ..generic import GenericProvider, Flavor, FlavorMetrics
from ...util import package_path
import re

GPU_RESOURCE='providers/azure/gpu.tsv'
FLAVOR_NAME_RE=re.compile(r'Standard_(?P<main>[A-Z0-9-]+)(?P<option>[a-z]+)?(_.*?)?$')
DEFAULT_OS_DISK=30

class Azure(GenericProvider):
    def __init__(self, subscription_id, client_id, client_secret, tenant_id, session,
                 regions=None, quotas=None, live=True):
        self.credentials = ClientSecretCredential(  
            client_id=client_id,  
            client_secret=client_secret,  
            tenant_id=tenant_id  
            )
        self.subscription_client = SubscriptionClient(self.credentials)
        self.compute_client = ComputeManagementClient(self.credentials, subscription_id)
        self.resourcegraph_client = ResourceGraphClient(credential=self.credentials, subscription_id=subscription_id)
        self.live = live


        if regions is None:
            self.regions = list([region.name for region in 
                                 self.subscription_client.subscriptions.list_locations(subscription_id)])
        else:
            self.regions = regions
        self.regions.sort()
        self.quotas = dict(zip(regions,quotas))
        self.session = session
        self.provider = 'azure'


            

#regions = list([region.name for region in subscription_client.subscriptions.list_locations(subscription_id)])
#regions.sort()

    def get_flavors(self):
        """Update flavors"""
        print('\nAdding GPU info')
        flavor_gpu = {}
        with open(package_path(GPU_RESOURCE),'rt',encoding='utf-8') as f:
            for entry in csv.DictReader(f,delimiter='\t'):
                flavor_gpu[entry['flavor']]=entry
        self.push('Updating Azure flavors')            
        seen_flavors = []
        flavors = []
        flavor_metrics = {}
        for region in self.regions:
            self.push('.')
            try:
                for flavor in self.compute_client.virtual_machine_sizes.list(location=region):
                    # the flavor name must contain a small s to be compatible with premium storage
                    m=FLAVOR_NAME_RE.match(flavor.name)
                    if not m:
                        # we know that basic are not accepted no need to shout for such
                        if 'Basic' not in flavor.name:
                            self.push(f'<Not a standard flavor {flavor.name}>')
                        continue
                    options=m.groupdict()['option']
                    if options is None or 's' not in options:
                        # no premium storage
                        continue
                    if 'p' in options:
                        # arm64 not supported yet
                        continue
                    if flavor.name not in seen_flavors:
                        try:
                            f=Flavor(
                                name=flavor.name,
                                provider=self.provider,
                                cpu=flavor.number_of_cores,
                                ram=flavor.memory_in_mb/1024,
                                disk=max(DEFAULT_OS_DISK,flavor.resource_disk_size_in_mb/1024), # do not use flavor.os_disk_size_in_mb, this is a maximal optional size not the real size
                                bandwidth=1,
                                tags='G' if flavor.name.startswith('Standard_N') else '')
                            if flavor.name in flavor_gpu:
                                f.gpu=flavor_gpu[flavor.name]['gpu']
                                f.gpumem=int(flavor_gpu[flavor.name]['gpumem'])
                        except:
                            log.exception('Flavor ill created')
                            self.push('!')
                        flavors.append(f)
                        seen_flavors.append(flavor.name)
                    try:
                        flavor_metrics[flavor.name,region]=FlavorMetrics(
                            flavor_name=flavor.name,
                            provider=self.provider,
                            region_name=region
                        )
                    except:
                        log.exception('FlavorMetrics ill created')
                        self.push('!')
            except:
                pass
        self.update_flavors(flavors=flavors)
        self.__flavor_metrics__ = flavor_metrics

    def get_metrics(self):
        # add price
        self.push('\nFinding prices')
        query="https://prices.azure.com/api/retail/prices?currencyCode='EUR'&$filter= serviceName eq 'Virtual Machines' and priceType eq 'Consumption' and contains(meterName, 'Spot')"
        query += ' and (' + ' or '.join([f"armRegionName eq '{region}'" for region in self.regions]) + ')'
        retain_metrics = []
        while query:
            self.push('.')
            data = requests.get(query).json()
            for item in data['Items']:
                flavor = item['armSkuName']
                region = item['armRegionName']
                price = item['unitPrice']

                if (flavor,region) in self.__flavor_metrics__:
                    retain_metrics.append( (flavor,region) )
                    metrics = self.__flavor_metrics__[flavor, region]
                    try:
                        metrics.cost = price
                    except:
                        self.push('!')


            query=data.get('NextPageLink',None)
    
        self.__flavor_metrics__ = {k:v for k,v in self.__flavor_metrics__.items() if k in retain_metrics}
        flavors_lower = { tuple((k.lower() for k in key)):value for key,value in self.__flavor_metrics__.items() }

        # add eviction
        self.push('\nFinding eviction rates')
        

        skip_token = True
        full_metric_pkeys = []
        while skip_token:
            self.push('.')
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
            query_response = self.resourcegraph_client.resources(query, )


            for item in query_response.data:
                if (item['skuName'],item['location']) in flavors_lower:
                    evictionRate=item['evictionRate'].split('-')[-1].strip('+')
                    eviction=int(evictionRate)
                    try:
                        flavors_lower[(item['skuName'],item['location'])].eviction=eviction
                    except:
                        self.push('!')
                    if (item['skuName'],item['location']) not in full_metric_pkeys:
                        full_metric_pkeys.append((item['skuName'],item['location']))


            skip_token=query_response.skip_token

        full_metrics = [flavors_lower[fmpk] for fmpk in full_metric_pkeys]
        self.update_flavor_metrics(metrics=full_metrics)
        self.push('\n')


def run():
    session = get_session()
    regions = config.AZURE_REGIONS.split()
    quotas = config.AZURE_CPUQUOTAS.split()
    if not regions or not quotas:
        raise RuntimeError('AZURE_REGIONS and AZURE_CPUQUOTAS *must* be set in /etc/scitq.conf for the updater to work')
    subscription_id = config.AZURE_SUBSCRIPTION_ID
    client_id = config.AZURE_CLIENT_ID
    client_secret = config.AZURE_SECRET 
    tenant_id = config.AZURE_TENANT

    updater=Azure(subscription_id=subscription_id, client_id=client_id, client_secret=client_secret, tenant_id=tenant_id,
                  session=session, regions=regions, quotas=quotas)
    updater.get_flavors()
    updater.get_metrics()
