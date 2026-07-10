"""Session lifecycle + timeline API (P0.2, P0.3).

Lifecycle endpoints validate legal state transitions and write a timeline event
on every change. The timeline read endpoint returns the session's events as
JSONL (default) so a completed session reconstructs from this stream alone.
"""

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import SessionTimelineEvent
from app.models.dtt import DttLoop
from app.models.session import StudySession
from app.schemas.dtt_loop import DttLoopRead
from app.schemas.session import SessionCreate, SessionRead
from app.services.preflight import run_preflight
from app.services.session_service import (
    apply_transition,
    create_session,
    get_session_or_404,
)
from app.services.timeline import record_timeline_event, serialize_timeline_event

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionRead, status_code=status.HTTP_201_CREATED)
def create(payload: SessionCreate, db: Session = Depends(get_db)):
    return create_session(db, payload)


@router.get("", response_model=list[SessionRead])
def list_sessions(db: Session = Depends(get_db)):
    return db.scalars(select(StudySession).order_by(StudySession.created_at)).all()


@router.get("/{session_id}", response_model=SessionRead)
def get_session(session_id: str, db: Session = Depends(get_db)):
    return get_session_or_404(db, session_id)


@router.get("/{session_id}/loops", response_model=list[DttLoopRead])
def get_loops(session_id: str, db: Session = Depends(get_db)):
    """The six dtt_loops rows generated for the session at start, ordered by
    loop position. Empty until the session is started (and only if it carries a
    pb_order_group)."""
    get_session_or_404(db, session_id)
    return db.scalars(
        select(DttLoop)
        .where(DttLoop.session_id == session_id)
        .order_by(DttLoop.loop_index)
    ).all()


# --- lifecycle transitions ---


@router.post("/{session_id}/start", response_model=SessionRead)
def start(
    session_id: str,
    override: bool = False,
    override_operator: Optional[str] = None,
    override_reason: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Start the session -- gated by the preflight checks (P0.12).

    A blocking failure (a required check that FAILED, e.g. recording or
    perception disabled) refuses the start with 409 and the failing checks,
    unless ``override=true`` is passed, in which case the override is recorded on
    the timeline and the session starts anyway."""
    session = get_session_or_404(db, session_id)
    report = run_preflight()
    blocking = report["blocking"]
    if blocking:
        if not override:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": "preflight checks failed; fix them or start with override=true",
                    "failed": [c["id"] for c in blocking],
                    "checks": blocking,
                },
            )
        # Overrides are a deliberate, logged decision (P0.12: override in timeline).
        record_timeline_event(
            db,
            session=session,
            source="preflight",
            type="preflight_overridden",
            payload={
                "failed": [c["id"] for c in blocking],
                "operator": override_operator,
                "reason": override_reason,
                "checks": blocking,
            },
        )
    return apply_transition(db, session, "start")


@router.post("/{session_id}/pause", response_model=SessionRead)
def pause(session_id: str, db: Session = Depends(get_db)):
    return apply_transition(db, get_session_or_404(db, session_id), "pause")


@router.post("/{session_id}/resume", response_model=SessionRead)
def resume(session_id: str, db: Session = Depends(get_db)):
    return apply_transition(db, get_session_or_404(db, session_id), "resume")


@router.post("/{session_id}/stop", response_model=SessionRead)
def stop(session_id: str, db: Session = Depends(get_db)):
    return apply_transition(db, get_session_or_404(db, session_id), "stop")


@router.post("/{session_id}/complete", response_model=SessionRead)
def complete(session_id: str, db: Session = Depends(get_db)):
    return apply_transition(db, get_session_or_404(db, session_id), "complete")


# --- timeline read-back ---


@router.get("/{session_id}/timeline")
def get_timeline(
    session_id: str,
    format: str = "jsonl",
    db: Session = Depends(get_db),
):
    """Return the session's timeline ordered monotonically by event_id.
    format=jsonl (default) -> one JSON object per line; format=json -> array."""
    get_session_or_404(db, session_id)  # 404 if the session does not exist
    events = db.scalars(
        select(SessionTimelineEvent)
        .where(SessionTimelineEvent.session_id == session_id)
        .order_by(SessionTimelineEvent.event_id)
    ).all()
    serialized = [serialize_timeline_event(e) for e in events]

    if format == "json":
        return serialized
    body = "\n".join(json.dumps(s) for s in serialized)
    return Response(content=body, media_type="application/x-ndjson")
