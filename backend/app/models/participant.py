"""Participant models.

Research-integrity rules (CLAUDE.md): participant IDs only in research tables;
no names in research data. ``participant_identity`` exists as P1.3 insurance and
is intentionally unwritten in v1.
"""

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timeutil import now_utc_iso
from app.models.base import Base


class Participant(Base):
    __tablename__ = "participants"

    participant_id: Mapped[str] = mapped_column(String, primary_key=True)  # e.g. P001
    consent_status: Mapped[str] = mapped_column(
        String, nullable=False, default="not_consented"
    )
    media_recording_consent: Mapped[str] = mapped_column(
        String, nullable=False, default="not_asked"
    )
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=now_utc_iso)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "consent_status IN ('consented','not_consented','withdrawn')",
            name="ck_participants_consent_status",
        ),
        CheckConstraint(
            "media_recording_consent IN ('granted','denied','withdrawn','not_asked')",
            name="ck_participants_media_consent",
        ),
    )


class ParticipantIdentity(Base):
    """Separate from research tables. UNUSED in v1 (no names written). P1.3."""

    __tablename__ = "participant_identity"

    identity_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    participant_id: Mapped[str] = mapped_column(
        ForeignKey("participants.participant_id"), nullable=False, unique=True
    )
    legal_name: Mapped[str | None] = mapped_column(String, nullable=True)
    contact: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=now_utc_iso)
