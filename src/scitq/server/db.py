from .config import SQLALCHEMY_POOL_SIZE
from flask_sqlalchemy import SQLAlchemy


if SQLALCHEMY_POOL_SIZE is not None:
    db = SQLAlchemy(engine_options={'pool_size': int(SQLALCHEMY_POOL_SIZE)})
else:
    db = SQLAlchemy()
