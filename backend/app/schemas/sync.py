"""Pydantic schemas for the BST<->platform sync gate API."""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Stage = Literal["tutorial", "instruction", "modeling"]
LoopCheckpoint = Literal["post_kid_response", "post_feedback"]


class SessionRegisterResult(BaseModel):
    session_id: str
    participant_id: str
    scenario_type: str
    state: str
    pb_order_group: Optional[int] = None
    support_condition: Optional[int] = None
    support_label: Optional[str] = None


class StageCompleteIn(BaseModel):
    stage: Stage


class KidResponseIn(BaseModel):
    """Opened after the child-behavior arc completes (kid has exhibited its
    behavior/problem behavior), before the trainer's feedback."""

    loop_index: int = Field(..., ge=1, le=6)
    trial_name: Optional[str] = None  # bst trial-name, for provenance/logging


class FeedbackDeliveredIn(BaseModel):
    loop_index: int = Field(..., ge=1, le=6)
    trial_name: Optional[str] = None
    evaluation_summary: Optional[str] = None


class OverrideIn(BaseModel):
    scope: Literal["stage", "loop"]
    checkpoint: Literal["baseline", "post_kid_response", "post_feedback"]
    stage: Optional[Stage] = None
    loop_index: Optional[int] = Field(default=None, ge=1, le=6)
    operator: Optional[str] = None
    reason: Optional[str] = None


class GateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    gate_id: int
    session_id: str
    gate_key: str
    scope: str
    stage_key: Optional[str] = None
    loop_index: Optional[int] = None
    checkpoint: str
    status: str
    closed_by: Optional[str] = None
    override_operator: Optional[str] = None
    override_reason: Optional[str] = None
    opened_at: str
    closed_at: Optional[str] = None


class GoAheadResult(BaseModel):
    proceed: bool
    gate_found: bool
    gate: Optional[GateRead] = None


class SessionCompleteResult(BaseModel):
    session_id: str
    total_gates: int
    open_gates: list[str]
    closed_gates: list[str]
    overridden_gates: list[str]
