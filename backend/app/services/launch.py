"""Robot launch-handoff service (Operator Console v2).

Turns the canonical session config into something BST can fetch, and tracks the
prepare -> waiting -> start_requested -> started / error handshake the console
drives. Additive to v1: no session/gate/questionnaire/export logic is changed.

Every state change also writes a session_timeline_events row, so the launch
handshake is auditable and flows into exports with no export-code change.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.timeutil import now_utc
from app.models.launch import SessionLaunch
from app.models.session import StudySession
from app.services.timeline import record_timeline_event

logger = logging.getLogger("bst.launch")


def support_label(support_condition) -> str | None:
    if support_condition == 1:
        return "supportive"
    if support_condition == 0:
        return "neutral"
    return None


def build_config(session: StudySession, platform_base: str) -> dict:
    """The canonical launch config, derived from the session (single source of
    truth). ``platform_base`` is the URL the console/BST should call back on."""
    return {
        "session_id": session.session_id,
        "participant_id": session.participant_id,
        "scenario_type": session.scenario_type,
        "pb_order_group": session.pb_order_group,
        "support_condition": session.support_condition,
        "support_label": support_label(session.support_condition),
        "platform_base": platform_base.rstrip("/"),
    }


def _get_row(db: Session, session_id: str) -> SessionLaunch | None:
    return db.scalar(select(SessionLaunch).where(SessionLaunch.session_id == session_id))


def _get_or_create(db: Session, session: StudySession) -> SessionLaunch:
    row = _get_row(db, session.session_id)
    if row is None:
        row = SessionLaunch(session_id=session.session_id, status="prepared")
        db.add(row)
        db.flush()
    return row


def _event(db: Session, session: StudySession, row: SessionLaunch, etype: str, now) -> None:
    record_timeline_event(
        db,
        session=session,
        source="launch",
        type=etype,
        payload={"status": row.status, "error_text": row.error_text},
        ref_table="session_launches",
        ref_id=str(row.launch_id),
        now=now,
    )


def get_status(db: Session, session: StudySession) -> dict:
    """Current launch state. Returns a safe 'none' default when nothing has been
    prepared yet, so the console never breaks on a missing row."""
    row = _get_row(db, session.session_id)
    if row is None:
        return {"session_id": session.session_id, "status": "none"}
    return {
        "session_id": row.session_id,
        "status": row.status,
        "prepared_at": row.prepared_at,
        "config_fetched_at": row.config_fetched_at,
        "start_requested_at": row.start_requested_at,
        "started_at": row.started_at,
        "error_at": row.error_at,
        "error_text": row.error_text,
        "requested_by": row.requested_by,
        "updated_at": row.updated_at,
    }


def prepare(db: Session, session: StudySession) -> dict:
    now = now_utc()
    row = _get_or_create(db, session)
    row.status = "prepared"
    row.prepared_at = now.isoformat()
    row.error_text = None
    row.error_at = None
    row.updated_at = now.isoformat()
    _event(db, session, row, "launch_prepared", now)
    db.commit()
    return get_status(db, session)


def request_start(db: Session, session: StudySession, requested_by: str | None) -> dict:
    """Operator-triggered start. Requires a running session (a start signal only
    makes sense for a live session)."""
    if session.state != "running":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"cannot request start for session '{session.session_id}' in state "
                f"'{session.state}'; the session must be running"
            ),
        )
    now = now_utc()
    row = _get_or_create(db, session)
    row.status = "start_requested"
    row.start_requested_at = now.isoformat()
    row.requested_by = requested_by
    row.updated_at = now.isoformat()
    _event(db, session, row, "launch_start_requested", now)
    db.commit()
    return get_status(db, session)


def ack(db: Session, session: StudySession, phase: str) -> dict:
    """BST acknowledges progress. 'config_received' -> waiting (unless already
    further along); 'started' -> started."""
    now = now_utc()
    row = _get_or_create(db, session)
    if phase == "config_received":
        row.config_fetched_at = now.isoformat()
        if row.status in ("prepared", "none"):
            row.status = "waiting"
    elif phase == "started":
        row.started_at = now.isoformat()
        row.status = "started"
    row.updated_at = now.isoformat()
    _event(db, session, row, "launch_ack", now)
    db.commit()
    return get_status(db, session)


def set_error(db: Session, session: StudySession, message: str) -> dict:
    now = now_utc()
    row = _get_or_create(db, session)
    row.status = "error"
    row.error_text = message
    row.error_at = now.isoformat()
    row.updated_at = now.isoformat()
    _event(db, session, row, "launch_error", now)
    db.commit()
    logger.warning("launch error for %s: %s", session.session_id, message)
    return get_status(db, session)
