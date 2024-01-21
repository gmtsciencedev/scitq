from threading import Thread
import os
import logging as log
from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from .db import db

from .config import WORKER_CREATE, SQLALCHEMY_POOL_SIZE

def __background__(*args):
    raise RuntimeError('Not initialized')

migrate=Migrate()

def create_app():
    log.info('Starting')
    log.warning(f'WORKER_CREATE is {WORKER_CREATE}')

    #worker_create_queue = queue.Queue()


    # via https://github.com/pallets/flask-sqlalchemy/blob/main/examples/hello/hello.py
    app = Flask(__name__, instance_relative_config=True)
    #app.config['SQLALCHEMY_DATABASE_URI'] = "postgresql://postgres:postgres@localhost:5432/"
    app.config.from_object('scitq.default_settings')

    # via https://flask-restx.readthedocs.io/en/latest/example.html
    app.wsgi_app = ProxyFix(app.wsgi_app)
    # from .db import init_app
    # migrate = init_app(app)
    
    from . import model

    if SQLALCHEMY_POOL_SIZE is not None:
        db.init_app(app,engine_options={'pool_size': int(SQLALCHEMY_POOL_SIZE)})
    else:
        db.init_app(app)


    with app.app_context():
        db.create_all()
    migrate.init_app(app, db)

    from .api import api
    api.init_app(app)

    from .ui import ui
    app.register_blueprint(ui)

    from .background import background
    global __background__
    __background__=background

    if not os.environ.get('SCITQ_PRODUCTION'):
        Thread(target=background, args=[app]).start()

    return app


def background():
    """This is run by scitq-queue service"""
    app=create_app()
    __background__(app)

