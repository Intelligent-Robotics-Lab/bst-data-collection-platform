"""Robot launch-handoff model (Operator Console v2).

One row per session tracks the state of handing the canonical session config to
the BST robot side and triggering start from the console, so the operator no
longer types session_id / pb_order_group / support_condition into the robot
terminal. The platform session stays the single source of truth: the launch
config is derived from the session, never re-entered.

State machine:
  prepared        -> operator marked the launch config ready
  waiting         -> BST fetched the config and is waiting for the start signal
  start_requested -> operator pressed Start in the console
  started         -> BST acknowledged the interaction started
  error           -> BST reported a launch failure

This model is additive: it introduces a new table only, so create_all adds it to
an existing DB without altering any other table.
"""

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timeutil import now_utc_iso
from app.models.base import Base


class SessionLaunch(Base):
    __tablename__ = "session_launches"

    launch_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.session_id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String, nullable=False, default="prepared")

    prepared_at: Mapped[str | None] = mapped_column(String, nullable=True)
    config_fetched_at: Mapped[str | None] = mapped_column(String, nullable=True)
    start_requested_at: Mapped[str | None] = mapped_column(String, nullable=True)
    started_at: Mapped[str | None] = mapped_column(String, nullable=True)
    error_at: Mapped[str | None] = mapped_column(String, nullable=True)
    error_text: Mapped[str | None] = mapped_column(String, nullable=True)
    # who requested start from the console (free-text; console sends "console")
    requested_by: Mapped[str | None] = mapped_column(String, nullable=True)

    updated_at: Mapped[str] = mapped_column(String, nullable=False, default=now_utc_iso)
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=now_utc_iso)

    __table_args__ = (
        UniqueConstraint("session_id", name="uq_session_launches_session"),
        CheckConstraint(
            "status IN ('prepared','waiting','start_requested','started','error')",
            name="ck_session_launches_status",
        ),
    )
