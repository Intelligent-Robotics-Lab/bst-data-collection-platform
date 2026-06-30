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
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timeutil import now_utc_iso
from app.models.base import Base

# Reusable bound for the nine bipolar self-report sliders.
_SLIDER_FIELDS = (
    "pleasure",
    "arousal",
    "dominance",
    "confidence",
    "frustration",
    "engagement",
    "perceived_challenge",
    "perceived_support",
    "cognitive_load",
)


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

    # PAD + ratings, continuous bipolar [-5, +5].
    pleasure: Mapped[float | None] = mapped_column(Float, nullable=True)  # == valence
    arousal: Mapped[float | None] = mapped_column(Float, nullable=True)
    dominance: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    frustration: Mapped[float | None] = mapped_column(Float, nullable=True)
    engagement: Mapped[float | None] = mapped_column(Float, nullable=True)
    perceived_challenge: Mapped[float | None] = mapped_column(Float, nullable=True)
    perceived_support: Mapped[float | None] = mapped_column(Float, nullable=True)
    cognitive_load: Mapped[float | None] = mapped_column(Float, nullable=True)

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
        *(
            CheckConstraint(f"{f} BETWEEN -5 AND 5", name=f"ck_self_reports_{f}_range")
            for f in _SLIDER_FIELDS
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

    # The nine bipolar sliders, continuous [-5, +5] (true-zero center).
    pleasure: Mapped[float | None] = mapped_column(Float, nullable=True)
    arousal: Mapped[float | None] = mapped_column(Float, nullable=True)
    dominance: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    frustration: Mapped[float | None] = mapped_column(Float, nullable=True)
    engagement: Mapped[float | None] = mapped_column(Float, nullable=True)
    perceived_challenge: Mapped[float | None] = mapped_column(Float, nullable=True)
    perceived_support: Mapped[float | None] = mapped_column(Float, nullable=True)
    cognitive_load: Mapped[float | None] = mapped_column(Float, nullable=True)

    raw_json: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[str] = mapped_column(String, nullable=False, default=now_utc_iso)
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=now_utc_iso)

    __table_args__ = (
        UniqueConstraint(
            "session_id", "context_key", name="uq_self_report_drafts_session_context"
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
