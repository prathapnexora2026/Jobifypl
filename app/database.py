"""Database connection and session management (SQLAlchemy)."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import settings

# Render (and Heroku) hand out DATABASE_URLs that start with "postgres://",
# but SQLAlchemy's driver name is "postgresql://". Normalise it so the same
# env var works everywhere without hand-editing.
DATABASE_URL = settings.DATABASE_URL
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# SQLite needs a special connect arg; Postgres/MySQL do not.
connect_args = {}
engine_kwargs = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
else:
    # Postgres / MySQL (e.g. PythonAnywhere MySQL). PythonAnywhere closes idle
    # DB connections after ~5 min, which raises "MySQL server has gone away".
    # pool_pre_ping checks the connection before use; pool_recycle drops
    # connections older than ~4.5 min so we never hand out a dead one.
    engine_kwargs = {"pool_pre_ping": True, "pool_recycle": 280}

engine = create_engine(DATABASE_URL, connect_args=connect_args, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency — yields a DB session and closes it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
