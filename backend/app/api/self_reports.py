"""Participant self-report API (P0.7).

Writes participant_self_reports + a timeline event; the trial_id FK is guarded
in the service (clean 422). Self-reports are typically pushed to the tablet (the
participant only moves sliders), but the endpoint accepts the full context so it
also works from the experimenter side.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.signals import ParticipantSelfReport
from app.schemas.self_report import (
    BeforeAfter,
    FunctionClass,
    IsProblem,
    Phase,
    RehearsalSelfReportCreate,
    SelfReportAutosave,
    SelfReportContext,
    SelfReportCreate,
    SelfReportDraftRead,
    SelfReportDraftSummary,
    SelfReportRead,
    Timepoint,
)
from app.services.self_report import (
    add_rehearsal_self_report,
    add_self_report,
    get_draft,
    save_draft,
)
from app.services.session_service import get_session_or_404

router = APIRouter(prefix="/sessions/{session_id}/self-reports", tags=["self-reports"])


@router.post("", response_model=SelfReportRead, status_code=status.HTTP_201_CREATED)
def create_self_report(
    session_id: str, payload: SelfReportCreate, db: Session = Depends(get_db)
):
    session = get_session_or_404(db, session_id)
    return add_self_report(db, session, payload)


@router.post(
    "/rehearsal",
    response_model=list[SelfReportRead],
    status_code=status.HTTP_201_CREATED,
)
def create_rehearsal_self_report(
    session_id: str, payload: RehearsalSelfReportCreate, db: Session = Depends(get_db)
):
    """Expanded post-trial/pre-feedback form: behavior checklist + two PAD+emotion
    sets. Writes two rows (child_behavior + self_handling) atomically."""
    session = get_session_or_404(db, session_id)
    return add_rehearsal_self_report(db, session, payload)


@router.get("", response_model=list[SelfReportRead])
def list_self_reports(session_id: str, db: Session = Depends(get_db)):
    get_session_or_404(db, session_id)
    return db.scalars(
        select(ParticipantSelfReport)
        .where(ParticipantSelfReport.session_id == session_id)
        .order_by(ParticipantSelfReport.self_report_id)
    ).all()


@router.post("/autosave", response_model=SelfReportDraftSummary)
def autosave_self_report(
    session_id: str, payload: SelfReportAutosave, db: Session = Depends(get_db)
):
    """Autosave in-progress SAM picks for one context (any subset of the three).
    Draft only: no raw row, no timeline event. Upserts the single draft for this
    (session, context)."""
    session = get_session_or_404(db, session_id)
    return save_draft(db, session, payload)


@router.get("/draft", response_model=SelfReportDraftRead)
def read_self_report_draft(
    session_id: str,
    loop_index: Optional[int] = Query(default=None, ge=1, le=6),
    phase: Phase = Query(...),
    timepoint: Timepoint = Query(...),
    function_class: FunctionClass = Query(...),
    is_problem: Optional[IsProblem] = Query(default=None),
    sequence_position: Optional[int] = Query(default=None, ge=1, le=6),
    before_after_robot_action: Optional[BeforeAfter] = Query(default="na"),
    trial_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
):
    """Restore the saved sliders for one context (refresh-restore on the tablet)."""
    session = get_session_or_404(db, session_id)
    ctx = SelfReportContext(
        loop_index=loop_index,
        phase=phase,
        timepoint=timepoint,
        function_class=function_class,
        is_problem=is_problem,
        sequence_position=sequence_position,
        before_after_robot_action=before_after_robot_action,
        trial_id=trial_id,
    )
    return get_draft(db, session, ctx)
