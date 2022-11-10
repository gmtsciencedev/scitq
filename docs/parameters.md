# Parameters

## pytq-server parameters

These parameters are environment variable that should be defined when launching `pytq-server`. Unless a specific install was done, this is done in `/etc/systemd/system/pytq.service` service file (an exemple is provided is `templates` directory) in `[Service]` section, using `Environment=...` so for instance the [PATH](#path) parameter will be defined like this:
```ini
[...]

[Service]
Environment=PATH=/usr/bin:/usr/local/bin
[...]
```

### PATH
The usual PATH setup. Not really important for the server, it must contain the PATH where pytq-server command was deployed with [setup.py install](install.md#install-python-package) and is very likely `/usr/local/bin` which is contained by default.

### FLASK_APP
This is required by Flask itself, it should be `pytq.pytq`, which is set by default, do not change that.

### SQLALCHEMY_DATABASE_URI
This is required by SQLAlchemy (more specifically flask-sqlalchemy), it can be either sqlite or PostgreSQL but sqlite should be avoided except for simple tests. In theory any SQLAlchemy compatible database should work but this has not been tested, and as for now, there is some raw SQL code at several place in the code... Yes we know it is bad... However an effort was made so that this code should work at least for mariadb/mysql but again this has never been tested.

For details look at [https://flask-sqlalchemy.palletsprojects.com/en/2.x/config/]. Default value of `postgresql://root@/pytq` should suit anybody.

### LOG_FILE
Default to `/var/log/pytq/pytq.log`, it should be a path ending with a file in `.log`. It will be rotated automatically creating some extra files so keeping it in a dedicated directory like here is recommanded.

### LOG_FILE_MAX_SIZE
At which size the log file should be rotated (in bytes).

### LOG_FILE_KEEP
How many rotated log files should we keep.

### PYTQ_SERVER
This is the one parameter that should always be changed and adapted to the IP address or name where the worker will be able to connect to the server.

Note that it is only used if workers are deployed with ansible, through pytq-server. This is covered in [usage](usage.md) and it is the default behaviour so it is recommand to change the default of `127.0.0.1`.

### OVH / OpenStack provider specific variables

These variable are only to be set with ansible.

These are not present in template and should added manually in `[Service]` section.
It should look like this:

```ini
[Service]
...
Environment=OS_AUTH_URL=https://auth.cloud.ovh.net/v3
Environment=OS_PROJECT_ID=0123456789abcdef0123456789abcdef
Environment=OS_PROJECT_NAME="123456789012345"
Environment=OS_USER_DOMAIN_NAME="Default"
Environment=OS_PROJECT_DOMAIN_ID="default"
Environment=OS_USERNAME="user-xxxxxxxxxxx"
Environment=OS_PASSWORD="SECRETPASSWORD123"
Environment=OS_REGION_NAME="GRA7"
Environment=OS_INTERFACE=public
Environment=OS_IDENTITY_API_VERSION=3
```

These variables are defined in Horizon rc file that is provided by OVH - when you log into Horizon this file can be exported clicking on [this link](https://horizon.cloud.ovh.net/project/api_access/openrc/).

Only the password must be set up manually as it is not included in the file associated to OS_PASSWORD variable.


## pytq-worker parameters

These parameters are environment variable that should be defined when launching `pytq-worker`. Unless a specific install was done, this is done in `/etc/systemd/system/pytq-worker.service` service file (an exemple is provided is `templates` directory) in `[Service]` section, using `Environment=...`.

Note that these parameters are only available when deploying the worker manually, see [installation](install.md#manual-worker-deployment). With Ansible automated deployment, this is set using `add_pytq.j2` template and it should not be modified.

### PATH
see [pytq-server](#path). Do not change that.

### PYTQ_SERVER
The IP address or name (not the URL) where pytq-server can be reached. This is the one parameter that should always be changed. On a permanent server, it is even advised to set PYTQ_SERVER environment variable globally at system level so that all PYTQ commands executed on the system know where to go.

### AWS_ENDPOINT_URL
This is due to a bug in Python boto3 AWS client library: when using a non standard endpoint for AWS (that is mainly for non-AWS S3), the AWS CLI (awscli) requires a plugin (awscli-plugin-endpoint) and a specific parameter file, `.aws/config` and it works. `.aws/config` typically looks like this:

```ini
[plugins]
endpoint = awscli_plugin_endpoint

[profile default]
region = gra
s3 =
  endpoint_url = https://s3.gra.perf.cloud.ovh.net
  signature_version = s3v4
s3api =
  endpoint_url = https://s3.gra.perf.cloud.ovh.net
```

However boto3 does not work when using this, the environment variable AWS_ENDPOINT_URL must be set to `https://s3.gra.perf.cloud.ovh.net`, the same value as `endpoint_url` in `.aws/config` file.

So to sumarise, this is required if you use OVH S3 (and has nothing to do with using OVH as an instance provider), in which case  `https://s3.gra.perf.cloud.ovh.net` is the right value for GRA region.

See [S3](specific.md#aws-or-others-s3) for details.

