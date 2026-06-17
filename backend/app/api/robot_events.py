"""Robot events API (manual entry for v1)."""

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.signals import RobotEvent
from app.schemas.robot_event import RobotEventCreate, RobotEventRead
from app.services.session_events import add_robot_event
from app.services.session_service import get_session_or_404

router = APIRouter(prefix="/sessions/{session_id}/robot-events", tags=["robot-events"])


@router.post("", response_model=RobotEventRead, status_code=status.HTTP_201_CREATED)
def create_robot_event(session_id: str, payload: RobotEventCreate, db: Session = Depends(get_db)):
    session = get_session_or_404(db, session_id)
    return add_robot_event(db, session, payload)


@router.get("", response_model=list[RobotEventRead])
def list_robot_events(session_id: str, db: Session = Depends(get_db)):
    get_session_or_404(db, session_id)
    return db.scalars(
        select(RobotEvent)
        .where(RobotEvent.session_id == session_id)
        .order_by(RobotEvent.robot_event_id)
    ).all()
