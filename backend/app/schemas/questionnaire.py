"""Pydantic schemas for the questionnaire engine (P0.4 / P0.6).

The engine validates each answer against the questionnaire config in the service
layer (item-membership, scale ranges, options); these schemas only shape the
request/response envelopes. Answer values are heterogeneous (int for Likert,
string for choices, free text, list for multi-choice), so ``answers`` is an
open map and the service does the typed validation (clean 422)."""

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class QuestionnaireRead(BaseModel):
    """A registered questionnaire (registry row; no item text)."""

    model_config = ConfigDict(from_attributes=True)

    questionnaire_key: str
    version: str
    title: Optional[str] = None
    scale_type: Optional[str] = None
    item_count: Optional[int] = None
    timepoint: Optional[str] = None


class AnswersPayload(BaseModel):
    """A map of item_id -> answer value, for autosave and submit."""

    answers: dict[str, Any] = Field(default_factory=dict)


class ResponseSummary(BaseModel):
    questionnaire_key: str
    questionnaire_version: str
    is_partial: bool
    saved_items: Optional[int] = None
    item_count: Optional[int] = None


class ResponsesRead(BaseModel):
    questionnaire_key: str
    questionnaire_version: str
    finalized: bool
    answers: dict[str, Any]
