"""Clean rebuild of ONLY the two self-report tables.

Drops and recreates `participant_self_reports` and `self_report_drafts` from the
current SQLAlchemy models, so their schema matches the polished definition
(integer SAM, integer feeling ratings, DB CHECK constraints, no obsolete slider
columns). Every OTHER table -- perception_events, sessions, participants,
dtt_*, questionnaires, timeline, etc. -- is left completely untouched.

Pre-launch use only. The existing self-report rows are test data and ARE
DELETED by this rebuild; a full database backup is taken first. The script is a
no-op dry run unless you pass --yes.

Run from the backend/ directory, e.g.:
    ./.venv/bin/python -m scripts.rebuild_self_report_tables            # dry run
    ./.venv/bin/python -m scripts.rebuild_self_report_tables --yes      # do it
It targets whatever DB DB_PATH/.env points at (settings.db_path).
"""

from __future__ import annotations

import argparse

from sqlalchemy import inspect, text

from app.db.session import engine
from app.models import Base
from app.models.signals import ParticipantSelfReport, SelfReportDraft
from app.services.backup import backup_database

# Only these two tables are rebuilt. Nothing references them via FK, so dropping
# the child tables is safe and leaves the rest of the schema intact.
TABLES = [ParticipantSelfReport.__table__, SelfReportDraft.__table__]


def _row_count(insp, name: str) -> int:
    if not insp.has_table(name):
        return -1
    with engine.connect() as conn:
        return conn.execute(text(f'SELECT count(*) FROM "{name}"')).scalar_one()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--yes", action="store_true", help="confirm the destructive rebuild")
    args = ap.parse_args()

    insp = inspect(engine)
    print(f"Target DB: {engine.url}")
    for t in TABLES:
        n = _row_count(insp, t.name)
        where = "absent" if n < 0 else f"{n} row(s)"
        print(f"  {t.name}: {where} -> drop + recreate")

    if not args.yes:
        print("\nDry run. Re-run with --yes to proceed (a full DB backup is taken first).")
        return

    backup = backup_database(reason="self_report_rebuild")
    print(f"\nBackup: {backup if backup else '(no existing DB file to back up)'}")
    Base.metadata.drop_all(bind=engine, tables=TABLES)
    Base.metadata.create_all(bind=engine, tables=TABLES)
    print("Rebuilt (clean schema): " + ", ".join(t.name for t in TABLES))


if __name__ == "__main__":
    main()
