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


# Columns added to existing tables after their first release. create_all only
# CREATEs missing tables; it never ALTERs an existing one to add a column, so an
# already-populated data/bst.db would lack these. ensure_added_columns() adds any
# that are missing (nullable, non-destructive, idempotent) at startup -- run after
# the startup DB backup. Fresh/test DBs get the column from the model via
# create_all, so the check simply finds it present and skips.
_ADDED_COLUMNS: list[tuple[str, str, str]] = [
    ("participant_self_reports", "emotion_category", "TEXT"),
    ("self_report_drafts", "emotion_category", "TEXT"),
    # Expanded rehearsal (post-trial/pre-feedback) self-report: two-row referent +
    # the child-behavior checklist on the raw table, and the matching second
    # PAD+emotion set + checklist on the working-draft table.
    ("participant_self_reports", "referent", "TEXT"),
    ("participant_self_reports", "child_behaviors", "TEXT"),
    ("self_report_drafts", "child_behaviors", "TEXT"),
    ("self_report_drafts", "handling_pleasure", "REAL"),
    ("self_report_drafts", "handling_arousal", "REAL"),
    ("self_report_drafts", "handling_dominance", "REAL"),
    ("self_report_drafts", "handling_emotion_category", "TEXT"),
]


def ensure_added_columns(bind: Engine = engine) -> list[str]:
    """Add any post-release columns missing from existing tables. Returns the
    'table.column' names it added (empty when nothing was needed)."""
    added: list[str] = []
    with bind.begin() as conn:
        for table, col, decl in _ADDED_COLUMNS:
            rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
            if not rows:
                continue  # table not created yet; create_all will make it with the column
            if col not in {r[1] for r in rows}:
                conn.exec_driver_sql(f'ALTER TABLE "{table}" ADD COLUMN "{col}" {decl}')
                added.append(f"{table}.{col}")
    return added


def get_db():
    """FastAPI dependency yielding a scoped Session per request."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
