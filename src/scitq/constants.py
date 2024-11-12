SIGNAL_CLEAN=-1
SIGNAL_RESTART=-2
SIGNAL_RESET_RESOURCES=-3

DEFAULT_SERVER_CONF='/etc/scitq.conf'
DEFAULT_WORKER_CONF='/etc/scitq-worker.conf'
DEFAULT_RCLONE_CONF='/etc/rclone.conf'
DEFAULT_SERVER='127.0.0.1'

HTTP_ERROR_CODE_NOT_FOUND = 404

TASK_STATUS = ['paused','waiting','pending','assigned','accepted','running','failed','succeeded','debug']
EXECUTION_STATUS = ['pending','accepted','running','failed','succeeded','refused']
WORKER_STATUS = ['paused','running','offline','failed','evicted']

PROTOFILTER_SYNTAX=r'^(?P<item>cpu|ram|disk|tags|gpumem|eviction|region|cost|provider)(?P<comparator>==|!=|>=|>|<|<=|~|#|!~|!#)(?P<value>[0-9\.]+|[A-Za-z0-9_%-]+)$'
PROTOFILTER_SEPARATOR=':'

FLAVOR_DEFAULT_LIMIT=10
FLAVOR_DEFAULT_EVICTION=5

TASK_STATUS_ID = {status:i for i,status in enumerate(TASK_STATUS)}
TASK_STATUS_ID_REVERSE = {i:status for i,status in enumerate(TASK_STATUS)}