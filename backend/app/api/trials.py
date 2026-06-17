"""DTT trial logging API (P0.5).

A trial is validated against the session's assigned protocol config in the
service layer; config-membership and FK/range problems return a clean 422, never
a DB 500. Each logged trial also writes a session_timeline_events row.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.dtt import DttTrial
from app.schemas.trial import TrialCreate, TrialRead
from app.services.session_service import get_session_or_404
from app.services.trial_service import create_trial

router = APIRouter(prefix="/sessions/{session_id}/trials", tags=["trials"])


@router.post("", response_model=TrialRead, status_code=status.HTTP_201_CREATED)
def log_trial(session_id: str, payload: TrialCreate, db: Session = Depends(get_db)):
    session = get_session_or_404(db, session_id)
    return create_trial(db, session, payload)


@router.get("", response_model=list[TrialRead])
def list_trials(session_id: str, db: Session = Depends(get_db)):
    get_session_or_404(db, session_id)
    return db.scalars(
        select(DttTrial)
        .where(DttTrial.session_id == session_id)
        .order_by(DttTrial.trial_number)
    ).all()
