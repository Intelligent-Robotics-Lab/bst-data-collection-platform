"""Archive a finished recording to a chosen location.

Zero video-data loss: the original file in RECORDINGS_DIR is NEVER moved,
altered, or deleted -- we only ever copy it. 'Save' targets the configured
SAVED_RECORDINGS_DIR; 'Save As' targets an operator-supplied path on the server
or a mounted drive. The copy is size-verified and refuses to clobber the
original or (without overwrite) an existing destination file.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import HTTPException, status as http_status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.session import StudySession
from app.models.signals import MediaRecording
from app.services.timeline import record_timeline_event


def get_recording_or_404(db: Session, session_id: str, recording_id: int) -> MediaRecording:
    rec = db.get(MediaRecording, recording_id)
    if rec is None or rec.session_id != session_id:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"no recording {recording_id} for session '{session_id}'",
        )
    return rec


def recording_file_or_409(rec: MediaRecording) -> Path:
    """The on-disk file for a recording, or a clean 409 if there is nothing
    playable/savable (e.g. a failed capture that produced no file)."""
    if not rec.file_path:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=f"recording {rec.recording_id} has no file path",
        )
    path = Path(rec.file_path)
    if not path.exists() or path.stat().st_size == 0:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=(
                f"no playable file on disk for recording {rec.recording_id} "
                f"(status '{rec.status}')"
            ),
        )
    return path


def save_recording(
    db: Session,
    session: StudySession,
    recording_id: int,
    *,
    mode: str,
    dest_path: str | None,
    overwrite: bool,
) -> dict:
    rec = get_recording_or_404(db, session.session_id, recording_id)
    src = recording_file_or_409(rec)

    if mode == "default":
        dest_dir = settings.saved_recordings_dir
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / (rec.file_name or src.name)
    else:  # "as"
        if not dest_path or not dest_path.strip():
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="dest_path is required for 'save as'",
            )
        dest = Path(dest_path.strip()).expanduser()
        # A path that names (or already is) a directory receives the file under
        # its original name; otherwise dest is treated as the full target path.
        if dest.is_dir() or dest_path.strip().endswith("/"):
            dest = dest / (rec.file_name or src.name)
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"cannot create destination folder '{dest.parent}': {exc}",
            )

    src_resolved = src.resolve()
    dest_resolved = dest.resolve()
    if dest_resolved == src_resolved:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="destination is the original recording file; choose another location",
        )
    overwritten = dest.exists()
    if overwritten and not overwrite:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=f"a file already exists at {dest_resolved}; pass overwrite=true to replace it",
        )

    # Copy (never move); copy2 preserves mtime. The original is untouched.
    try:
        shutil.copy2(src, dest)
    except OSError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"copy to '{dest_resolved}' failed: {exc}",
        )
    # Integrity: the copy must be byte-for-byte the same size as the source.
    if dest.stat().st_size != src.stat().st_size:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="copy size mismatch; the destination copy may be incomplete",
        )

    record_timeline_event(
        db,
        session=session,
        source="recording",
        type="recording_saved",
        payload={
            "recording_id": rec.recording_id,
            "saved_to": str(dest_resolved),
            "mode": mode,
            "bytes": dest.stat().st_size,
            "overwritten": overwritten,
        },
        ref_table="media_recordings",
        ref_id=str(rec.recording_id),
    )
    db.commit()

    return {
        "recording_id": rec.recording_id,
        "saved_to": str(dest_resolved),
        "bytes": dest.stat().st_size,
        "source": str(src_resolved),
        "overwritten": overwritten,
    }
