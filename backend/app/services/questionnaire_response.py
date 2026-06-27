"""Questionnaire response persistence (P0.4 / P0.6).

Responses are stored one row per item in ``questionnaire_responses`` (stable
item_id; no item text). Two write paths:

* autosave  -> is_partial=1 draft rows, upserted as the participant fills the
  form, so a tablet refresh restores every answer (P0.6). Drafts are working
  state, not the research record, so they may be replaced.
* submit    -> is_partial=0 rows; the finalized research record. Submission is
  guarded: once a questionnaire is finalized for a session it cannot be
  re-submitted or autosaved (corrections go through annotations -- the raw-record
  immutability rule), and a finalize writes one session_timeline_events row.

FK/validation problems (unknown questionnaire, unknown item_id, out-of-range
value, missing required item) return a clean 422, never a DB 500.
"""

from __future__ import annotations

import json

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.timeutil import now_utc
from app.models.questionnaire import QuestionnaireResponse
from app.models.session import StudySession
from app.services.questionnaire import (
    get_questionnaire,
    get_questionnaire_config,
    normalize_answers,
)
from app.services.timeline import record_timeline_event


def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)


def _resolve(db: Session, key: str, version: str | None):
    """Resolve a questionnaire to its registry row + parsed config, or 422."""
    row = get_questionnaire(db, key, version)
    cfg = get_questionnaire_config(db, key, version)
    if row is None or cfg is None:
        raise _unprocessable(
            f"unknown questionnaire '{key}'"
            + (f" version '{version}'" if version else "")
            + "; not registered"
        )
    return row, cfg


def _existing_rows(db: Session, session_id: str, key: str, version: str):
    return db.scalars(
        select(QuestionnaireResponse).where(
            QuestionnaireResponse.session_id == session_id,
            QuestionnaireResponse.questionnaire_key == key,
            QuestionnaireResponse.questionnaire_version == version,
        )
    ).all()


def _is_finalized(rows) -> bool:
    return any(r.is_partial == 0 for r in rows)


def save_partial(
    db: Session, session: StudySession, key: str, version: str | None, answers: dict
) -> dict:
    """Autosave draft answers (is_partial=1). Upserts per item; no timeline
    event (drafts are not significant events). Rejected if already finalized."""
    row, cfg = _resolve(db, key, version)
    version = row.version
    normalized = normalize_answers(cfg, answers, require_required=False)

    existing = {
        r.item_id: r for r in _existing_rows(db, session.session_id, key, version)
    }
    if _is_finalized(existing.values()):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"questionnaire '{key}' already finalized for session '{session.session_id}'",
        )

    now_iso = now_utc().isoformat()
    for ans in normalized:
        existing_row = existing.get(ans["item_id"])
        if existing_row is not None:
            existing_row.response_raw = ans["response_raw"]
            existing_row.response_numeric = ans["response_numeric"]
            existing_row.item_index = ans["item_index"]
            existing_row.is_partial = 1
            existing_row.recorded_at = now_iso
        else:
            db.add(
                QuestionnaireResponse(
                    session_id=session.session_id,
                    participant_id=session.participant_id,
                    questionnaire_key=key,
                    questionnaire_version=version,
                    item_id=ans["item_id"],
                    item_index=ans["item_index"],
                    response_raw=ans["response_raw"],
                    response_numeric=ans["response_numeric"],
                    timepoint=cfg.get("timepoint", "na"),
                    is_partial=1,
                    recorded_at=now_iso,
                )
            )
    db.commit()
    return {
        "questionnaire_key": key,
        "questionnaire_version": version,
        "saved_items": len(normalized),
        "is_partial": True,
    }


def submit(
    db: Session, session: StudySession, key: str, version: str | None, answers: dict
) -> dict:
    """Finalize a questionnaire (is_partial=0). Requires every required item.
    Replaces any draft rows and writes a session_timeline_events row. Rejected
    if already finalized (raw records are never overwritten)."""
    row, cfg = _resolve(db, key, version)
    version = row.version
    normalized = normalize_answers(cfg, answers, require_required=True)

    existing = _existing_rows(db, session.session_id, key, version)
    if _is_finalized(existing):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"questionnaire '{key}' already finalized for session '{session.session_id}'",
        )
    # Drop draft rows; the submission below is the authoritative finalized set.
    for r in existing:
        db.delete(r)
    db.flush()

    now = now_utc()
    now_iso = now.isoformat()
    first_id = None
    for ans in normalized:
        resp = QuestionnaireResponse(
            session_id=session.session_id,
            participant_id=session.participant_id,
            questionnaire_key=key,
            questionnaire_version=version,
            item_id=ans["item_id"],
            item_index=ans["item_index"],
            response_raw=ans["response_raw"],
            response_numeric=ans["response_numeric"],
            timepoint=cfg.get("timepoint", "na"),
            is_partial=0,
            recorded_at=now_iso,
        )
        db.add(resp)
        db.flush()
        if first_id is None:
            first_id = resp.response_id

    record_timeline_event(
        db,
        session=session,
        source="questionnaire",
        type="questionnaire_submitted",
        payload={
            "questionnaire_key": key,
            "questionnaire_version": version,
            "timepoint": cfg.get("timepoint", "na"),
            "item_count": len(normalized),
        },
        ref_table="questionnaire_responses",
        ref_id=str(first_id) if first_id is not None else None,
        now=now,
    )
    db.commit()
    return {
        "questionnaire_key": key,
        "questionnaire_version": version,
        "item_count": len(normalized),
        "is_partial": False,
    }


def _reconstruct_value(cfg_item_type: str, row: QuestionnaireResponse):
    """Best-effort typed value for the tablet to repopulate a field."""
    if row.response_numeric is not None:
        n = row.response_numeric
        return int(n) if n == int(n) else n
    if cfg_item_type == "multi_choice" and row.response_raw:
        try:
            return json.loads(row.response_raw)
        except json.JSONDecodeError:
            return row.response_raw
    return row.response_raw


def get_responses(
    db: Session, session: StudySession, key: str, version: str | None
) -> dict:
    """Saved answers for a questionnaire, for refresh-restore on the tablet."""
    row, cfg = _resolve(db, key, version)
    version = row.version
    types = {
        it["item_id"]: (it.get("type") or ("likert" if cfg.get("response_scale") else "text"))
        for it in cfg.get("items", [])
    }
    rows = _existing_rows(db, session.session_id, key, version)
    answers = {
        r.item_id: {
            "value": _reconstruct_value(types.get(r.item_id, "text"), r),
            "response_raw": r.response_raw,
            "response_numeric": r.response_numeric,
            "is_partial": bool(r.is_partial),
        }
        for r in rows
    }
    return {
        "questionnaire_key": key,
        "questionnaire_version": version,
        "finalized": _is_finalized(rows),
        "answers": answers,
    }
