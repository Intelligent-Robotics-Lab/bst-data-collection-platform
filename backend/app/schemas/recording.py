"""Pydantic schemas for media recordings (P0.8). Read-only: recordings are
created by the recording service under the session lifecycle, not via the API."""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class RecordingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    recording_id: int
    session_id: str
    participant_id: Optional[str] = None
    recording_type: str
    device_name: Optional[str] = None
    audio_device: Optional[str] = None
    file_path: str
    file_name: Optional[str] = None
    start_timestamp_utc: Optional[str] = None
    stop_timestamp_utc: Optional[str] = None
    session_time_ms_at_start: Optional[int] = None
    duration_ms: Optional[int] = None
    status: str
    codec: Optional[str] = None
    container: Optional[str] = None
    resolution: Optional[str] = None
    fps: Optional[int] = None
    bitrate_kbps: Optional[int] = None
    pix_fmt: Optional[str] = None
    ffmpeg_command: Optional[str] = None
    error_text: Optional[str] = None
    created_at: str


class SaveRecordingRequest(BaseModel):
    """Copy a finished recording to an archival location. The original is never
    moved. mode='default' -> the configured SAVED_RECORDINGS_DIR; mode='as' ->
    the operator-supplied dest_path (a folder or a full file path on the server
    / a mounted drive). overwrite guards against clobbering an existing copy."""

    mode: Literal["default", "as"] = "default"
    dest_path: Optional[str] = None
    overwrite: bool = False


class SaveRecordingResult(BaseModel):
    recording_id: int
    saved_to: str
    bytes: int
    source: str
    overwritten: bool = False
