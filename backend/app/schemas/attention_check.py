"""Pydantic schemas for attention-check responses.

The log payload carries the participant's answer for one question; the platform
computes ``is_correct`` from the answer + the config (never trusted from the
caller). ``question_id`` is validated against configs/attention_checks.yaml in
the service (clean 422). The questions endpoint serves the admin console the
full question set (it is administrator-facing, so it may include the correct
answer; the participant tablet never calls it).
"""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

Phase = Literal["tutorial", "instruction", "modeling"]
Source = Literal["auto", "manual"]


class AttentionCheckLog(BaseModel):
    """Log (create-or-update) one attention-check answer."""

    question_id: str
    participant_answer: str
    # 'auto' (robot-reported) or 'manual' (administrator-logged)
    source: Source = "auto"
    operator: Optional[str] = None
    notes: Optional[str] = None
    # session_time_ms may be supplied by the robot; else the platform computes it
    session_time_ms: Optional[int] = None


class AttentionCheckRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    attention_check_id: int
    session_id: str
    participant_id: str
    phase: str
    question_id: str
    question_text: Optional[str] = None
    correct_answer: Optional[str] = None
    participant_answer: Optional[str] = None
    is_correct: bool
    source: str
    operator: Optional[str] = None
    notes: Optional[str] = None
    timestamp_utc: str
    session_time_ms: Optional[int] = None
    created_at: str
    updated_at: str


class AttentionCheckQuestion(BaseModel):
    """One question from the config (admin console rendering)."""

    question_id: str
    phase: str
    order: int
    text: str
    choices: list[str]
    correct_answer: str
