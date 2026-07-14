"""Participant self-report persistence (P0.7).

Writes one ``participant_self_reports`` row (source='sr') plus a
session_timeline_events row. The nine PAD/rating sliders are continuous bipolar
[-5, +5] (true-zero center), stored raw/unrounded. Each report carries the
analysis-join context (loop_index, phase, timepoint, function_class, optional
trial_id/sequence_position/is_problem) and the before/after-robot-action flag.

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

# Only the PAD affect dimensions are collected. The other six slider columns
# remain in the schema (nullable) for provenance/compatibility, but are not
# collected here, so they stay NULL (honestly "not collected", never a fake 0).
SLIDER_FIELDS = (
    "pleasure",
    "arousal",
    "dominance",
)

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


def add_self_report(db: Session, session: StudySession, payload) -> ParticipantSelfReport:
    _guard_trial(db, session, payload.trial_id)

    sliders = {f: getattr(payload, f) for f in SLIDER_FIELDS}

    now = now_utc()
    report = ParticipantSelfReport(
        session_id=session.session_id,
        participant_id=session.participant_id,
        trial_id=payload.trial_id,
        loop_index=payload.loop_index,
        sequence_position=payload.sequence_position,
        phase=payload.phase,
        timepoint=payload.timepoint,
        function_class=payload.function_class,
        is_problem=payload.is_problem,
        source="sr",
        before_after_robot_action=payload.before_after_robot_action,
        raw_json=json.dumps(sliders),
        timestamp_utc=now.isoformat(),
        session_time_ms=compute_session_time_ms(session, now),
        **sliders,
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
            **sliders,
        },
        ref_table="participant_self_reports",
        ref_id=str(report.self_report_id),
        now=now,
    )

    # The raw record now owns this context; drop its working draft (same
    # transaction, so the draft never outlives the finalized row).
    draft = _find_draft(db, session.session_id, context_key(payload))
    if draft is not None:
        db.delete(draft)

    db.commit()
    db.refresh(report)
    return report


def save_draft(db: Session, session: StudySession, payload) -> dict:
    """Autosave the in-progress sliders for one context (is_partial). Upserts the
    single (session_id, context_key) draft row; never writes a timeline event and
    never touches participant_self_reports (drafts are working state)."""
    _guard_trial(db, session, payload.trial_id)

    key = context_key(payload)
    sliders = {f: getattr(payload, f) for f in SLIDER_FIELDS}
    now_iso = now_utc().isoformat()

    draft = _find_draft(db, session.session_id, key)
    if draft is not None:
        for f, v in sliders.items():
            setattr(draft, f, v)
        draft.raw_json = json.dumps(sliders)
        draft.updated_at = now_iso
    else:
        db.add(
            SelfReportDraft(
                session_id=session.session_id,
                participant_id=session.participant_id,
                context_key=key,
                **{f: getattr(payload, f) for f in CONTEXT_FIELDS},
                raw_json=json.dumps(sliders),
                updated_at=now_iso,
                **sliders,
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
    return {
        "found": True,
        "context_key": key,
        "sliders": {f: getattr(draft, f) for f in SLIDER_FIELDS},
    }
