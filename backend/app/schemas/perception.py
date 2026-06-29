"""Pydantic schema for perception events (P0.9). Read-only: events are produced
by the perception polling adapter, not via the API."""

from typing import Optional

from pydantic import BaseModel, ConfigDict


class PerceptionEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_id: int
    session_id: str
    participant_id: Optional[str] = None
    task: str
    source: str
    backend_name: Optional[str] = None
    source_timestamp_utc: Optional[str] = None
    received_timestamp_utc: str
    session_time_ms: int
    detected_label: Optional[str] = None
    confidence: Optional[float] = None
    valence: Optional[float] = None
    arousal: Optional[float] = None
    transcript: Optional[str] = None
    face_detected: Optional[int] = None
    latency_ms: Optional[float] = None
    connection_status: str
    raw_payload: Optional[str] = None
    created_at: str
