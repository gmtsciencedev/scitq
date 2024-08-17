import json
import requests
from time import sleep
from .lib import Server
import logging as log

AZURE_EVENT_URL ="http://169.254.169.254/metadata/scheduledevents"
AZURE_HEADERS = {'Metadata' : 'true'}
AZURE_PARAMS = {'api-version':'2020-07-01'}

WAITING_TIME = 2

def get_azure_events():           
    resp = requests.get(AZURE_EVENT_URL, headers = AZURE_HEADERS, params = AZURE_PARAMS)
    data = resp.json()
    events = data.get('Events',[])
    if events and events[0].get('EventType',None)=='Preempt':
        return True
    else:
        return False

def monitor_events(server, provider, worker_id):
    """Thread to launch when the client is launched to monitor events"""
    if provider=='azure':
        log.warning(f'{provider} eviction monitor started')
        get_event = get_azure_events
    else:
        log.warning(f'No events to monitor for provider {provider}')
        return None
    s = Server(server, style='object')
    while True:
        if get_event():
            log.exception('An eviction event was detected.')
            s.worker_update(worker_id,status='evicted', asynchronous=False)
            return None
        sleep(WAITING_TIME)           

