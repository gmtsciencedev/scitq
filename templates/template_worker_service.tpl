[Unit]
Description=scitq-worker
After=multi-user.target

[Service]
Environment=PATH=/usr/bin:/usr/local/bin
Environment=SCITQ_SERVER=127.0.0.1
EnvironmentFile=/etc/scitq-worker.conf
Type=simple
ExecStart=scitq-worker -s paused $SCITQ_SERVER 1

[Install]
WantedBy=multi-user.target