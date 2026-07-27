"""Participant self-report persistence (P0.7).

Writes one ``participant_self_reports`` row (source='sr') plus a
session_timeline_events row. PAD (pleasure/arousal/dominance) is a 9-point SAM,
integer [-4, +4]. Each finalized row is tagged in ``raw_json`` with
instrument="SAM-9" + scale_min/scale_max so it is distinguishable from the
pre-SAM pilot rows (continuous [-5, +5] sliders, whose raw_json has no instrument
key). Each report carries the analysis-join context (loop_index, phase,
timepoint, function_class, optional trial_id/sequence_position/is_problem) and
the before/after-robot-action flag.

The trial_id FK is guarded so a dangling reference returns a clean 422 (the
protocol_id lesson), never a DB 500.
"""

from __future__ import annotations

import json

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.timeutil import now_utc
from app.models.dtt import DttTrial
from app.models.session import StudySession
from app.models.signals import ParticipantSelfReport, SelfReportDraft
from app.services.timeline import compute_session_time_ms, record_timeline_event

# One answer set = the 3 SAM dimensions + the 4 task-feeling ratings (1..5). The
# other retained slider columns stay NULL (honestly "not collected", never 0).
SLIDER_FIELDS = ("pleasure", "arousal", "dominance")
EMOTION_FIELDS = ("enjoyment", "confusion", "frustration", "boredom")
# Set B of the expanded rehearsal page (how the participant handled the
# interaction), autosaved on the draft alongside set A above.
HANDLING_FIELDS = ("handling_pleasure", "handling_arousal", "handling_dominance")
HANDLING_EMOTION_FIELDS = (
    "handling_enjoyment",
    "handling_confusion",
    "handling_frustration",
    "handling_boredom",
)

# Provenance stamped into each finalized row's raw_json, so SAM-9 data is never
# confused with the pre-SAM [-5, +5] slider pilots (whose raw_json lacks these).
INSTRUMENT = "SAM-9"
SCALE_MIN, SCALE_MAX = -4, 4

# The context fields that, together with session_id, uniquely identify a draft.
CONTEXT_FIELDS = (
    "loop_index",
    "phase",
    "timepoint",
    "function_class",
    "is_problem",
    "sequence_position",
    "before_after_robot_action",
    "trial_id",
)


def context_key(ctx) -> str:
    """Canonical, stable encoding of a self-report context. Computed the same way
    for autosave, restore, and submit so a submit deletes exactly the draft its
    context produced (and two different contexts never collide)."""
    return json.dumps(
        {f: getattr(ctx, f) for f in CONTEXT_FIELDS},
        sort_keys=True,
        separators=(",", ":"),
    )


def _guard_trial(db: Session, session: StudySession, trial_id: int | None) -> None:
    """A dangling trial_id returns a clean 422, never a DB integrity 500."""
    if trial_id is None:
        return
    trial = db.get(DttTrial, trial_id)
    if trial is None or trial.session_id != session.session_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"unknown trial_id {trial_id} for session '{session.session_id}'",
        )


def _find_draft(db: Session, session_id: str, key: str) -> SelfReportDraft | None:
    return db.scalar(
        select(SelfReportDraft).where(
            SelfReportDraft.session_id == session_id,
            SelfReportDraft.context_key == key,
        )
    )


def _persist_report(
    db: Session,
    session: StudySession,
    ctx,
    now,
    *,
    referent: str,
    sam: dict,
    emotions: dict,
    child_behaviors: list[str] | None = None,
) -> ParticipantSelfReport:
    """Insert one participant_self_reports row (raw record) + its timeline event.
    ``sam`` is {pleasure, arousal, dominance}; ``emotions`` is the four task-feeling
    ratings {enjoyment, confusion, frustration, boredom}. Shared by the simple form
    (referent='overall') and the expanded rehearsal form (two rows). Does NOT
    commit -- the caller owns the transaction so a multi-row submit is atomic."""
    behaviors_json = json.dumps(child_behaviors) if child_behaviors is not None else None

    report = ParticipantSelfReport(
        session_id=session.session_id,
        participant_id=session.participant_id,
        trial_id=ctx.trial_id,
        loop_index=ctx.loop_index,
        sequence_position=ctx.sequence_position,
        phase=ctx.phase,
        timepoint=ctx.timepoint,
        function_class=ctx.function_class,
        is_problem=ctx.is_problem,
        source="sr",
        before_after_robot_action=ctx.before_after_robot_action,
        referent=referent,
        child_behaviors=behaviors_json,
        raw_json=json.dumps(
            {
                **sam,
                **emotions,
                "referent": referent,
                "child_behaviors": child_behaviors,
                "instrument": INSTRUMENT,
                "scale_min": SCALE_MIN,
                "scale_max": SCALE_MAX,
            }
        ),
        timestamp_utc=now.isoformat(),
        session_time_ms=compute_session_time_ms(session, now),
        **sam,
        **emotions,
    )
    db.add(report)
    db.flush()

    record_timeline_event(
        db,
        session=session,
        source="self_report",
        type="self_report_submitted",
        payload={
            "self_report_id": report.self_report_id,
            "trial_id": report.trial_id,
            "loop_index": report.loop_index,
            "sequence_position": report.sequence_position,
            "phase": report.phase,
            "timepoint": report.timepoint,
            "function_class": report.function_class,
            "is_problem": report.is_problem,
            "before_after_robot_action": report.before_after_robot_action,
            "referent": report.referent,
            "child_behaviors": child_behaviors,
            **sam,
            **emotions,
        },
        ref_table="participant_self_reports",
        ref_id=str(report.self_report_id),
        now=now,
    )
    return report


