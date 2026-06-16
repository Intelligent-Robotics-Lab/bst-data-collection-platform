"""Questionnaire models.

No copyrighted item text is stored in the DB. ``questionnaires`` registers a
config file (key/version/path/hash); responses reference stable ``item_id``s.
``questionnaire_scores`` is defined but UNUSED in v1 (P2.3): scoring is post-hoc.
"""

from sqlalchemy import CheckConstraint, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timeutil import now_utc_iso
from app.models.base import Base


class Questionnaire(Base):
    """Registry of a questionnaire config file."""

    __tablename__ = "questionnaires"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    questionnaire_key: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    scale_type: Mapped[str | None] = mapped_column(String, nullable=True)
    item_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    timepoint: Mapped[str | None] = mapped_column(String, nullable=True)
    config_path: Mapped[str] = mapped_column(String, nullable=False)
    config_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    scoring_config_json: Mapped[str | None] = mapped_column(String, nullable=True)  # P2 slot
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=now_utc_iso)

    __table_args__ = (
        UniqueConstraint("questionnaire_key", "version", name="uq_questionnaires_key_version"),
        CheckConstraint("timepoint IN ('pre','post','na')", name="ck_questionnaires_timepoint"),
    )


class QuestionnaireResponse(Base):
    __tablename__ = "questionnaire_responses"

    response_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.session_id"), nullable=False
    )
    participant_id: Mapped[str] = mapped_column(
        ForeignKey("participants.participant_id"), nullable=False
    )
    questionnaire_key: Mapped[str] = mapped_column(String, nullable=False)
    questionnaire_version: Mapped[str] = mapped_column(String, nullable=False)
    item_id: Mapped[str] = mapped_column(String, nullable=False)  # stable; no item text
    item_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_raw: Mapped[str | None] = mapped_column(String, nullable=True)
    response_numeric: Mapped[float | None] = mapped_column(Float, nullable=True)
    timepoint: Mapped[str | None] = mapped_column(String, nullable=True)
    is_partial: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # autosave
    recorded_at: Mapped[str] = mapped_column(String, nullable=False, default=now_utc_iso)
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=now_utc_iso)

    __table_args__ = (
        CheckConstraint(
            "timepoint IN ('pre','post','na')", name="ck_quest_responses_timepoint"
        ),
        CheckConstraint("is_partial IN (0,1)", name="ck_quest_responses_is_partial"),
    )


class QuestionnaireScore(Base):
    """Defined but UNUSED in v1 (P2.3). Scoring is post-hoc in analysis."""

    __tablename__ = "questionnaire_scores"

    score_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str | None] = mapped_column(
        ForeignKey("sessions.session_id"), nullable=True
    )
    participant_id: Mapped[str | None] = mapped_column(
        ForeignKey("participants.participant_id"), nullable=True
    )
    questionnaire_key: Mapped[str] = mapped_column(String, nullable=False)
    questionnaire_version: Mapped[str] = mapped_column(String, nullable=False)
    subscale: Mapped[str | None] = mapped_column(String, nullable=True)
    score_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    scoring_version: Mapped[str | None] = mapped_column(String, nullable=True)
    computed_at: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=now_utc_iso)
