"""Attention-check (comprehension) responses.

One row per (session_id, question_id): whether the participant answered a given
instructional-stage attention-check question correctly. The questions come from
the robot codebase (see configs/attention_checks.yaml); the response is logged
either automatically (the robot reports the participant's answer, source='auto')
or by the research administrator in the console (source='manual'). ``is_correct``
is computed by the platform from the answer + the config, not trusted from the
caller. The row is a scoring/annotation record (CLAUDE.md: scoring = derived
rows), so a mislogged answer can be corrected; ``updated_at`` tracks revisions,
and the question text / correct answer are denormalized for a self-describing
export.
"""

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timeutil import now_utc_iso
from app.models.base import Base


class AttentionCheckResponse(Base):
    __tablename__ = "attention_check_responses"

    attention_check_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.session_id"), nullable=False
    )
    participant_id: Mapped[str] = mapped_column(
        ForeignKey("participants.participant_id"), nullable=False
    )
    # instructional stage the question belongs to (no attention checks in tutorial)
    phase: Mapped[str] = mapped_column(String, nullable=False)
    # stable id from configs/attention_checks.yaml (e.g. 'instruction_1')
    question_id: Mapped[str] = mapped_column(String, nullable=False)
    # denormalized from the config for a self-describing export
    question_text: Mapped[str | None] = mapped_column(String, nullable=True)
    correct_answer: Mapped[str | None] = mapped_column(String, nullable=True)

    # what the participant answered (option number or spoken/typed text)
    participant_answer: Mapped[str | None] = mapped_column(String, nullable=True)
    # platform-computed correctness: 1 correct, 0 incorrect
    is_correct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 'auto' (robot-reported) | 'manual' (administrator-logged)
    source: Mapped[str] = mapped_column(String, nullable=False, default="auto")
    operator: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_json: Mapped[str | None] = mapped_column(String, nullable=True)

    timestamp_utc: Mapped[str] = mapped_column(String, nullable=False)
    session_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=now_utc_iso)
    updated_at: Mapped[str] = mapped_column(String, nullable=False, default=now_utc_iso)

    __table_args__ = (
        # One current logged answer per (session, question); the console/robot
        # upserts it, and it also serves the per-session list read.
        UniqueConstraint(
            "session_id", "question_id", name="uq_attention_checks_session_question"
        ),
        CheckConstraint(
            "phase IN ('tutorial','instruction','modeling')",
            name="ck_attention_checks_phase",
        ),
        CheckConstraint("is_correct IN (0,1)", name="ck_attention_checks_is_correct"),
        CheckConstraint("source IN ('auto','manual')", name="ck_attention_checks_source"),
    )