def add_self_report(db: Session, session: StudySession, payload) -> ParticipantSelfReport:
    """Simple single-form submit (baseline + post-feedback slots). One 'overall'
    row per context."""
    _guard_trial(db, session, payload.trial_id)

    now = now_utc()
    report = _persist_report(
        db,
        session,
        payload,
        now,
        referent="overall",
        sam={f: getattr(payload, f) for f in SLIDER_FIELDS},
        emotions={f: getattr(payload, f) for f in EMOTION_FIELDS},
    )

    # The raw record now owns this context; drop its working draft (same
    # transaction, so the draft never outlives the finalized row).
    draft = _find_draft(db, session.session_id, context_key(payload))
    if draft is not None:
        db.delete(draft)

    db.commit()
    db.refresh(report)
    return report


def add_rehearsal_self_report(
    db: Session, session: StudySession, payload
) -> list[ParticipantSelfReport]:
    """Expanded post-trial/pre-feedback rehearsal submit. Writes TWO rows in one
    transaction: 'child_behavior' (carries the behavior checklist + how the
    child's behaviors made the participant feel) and 'self_handling' (how they
    felt about how they handled the interaction). Atomic, so a mid-submit failure
    leaves NO partial rows and the sync gate (which matches on the self_handling
    row) stays open for a clean retry."""
    if payload.phase != "rehearsal":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"rehearsal self-report requires phase 'rehearsal'; got {payload.phase!r}",
        )
    _guard_trial(db, session, payload.trial_id)

    now = now_utc()
    child = payload.child_behavior_affect
    handling = payload.self_handling_affect
    reports = [
        _persist_report(
            db, session, payload, now,
            referent="child_behavior",
            sam={f: getattr(child, f) for f in SLIDER_FIELDS},
            emotions={f: getattr(child, f) for f in EMOTION_FIELDS},
            child_behaviors=payload.child_behaviors,
        ),
        _persist_report(
            db, session, payload, now,
            referent="self_handling",
            sam={f: getattr(handling, f) for f in SLIDER_FIELDS},
            emotions={f: getattr(handling, f) for f in EMOTION_FIELDS},
        ),
    ]

    draft = _find_draft(db, session.session_id, context_key(payload))
    if draft is not None:
        db.delete(draft)

    db.commit()
    for r in reports:
        db.refresh(r)
    return reports


def save_draft(db: Session, session: StudySession, payload) -> dict:
    """Autosave the in-progress sliders for one context (is_partial). Upserts the
    single (session_id, context_key) draft row; never writes a timeline event and
    never touches participant_self_reports (drafts are working state)."""
    _guard_trial(db, session, payload.trial_id)

    key = context_key(payload)
    # Set A (simple form) + set B (rehearsal handling_*). getattr with a default
    # tolerates the simple-form payload, which lacks the handling_* fields.
    answers = {
        **{f: getattr(payload, f, None) for f in SLIDER_FIELDS},
        **{f: getattr(payload, f, None) for f in EMOTION_FIELDS},
        **{f: getattr(payload, f, None) for f in HANDLING_FIELDS},
        **{f: getattr(payload, f, None) for f in HANDLING_EMOTION_FIELDS},
    }
    behaviors = getattr(payload, "child_behaviors", None)
    behaviors_json = json.dumps(behaviors) if behaviors is not None else None
    now_iso = now_utc().isoformat()

    draft = _find_draft(db, session.session_id, key)
    if draft is not None:
        for f, v in answers.items():
            setattr(draft, f, v)
        draft.child_behaviors = behaviors_json
        draft.raw_json = json.dumps(answers)
        draft.updated_at = now_iso
    else:
        db.add(
            SelfReportDraft(
                session_id=session.session_id,
                participant_id=session.participant_id,
                context_key=key,
                **{f: getattr(payload, f) for f in CONTEXT_FIELDS},
                child_behaviors=behaviors_json,
                raw_json=json.dumps(answers),
                updated_at=now_iso,
                **answers,
            )
        )
    db.commit()
    return {"context_key": key, "saved": True, "is_partial": True}


def get_draft(db: Session, session: StudySession, ctx) -> dict:
    """Restore the saved slider positions for one context, so a tablet refresh
    mid-form does not lose the participant's in-progress answers."""
    key = context_key(ctx)
    draft = _find_draft(db, session.session_id, key)
    if draft is None:
        return {"found": False, "context_key": key, "sliders": {}}
    try:
        behaviors = json.loads(draft.child_behaviors) if draft.child_behaviors else None
    except (ValueError, TypeError):
        behaviors = None
    return {
        "found": True,
        "context_key": key,
        "sliders": {f: getattr(draft, f) for f in SLIDER_FIELDS},
        "emotions": {f: getattr(draft, f) for f in EMOTION_FIELDS},
        # rehearsal-page extras (None/empty on a simple-form draft)
        "child_behaviors": behaviors,
        "handling_sliders": {
            f.replace("handling_", ""): getattr(draft, f) for f in HANDLING_FIELDS
        },
        "handling_emotions": {
            f.replace("handling_", ""): getattr(draft, f) for f in HANDLING_EMOTION_FIELDS
        },
    }
