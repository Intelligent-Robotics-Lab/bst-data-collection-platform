"""Media recordings API (P0.8).

Read-only. Recordings are produced by the recording service under the session
lifecycle (start on session start, graceful stop on session stop); this endpoint
exposes the resulting ``media_recordings`` rows for the dashboard and for
verifying that a session captured A/V.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.signals import MediaRecording
from app.schemas.recording import RecordingRead
from app.services.session_service import get_session_or_404

router = APIRouter(prefix="/sessions/{session_id}/recordings", tags=["recordings"])


@router.get("", response_model=list[RecordingRead])
def list_recordings(session_id: str, db: Session = Depends(get_db)):
    get_session_or_404(db, session_id)
    return db.scalars(
        select(MediaRecording)
        .where(MediaRecording.session_id == session_id)
        .order_by(MediaRecording.recording_id)
    ).all()
