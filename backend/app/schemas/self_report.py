"""Pydantic schemas for participant self-reports (P0.7).

PAD affect is collected with a 9-point Self-Assessment Manikin (SAM) per
dimension: integer bipolar [-4, +4] (pleasure/arousal/dominance). There is NO
auto-neutral default -- the participant taps a manikin (or the gap between two),
so an unset value means "not answered", never 0. Submit requires all three
(SelfReportCreate); autosave allows any subset (SelfReportAutosave). Context
fields (loop_index, phase, timepoint, function_class) are required by the model;
range and enum inputs are guarded here (clean 422).

The pre-SAM pilots collected these three as continuous [-5, +5] sliders; those
rows are distinguished by their raw_json (no instrument key). New SAM rows carry
instrument="SAM-9" + scale_min/scale_max in raw_json (see services/self_report)."""

import json
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

Phase = Literal["tutorial", "instruction", "modeling", "rehearsal", "feedback"]
Timepoint = Literal["pre", "post"]
FunctionClass = Literal["baseline", "PR", "NR", "AR", "not_applicable"]
IsProblem = Literal["0", "1", "not_applicable"]
BeforeAfter = Literal["before", "after", "na"]
# Categorical "overall feeling": neutral + the six basic emotions + contempt
# (the 8-class set the perception affect model also uses).
EmotionCategory = Literal[
    "neutral", "happy", "sad", "surprise", "fear", "anger", "disgust", "contempt"
]
# What a self-report row is ABOUT. Every existing/simple report is "overall"
# (one row per slot). The 6 post-trial/pre-feedback rehearsal slots split into
# two rows: the participant's affect toward the CHILD's behavior, and toward
# how THEY handled the interaction.
Referent = Literal["overall", "child_behavior", "self_handling"]
# The child-behavior question answered on the rehearsal (post-kid-response) slot.
# Single-select: exactly one of these (stored as a one-element list in
# child_behaviors, so the column/export shape is unchanged).
ChildBehavior = Literal["screaming", "demanding", "repetition", "none"]

# 9-point SAM per dimension, integer bipolar [-4, +4]. No default: an unset value
# is "not answered", never coerced to 0 (a centered slider used to mean neutral;
# a SAM has no such centre-default -- the participant must actively choose).
_SAM_REQUIRED = Field(ge=-4, le=4)
_SAM_OPTIONAL = Field(default=None, ge=-4, le=4)


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
    # PAD via 9-point SAM; integer [-4, +4]; all three required at submit.
    pleasure: int = _SAM_REQUIRED
    arousal: int = _SAM_REQUIRED
    dominance: int = _SAM_REQUIRED
    # categorical "overall feeling"; required at submit
    emotion_category: EmotionCategory


class SelfReportAutosave(SelfReportContext):
    """Partial-progress autosave: any subset may be present (the participant may
    have chosen one or two manikins so far). Missing = not yet answered; never
    coerced to a value. Serves BOTH the simple form (pleasure/arousal/dominance/
    emotion_category) and the expanded rehearsal page, which additionally carries
    the child-behavior checklist and a second PAD+emotion set (handling_*)."""

    # simple form + set A of the rehearsal page (feeling about the child's behavior)
    pleasure: Optional[int] = _SAM_OPTIONAL
    arousal: Optional[int] = _SAM_OPTIONAL
    dominance: Optional[int] = _SAM_OPTIONAL
    emotion_category: Optional[EmotionCategory] = None
    # rehearsal page only: the behavior checklist + set B (feeling about how the
    # participant handled the interaction). All optional for partial autosave.
    child_behaviors: Optional[list[ChildBehavior]] = None
    handling_pleasure: Optional[int] = _SAM_OPTIONAL
    handling_arousal: Optional[int] = _SAM_OPTIONAL
    handling_dominance: Optional[int] = _SAM_OPTIONAL
    handling_emotion_category: Optional[EmotionCategory] = None


class PadEmotion(BaseModel):
    """One complete PAD+emotion answer set (all four required)."""

    pleasure: int = _SAM_REQUIRED
    arousal: int = _SAM_REQUIRED
    dominance: int = _SAM_REQUIRED
    emotion_category: EmotionCategory


class RehearsalSelfReportCreate(SelfReportContext):
    """Submit payload for the expanded post-trial/pre-feedback rehearsal form.
    One page -> two persisted rows (child_behavior + self_handling). The behavior
    checklist attaches to the child_behavior row."""

    # single-select: exactly one behavior, carried as a one-element list
    child_behaviors: list[ChildBehavior] = Field(min_length=1, max_length=1)
    child_behavior_affect: PadEmotion  # how the child's behavior made them feel
    self_handling_affect: PadEmotion   # how they felt about how they handled it


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
    # a value is None when that SAM dimension has not been picked yet (partial draft)
    sliders: dict[str, Optional[float]] = Field(default_factory=dict)
    # the categorical pick, or None if not chosen yet
    emotion_category: Optional[str] = None
    # rehearsal page only: restored checklist + the second PAD+emotion set. None/
    # empty on a simple-form draft (the tablet ignores them there).
    child_behaviors: Optional[list[str]] = None
    handling_sliders: dict[str, Optional[float]] = Field(default_factory=dict)
    handling_emotion_category: Optional[str] = None


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
    # overall | child_behavior | self_handling (see Referent)
    referent: Optional[str] = None
    # the child-behavior checklist, stored as a JSON list on the child_behavior
    # row (parsed back to a list here); None on every other row
    child_behaviors: Optional[list[str]] = None
    pleasure: Optional[float] = None
    arousal: Optional[float] = None
    dominance: Optional[float] = None
    emotion_category: Optional[str] = None
    confidence: Optional[float] = None
    frustration: Optional[float] = None
    engagement: Optional[float] = None
    perceived_challenge: Optional[float] = None
    perceived_support: Optional[float] = None
    cognitive_load: Optional[float] = None
    timestamp_utc: str
    session_time_ms: int
    created_at: str

    @field_validator("child_behaviors", mode="before")
    @classmethod
    def _parse_child_behaviors(cls, v):
        """The column stores a JSON list string; expose it as a list."""
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (ValueError, TypeError):
                return None
        return v
