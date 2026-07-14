"""Participant-facing experiment-progress API.

  GET /progress                     progress for the current session (tablet)
  GET /sessions/{session_id}/progress   progress for one session

Read-only, derived from the sync gates + session state. The tablet shows this
between forms; it switches to a questionnaire/self-report the moment one is
pushed (via /tablet/assignment).
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.progress import compute_progress, current_progress
from app.services.session_service import get_session_or_404

router = APIRouter(tags=["progress"])


@router.get("/progress")
def progress(db: Session = Depends(get_db)) -> dict:
    """Progress for the current (running, else most recent) session."""
    return current_progress(db)


@router.get("/sessions/{session_id}/progress")
def session_progress(session_id: str, db: Session = Depends(get_db)) -> dict:
    return compute_progress(db, get_session_or_404(db, session_id))
