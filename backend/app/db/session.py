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
    """Per-connection SQLite tuning.

    - foreign_keys=ON: enforce FKs (off by default in SQLite).
    - journal_mode=WAL: readers no longer block writers. During a live session the
      DB takes high-frequency perception writes (~200-500ms) plus gate/timeline
      writes; without WAL a read like BST's ``GET /go-ahead`` gate poll or the
      console's live poll waits on the single-writer lock (up to the busy timeout,
      ~5s) and can exceed the client's HTTP read timeout. WAL lets those reads run
      concurrently, so polls return in milliseconds. (On the in-memory test DB
      this pragma is a harmless no-op that stays 'memory'.)
    - busy_timeout=10000: wait up to 10s for a brief lock instead of erroring.
    - synchronous=NORMAL: durable under WAL and far fewer fsyncs on the slow
      shared disk.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=10000")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db():
    """FastAPI dependency yielding a scoped Session per request."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
