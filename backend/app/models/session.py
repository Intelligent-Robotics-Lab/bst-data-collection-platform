"""Session and study-condition models.

``support_condition`` and ``pb_order_group`` are between-subject factors stored
here on the session (the export/analysis unit). ``study_conditions`` is defined
but UNUSED in v1 (P2); v1 carries condition inline on the session.
"""

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timeutil import now_utc_iso
from app.models.base import Base


class StudySession(Base):
    __tablename__ = "sessions"

    session_id: Mapped[str] = mapped_column(String, primary_key=True)  # e.g. P001_S1
    participant_id: Mapped[str] = mapped_column(
        ForeignKey("participants.participant_id"), nullable=False
    )
    scenario_type: Mapped[str] = mapped_column(String, nullable=False)
    support_condition: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pb_order_group: Mapped[int | None] = mapped_column(Integer, nullable=True)
    protocol_id: Mapped[int | None] = mapped_column(
        ForeignKey("dtt_protocols.protocol_id"), nullable=True
    )
    state: Mapped[str] = mapped_column(String, nullable=False, default="created")
    # t0 anchor for session_time_ms; set on the first transition to 'running'.
    start_timestamp_utc: Mapped[str | None] = mapped_column(String, nullable=True)
    stop_timestamp_utc: Mapped[str | None] = mapped_column(String, nullable=True)
    completed_at: Mapped[str | None] = mapped_column(String, nullable=True)
    platform_version: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=now_utc_iso)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "scenario_type IN ('bst_dtt','customer_service')",
            name="ck_sessions_scenario_type",
        ),
        CheckConstraint(
            "support_condition IN (0,1)", name="ck_sessions_support_condition"
        ),
        CheckConstraint(
            "pb_order_group IN (1,2,3)", name="ck_sessions_pb_order_group"
        ),
        CheckConstraint(
            "state IN ('created','running','paused','stopped','completed')",
            name="ck_sessions_state",
        ),
    )


class StudyCondition(Base):
    """Condition catalog. Defined but UNUSED in v1 (P2)."""

    __tablename__ = "study_conditions"

    condition_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    config_json: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=now_utc_iso)
