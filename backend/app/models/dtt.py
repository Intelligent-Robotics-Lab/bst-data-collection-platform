"""DTT models: protocols, phases, loops, trials, and (unused) performance events.

Naming: ``dtt_phases.phase_key`` is the DTT *protocol* phase (e.g. baseline,
acquisition) and is distinct from the loop structural ``phase`` (dtt | feedback)
that lives on self-reports.

``dtt_loops`` is the canonical per-session x loop record and the source of truth
for loop attributes (function_class, is_problem, sequence_position, and the
loop's mapping to support_condition / pb_order_group). Trials and self-reports
reference a loop by ``loop_index`` within the session.
"""

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timeutil import now_utc_iso
from app.models.base import Base


class DttProtocol(Base):
    """Registry of a protocol config file (provenance). Content lives in
    configs/dtt_protocols/*; this table records key/version/path/hash."""

    __tablename__ = "dtt_protocols"

    protocol_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    protocol_key: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    config_path: Mapped[str] = mapped_column(String, nullable=False)
    config_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=now_utc_iso)

    __table_args__ = (
        UniqueConstraint("protocol_key", "version", name="uq_dtt_protocols_key_version"),
    )


class DttPhase(Base):
    """A DTT protocol phase, synced from the protocol config."""

    __tablename__ = "dtt_phases"

    phase_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    protocol_id: Mapped[int] = mapped_column(
        ForeignKey("dtt_protocols.protocol_id"), nullable=False
    )
    phase_key: Mapped[str] = mapped_column(String, nullable=False)
    phase_label: Mapped[str | None] = mapped_column(String, nullable=True)
    order_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_skills_json: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=now_utc_iso)

    __table_args__ = (
        UniqueConstraint("protocol_id", "phase_key", name="uq_dtt_phases_protocol_phase"),
    )


class DttLoop(Base):
    """Canonical per-session x loop record. Source of truth for loop attributes."""

    __tablename__ = "dtt_loops"

    loop_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.session_id"), nullable=False
    )
    participant_id: Mapped[str] = mapped_column(
        ForeignKey("participants.participant_id"), nullable=False
    )
    loop_index: Mapped[int] = mapped_column(Integer, nullable=False)
    sequence_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    function_class: Mapped[str] = mapped_column(String, nullable=False)
    is_problem: Mapped[str | None] = mapped_column(String, nullable=True)
    # The loop's mapping to the session's between-subject factors (denormalized
    # onto the loop for the Day-6 analysis frame).
    support_condition: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pb_order_group: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=now_utc_iso)

    __table_args__ = (
        UniqueConstraint("session_id", "loop_index", name="uq_dtt_loops_session_loop"),
        CheckConstraint("loop_index BETWEEN 1 AND 6", name="ck_dtt_loops_loop_index"),
        CheckConstraint(
            "sequence_position BETWEEN 1 AND 6", name="ck_dtt_loops_sequence_position"
        ),
        CheckConstraint(
            "function_class IN ('baseline','PR','NR','AR','not_applicable')",
            name="ck_dtt_loops_function_class",
        ),
        CheckConstraint(
            "is_problem IN ('0','1','not_applicable')", name="ck_dtt_loops_is_problem"
        ),
        CheckConstraint("support_condition IN (0,1)", name="ck_dtt_loops_support_condition"),
        CheckConstraint("pb_order_group IN (1,2,3)", name="ck_dtt_loops_pb_order_group"),
    )


class DttTrial(Base):
    __tablename__ = "dtt_trials"

    trial_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.session_id"), nullable=False
    )
    participant_id: Mapped[str] = mapped_column(
        ForeignKey("participants.participant_id"), nullable=False
    )
    trial_number: Mapped[int] = mapped_column(Integer, nullable=False)  # auto, per session
    # References dtt_loops by (session_id, loop_index); nullable so trials can
    # exist outside the loop structure.
    loop_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    protocol_id: Mapped[int | None] = mapped_column(
        ForeignKey("dtt_protocols.protocol_id"), nullable=True
    )
    dtt_phase_id: Mapped[int | None] = mapped_column(
        ForeignKey("dtt_phases.phase_id"), nullable=True
    )
    phase_key: Mapped[str | None] = mapped_column(String, nullable=True)  # denormalized
    target_skill: Mapped[str | None] = mapped_column(String, nullable=True)
    instruction: Mapped[str | None] = mapped_column(String, nullable=True)  # SD
    participant_response: Mapped[str | None] = mapped_column(String, nullable=True)
    response_correctness: Mapped[str | None] = mapped_column(String, nullable=True)
    response_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prompt_level: Mapped[str | None] = mapped_column(String, nullable=True)
    reinforcement_delivered: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_correction_delivered: Mapped[int | None] = mapped_column(Integer, nullable=True)
    missed_steps_json: Mapped[str | None] = mapped_column(String, nullable=True)
    extra_steps_json: Mapped[str | None] = mapped_column(String, nullable=True)
    deviation_flag: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)
    timestamp_utc: Mapped[str] = mapped_column(String, nullable=False)
    session_time_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=now_utc_iso)

    __table_args__ = (
        CheckConstraint("loop_index BETWEEN 1 AND 6", name="ck_dtt_trials_loop_index"),
        CheckConstraint(
            "response_correctness IN ('correct','incorrect','no_response','partial')",
            name="ck_dtt_trials_correctness",
        ),
        CheckConstraint(
            "reinforcement_delivered IN (0,1)", name="ck_dtt_trials_reinforcement"
        ),
        CheckConstraint(
            "error_correction_delivered IN (0,1)", name="ck_dtt_trials_error_correction"
        ),
        CheckConstraint("deviation_flag IN (0,1)", name="ck_dtt_trials_deviation_flag"),
    )


class DttPerformanceEvent(Base):
    """Fine-grained step events. Defined but UNUSED in v1 (P1.2); v1 folds
    step detail into dtt_trials + the timeline."""

    __tablename__ = "dtt_performance_events"

    perf_event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trial_id: Mapped[int | None] = mapped_column(
        ForeignKey("dtt_trials.trial_id"), nullable=True
    )
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.session_id"), nullable=False
    )
    participant_id: Mapped[str | None] = mapped_column(
        ForeignKey("participants.participant_id"), nullable=True
    )
    step_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    step_label: Mapped[str | None] = mapped_column(String, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String, nullable=True)
    timestamp_utc: Mapped[str | None] = mapped_column(String, nullable=True)
    session_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_json: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=now_utc_iso)
