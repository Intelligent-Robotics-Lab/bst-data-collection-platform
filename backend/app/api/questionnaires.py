"""Questionnaire engine API (P0.4 / P0.6).

Two surfaces:
* discovery/rendering -- list registered questionnaires and fetch a render-ready
  config (resolved item types + scales) for the tablet to draw dynamically.
* responses (scoped to a session) -- autosave drafts, submit finalized answers,
  and read back saved answers for refresh-restore.

Adding or editing a questionnaire is a config change (configs/questionnaires/*)
plus a backend restart; no code change here.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.questionnaire import Questionnaire
from app.schemas.questionnaire import (
    AnswersPayload,
    QuestionnaireRead,
    ResponseSummary,
    ResponsesRead,
)
from app.services.questionnaire import build_render_spec, get_questionnaire_config
from app.services.questionnaire_response import (
    get_responses,
    save_partial,
    submit,
)
from app.services.session_service import get_session_or_404

router = APIRouter(prefix="/questionnaires", tags=["questionnaires"])
responses_router = APIRouter(
    prefix="/sessions/{session_id}/questionnaires", tags=["questionnaires"]
)


@router.get("", response_model=list[QuestionnaireRead])
def list_questionnaires(
    timepoint: str | None = Query(default=None, pattern="^(pre|post|na)$"),
    db: Session = Depends(get_db),
):
    stmt = select(Questionnaire)
    if timepoint is not None:
        stmt = stmt.where(Questionnaire.timepoint == timepoint)
    return db.scalars(stmt.order_by(Questionnaire.id)).all()


@router.get("/{questionnaire_key}/config")
def get_config(
    questionnaire_key: str,
    version: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    """Render-ready config: every item has a resolved type and (for numeric
    items) a resolved scale, so the tablet draws the form with no engine logic."""
    cfg = get_questionnaire_config(db, questionnaire_key, version)
    if cfg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no registered questionnaire '{questionnaire_key}'"
            + (f" version '{version}'" if version else ""),
        )
    return build_render_spec(cfg)


# --- responses (scoped to a session) ---------------------------------------


@responses_router.get("/{questionnaire_key}/responses", response_model=ResponsesRead)
def read_responses(
    session_id: str,
    questionnaire_key: str,
    version: str | None = None,
    db: Session = Depends(get_db),
):
    session = get_session_or_404(db, session_id)
    return get_responses(db, session, questionnaire_key, version)


@responses_router.post("/{questionnaire_key}/autosave", response_model=ResponseSummary)
def autosave(
    session_id: str,
    questionnaire_key: str,
    payload: AnswersPayload,
    version: str | None = None,
    db: Session = Depends(get_db),
):
    session = get_session_or_404(db, session_id)
    return save_partial(db, session, questionnaire_key, version, payload.answers)


@responses_router.post(
    "/{questionnaire_key}/submit",
    response_model=ResponseSummary,
    status_code=status.HTTP_201_CREATED,
)
def submit_responses(
    session_id: str,
    questionnaire_key: str,
    payload: AnswersPayload,
    version: str | None = None,
    db: Session = Depends(get_db),
):
    session = get_session_or_404(db, session_id)
    return submit(db, session, questionnaire_key, version, payload.answers)
