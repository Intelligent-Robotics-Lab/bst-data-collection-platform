"""BST<->platform synchronization gate model.

A sync gate is the barrier the BST robot run waits on so a self-report can be
collected before BST advances. There are 15 gates per session:

  * 3 instructional baseline gates: scope='stage', stage_key in
    (tutorial, instruction, modeling), checkpoint='baseline'.
  * 12 loop gates: scope='loop', loop_index in 1..6, checkpoint in
    (post_kid_response, post_feedback) -> two self-reports per DTT loop. The
    post_kid_response report measures the participant's reaction to the CHILD'S
    behavior (the PR/NR/AR manipulation), collected after the kid-behavior arc
    and before the trainer's feedback.

State machine: a gate OPENS on stage_complete / kid_response_complete /
feedback_delivered and CLOSES on either the matching self-report being submitted
(closed_by='self_report')
or an operator override (closed_by='override'). ``go_ahead`` reports
proceed=false only while an open gate has not yet been satisfied.

Keyed by (session_id, gate_key) where gate_key canonically encodes
scope/ref/checkpoint, so each of the 15 checkpoints is a single idempotent row.
"""

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timeutil import now_utc_iso
from app.models.base import Base


class SyncGate(Base):
    __tablename__ = "sync_gates"

    gate_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.session_id"), nullable=False
    )
    # Canonical key, e.g. "stage:tutorial:baseline" or "loop:2:post_kid_response".
    gate_key: Mapped[str] = mapped_column(String, nullable=False)

    scope: Mapped[str] = mapped_column(String, nullable=False)  # stage | loop
    stage_key: Mapped[str | None] = mapped_column(String, nullable=True)  # tutorial|instruction|modeling
    loop_index: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1..6
    checkpoint: Mapped[str] = mapped_column(String, nullable=False)  # baseline|post_kid_response|post_feedback

    status: Mapped[str] = mapped_column(String, nullable=False, default="open")  # open | closed
    closed_by: Mapped[str | None] = mapped_column(String, nullable=True)  # self_report | override
    override_operator: Mapped[str | None] = mapped_column(String, nullable=True)
    override_reason: Mapped[str | None] = mapped_column(String, nullable=True)

    opened_at: Mapped[str] = mapped_column(String, nullable=False, default=now_utc_iso)
    closed_at: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=now_utc_iso)

    __table_args__ = (
        UniqueConstraint("session_id", "gate_key", name="uq_sync_gates_session_gate"),
        CheckConstraint("scope IN ('stage','loop')", name="ck_sync_gates_scope"),
        CheckConstraint(
            "checkpoint IN ('baseline','post_kid_response','post_feedback')",
            name="ck_sync_gates_checkpoint",
        ),
        CheckConstraint("status IN ('open','closed')", name="ck_sync_gates_status"),
        CheckConstraint(
            "closed_by IS NULL OR closed_by IN ('self_report','override')",
            name="ck_sync_gates_closed_by",
        ),
        CheckConstraint(
            "loop_index IS NULL OR loop_index BETWEEN 1 AND 6",
            name="ck_sync_gates_loop_index",
        ),
    )
