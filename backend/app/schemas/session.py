"""Pydantic schemas for the sessions API."""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

ScenarioType = Literal["bst_dtt", "customer_service"]
SessionState = Literal["created", "running", "paused", "stopped", "completed"]


class SessionCreate(BaseModel):
    session_id: str = Field(..., examples=["P001_S1"])
    participant_id: str = Field(..., examples=["P001"])
    scenario_type: ScenarioType = "bst_dtt"
    support_condition: Optional[Literal[0, 1]] = None
    pb_order_group: Optional[Literal[1, 2, 3]] = None
    # 0 is never a valid protocol id; show null in the OpenAPI example.
    protocol_id: Optional[int] = Field(default=None, examples=[None])
    notes: Optional[str] = None


class SessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_id: str
    participant_id: str
    scenario_type: ScenarioType
    support_condition: Optional[int] = None
    pb_order_group: Optional[int] = None
    protocol_id: Optional[int] = None
    state: SessionState
    start_timestamp_utc: Optional[str] = None
    stop_timestamp_utc: Optional[str] = None
    completed_at: Optional[str] = None
    platform_version: Optional[str] = None
    created_at: str
    notes: Optional[str] = None
