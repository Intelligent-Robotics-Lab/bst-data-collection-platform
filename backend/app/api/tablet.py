"""Push-to-tablet API (P0.6).

The experimenter pushes the next form; the tablet polls ``/tablet/assignment``
and switches to it without participant action. The assignment is ephemeral
in-memory routing state; the responses it produces are persisted in their own
tables. A push that names a session also writes a session_timeline_events row
(every significant event is on the timeline).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.tablet import AssignmentRead, PushPayload
from app.services.questionnaire import get_questionnaire
from app.services.session_service import get_session_or_404
from app.services.tablet import (
    clear_assignment,
    get_assignment,
    mark_tablet_poll,
    set_assignment,
)
from app.services.timeline import record_timeline_event

router = APIRouter(prefix="/tablet", tags=["tablet"])


@router.get("/assignment", response_model=AssignmentRead)
def poll_assignment():
    """Tablet poll target. No experimenter data or navigation here (P0.6).
    Records the poll so the preflight gate can tell a tablet is connected."""
    mark_tablet_poll()
    return get_assignment()


@router.post("/push", response_model=AssignmentRead)
def push(payload: PushPayload, db: Session = Depends(get_db)):
    version = payload.questionnaire_version

    if payload.form_type == "idle":
        return clear_assignment()

    # Both real forms must route their responses to a real session.
    if not payload.session_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"session_id is required to push a '{payload.form_type}' form",
        )
    session = get_session_or_404(db, payload.session_id)

    if payload.form_type == "questionnaire":
        if not payload.questionnaire_key:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="questionnaire_key is required to push a questionnaire",
            )
        row = get_questionnaire(db, payload.questionnaire_key, version)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"unknown questionnaire '{payload.questionnaire_key}'"
                + (f" version '{version}'" if version else "")
                + "; not registered",
            )
        version = row.version
        event_payload = {
            "form_type": "questionnaire",
            "questionnaire_key": payload.questionnaire_key,
            "questionnaire_version": version,
        }
    else:  # self_report
        event_payload = {
            "form_type": "self_report",
            "self_report_context": payload.self_report_context,
        }

    record_timeline_event(
        db,
        session=session,
        source="tablet",
        type="form_pushed",
        payload=event_payload,
        ref_table="sessions",
        ref_id=session.session_id,
    )
    db.commit()

    return set_assignment(
        form_type=payload.form_type,
        session_id=payload.session_id,
        questionnaire_key=payload.questionnaire_key,
        questionnaire_version=version,
        self_report_context=payload.self_report_context,
        message=payload.message,
    )


@router.post("/clear", response_model=AssignmentRead)
def clear():
    return clear_assignment()
