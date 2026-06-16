"""Participants CRUD. Minimal Day-1 surface to verify the data model via /docs
(P0.1). Full intake flow is Phase 2 (Day 2)."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.participant import Participant
from app.schemas.participant import ParticipantCreate, ParticipantRead

router = APIRouter(prefix="/participants", tags=["participants"])


@router.post("", response_model=ParticipantRead, status_code=status.HTTP_201_CREATED)
def create_participant(payload: ParticipantCreate, db: Session = Depends(get_db)):
    existing = db.get(Participant, payload.participant_id)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"participant_id '{payload.participant_id}' already exists",
        )
    participant = Participant(**payload.model_dump())
    db.add(participant)
    db.commit()
    db.refresh(participant)
    return participant


@router.get("", response_model=list[ParticipantRead])
def list_participants(db: Session = Depends(get_db)):
    return db.scalars(select(Participant).order_by(Participant.participant_id)).all()


@router.get("/{participant_id}", response_model=ParticipantRead)
def get_participant(participant_id: str, db: Session = Depends(get_db)):
    participant = db.get(Participant, participant_id)
    if participant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"participant_id '{participant_id}' not found",
        )
    return participant
