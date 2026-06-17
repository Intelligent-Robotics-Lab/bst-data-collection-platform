"""Experimenter notes API. A timestamped note can be added at any moment."""

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.system import ExperimenterNote
from app.schemas.note import NoteCreate, NoteRead
from app.services.session_events import add_note
from app.services.session_service import get_session_or_404

router = APIRouter(prefix="/sessions/{session_id}/notes", tags=["notes"])


@router.post("", response_model=NoteRead, status_code=status.HTTP_201_CREATED)
def create_note(session_id: str, payload: NoteCreate, db: Session = Depends(get_db)):
    session = get_session_or_404(db, session_id)
    return add_note(db, session, payload)


@router.get("", response_model=list[NoteRead])
def list_notes(session_id: str, db: Session = Depends(get_db)):
    get_session_or_404(db, session_id)
    return db.scalars(
        select(ExperimenterNote)
        .where(ExperimenterNote.session_id == session_id)
        .order_by(ExperimenterNote.note_id)
    ).all()
