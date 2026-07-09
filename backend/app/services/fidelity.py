"""Human fidelity scoring persistence (Operator Console v3).

Upserts the single (session_id, loop_index) fidelity row, backfilling
function_class/sd_id from dtt_loops (source of truth). Draft autosaves are
working state and do NOT spam the timeline; the significant events -- a loop's
score first opened, and a loop marked complete -- each write a
session_timeline_events row (CLAUDE.md: every significant event is on the
timeline). This table is scoring/annotation, so rows are editable; raw records
are never touched here.
"""

from __future__ import annotations

import json

from fastapi import HTTPException, status as http_status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.timeutil import now_utc
from app.models.dtt import DttLoop
from app.models.fidelity import FIDELITY_SCORE_FIELDS, FidelityScore
from app.models.session import StudySession
from app.services.timeline import record_timeline_event


def _loop_meta(db: Session, session_id: str, loop_index: int) -> tuple[str | None, str | None]:
    """(function_class, sd_id) from dtt_loops for this loop, or (None, None)."""
    loop = db.scalar(
        select(DttLoop).where(
            DttLoop.session_id == session_id, DttLoop.loop_index == loop_index
        )
    )
    if loop is None:
        return None, None
    return loop.function_class, loop.sd_id


def _find(db: Session, session_id: str, loop_index: int) -> FidelityScore | None:
    return db.scalar(
        select(FidelityScore).where(
            FidelityScore.session_id == session_id,
            FidelityScore.loop_index == loop_index,
        )
    )


def serialize_fidelity_score(row: FidelityScore) -> dict:
    """Model row -> API dict, parsing error_sources_json back to a list."""
    out = {field: getattr(row, field) for field in FIDELITY_SCORE_FIELDS}
    out.update(
        {
            "fidelity_score_id": row.fidelity_score_id,
            "session_id": row.session_id,
            "participant_id": row.participant_id,
            "loop_index": row.loop_index,
            "function_class": row.function_class,
            "sd_id": row.sd_id,
            "error_sources": json.loads(row.error_sources_json)
            if row.error_sources_json
            else [],
            "notes": row.notes,
            "status": row.status,
            "scored_by": row.scored_by,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
    )
    return out


def list_scores(db: Session, session: StudySession) -> list[FidelityScore]:
    return db.scalars(
        select(FidelityScore)
        .where(FidelityScore.session_id == session.session_id)
        .order_by(FidelityScore.loop_index)
    ).all()


def get_score(db: Session, session: StudySession, loop_index: int) -> FidelityScore:
    row = _find(db, session.session_id, loop_index)
    if row is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"no fidelity score for session '{session.session_id}' loop {loop_index}",
        )
    return row


def upsert_score(
    db: Session, session: StudySession, loop_index: int, payload
) -> FidelityScore:
    """Create or update the (session, loop) score. Autosave-safe: a payload with
    status=None keeps the existing status (never demotes a completed loop)."""
    now = now_utc()
    now_iso = now.isoformat()
    function_class, sd_id = _loop_meta(db, session.session_id, loop_index)
    ratings = {field: getattr(payload, field) for field in FIDELITY_SCORE_FIELDS}
    error_json = json.dumps(payload.error_sources) if payload.error_sources else None

    row = _find(db, session.session_id, loop_index)
    created = row is None
    if created:
        row = FidelityScore(
            session_id=session.session_id,
            participant_id=session.participant_id,
            loop_index=loop_index,
            function_class=function_class,
            sd_id=sd_id,
            error_sources_json=error_json,
            notes=payload.notes,
            status=payload.status or "draft",
            scored_by=payload.scored_by,
            created_at=now_iso,
            updated_at=now_iso,
            **ratings,
        )
        db.add(row)
    else:
        for field, value in ratings.items():
            setattr(row, field, value)
        # Keep the denormalized loop meta fresh (loops exist by scoring time).
        if function_class is not None:
            row.function_class = function_class
        if sd_id is not None:
            row.sd_id = sd_id
        row.error_sources_json = error_json
        row.notes = payload.notes
        row.scored_by = payload.scored_by
        if payload.status is not None:
            row.status = payload.status
        row.updated_at = now_iso

    db.flush()
    if created:
        record_timeline_event(
            db,
            session=session,
            source="fidelity",
            type="fidelity_score_started",
            payload={
                "loop_index": loop_index,
                "function_class": function_class,
                "sd_id": sd_id,
                "status": row.status,
            },
            ref_table="fidelity_scores",
            ref_id=str(row.fidelity_score_id),
            now=now,
        )
    db.commit()
    db.refresh(row)
    return row


def complete_score(db: Session, session: StudySession, loop_index: int) -> FidelityScore:
    """Mark the (session, loop) score complete. The row must already exist (the
    UI saves a draft first); a missing row is a clean 404."""
    row = _find(db, session.session_id, loop_index)
    if row is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=(
                f"no fidelity score to complete for session '{session.session_id}' "
                f"loop {loop_index}; save it first"
            ),
        )
    now = now_utc()
    row.status = "complete"
    row.updated_at = now.isoformat()
    db.flush()
    record_timeline_event(
        db,
        session=session,
        source="fidelity",
        type="fidelity_score_completed",
        payload={
            "loop_index": loop_index,
            "function_class": row.function_class,
            "sd_id": row.sd_id,
        },
        ref_table="fidelity_scores",
        ref_id=str(row.fidelity_score_id),
        now=now,
    )
    db.commit()
    db.refresh(row)
    return row
