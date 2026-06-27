"""Pydantic schemas for the push-to-tablet assignment (P0.6)."""

from typing import Any, Literal, Optional

from pydantic import BaseModel

FormType = Literal["idle", "questionnaire", "self_report"]


class PushPayload(BaseModel):
    form_type: FormType
    session_id: Optional[str] = None
    questionnaire_key: Optional[str] = None
    questionnaire_version: Optional[str] = None
    # Pre-fill context for a self-report (loop_index, phase, timepoint,
    # function_class, before/after, etc.); echoed back by the tablet on submit.
    self_report_context: Optional[dict[str, Any]] = None
    message: Optional[str] = None


class AssignmentRead(BaseModel):
    revision: int
    form_type: str
    session_id: Optional[str] = None
    questionnaire_key: Optional[str] = None
    questionnaire_version: Optional[str] = None
    self_report_context: Optional[dict[str, Any]] = None
    message: Optional[str] = None
    pushed_at: Optional[str] = None
