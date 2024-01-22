from threading import Thread
import os
import logging as log
from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_migrate import Migrate
from .db import db

from .config import WORKER_CREATE

def __background__(*args):
    raise RuntimeError('Not initialized')

migrate=Migrate()

def create_app():
    log.info('Starting')
    log.warning(f'WORKER_CREATE is {WORKER_CREATE}')

    # via https://github.com/pallets/flask-sqlalchemy/blob/main/examples/hello/hello.py
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object('scitq.default_settings')

    # via https://flask-restx.readthedocs.io/en/latest/example.html
    app.wsgi_app = ProxyFix(app.wsgi_app)
    
    from . import model
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


def background_app():
    """This is run by scitq-queue service"""
    app=create_app()
    __background__(app)

#def app(*args, **nargs):
#    """Hack for uwsgi"""
#    global app
#    app = create_app()
#    return app(*args, **nargs)
    
app = create_app()