"""Pydantic schemas for experimenter notes."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class NoteCreate(BaseModel):
    text: str = Field(..., min_length=1)
    loop_index: Optional[int] = Field(default=None, ge=1, le=6)
    trial_id: Optional[int] = None


class NoteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    note_id: int
    session_id: str
    participant_id: Optional[str] = None
    text: str
    loop_index: Optional[int] = None
    trial_id: Optional[int] = None
    timestamp_utc: str
    session_time_ms: int
    created_at: str
