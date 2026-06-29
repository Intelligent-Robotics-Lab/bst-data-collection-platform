"""Pydantic schemas for media recordings (P0.8). Read-only: recordings are
created by the recording service under the session lifecycle, not via the API."""

from typing import Optional

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
