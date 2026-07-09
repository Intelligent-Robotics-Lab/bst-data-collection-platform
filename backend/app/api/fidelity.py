"""Human fidelity scoring API (Operator Console v3).

Per-loop ABA/BST fidelity scoring, keyed by (session_id, loop_index):

  GET  .../fidelity-scores               list all loop scores for the session
  GET  .../fidelity-scores/{loop_index}  one loop score
  PUT  .../fidelity-scores/{loop_index}  create or update (draft autosave / edit)
  POST .../fidelity-scores/{loop_index}/complete   mark the loop score complete

Human scoring only: no automated/LLM score is stored or returned (v3). Scoring
never gates the robot; these are plain operator writes.
"""

from fastapi import APIRouter, Depends, Path
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.fidelity import FidelityScoreRead, FidelityScoreUpsert
from app.services.fidelity import (
    complete_score,
    get_score,
    list_scores,
    serialize_fidelity_score,
    upsert_score,
)
from app.services.session_service import get_session_or_404

router = APIRouter(prefix="/sessions/{session_id}/fidelity-scores", tags=["fidelity"])


@router.get("", response_model=list[FidelityScoreRead])
def list_fidelity_scores(session_id: str, db: Session = Depends(get_db)):
    session = get_session_or_404(db, session_id)
    return [serialize_fidelity_score(r) for r in list_scores(db, session)]


@router.get("/{loop_index}", response_model=FidelityScoreRead)
def read_fidelity_score(
    session_id: str,
    loop_index: int = Path(ge=1, le=6),
    db: Session = Depends(get_db),
):
    session = get_session_or_404(db, session_id)
    return serialize_fidelity_score(get_score(db, session, loop_index))


@router.put("/{loop_index}", response_model=FidelityScoreRead)
def put_fidelity_score(
    session_id: str,
    payload: FidelityScoreUpsert,
    loop_index: int = Path(ge=1, le=6),
    db: Session = Depends(get_db),
):
    session = get_session_or_404(db, session_id)
    return serialize_fidelity_score(upsert_score(db, session, loop_index, payload))


@router.post("/{loop_index}/complete", response_model=FidelityScoreRead)
def complete_fidelity_score(
    session_id: str,
    loop_index: int = Path(ge=1, le=6),
    db: Session = Depends(get_db),
):
    session = get_session_or_404(db, session_id)
    return serialize_fidelity_score(complete_score(db, session, loop_index))
