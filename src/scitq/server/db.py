from .config import SQLALCHEMY_POOL_SIZE
from flask_sqlalchemy import SQLAlchemy


if SQLALCHEMY_POOL_SIZE is not None:
    db = SQLAlchemy(engine_options={'pool_size': int(SQLALCHEMY_POOL_SIZE)})
else:
    db = SQLAlchemy()

# with uwsgi, the master worker is forking to create the workers which receive a 
# non-working connection (because it comes from another process), it must be discarded
# so that workers re-open the connection properly
# idea from https://stackoverflow.com/questions/39562838/how-to-configure-pyramid-uwsgi-sqlalchemy
try:
    # import uwsgi is only working in uwsgi context. It is normal that is fails
    # to import in VisualStudioCode or manually
    import uwsgi # pyright: ignore[reportMissingImports]

    def postfork():
        db.engine.dispose()
    uwsgi.post_fork_hook = postfork
except ImportError:
    pass
