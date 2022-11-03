[Unit]
Description=pytq
After=multi-user.target

[Service]
Environment=PATH=/usr/bin:/usr/local/bin
Environment=FLASK_APP=pytq.pytq
#Environment=SQLALCHEMY_DATABASE_URI=sqlite:////var/lib/pytq/pytq.db
Environment=SQLALCHEMY_DATABASE_URI=postgresql://root@/pytq
Environment=LOG_FILE=/var/log/pytq/pytq.log
Environment=LOG_FILE_MAX_SIZE=10000000
Environment=LOG_FILE_KEEP=10
Environment=PYTQ_SERVER=127.0.0.1
Type=simple
ExecStart=flask run --host=0.0.0.0

[Install]
WantedBy=multi-user.target