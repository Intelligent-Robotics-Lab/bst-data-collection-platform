"""Perception events API (P0.9).

Read-only. Events are produced by the perception polling adapter under the
session lifecycle; this endpoint exposes the resulting ``perception_events`` rows
for the dashboard and for verifying ingestion. A ``summary`` endpoint gives
per-task counts and the current connection status without pulling thousands of
high-frequency rows.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.signals import PerceptionEvent
from app.schemas.perception import PerceptionEventRead
from app.services.perception_source import TASKS
from app.services.session_service import get_session_or_404

router = APIRouter(prefix="/sessions/{session_id}/perception-events", tags=["perception"])


@router.get("", response_model=list[PerceptionEventRead])
def list_perception_events(
    session_id: str,
    task: Optional[str] = Query(default=None, pattern="^(asr|emotion|gesture)$"),
    limit: int = Query(default=200, ge=1, le=5000),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
):
    """Most recent events first by default (these streams are high-frequency)."""
    get_session_or_404(db, session_id)
    stmt = select(PerceptionEvent).where(PerceptionEvent.session_id == session_id)
    if task is not None:
        stmt = stmt.where(PerceptionEvent.task == task)
    col = PerceptionEvent.event_id
    stmt = stmt.order_by(col.desc() if order == "desc" else col.asc()).limit(limit)
    return db.scalars(stmt).all()


@router.get("/summary")
def perception_summary(session_id: str, db: Session = Depends(get_db)) -> dict:
    """Per-task counts + latest connection status, for the dashboard/checklist."""
    get_session_or_404(db, session_id)
    out: dict = {"session_id": session_id, "tasks": {}}
    for task in TASKS:
        total = db.scalar(
            select(func.count())
            .select_from(PerceptionEvent)
            .where(PerceptionEvent.session_id == session_id, PerceptionEvent.task == task)
        )
        down = db.scalar(
            select(func.count())
            .select_from(PerceptionEvent)
            .where(
                PerceptionEvent.session_id == session_id,
                PerceptionEvent.task == task,
                PerceptionEvent.connection_status == "down",
            )
        )
        latest = db.scalar(
            select(PerceptionEvent)
            .where(PerceptionEvent.session_id == session_id, PerceptionEvent.task == task)
            .order_by(PerceptionEvent.event_id.desc())
            .limit(1)
        )
        out["tasks"][task] = {
            "count": total or 0,
            "down_count": down or 0,
            "latest_connection_status": latest.connection_status if latest else None,
            "latest_source_timestamp_utc": latest.source_timestamp_utc if latest else None,
        }
    return out
