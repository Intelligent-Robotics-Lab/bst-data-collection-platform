"""BST<->platform synchronization API (Phase 7, P0.13).

The contract the BST robot run uses to (a) report progress and (b) wait at a gate
until a self-report is collected (or an operator overrides). Gate state machine
lives in services/sync_gate. All endpoints are keyed by
(session_id, stage-or-loop_index, checkpoint) and are testable now via API,
before any operator UI exists (override included).

  POST .../sync/register               session_register
  POST .../sync/stage-complete         open a stage baseline gate
  POST .../sync/kid-response-complete  open a loop post_kid_response gate
  POST .../sync/feedback-delivered     open a loop post_feedback gate
  GET  .../sync/go-ahead            poll a gate (proceed true/false)
  POST .../sync/override            operator releases a gate (+ marker)
  POST .../sync/complete            session_complete marker
"""

from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.sync import (
    FeedbackDeliveredIn,
    GateRead,
    GoAheadResult,
    KidResponseIn,
    OverrideIn,
    SessionCompleteResult,
    SessionRegisterResult,
    StageCompleteIn,
)
from app.services.session_service import get_session_or_404
from app.services.sync_gate import (
    complete_session,
    go_ahead,
    open_loop_gate,
    open_stage_gate,
    override_gate,
    register_session,
    resolve_gate_identity,
)

router = APIRouter(prefix="/sessions/{session_id}/sync", tags=["sync"])


@router.post("/register", response_model=SessionRegisterResult)
def register(session_id: str, db: Session = Depends(get_db)):
    session = get_session_or_404(db, session_id)
    return register_session(db, session)


@router.post("/stage-complete", response_model=GateRead, status_code=status.HTTP_201_CREATED)
def stage_complete(session_id: str, payload: StageCompleteIn, db: Session = Depends(get_db)):
    session = get_session_or_404(db, session_id)
    return open_stage_gate(db, session, payload.stage)


@router.post(
    "/kid-response-complete", response_model=GateRead, status_code=status.HTTP_201_CREATED
)
def kid_response_complete(
    session_id: str, payload: KidResponseIn, db: Session = Depends(get_db)
):
    """The child-behavior arc has completed (kid exhibited its behavior); feedback
    not yet delivered. Opens the loop post_kid_response gate."""
    session = get_session_or_404(db, session_id)
    return open_loop_gate(db, session, payload.loop_index, "post_kid_response")


@router.post(
    "/feedback-delivered", response_model=GateRead, status_code=status.HTTP_201_CREATED
)
def feedback_delivered(
    session_id: str, payload: FeedbackDeliveredIn, db: Session = Depends(get_db)
):
    session = get_session_or_404(db, session_id)
    return open_loop_gate(db, session, payload.loop_index, "post_feedback")


@router.get("/go-ahead", response_model=GoAheadResult)
def poll_go_ahead(
    session_id: str,
    scope: Literal["stage", "loop"] = Query(...),
    checkpoint: Literal["baseline", "post_kid_response", "post_feedback"] = Query(...),
    stage: Optional[Literal["tutorial", "instruction", "modeling"]] = Query(default=None),
    loop_index: Optional[int] = Query(default=None, ge=1, le=6),
    db: Session = Depends(get_db),
):
    session = get_session_or_404(db, session_id)
    ident = resolve_gate_identity(
        scope=scope, stage_key=stage, loop_index=loop_index, checkpoint=checkpoint
    )
    return go_ahead(db, session, ident)


@router.post("/override", response_model=GateRead)
def override(session_id: str, payload: OverrideIn, db: Session = Depends(get_db)):
    session = get_session_or_404(db, session_id)
    ident = resolve_gate_identity(
        scope=payload.scope,
        stage_key=payload.stage,
        loop_index=payload.loop_index,
        checkpoint=payload.checkpoint,
    )
    return override_gate(db, session, ident, operator=payload.operator, reason=payload.reason)


@router.post("/complete", response_model=SessionCompleteResult)
def session_complete(session_id: str, db: Session = Depends(get_db)):
    session = get_session_or_404(db, session_id)
    return complete_session(db, session)
