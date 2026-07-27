"""Live-session signal models: robot events, participant self-reports,
perception events, and media recordings.

Affect/rating sliders use a continuous bipolar scale in [-5, +5] (true-zero
center), stored raw/unrounded. ``participant_self_reports`` holds source='sr'
rows only in practice; perception (ml) affect lives in ``perception_events``.
The sr/ml union is the Day-6 analysis assembly script's job.
"""

from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timeutil import now_utc_iso
from app.models.base import Base

# The active self-report answer columns and their DB-level CHECK ranges. SAM
# dimensions are integer [-4, +4]; the four task-feeling ratings are integer
# [1, 5]. Reused to generate CHECK constraints on both the record and draft
# tables (NULL passes a range CHECK, so partial autosave drafts are allowed).
_SAM_COLS = ("pleasure", "arousal", "dominance")
_EMO_COLS = ("enjoyment", "confusion", "frustration", "boredom")


class RobotEvent(Base):
    __tablename__ = "robot_events"

    robot_event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.session_id"), nullable=False
    )
    participant_id: Mapped[str | None] = mapped_column(
        ForeignKey("participants.participant_id"), nullable=True
    )
    role: Mapped[str | None] = mapped_column(String, nullable=True)
    utterance_or_action: Mapped[str | None] = mapped_column(String, nullable=True)
    condition: Mapped[str | None] = mapped_column(String, nullable=True)
    script_version: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str] = mapped_column(String, nullable=False, default="manual")
    loop_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload_json: Mapped[str | None] = mapped_column(String, nullable=True)
    timestamp_utc: Mapped[str] = mapped_column(String, nullable=False)
    session_time_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=now_utc_iso)

    __table_args__ = (
        CheckConstraint("role IN ('trainer','child')", name="ck_robot_events_role"),
        CheckConstraint("source IN ('manual','auto')", name="ck_robot_events_source"),
        CheckConstraint("loop_index BETWEEN 1 AND 6", name="ck_robot_events_loop_index"),
    )


class ParticipantSelfReport(Base):
    __tablename__ = "participant_self_reports"

    self_report_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.session_id"), nullable=False
    )
    participant_id: Mapped[str] = mapped_column(
        ForeignKey("participants.participant_id"), nullable=False
    )
    trial_id: Mapped[int | None] = mapped_column(
        ForeignKey("dtt_trials.trial_id"), nullable=True
    )

    # Analysis join keys (canonical in dtt_loops; carried here for convenience).
    # loop_index is nullable: instructional-stage baseline self-reports
    # (phase tutorial|instruction|modeling) precede any rehearsal loop and have
    # no loop_index; loop-bound reports (rehearsal/feedback) still carry 1..6.
    loop_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sequence_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # tutorial | instruction | modeling (baseline) | rehearsal | feedback
    phase: Mapped[str] = mapped_column(String, nullable=False)
    timepoint: Mapped[str] = mapped_column(String, nullable=False)  # pre | post
    function_class: Mapped[str] = mapped_column(String, nullable=False)
    is_problem: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str] = mapped_column(String, nullable=False, default="sr")
    before_after_robot_action: Mapped[str | None] = mapped_column(String, nullable=True)
    # What this row is ABOUT: 'overall' (every simple report) | 'child_behavior' |
    # 'self_handling'. The 6 post-trial/pre-feedback rehearsal slots write two rows
    # (child_behavior + self_handling); all other slots write one 'overall' row.
    # Nullable: rows written before this field never had it (they are 'overall').
    referent: Mapped[str | None] = mapped_column(String, nullable=True)
    # Child-behavior checklist for the rehearsal slot, JSON list (e.g.
    # ["vocalization","disruption"] or ["none"]). Set only on the child_behavior
    # row; NULL everywhere else.
    child_behaviors: Mapped[str | None] = mapped_column(String, nullable=True)

    # PAD via 9-point SAM, integer [-4, +4] (nullable: unset = not answered).
    pleasure: Mapped[int | None] = mapped_column(Integer, nullable=True)  # == valence
    arousal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dominance: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Four independent task-related feeling intensities, integer 1..5 (1=Not at
    # all .. 5=Very strong), asked alongside the SAM.
    enjoyment: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confusion: Mapped[int | None] = mapped_column(Integer, nullable=True)
    frustration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    boredom: Mapped[int | None] = mapped_column(Integer, nullable=True)

    raw_json: Mapped[str | None] = mapped_column(String, nullable=True)
    timestamp_utc: Mapped[str] = mapped_column(String, nullable=False)
    session_time_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=now_utc_iso)

    __table_args__ = (
        CheckConstraint(
            "loop_index IS NULL OR loop_index BETWEEN 1 AND 6",
            name="ck_self_reports_loop_index",
        ),
        CheckConstraint(
            "sequence_position BETWEEN 1 AND 6", name="ck_self_reports_sequence_position"
        ),
        CheckConstraint(
            "phase IN ('tutorial','instruction','modeling','rehearsal','feedback')",
            name="ck_self_reports_phase",
        ),
        CheckConstraint("timepoint IN ('pre','post')", name="ck_self_reports_timepoint"),
        CheckConstraint(
            "function_class IN ('baseline','PR','NR','AR','not_applicable')",
            name="ck_self_reports_function_class",
        ),
        CheckConstraint(
            "is_problem IN ('0','1','not_applicable')", name="ck_self_reports_is_problem"
        ),
        CheckConstraint("source IN ('sr','ml')", name="ck_self_reports_source"),
        CheckConstraint(
            "before_after_robot_action IN ('before','after','na')",
            name="ck_self_reports_before_after",
        ),
        # Range CHECKs for the seven active answers (NULL passes, so drafts elsewhere
        # and partial rows are unaffected; a submitted row is fully validated too).
        *(
            CheckConstraint(f"{c} BETWEEN -4 AND 4", name=f"ck_self_reports_{c}_range")
            for c in _SAM_COLS
        ),
        *(
            CheckConstraint(f"{c} BETWEEN 1 AND 5", name=f"ck_self_reports_{c}_range")
            for c in _EMO_COLS
        ),
    )


