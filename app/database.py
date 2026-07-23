"""Database connection and session management (SQLAlchemy)."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import settings

# SQLite needs a special connect arg; Postgres/MySQL do not.
connect_args = {}
engine_kwargs = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
else:
    # Postgres / MySQL (e.g. PythonAnywhere MySQL). PythonAnywhere closes idle
    # DB connections after ~5 min, which raises "MySQL server has gone away".
    # pool_pre_ping checks the connection before use; pool_recycle drops
    # connections older than ~4.5 min so we never hand out a dead one.
    engine_kwargs = {"pool_pre_ping": True, "pool_recycle": 280}

engine = create_engine(settings.DATABASE_URL, connect_args=connect_args, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency — yields a DB session and closes it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
