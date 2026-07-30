"""Pydantic schemas for DTT trial logging.

Enum/range inputs are guarded at this layer (clean 422); config-membership
(sd_id, phase_key, target_skill, prompt_level, steps) is validated in the
service against the session's protocol config.

A trial may carry the within-trial INTERACTION FLOW as an ordered list of steps
(the robot's TrialState machine). The trial row and its steps are written in one
transaction and never updated afterwards.
"""

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

ResponseCorrectness = Literal["correct", "incorrect", "no_response", "partial"]

# Canonical step labels. These mirror the robot's TrialState enum, snake_cased:
#   sd, kid behavior 1, reinforcement, prompting, kid behavior 2, hp_sd,
#   kid behavior HP, retry sd, kid behavior retry, feedback
TrialStepLabel = Literal[
    "sd",
    "kid_behavior_1",
    "reinforcement",
    "prompting",
    "kid_behavior_2",
    "hp_sd",
    "kid_behavior_hp",
    "retry_sd",
    "kid_behavior_retry",
    "feedback",
]
# Who acts at this step (the robot's CurrentState).
TrialActor = Literal["user", "kid", "trainer"]


class TrialStep(BaseModel):
    """One step of the within-trial interaction flow (append-only)."""

    step_index: int = Field(..., ge=1)
    step_label: TrialStepLabel
    actor: Optional[TrialActor] = None
    # e.g. "recognized" / "not_recognized" for a user step, "emitted" for a kid
    # step, "delivered" for reinforcement. Free-form; recorded verbatim.
    outcome: Optional[str] = None
    # The robot's own clock for this step; the server also stamps session_time_ms.
    timestamp_utc: Optional[str] = None
    detail: Optional[dict[str, Any]] = None  # stored verbatim in raw_json


class TrialCreate(BaseModel):
    loop_index: int = Field(..., ge=1, le=6)
    # sd_id / phase_key / target_skill are derivable from the loop + the
    # participant's order group, so a robot need not hardcode platform
    # vocabulary. Supply them to override; omit them to have them resolved.
    sd_id: Optional[str] = None
    phase_key: Optional[str] = None
    target_skill: Optional[str] = None  # skill_id from the protocol config
    # The named SD the caller believes it ran (e.g. "Receptive Instruction").
    # When supplied it is checked against the Latin-square mapping for this
    # loop + order group, so a robot/platform mismatch fails loudly at ingest.
    trial_name: Optional[str] = None
    response_correctness: ResponseCorrectness
    # Optional: this protocol has no prompt-level hierarchy (error correction is
    # a fixed prompting -> hp_sd -> retry_sd sequence). When supplied it must be
    # one of the protocol config's prompt_levels.
    prompt_level: Optional[str] = None
    reinforcement_delivered: bool
    error_correction_delivered: bool
    missed_steps: Optional[list[str]] = None
    extra_steps: Optional[list[str]] = None
    deviation_flag: bool = False
    notes: Optional[str] = None
    # optional, PRD-listed
    participant_response: Optional[str] = None
    response_latency_ms: Optional[int] = None
    # The within-trial interaction flow, in order.
    steps: Optional[list[TrialStep]] = None


class PerformanceEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    perf_event_id: int
    trial_id: Optional[int] = None
    session_id: str
    participant_id: Optional[str] = None
    step_index: Optional[int] = None
    step_label: Optional[str] = None
    outcome: Optional[str] = None
    timestamp_utc: Optional[str] = None
    session_time_ms: Optional[int] = None
    raw_json: Optional[str] = None
    created_at: str


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
