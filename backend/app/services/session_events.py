"""Services for logging experimenter notes and robot events into a session.

Both write their own row plus a session_timeline_events row (with the content in
the payload, so the session reconstructs from the timeline alone). FK and range
inputs are guarded so bad references return a clean 4xx instead of a DB 500.
"""

from __future__ import annotations

import json

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.timeutil import now_utc
from app.models.dtt import DttTrial
from app.models.session import StudySession
from app.models.signals import RobotEvent
from app.models.system import ExperimenterNote
from app.services.timeline import compute_session_time_ms, record_timeline_event


def add_note(db: Session, session: StudySession, payload) -> ExperimenterNote:
    if payload.trial_id is not None:
        trial = db.get(DttTrial, payload.trial_id)
        if trial is None or trial.session_id != session.session_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"unknown trial_id {payload.trial_id} for session '{session.session_id}'",
            )

    now = now_utc()
    note = ExperimenterNote(
        session_id=session.session_id,
        participant_id=session.participant_id,
        text=payload.text,
        loop_index=payload.loop_index,
        trial_id=payload.trial_id,
        timestamp_utc=now.isoformat(),
        session_time_ms=compute_session_time_ms(session, now),
    )
    db.add(note)
    db.flush()

    record_timeline_event(
        db,
        session=session,
        source="note",
        type="note_added",
        payload={
            "note_id": note.note_id,
            "text": note.text,
            "loop_index": note.loop_index,
            "trial_id": note.trial_id,
        },
        ref_table="experimenter_notes",
        ref_id=str(note.note_id),
        now=now,
    )
    db.commit()
    db.refresh(note)
    return note


def add_robot_event(db: Session, session: StudySession, payload) -> RobotEvent:
    now = now_utc()
    event = RobotEvent(
        session_id=session.session_id,
        participant_id=session.participant_id,
        role=payload.role,
        utterance_or_action=payload.utterance_or_action,
        condition=payload.condition,
        script_version=payload.script_version,
        source=payload.source,
        loop_index=payload.loop_index,
        payload_json=json.dumps(payload.payload) if payload.payload is not None else None,
        timestamp_utc=now.isoformat(),
        session_time_ms=compute_session_time_ms(session, now),
    )
    db.add(event)
    db.flush()

    record_timeline_event(
        db,
        session=session,
        source="robot",
        type="robot_event",
        payload={
            "robot_event_id": event.robot_event_id,
            "role": event.role,
            "utterance_or_action": event.utterance_or_action,
            "condition": event.condition,
            "script_version": event.script_version,
            "source": event.source,
            "loop_index": event.loop_index,
            "payload": payload.payload,
        },
        ref_table="robot_events",
        ref_id=str(event.robot_event_id),
        now=now,
    )
    db.commit()
    db.refresh(event)
    return event
