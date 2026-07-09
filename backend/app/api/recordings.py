"""Media recordings API (P0.8).

Recordings are produced by the recording service under the session lifecycle
(start on session start, graceful stop on session stop). This router exposes the
``media_recordings`` rows plus, for the console's recordings tab:
  * GET  .../{id}/file   -- stream the mp4 inline (Range-enabled) for rewatch
  * POST .../{id}/save   -- copy the file to an archival location

Playback and save are strictly non-destructive: the original file in
RECORDINGS_DIR is only ever read/copied, never moved or deleted.
"""

from fastapi import APIRouter, Depends, Path
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.signals import MediaRecording
from app.schemas.recording import (
    RecordingRead,
    SaveRecordingRequest,
    SaveRecordingResult,
)
from app.services.recording_save import (
    get_recording_or_404,
    recording_file_or_409,
    save_recording,
)
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


@router.get("/{recording_id}/file")
def stream_recording_file(
    session_id: str,
    recording_id: int = Path(ge=1),
    db: Session = Depends(get_db),
):
    """Stream the recording inline for the in-browser player. FileResponse sets
    Accept-Ranges and serves Range requests, so the <video> element can seek.
    Read-only; the file is never modified."""
    get_session_or_404(db, session_id)
    rec = get_recording_or_404(db, session_id, recording_id)
    path = recording_file_or_409(rec)
    return FileResponse(str(path), media_type="video/mp4")


@router.post("/{recording_id}/save", response_model=SaveRecordingResult)
def save_recording_endpoint(
    session_id: str,
    payload: SaveRecordingRequest,
    recording_id: int = Path(ge=1),
    db: Session = Depends(get_db),
):
    """Copy the recording to the default saved-recordings folder ('default') or
    an operator path ('as'). Never moves the original."""
    session = get_session_or_404(db, session_id)
    return save_recording(
        db,
        session,
        recording_id,
        mode=payload.mode,
        dest_path=payload.dest_path,
        overwrite=payload.overwrite,
    )
