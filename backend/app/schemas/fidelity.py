"""Pydantic schemas for human fidelity scoring (Operator Console v3).

Every rating field accepts correct|incorrect|not_applicable|unscored and
defaults to 'unscored' (the initial state), so a partially scored loop is a
valid autosave. ``error_sources`` is a multi-select validated against the
allowed set; ``status`` is optional on upsert (a plain autosave omits it and
never demotes a completed score). Enum/range inputs are guarded here so bad
input is a clean 422, never a DB error.
"""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

ScoreValue = Literal["correct", "incorrect", "not_applicable", "unscored"]
ErrorSource = Literal[
    "interaction_flow",
    "ordering",
    "timing",
    "latency",
    "wrong_item",
    "sd_delivery",
    "prompting",
    "reinforcement",
    "error_correction",
    "other",
]
Status = Literal["draft", "complete"]


class FidelityScoreUpsert(BaseModel):
    """Create-or-update payload (PUT). Full state: a plain autosave sends all
    ratings + current error sources/notes, omitting ``status`` so it stays a
    draft (or stays complete if the operator is editing a completed loop)."""

    delivered_target: ScoreValue = "unscored"
    sd_delivered_as_written: ScoreValue = "unscored"
    sd_timing: ScoreValue = "unscored"
    primary_rplus_delivery: ScoreValue = "unscored"
    primary_rplus_timing: ScoreValue = "unscored"
    ec_prompting_delivery: ScoreValue = "unscored"
    ec_prompting_timing: ScoreValue = "unscored"
    ec_hp_delivery: ScoreValue = "unscored"
    ec_hp_timing: ScoreValue = "unscored"
    ec_rplus_delivery: ScoreValue = "unscored"
    ec_rplus_timing: ScoreValue = "unscored"
    initial_sd_delivery: ScoreValue = "unscored"
    initial_sd_timing: ScoreValue = "unscored"
    final_rplus_delivery: ScoreValue = "unscored"
    final_rplus_timing: ScoreValue = "unscored"

    error_sources: list[ErrorSource] = Field(default_factory=list)
    notes: Optional[str] = None
    scored_by: Optional[str] = None
    status: Optional[Status] = None


class FidelityScoreRead(BaseModel):
    """One loop's scored row. ``error_sources`` is the parsed JSON array."""

    model_config = ConfigDict(from_attributes=True)

    fidelity_score_id: int
    session_id: str
    participant_id: str
    loop_index: int
    function_class: Optional[str] = None
    sd_id: Optional[str] = None

    delivered_target: ScoreValue
    sd_delivered_as_written: ScoreValue
    sd_timing: ScoreValue
    primary_rplus_delivery: ScoreValue
    primary_rplus_timing: ScoreValue
    ec_prompting_delivery: ScoreValue
    ec_prompting_timing: ScoreValue
    ec_hp_delivery: ScoreValue
    ec_hp_timing: ScoreValue
    ec_rplus_delivery: ScoreValue
    ec_rplus_timing: ScoreValue
    initial_sd_delivery: ScoreValue
    initial_sd_timing: ScoreValue
    final_rplus_delivery: ScoreValue
    final_rplus_timing: ScoreValue

    error_sources: list[str] = Field(default_factory=list)
    notes: Optional[str] = None
    status: Status
    scored_by: Optional[str] = None
    created_at: str
    updated_at: str
