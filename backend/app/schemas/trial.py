"""Pydantic schemas for DTT trial logging.

Enum/range inputs are guarded at this layer (clean 422); config-membership
(sd_id, phase_key, target_skill, prompt_level, steps) is validated in the
service against the session's protocol config.
"""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

ResponseCorrectness = Literal["correct", "incorrect", "no_response", "partial"]


class TrialCreate(BaseModel):
    loop_index: int = Field(..., ge=1, le=6)
    sd_id: str
    phase_key: str
    target_skill: str  # skill_id from the protocol config
    response_correctness: ResponseCorrectness
    prompt_level: str
    reinforcement_delivered: bool
    error_correction_delivered: bool
    missed_steps: Optional[list[str]] = None
    extra_steps: Optional[list[str]] = None
    deviation_flag: bool = False
    notes: Optional[str] = None
    # optional, PRD-listed
    participant_response: Optional[str] = None
    response_latency_ms: Optional[int] = None


class TrialRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    trial_id: int
    session_id: str
    participant_id: Optional[str] = None
    trial_number: int
    loop_index: Optional[int] = None
    protocol_id: Optional[int] = None
    dtt_phase_id: Optional[int] = None
    phase_key: Optional[str] = None
    sd_id: Optional[str] = None
    target_skill: Optional[str] = None
    instruction: Optional[str] = None
    participant_response: Optional[str] = None
    response_correctness: Optional[str] = None
    response_latency_ms: Optional[int] = None
    prompt_level: Optional[str] = None
    reinforcement_delivered: Optional[int] = None
    error_correction_delivered: Optional[int] = None
    missed_steps_json: Optional[str] = None
    extra_steps_json: Optional[str] = None
    deviation_flag: Optional[int] = None
    notes: Optional[str] = None
    timestamp_utc: str
    session_time_ms: int
    created_at: str
