from threading import Thread
import os
import logging as log
from .config import WORKER_CREATE, setup_log
from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_migrate import Migrate
from sqlalchemy.orm import Session

from .db import db

def __background__(*args):
    raise RuntimeError('Not initialized')

migrate=Migrate()

def create_app(get_background=True, get_webapp=True):
    setup_log()
    log.info('Starting')
    
    # via https://github.com/pallets/flask-sqlalchemy/blob/main/examples/hello/hello.py
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object('scitq.default_settings')

    # via https://flask-restx.readthedocs.io/en/latest/example.html
    app.wsgi_app = ProxyFix(app.wsgi_app)
    
    from . import model
    db.init_app(app)

    # with uwsgi, the master worker is forking to create the workers which receive a 
    # non-working connection (because it comes from another process), it must be discarded
    # so that workers re-open the connection properly
    # idea from https://stackoverflow.com/questions/39562838/how-to-configure-pyramid-uwsgi-sqlalchemy
    try:
        # import uwsgi is only working in uwsgi context. It is normal that is fails
        # to import in VisualStudioCode or manually
        import uwsgi # pyright: ignore[reportMissingImports]

        def postfork():
            with app.app_context():
                db.engine.dispose()
        uwsgi.post_fork_hook = postfork
    except ImportError:
        pass
    
    with app.app_context():
        db.create_all()
    migrate.init_app(app, db)

    from .api import api
    api.init_app(app)

    from .ui import ui
    app.register_blueprint(ui)

    if get_background:
        from .background import background
        global __background__
        __background__=background
    


    if get_webapp and not os.environ.get('SCITQ_PRODUCTION'):
        Thread(target=background, args=[app]).start()

    return app


def background_app():
    """This is run by scitq-queue service"""
    app=create_app()
    __background__(app)

def ansible_inventory():
    """This is run when calling scitq-inventory"""
    app=create_app(get_background=False, get_webapp=False)
    from .inventory import inventory
    result = inventory(app)
    if result:
        print(result)

def get_session():
    """Return a simple session for the database access"""
    app=create_app(get_background=False, get_webapp=False)
    with app.app_context():
        session = Session(db.engine)
    return session

if os.environ.get('SCITQ_PRODUCTION'):
    app = create_app()