"""Timeline event store helpers (P0.3).

Every significant event also writes a session_timeline_events row carrying
timestamp_utc and session_time_ms. session_time_ms is wall-clock milliseconds
since the session's start_timestamp_utc (paused time INCLUDED, per the locked
schema); pause/resume are logged as their own events so paused intervals can be
subtracted in analysis if needed. Events recorded before the session starts
(e.g. session_created) carry session_time_ms = 0.
"""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.timeutil import now_utc
from app.models import SessionTimelineEvent
from app.models.session import StudySession


def compute_session_time_ms(session: StudySession, now: datetime) -> int:
    """Wall-clock ms since start_timestamp_utc; 0 before the session starts."""
    if not session.start_timestamp_utc:
        return 0
    start = datetime.fromisoformat(session.start_timestamp_utc)
    delta_ms = int((now - start).total_seconds() * 1000)
    return max(0, delta_ms)


def record_timeline_event(
    db: Session,
    *,
    session: StudySession,
    source: str,
    type: str,
    payload: dict | None = None,
    ref_table: str | None = None,
    ref_id: str | None = None,
    now: datetime | None = None,
) -> SessionTimelineEvent:
    """Append one timeline row. Flushes (no commit) so callers control the
    transaction boundary. Pass ``now`` to share a single clock reading with the
    state change that triggered the event (keeps session_time_ms consistent)."""
    now = now or now_utc()
    event = SessionTimelineEvent(
        session_id=session.session_id,
        participant_id=session.participant_id,
        timestamp_utc=now.isoformat(),
        session_time_ms=compute_session_time_ms(session, now),
        source=source,
        type=type,
        payload=json.dumps(payload) if payload is not None else None,
        ref_table=ref_table,
        ref_id=ref_id,
    )
    db.add(event)
    db.flush()
    return event


def serialize_timeline_event(event: SessionTimelineEvent) -> dict:
    """Plain dict for JSONL/JSON output; payload parsed back to an object."""
    return {
        "event_id": event.event_id,
        "session_id": event.session_id,
        "participant_id": event.participant_id,
        "timestamp_utc": event.timestamp_utc,
        "session_time_ms": event.session_time_ms,
        "source": event.source,
        "type": event.type,
        "payload": json.loads(event.payload) if event.payload else None,
        "ref_table": event.ref_table,
        "ref_id": event.ref_id,
    }
