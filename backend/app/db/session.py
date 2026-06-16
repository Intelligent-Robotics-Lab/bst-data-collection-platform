"""Database engine and session factory.

SQLite with foreign-key enforcement turned on per-connection (off by default in
SQLite). check_same_thread=False lets FastAPI's threadpool share the engine; we
never share a single Session across threads.
"""

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
    future=True,
)


@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):  # noqa: ANN001
    """Enforce foreign keys on every SQLite connection."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db():
    """FastAPI dependency yielding a scoped Session per request."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
