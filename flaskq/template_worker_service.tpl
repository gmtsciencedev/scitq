[Unit]
Description=pytq-worker
After=multi-user.target

[Service]
Environment=PATH=/usr/bin:/usr/local/bin
Environment=AWS_ENDPOINT_URL=https://s3.gra.perf.cloud.ovh.net
Type=simple
ExecStart=pytq-worker -s paused 192.168.1.1 1 >> /tmp/worker.log 

[Install]
WantedBy=multi-user.target