class SelfReportDraft(Base):
    """Autosave draft for an in-progress self-report (P0.7 autosave).

    Working state, NOT the research record: a draft is overwritten on every
    autosave and deleted the moment the participant submits. The raw, immutable
    record lives in ``participant_self_reports``; drafts never touch that table
    and never write a timeline event (only the submit does).

    One draft per (session_id, context_key). ``context_key`` is a canonical
    encoding of the FULL self-report context (loop_index, phase, timepoint,
    function_class, is_problem, sequence_position, before_after_robot_action,
    trial_id), so the many self-reports a participant gives in one session each
    keep their own draft and never share or overwrite one another.
    """

    __tablename__ = "self_report_drafts"

    draft_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.session_id"), nullable=False
    )
    participant_id: Mapped[str | None] = mapped_column(
        ForeignKey("participants.participant_id"), nullable=True
    )
    # Canonical encoding of the full context; uniqueness is enforced on this.
    context_key: Mapped[str] = mapped_column(String, nullable=False)

    # Context fields, retained for inspection (the key is derived from these).
    loop_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sequence_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    phase: Mapped[str | None] = mapped_column(String, nullable=True)
    timepoint: Mapped[str | None] = mapped_column(String, nullable=True)
    function_class: Mapped[str | None] = mapped_column(String, nullable=True)
    is_problem: Mapped[str | None] = mapped_column(String, nullable=True)
    before_after_robot_action: Mapped[str | None] = mapped_column(String, nullable=True)
    trial_id: Mapped[int | None] = mapped_column(
        ForeignKey("dtt_trials.trial_id"), nullable=True
    )

    # SET A (simple form, or the child-behavior block of the rehearsal page):
    # the 3 SAM dimensions (integer [-4, +4]) + the 4 task-feeling ratings (1..5).
    pleasure: Mapped[int | None] = mapped_column(Integer, nullable=True)
    arousal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dominance: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enjoyment: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confusion: Mapped[int | None] = mapped_column(Integer, nullable=True)
    frustration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    boredom: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Rehearsal page only: the child-behavior checklist (JSON list) and SET B
    # (how the participant handled the interaction): its SAM + feelings.
    # NULL on a simple-form draft.
    child_behaviors: Mapped[str | None] = mapped_column(String, nullable=True)
    handling_pleasure: Mapped[int | None] = mapped_column(Integer, nullable=True)
    handling_arousal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    handling_dominance: Mapped[int | None] = mapped_column(Integer, nullable=True)
    handling_enjoyment: Mapped[int | None] = mapped_column(Integer, nullable=True)
    handling_confusion: Mapped[int | None] = mapped_column(Integer, nullable=True)
    handling_frustration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    handling_boredom: Mapped[int | None] = mapped_column(Integer, nullable=True)

    raw_json: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[str] = mapped_column(String, nullable=False, default=now_utc_iso)
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=now_utc_iso)

    __table_args__ = (
        UniqueConstraint(
            "session_id", "context_key", name="uq_self_report_drafts_session_context"
        ),
        # Same range CHECKs as the record table, for set A and set B. NULL passes,
        # so partial autosave is unaffected.
        *(
            CheckConstraint(f"{c} BETWEEN -4 AND 4", name=f"ck_draft_{c}_range")
            for c in _SAM_COLS + tuple(f"handling_{c}" for c in _SAM_COLS)
        ),
        *(
            CheckConstraint(f"{c} BETWEEN 1 AND 5", name=f"ck_draft_{c}_range")
            for c in _EMO_COLS + tuple(f"handling_{c}" for c in _EMO_COLS)
        ),
    )


