"""Attention-check logging API.

  GET  /attention-checks/questions            the question set (admin console)
  GET  /sessions/{id}/attention-checks         responses logged for a session
  POST /sessions/{id}/attention-checks         log/correct one answer (auto|manual)

The POST is used both by the automated path (the robot reports the participant's
answer, source='auto') and by the research administrator in the console
(source='manual'). Correctness is computed server-side from the config.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.attention_check import (
    AttentionCheckLog,
    AttentionCheckQuestion,
    AttentionCheckRead,
    Phase,
)
from app.services.attention_check import list_questions, list_responses, log_response
from app.services.session_service import get_session_or_404

# Question catalogue (session-independent).
questions_router = APIRouter(prefix="/attention-checks", tags=["attention-checks"])


@questions_router.get("/questions", response_model=list[AttentionCheckQuestion])
def get_attention_check_questions(phase: Optional[Phase] = Query(default=None)):
    """The attention-check questions, optionally filtered to one stage."""
    return list_questions(phase)


# Per-session responses.
router = APIRouter(
    prefix="/sessions/{session_id}/attention-checks", tags=["attention-checks"]
)


@router.get("", response_model=list[AttentionCheckRead])
def list_session_attention_checks(session_id: str, db: Session = Depends(get_db)):
    session = get_session_or_404(db, session_id)
    return list_responses(db, session)


@router.post("", response_model=AttentionCheckRead)
def log_attention_check(
    session_id: str, payload: AttentionCheckLog, db: Session = Depends(get_db)
):
    session = get_session_or_404(db, session_id)
    return log_response(db, session, payload)
