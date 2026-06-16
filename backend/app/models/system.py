"""System and integrity models: the unified timeline, notes, (unused) health
events, export manifests, and annotations.

``session_timeline_events`` is the unified spine: every significant event also
writes a row here (UTC + session_time_ms), and a completed session reconstructs
from this table alone. ``annotations`` implements corrections/exclusions/scoring
as derived rows, never by overwriting a raw record (CLAUDE.md hard rule).
"""

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timeutil import now_utc_iso
from app.models.base import Base


class SessionTimelineEvent(Base):
    __tablename__ = "session_timeline_events"

    # AUTOINCREMENT gives a globally monotonic id; per-session ordering is
    # (session_id, event_id), with session_time_ms for time placement.
    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.session_id"), nullable=False
    )
    participant_id: Mapped[str | None] = mapped_column(
        ForeignKey("participants.participant_id"), nullable=True
    )
    timestamp_utc: Mapped[str] = mapped_column(String, nullable=False)
    session_time_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[str | None] = mapped_column(String, nullable=True)  # JSON
    ref_table: Mapped[str | None] = mapped_column(String, nullable=True)
    ref_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=now_utc_iso)


class ExperimenterNote(Base):
    __tablename__ = "experimenter_notes"

    note_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.session_id"), nullable=False
    )
    participant_id: Mapped[str | None] = mapped_column(
        ForeignKey("participants.participant_id"), nullable=True
    )
    text: Mapped[str] = mapped_column(String, nullable=False)
    loop_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trial_id: Mapped[int | None] = mapped_column(
        ForeignKey("dtt_trials.trial_id"), nullable=True
    )
    timestamp_utc: Mapped[str] = mapped_column(String, nullable=False)
    session_time_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=now_utc_iso)


class SystemHealthEvent(Base):
    """Defined but UNUSED in v1 (P1.4)."""

    __tablename__ = "system_health_events"

    health_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str | None] = mapped_column(
        ForeignKey("sessions.session_id"), nullable=True
    )
    type: Mapped[str] = mapped_column(String, nullable=False)
    severity: Mapped[str | None] = mapped_column(String, nullable=True)
    detail_json: Mapped[str | None] = mapped_column(String, nullable=True)
    timestamp_utc: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=now_utc_iso)

    __table_args__ = (
        CheckConstraint(
            "type IN ('disk','backend_error','recording_bitrate','perception_outage')",
            name="ck_system_health_type",
        ),
    )


class Export(Base):
    __tablename__ = "exports"

    export_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str | None] = mapped_column(
        ForeignKey("sessions.session_id"), nullable=True
    )
    scope: Mapped[str] = mapped_column(String, nullable=False)
    export_dir: Mapped[str] = mapped_column(String, nullable=False)
    files_json: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    platform_version: Mapped[str | None] = mapped_column(String, nullable=True)
    completed_at: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=now_utc_iso)

    __table_args__ = (
        CheckConstraint(
            "scope IN ('session','participant','study')", name="ck_exports_scope"
        ),
        CheckConstraint(
            "status IN ('pending','completed','failed')", name="ck_exports_status"
        ),
    )


class Annotation(Base):
    """Corrections, exclusions, and scoring as derived rows. Never overwrites a
    raw record; soft-links to any raw row via (target_table, target_id)."""

    __tablename__ = "annotations"

    annotation_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    target_table: Mapped[str] = mapped_column(String, nullable=False)
    target_id: Mapped[str] = mapped_column(String, nullable=False)
    session_id: Mapped[str | None] = mapped_column(
        ForeignKey("sessions.session_id"), nullable=True
    )
    participant_id: Mapped[str | None] = mapped_column(
        ForeignKey("participants.participant_id"), nullable=True
    )
    annotation_type: Mapped[str] = mapped_column(String, nullable=False)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    payload_json: Mapped[str | None] = mapped_column(String, nullable=True)
    author: Mapped[str | None] = mapped_column(String, nullable=True)
    timestamp_utc: Mapped[str] = mapped_column(String, nullable=False)
    session_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=now_utc_iso)

    __table_args__ = (
        CheckConstraint(
            "annotation_type IN ('exclusion','correction','note','scoring')",
            name="ck_annotations_type",
        ),
    )
