"""Pydantic schemas for the robot launch handoff (Operator Console v2)."""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class LaunchConfig(BaseModel):
    """The canonical, platform-owned config BST consumes instead of terminal
    input. Derived from the session; never re-typed by the operator."""

    session_id: str
    participant_id: str
    scenario_type: str
    pb_order_group: Optional[int] = None
    support_condition: Optional[int] = None
    support_label: Optional[str] = None
    platform_base: str


class LaunchStatusRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_id: str
    status: str  # none | prepared | waiting | start_requested | started | error
    prepared_at: Optional[str] = None
    config_fetched_at: Optional[str] = None
    start_requested_at: Optional[str] = None
    started_at: Optional[str] = None
    error_at: Optional[str] = None
    error_text: Optional[str] = None
    requested_by: Optional[str] = None
    updated_at: Optional[str] = None


class AckIn(BaseModel):
    """BST acknowledges progress: config received, or interaction started."""

    phase: Literal["config_received", "started"]


class ErrorIn(BaseModel):
    message: str
