[Unit]
Description=pytq-worker
After=multi-user.target

[Service]
Environment=PATH=/usr/bin:/usr/local/bin
Environment=AWS_ENDPOINT_URL=https://s3.gra.perf.cloud.ovh.net
Environment=PYTQ_SERVER=127.0.0.1
Type=simple
ExecStart=pytq-worker -s paused $PYTQ_SERVER 1

[Install]
WantedBy=multi-user.target