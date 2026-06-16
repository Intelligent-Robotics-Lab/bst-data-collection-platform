"""Database backup safeguard.

Zero data loss is paramount and the live SQLite DB is irreplaceable participant
data. We take timestamped, non-destructive file-copy backups:

- on startup (before create_all), capturing the pre-run state; protects against
  starting on top of an emptied/corrupted DB, since prior backups remain.
- on session completion, so every finished session is immediately preserved
  even if the live DB is later corrupted.

The last ``DB_BACKUP_KEEP`` copies are retained in ``BACKUPS_DIR``; older ones
are pruned. Backups never touch the live DB and never raise: a backup failure is
logged but must not break startup or session completion.

Note: a plain file copy is consistent here because the experimenter runs one
session at a time and backups are taken when no write is in flight (startup is
before any connection; completion is immediately after commit). If concurrency
ever increases, switch to SQLite's online backup API / ``VACUUM INTO``.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from app.core.config import settings
from app.core.timeutil import now_utc

logger = logging.getLogger("bst.backup")


def backup_database(reason: str) -> Path | None:
    """Copy the live DB to a timestamped file in BACKUPS_DIR. Returns the backup
    path, or None if there was nothing to back up or the copy failed."""
    src = settings.db_path
    if not src.exists():
        logger.info("DB backup skipped (%s): no database file at %s", reason, src)
        return None

    backups_dir = settings.backups_dir
    ts = now_utc().strftime("%Y%m%dT%H%M%S_%fZ")
    dest = backups_dir / f"bst-{ts}-{reason}.db"
    try:
        backups_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)  # non-destructive; preserves metadata
        logger.info("DB backup written (%s): %s", reason, dest)
    except Exception as exc:  # never let a backup failure break the caller
        logger.error("DB backup FAILED (%s): %s", reason, exc)
        return None

    _prune_backups(backups_dir, settings.DB_BACKUP_KEEP)
    return dest


def _prune_backups(backups_dir: Path, keep: int) -> None:
    """Keep the newest ``keep`` backups; delete older ones. Operates only on
    files in BACKUPS_DIR, never the live DB. The timestamp-prefixed names sort
    chronologically."""
    if keep < 0:
        return
    backups = sorted(backups_dir.glob("bst-*.db"))
    excess = len(backups) - keep
    for old in backups[: max(0, excess)]:
        try:
            old.unlink()
            logger.info("DB backup pruned: %s", old)
        except OSError as exc:
            logger.warning("could not prune backup %s: %s", old, exc)
