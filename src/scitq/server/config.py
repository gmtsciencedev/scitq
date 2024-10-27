import os
from ..constants import DEFAULT_SERVER_CONF

if 'FLASK_APP' not in os.environ and 'SCITQ_PRODUCTION' not in os.environ:
    import dotenv
    dotenv.load_dotenv(DEFAULT_SERVER_CONF, override=False)

from socket import gethostname
from ..util import check_dir, package_path
from logging.config import dictConfig
from ..default_settings import SQLALCHEMY_POOL_SIZE, SQLALCHEMY_DATABASE_URI




MAIN_THREAD_SLEEP = 5
WORKER_OFFLINE_DELAY = 15
SCITQ_SERVER = os.environ.get('SCITQ_SERVER',None)

WORKER_CREATE = f'cd {package_path("ansible","playbooks")} && ansible-playbook deploy_one_vm.yaml --extra-vars \
"nodename={{hostname}} concurrency={{concurrency}} status=running flavor={{flavor}} \
region={{region}} provider={{provider}} tags={{tags}}"'

FAKE_ANSIBLE = f'sleep 10; echo a PERCENT_20; sleep 10; echo b PERCENT_40; sleep 10; echo c PERCENT_60; sleep 10; echo d PERCENT_80'

if SCITQ_SERVER is not None:
    WORKER_CREATE = WORKER_CREATE[:-1] + f' target={SCITQ_SERVER}"'
    SCITQ_SHORTNAME = SCITQ_SERVER.split('.')[0]
else:
    SCITQ_SHORTNAME = gethostname().split('.')[0]
WORKER_DELETE = os.environ.get('WORKER_DELETE',
    f'cd {package_path("ansible","playbooks")} && ansible-playbook destroy_vm.yaml --extra-vars "nodename={{hostname}}"')
SERVER_CRASH_WORKER_RECOVERY = os.environ.get('SERVER_CRASH_WORKER_RECOVERY',
    f'cd {package_path("ansible","playbooks")} && ansible-playbook check_after_reboot.yaml')
WORKER_IDLE_CALLBACK = os.environ.get('WORKER_IDLE_CALLBACK',WORKER_DELETE)
WORKER_CREATE_CONCURRENCY = 10
WORKER_CREATE_RETRY=2
WORKER_CREATE_RETRY_SLEEP=30
UI_OUTPUT_TRUNC=100
UI_MAX_DISPLAYED_ROW = 500
WORKER_DESTROY_RETRY=2
DEFAULT_BATCH = 'Default'
TERMINATE_TIMEOUT = 20
KILL_TIMEOUT = 30
JOB_MAX_LIFETIME = 600

def _(x):
    """a fail-free shortcut to os.environ.get to import an env variable"""
    return os.environ.get(x,'')

def _num(x, default=None):
    """a failing shortcut to os.environ.get to import an env variable supposed to be numerical"""
    if x in os.environ:
        return float(os.environ[x])
    return default

AZURE_REGIONS=_('AZURE_REGIONS')
AZURE_CPUQUOTAS=_('AZURE_CPUQUOTAS')
AZURE_SUBSCRIPTION_ID=_('AZURE_SUBSCRIPTION_ID')
AZURE_CLIENT_ID=_('AZURE_CLIENT_ID')
AZURE_SECRET=_('AZURE_SECRET')
AZURE_TENANT=_('AZURE_TENANT')
PREFERRED_REGIONS=dict([preference.split(':') for preference in _('PREFERRED_REGIONS').split(',') if ':' in preference])

OVH_REGIONS=_('OVH_REGIONS')
OVH_CPUQUOTAS=_('OVH_CPUQUOTAS')
OVH_APPLICATIONKEY    = _('OVH_APPLICATIONKEY') 
OVH_APPLICATIONSECRET = _('OVH_APPLICATIONSECRET')
OVH_CONSUMERKEY       = _('OVH_CONSUMERKEY')
OS_PROJECT_ID         = _('OS_PROJECT_ID')

EVICTION_ACTION=_('EVICTION_ACTION')
EVICTION_COST_MARGIN=_num('EVICTION_COST_MARGIN', default=10)

def get_quotas(provider=None):
    if provider=='ovh':
        return dict(zip(OVH_REGIONS.split(),map(int,OVH_CPUQUOTAS.split())))
    elif provider=='azure':
        return dict(zip(AZURE_REGIONS.split(),map(int,AZURE_CPUQUOTAS.split())))
    elif provider is None:
        quotas = {}
        for provider in ['ovh','azure']:
            for region, cpuquota in get_quotas(provider).items():
                quotas[(provider,region)]=cpuquota
        return quotas
    else:
        raise RuntimeError(f'Cannot give quotas for unknown provider: {provider}')

def setup_log():
    """Setting up log must occur only in specific contexts"""
    if os.environ.get('QUEUE_PROCESS') and os.environ.get('QUEUE_LOG_FILE'):
        check_dir(os.environ.get('QUEUE_LOG_FILE'))
        dictConfig({
            'version': 1,
            'formatters': {'default': {
                'format': '[%(asctime)s] %(levelname)s in %(module)s: %(message)s',
            }},
            'handlers': {'wsgi': {
                'class': 'logging.StreamHandler',
                'stream': 'ext://flask.logging.wsgi_errors_stream',
                'formatter': 'default'
            }, "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "formatter": "default",
                "filename": os.environ.get('QUEUE_LOG_FILE'),
                "maxBytes": int(os.environ.get('QUEUE_LOG_FILE_MAX_SIZE',
                    os.environ.get('LOG_FILE_MAX_SIZE',"10000000"))),
                "backupCount": int(os.environ.get('QUEUE_LOG_FILE_KEEP',
                    os.environ.get('LOG_FILE_KEEP',"3")))
            }},
            'root': {
                'level': os.environ.get('LOG_LEVEL',"INFO"),
                'handlers': ['wsgi' if 'DEBUG' in os.environ else 'file']
            }
        })
    else:
        check_dir(os.environ.get('LOG_FILE',"/tmp/scitq.log"))
        dictConfig({
            'version': 1,
            'formatters': {'default': {
                'format': '[%(asctime)s] %(levelname)s in %(module)s: %(message)s',
            }},
            'handlers': {'wsgi': {
                'class': 'logging.StreamHandler',
                'stream': 'ext://flask.logging.wsgi_errors_stream',
                'formatter': 'default'
            }, "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "formatter": "default",
                "filename": os.environ.get('LOG_FILE',"/tmp/scitq.log"),
                "maxBytes": int(os.environ.get('LOG_FILE_MAX_SIZE',"10000000")),
                "backupCount": int(os.environ.get('LOG_FILE_KEEP',"3"))
            }},
            'root': {
                'level': os.environ.get('LOG_LEVEL',"INFO"),
                'handlers': ['wsgi' if 'DEBUG' in os.environ else 'file']
            }
        })

IS_SQLITE = 'sqlite' in SQLALCHEMY_DATABASE_URI

