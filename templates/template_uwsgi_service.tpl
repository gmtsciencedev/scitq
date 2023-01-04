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
Environment=PYTHONPATH=/usr/lib/python3.8/site-packages:/usr/local/lib/python3.8/dist-packages/
Type=simple
ExecStart=pyuwsgi --http :5000 --gevent 1000 --http-websockets --master --enable-threads -w scitq.wsgi:app

[Install]
WantedBy=multi-user.target