class PerceptionEvent(Base):
    """One row per successful poll; failed polls write a gap marker with
    connection_status='down' and a null payload (outages are data)."""

    __tablename__ = "perception_events"

    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.session_id"), nullable=False
    )
    participant_id: Mapped[str | None] = mapped_column(
        ForeignKey("participants.participant_id"), nullable=True
    )
    task: Mapped[str] = mapped_column(String, nullable=False)  # asr | emotion | gesture
    source: Mapped[str] = mapped_column(String, nullable=False, default="ml")
    backend_name: Mapped[str | None] = mapped_column(String, nullable=True)
    source_timestamp_utc: Mapped[str | None] = mapped_column(String, nullable=True)
    received_timestamp_utc: Mapped[str] = mapped_column(String, nullable=False)
    session_time_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    detected_label: Mapped[str | None] = mapped_column(String, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    valence: Mapped[float | None] = mapped_column(Float, nullable=True)  # == pleasure
    arousal: Mapped[float | None] = mapped_column(Float, nullable=True)
    transcript: Mapped[str | None] = mapped_column(String, nullable=True)
    face_detected: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    connection_status: Mapped[str] = mapped_column(String, nullable=False)
    raw_payload: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=now_utc_iso)

    __table_args__ = (
        CheckConstraint(
            "task IN ('asr','emotion','gesture')", name="ck_perception_task"
        ),
        CheckConstraint("source IN ('ml')", name="ck_perception_source"),
        CheckConstraint("face_detected IN (0,1)", name="ck_perception_face_detected"),
        CheckConstraint(
            "connection_status IN ('ok','degraded','down')",
            name="ck_perception_connection_status",
        ),
        # This table is the highest-volume in the system (~9 rows/sec during a
        # live session, millions of rows across a study). Every per-session read
        # -- the console's live health poll (/perception-events/summary), the
        # event list, and the export -- filters by session_id (often + task).
        # Without these indexes those are full-table scans that grow with every
        # loop, starving the connection pool and delaying the tablet form push
        # (measured: the summary poll went from ~8.2s to ~0.08s on a 2M-row
        # session). Two focused composites, each covering a distinct query shape:
        #   - (session_id, task, event_id): the summary's per-task count and its
        #     "latest by event_id" lookup (event_id must sit right after the
        #     equality columns so the ORDER BY is a seek, not a sort), plus the
        #     session-scoped list/export ordered by event_id.
        #   - (session_id, task, connection_status): the summary's per-task
        #     outage (down) count, served covering with no row fetches.
        Index(
            "ix_perception_events_session_task_event",
            "session_id",
            "task",
            "event_id",
        ),
        Index(
            "ix_perception_events_session_task_conn",
            "session_id",
            "task",
            "connection_status",
        ),
    )


class MediaRecording(Base):
    __tablename__ = "media_recordings"

    recording_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.session_id"), nullable=False
    )
    participant_id: Mapped[str | None] = mapped_column(
        ForeignKey("participants.participant_id"), nullable=True
    )
    recording_type: Mapped[str] = mapped_column(String, nullable=False, default="av")
    device_name: Mapped[str | None] = mapped_column(String, nullable=True)
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    file_name: Mapped[str | None] = mapped_column(String, nullable=True)
    start_timestamp_utc: Mapped[str | None] = mapped_column(String, nullable=True)
    stop_timestamp_utc: Mapped[str | None] = mapped_column(String, nullable=True)
    # session_time_ms at recording start enables trial->video offsets (P2.5).
    session_time_ms_at_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    # ffmpeg provenance.
    codec: Mapped[str | None] = mapped_column(String, nullable=True)
    container: Mapped[str | None] = mapped_column(String, nullable=True)
    resolution: Mapped[str | None] = mapped_column(String, nullable=True)
    fps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bitrate_kbps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pix_fmt: Mapped[str | None] = mapped_column(String, nullable=True)
    audio_device: Mapped[str | None] = mapped_column(String, nullable=True)
    ffmpeg_command: Mapped[str | None] = mapped_column(String, nullable=True)
    error_text: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=now_utc_iso)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','recording','completed','failed','interrupted')",
            name="ck_media_recordings_status",
        ),
    )
