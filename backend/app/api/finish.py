"""Session finish-readiness API (Operator Console closeout).

  GET .../finish-readiness   read-only completeness report for the finish flow

Read-only: computes what has/hasn't been captured so the console can surface
anything missing BEFORE the operator finalizes an unrepeatable session. The
finish flow itself (stop -> complete -> export) uses the existing lifecycle
endpoints; only this completeness computation is new.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.finish import compute_completeness
from app.services.session_service import get_session_or_404

router = APIRouter(prefix="/sessions/{session_id}", tags=["finish"])


@router.get("/finish-readiness")
def finish_readiness(session_id: str, db: Session = Depends(get_db)) -> dict:
    session = get_session_or_404(db, session_id)
    return compute_completeness(db, session)
