"""Human fidelity scoring (Operator Console v3, FIDELITY_SCORING_V3_SPEC.md).

One row per (session_id, loop_index): the operator's ABA/BST fidelity ratings
for a DTT loop/SD, scored live during the session and included in exports. This
is HUMAN scoring only (v3); no automated/LLM score is stored or shown here, so
the human rating stays a valid, blind ground truth for later validation.

Each rating field is one of: correct | incorrect | not_applicable | unscored
('unscored' is the initial state). ``function_class`` and ``sd_id`` are
denormalized from dtt_loops for analysis convenience (dtt_loops stays the
source of truth). This is a scoring/annotation table (CLAUDE.md: scoring =
annotations/derived rows), so a draft row is editable and a completed score may
be revised if the operator corrects it; ``updated_at`` tracks revisions.
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

# The 15 ABA fidelity rating fields, in spec order. Reused by the schema,
# service, and export so the field set is defined in exactly one place.
FIDELITY_SCORE_FIELDS = (
    "delivered_target",
    "sd_delivered_as_written",
    "sd_timing",
    "primary_rplus_delivery",
    "primary_rplus_timing",
    "ec_prompting_delivery",
    "ec_prompting_timing",
    "ec_hp_delivery",
    "ec_hp_timing",
    "ec_rplus_delivery",
    "ec_rplus_timing",
    "initial_sd_delivery",
    "initial_sd_timing",
    "final_rplus_delivery",
    "final_rplus_timing",
)

# Allowed value for every rating field. 'unscored' is the initial state.
SCORE_VALUES = ("correct", "incorrect", "not_applicable", "unscored")

# Allowed values for the multi-select error-source field (stored as a JSON array
# in error_sources_json; validated at the schema boundary, not the DB).
ERROR_SOURCES = (
    "interaction_flow",
    "ordering",
    "timing",
    "latency",
    "wrong_item",
    "sd_delivery",
    "prompting",
    "reinforcement",
    "error_correction",
    "other",
)


class FidelityScore(Base):
    __tablename__ = "fidelity_scores"

    fidelity_score_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.session_id"), nullable=False
    )
    participant_id: Mapped[str] = mapped_column(
        ForeignKey("participants.participant_id"), nullable=False
    )
    loop_index: Mapped[int] = mapped_column(Integer, nullable=False)

    # Denormalized from dtt_loops (the source of truth) for analysis convenience.
    function_class: Mapped[str | None] = mapped_column(String, nullable=True)
    sd_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # The 15 ABA fidelity ratings. Each: correct|incorrect|not_applicable|unscored.
    delivered_target: Mapped[str] = mapped_column(String, nullable=False, default="unscored")
    sd_delivered_as_written: Mapped[str] = mapped_column(String, nullable=False, default="unscored")
    sd_timing: Mapped[str] = mapped_column(String, nullable=False, default="unscored")
    primary_rplus_delivery: Mapped[str] = mapped_column(String, nullable=False, default="unscored")
    primary_rplus_timing: Mapped[str] = mapped_column(String, nullable=False, default="unscored")
    ec_prompting_delivery: Mapped[str] = mapped_column(String, nullable=False, default="unscored")
    ec_prompting_timing: Mapped[str] = mapped_column(String, nullable=False, default="unscored")
    ec_hp_delivery: Mapped[str] = mapped_column(String, nullable=False, default="unscored")
    ec_hp_timing: Mapped[str] = mapped_column(String, nullable=False, default="unscored")
    ec_rplus_delivery: Mapped[str] = mapped_column(String, nullable=False, default="unscored")
    ec_rplus_timing: Mapped[str] = mapped_column(String, nullable=False, default="unscored")
    initial_sd_delivery: Mapped[str] = mapped_column(String, nullable=False, default="unscored")
    initial_sd_timing: Mapped[str] = mapped_column(String, nullable=False, default="unscored")
    final_rplus_delivery: Mapped[str] = mapped_column(String, nullable=False, default="unscored")
    final_rplus_timing: Mapped[str] = mapped_column(String, nullable=False, default="unscored")

    # Multi-select error source(s), stored as a JSON array of ERROR_SOURCES.
    error_sources_json: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)

    status: Mapped[str] = mapped_column(String, nullable=False, default="draft")
    scored_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=now_utc_iso)
    updated_at: Mapped[str] = mapped_column(String, nullable=False, default=now_utc_iso)

    __table_args__ = (
        # At most one current human fidelity score row per (session, loop). The
        # unique index also serves the per-session list read (small table).
        UniqueConstraint(
            "session_id", "loop_index", name="uq_fidelity_scores_session_loop"
        ),
        CheckConstraint("loop_index BETWEEN 1 AND 6", name="ck_fidelity_scores_loop_index"),
        CheckConstraint(
            "status IN ('draft','complete')", name="ck_fidelity_scores_status"
        ),
        *[
            CheckConstraint(
                f"{field} IN ('correct','incorrect','not_applicable','unscored')",
                name=f"ck_fidelity_{field}",
            )
            for field in FIDELITY_SCORE_FIELDS
        ],
    )
