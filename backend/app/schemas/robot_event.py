"""Pydantic schemas for robot events.

Manual entry for v1, but the model carries a ``source`` field (manual|auto) and
a flexible ``payload`` JSON object so machine ingestion can be added later with
no migration.
"""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class RobotEventCreate(BaseModel):
    role: Optional[Literal["trainer", "child"]] = None
    utterance_or_action: Optional[str] = None
    condition: Optional[str] = None
    script_version: Optional[str] = None
    source: Literal["manual", "auto"] = "manual"
    loop_index: Optional[int] = Field(default=None, ge=1, le=6)
    payload: Optional[dict] = None


class RobotEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    robot_event_id: int
    session_id: str
    participant_id: Optional[str] = None
    role: Optional[str] = None
    utterance_or_action: Optional[str] = None
    condition: Optional[str] = None
    script_version: Optional[str] = None
    source: str
    loop_index: Optional[int] = None
    payload_json: Optional[str] = None
    timestamp_utc: str
    session_time_ms: int
    created_at: str
