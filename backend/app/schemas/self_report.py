"""Pydantic schemas for participant self-reports (P0.7).

The nine PAD/rating sliders are continuous bipolar [-5, +5] (true-zero center);
each defaults to 0.0 because the tablet form starts every slider centered and a
centered slider is a real neutral response, not a missing value. Context fields
(loop_index, phase, timepoint, function_class) are required by the model; range
and enum inputs are guarded here (clean 422)."""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Phase = Literal["tutorial", "instruction", "modeling", "rehearsal", "feedback"]
Timepoint = Literal["pre", "post"]
FunctionClass = Literal["baseline", "PR", "NR", "AR", "not_applicable"]
IsProblem = Literal["0", "1", "not_applicable"]
BeforeAfter = Literal["before", "after", "na"]

_SLIDER = Field(default=0.0, ge=-5, le=5)


class SelfReportContext(BaseModel):
    """The analysis-join context that identifies one self-report slot. A draft is
    unique per (session_id + this full context), so two different contexts in the
    same session never share or overwrite each other's autosaved draft."""

    # loop_index is optional: instructional-stage baseline reports (phase
    # tutorial|instruction|modeling) have no loop; rehearsal/feedback reports
    # carry 1..6.
    loop_index: Optional[int] = Field(default=None, ge=1, le=6)
    phase: Phase
    timepoint: Timepoint
    function_class: FunctionClass
    is_problem: Optional[IsProblem] = None
    sequence_position: Optional[int] = Field(default=None, ge=1, le=6)
    before_after_robot_action: Optional[BeforeAfter] = "na"
    trial_id: Optional[int] = None


class SelfReportCreate(SelfReportContext):
    # nine bipolar sliders, [-5, +5]
    pleasure: float = _SLIDER
    arousal: float = _SLIDER
    dominance: float = _SLIDER
    confidence: float = _SLIDER
    frustration: float = _SLIDER
    engagement: float = _SLIDER
    perceived_challenge: float = _SLIDER
    perceived_support: float = _SLIDER
    cognitive_load: float = _SLIDER


class SelfReportDraftSummary(BaseModel):
    """Autosave acknowledgement. No research data, no timeline event."""

    context_key: str
    saved: bool = True
    is_partial: bool = True


class SelfReportDraftRead(BaseModel):
    """Restore payload for the tablet: the saved slider positions for one context,
    or found=False when no draft exists yet."""

    found: bool
    context_key: str
    sliders: dict[str, float] = Field(default_factory=dict)


class SelfReportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    self_report_id: int
    session_id: str
    participant_id: str
    trial_id: Optional[int] = None
    loop_index: Optional[int] = None
    sequence_position: Optional[int] = None
    phase: str
    timepoint: str
    function_class: str
    is_problem: Optional[str] = None
    source: str
    before_after_robot_action: Optional[str] = None
    pleasure: Optional[float] = None
    arousal: Optional[float] = None
    dominance: Optional[float] = None
    confidence: Optional[float] = None
    frustration: Optional[float] = None
    engagement: Optional[float] = None
    perceived_challenge: Optional[float] = None
    perceived_support: Optional[float] = None
    cognitive_load: Optional[float] = None
    timestamp_utc: str
    session_time_ms: int
    created_at: str
