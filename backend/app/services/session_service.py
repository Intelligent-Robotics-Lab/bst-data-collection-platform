"""Session lifecycle service (P0.2).

State machine:  created -> running <-> paused -> stopped -> completed

Every transition is validated against the legal map and writes a timeline
event. Illegal transitions raise HTTP 409 (e.g. resuming a session that is not
paused).
"""

from __future__ import annotations

import logging

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.timeutil import now_utc
from app.models.dtt import DttProtocol
from app.models.participant import Participant
from app.models.session import StudySession
from app.services import perception, recording
from app.services.backup import backup_database
from app.services.dtt_loops import generate_dtt_loops
from app.services.monitor import clear_monitor
from app.services.timeline import record_timeline_event

logger = logging.getLogger("bst.session")

# action -> (states it is legal from, resulting state, timeline event type)
LEGAL_TRANSITIONS: dict[str, tuple[frozenset[str], str, str]] = {
    "start": (frozenset({"created"}), "running", "session_started"),
    "pause": (frozenset({"running"}), "paused", "session_paused"),
    "resume": (frozenset({"paused"}), "running", "session_resumed"),
    "stop": (frozenset({"running", "paused"}), "stopped", "session_stopped"),
    "complete": (frozenset({"stopped"}), "completed", "session_completed"),
}


def get_session_or_404(db: Session, session_id: str) -> StudySession:
    session = db.get(StudySession, session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"session_id '{session_id}' not found",
        )
    return session


def create_session(db: Session, payload) -> StudySession:
    if db.get(StudySession, payload.session_id) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"session_id '{payload.session_id}' already exists",
        )
    if db.get(Participant, payload.participant_id) is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unknown participant_id '{payload.participant_id}'",
        )
    # Guard the protocol_id FK so a dangling reference returns a clean 422
    # instead of surfacing the DB IntegrityError as a 500.
    if payload.protocol_id is not None and db.get(DttProtocol, payload.protocol_id) is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"unknown protocol_id {payload.protocol_id}; no such dtt_protocols row",
        )

    session = StudySession(
        session_id=payload.session_id,
        participant_id=payload.participant_id,
        scenario_type=payload.scenario_type,
        support_condition=payload.support_condition,
        pb_order_group=payload.pb_order_group,
        protocol_id=payload.protocol_id,
        state="created",
        platform_version=settings.PLATFORM_VERSION,
        notes=payload.notes,
    )
    db.add(session)
    db.flush()  # ensure the row exists before the timeline FK references it

    record_timeline_event(
        db,
        session=session,
        source="session",
        type="session_created",
        payload={
            "scenario_type": session.scenario_type,
            "support_condition": session.support_condition,
            "pb_order_group": session.pb_order_group,
        },
        ref_table="sessions",
        ref_id=session.session_id,
    )
    db.commit()
    db.refresh(session)
    return session


def apply_transition(db: Session, session: StudySession, action: str) -> StudySession:
    allowed, target_state, event_type = LEGAL_TRANSITIONS[action]
    if session.state not in allowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"cannot '{action}' a session in state '{session.state}'; "
                f"allowed only from {sorted(allowed)}"
            ),
        )

    now = now_utc()
    # Set start anchor first so the session_started event itself reads 0 ms.
    if action == "start":
        session.start_timestamp_utc = now.isoformat()
    session.state = target_state
    if action == "stop":
        session.stop_timestamp_utc = now.isoformat()
    if action == "complete":
        session.completed_at = now.isoformat()

    record_timeline_event(
        db,
        session=session,
        source="session",
        type=event_type,
        payload={"from_state": sorted(allowed), "to_state": target_state},
        ref_table="sessions",
        ref_id=session.session_id,
        now=now,
    )

    # Materialize the six dtt_loops rows once, atomically with the start
    # transition (created -> running). Generation is idempotent and never
    # overwrites existing rows, so the once-only state machine plus this guard
    # together preserve raw-data immutability.
    if action == "start":
        generate_dtt_loops(db, session)

    db.commit()
    db.refresh(session)

    # A/V recording follows the session lifecycle: start on 'start', stop on
    # 'stop'. The recording service logs its own failures and never raises; the
    # outer guard is belt-and-suspenders so an unexpected bug there can never
    # turn a lifecycle transition into a 500 and disrupt a live session.
    try:
        if action == "start":
            recording.start_session_recording(db, session)
        elif action == "stop":
            recording.stop_session_recording(db, session)
    except Exception:  # noqa: BLE001
        logger.exception("Recording hook failed on '%s' for %s", action, session.session_id)

    # Perception polling follows the session lifecycle: start on 'start', stop on
    # 'stop'. The adapter logs its own outages and never raises; the outer guard
    # is belt-and-suspenders so a perception bug can never turn a lifecycle
    # transition into a 500 and disrupt a live session.
    try:
        if action == "start":
            perception.start_session_perception(db, session)
        elif action == "stop":
            perception.stop_session_perception(db, session)
    except Exception:  # noqa: BLE001
        logger.exception("Perception hook failed on '%s' for %s", action, session.session_id)

    # The live monitor mirror is process-global and outlives a session, so a new
    # session would otherwise inherit the SD/trial_state the previous one ended
    # on until the robot next pushes. Clear it as the session goes live so the
    # tablet starts fresh from SD 1, and again when a session ends so the value
    # it stopped on does not linger for the next one.
    if action in ("start", "stop", "complete"):
        clear_monitor()

    # Preserve every finished session immediately (non-destructive; never raises).
    if action == "complete":
        backup_database(reason="completion")

    return session
