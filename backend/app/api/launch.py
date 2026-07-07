"""Robot launch-handoff API (Operator Console v2).

Lets the console hand the canonical session config to BST and trigger start, so
the operator never re-types session_id / pb_order_group / support_condition into
the robot terminal. Read endpoints are safe when nothing is prepared yet.

  GET  .../launch/config    canonical config BST consumes (single source of truth)
  GET  .../launch/status    console polls this to show launch state
  POST .../launch/prepare   operator marks the launch config ready
  POST .../launch/start     operator start signal (requires a running session)
  POST .../launch/ack       BST: config received / interaction started
  POST .../launch/error     BST: launch failed
"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.launch import AckIn, ErrorIn, LaunchConfig, LaunchStatusRead
from app.services.launch import (
    ack,
    build_config,
    get_status,
    prepare,
    request_start,
    set_error,
)
from app.services.session_service import get_session_or_404

router = APIRouter(prefix="/sessions/{session_id}/launch", tags=["launch"])


@router.get("/config", response_model=LaunchConfig)
def launch_config(session_id: str, request: Request, db: Session = Depends(get_db)):
    session = get_session_or_404(db, session_id)
    return build_config(session, str(request.base_url))


@router.get("/status", response_model=LaunchStatusRead)
def launch_status(session_id: str, db: Session = Depends(get_db)):
    session = get_session_or_404(db, session_id)
    return get_status(db, session)


@router.post("/prepare", response_model=LaunchStatusRead)
def launch_prepare(session_id: str, db: Session = Depends(get_db)):
    session = get_session_or_404(db, session_id)
    return prepare(db, session)


@router.post("/start", response_model=LaunchStatusRead)
def launch_start(session_id: str, db: Session = Depends(get_db)):
    session = get_session_or_404(db, session_id)
    return request_start(db, session, requested_by="console")


@router.post("/ack", response_model=LaunchStatusRead)
def launch_ack(session_id: str, payload: AckIn, db: Session = Depends(get_db)):
    session = get_session_or_404(db, session_id)
    return ack(db, session, payload.phase)


@router.post("/error", response_model=LaunchStatusRead)
def launch_error(session_id: str, payload: ErrorIn, db: Session = Depends(get_db)):
    session = get_session_or_404(db, session_id)
    return set_error(db, session, payload.message)
