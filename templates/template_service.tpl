[Unit]
Description=scitq
After=multi-user.target

[Service]
Environment=PATH=/usr/bin:/usr/local/bin
Environment=FLASK_APP=scitq.server
#Environment=SQLALCHEMY_DATABASE_URI=sqlite:////var/lib/scitq/scitq.db
Environment=SQLALCHEMY_DATABASE_URI=postgresql://root@/scitq
Environment=LOG_FILE=/var/log/scitq/scitq.log
Environment=LOG_FILE_MAX_SIZE=10000000
Environment=LOG_FILE_KEEP=10
Environment=SCITQ_SERVER=127.0.0.1
Type=simple
ExecStart=flask run --host=0.0.0.0

[Install]
WantedBy=multi-user.target