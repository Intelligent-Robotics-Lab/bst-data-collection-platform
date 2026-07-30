"""Attention-check response persistence + scoring.

Loads the attention-check questions from configs/attention_checks.yaml (cached),
computes ``is_correct`` for a participant's answer against that config (option
number, accepted spoken/typed forms, or an "option N"-style answer), and upserts
one row per (session, question). A mislogged answer can be re-logged (the row is
a scoring/annotation record); each log writes a session_timeline_events row.
"""

from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path

import yaml
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.timeutil import now_utc
from app.models.attention_check import AttentionCheckResponse
from app.models.session import StudySession
from app.services.timeline import compute_session_time_ms, record_timeline_event


def _config_path() -> Path:
    return settings.configs_dir / "attention_checks.yaml"


@lru_cache(maxsize=4)
def _load(path: str, file_hash: str) -> dict:
    """Parse the config; file_hash keys the cache so edits bypass it."""
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _cfg() -> dict:
    path = _config_path()
    if not path.exists():
        return {"questions": []}
    return _load(str(path), hashlib.sha256(path.read_bytes()).hexdigest())


def list_questions(phase: str | None = None) -> list[dict]:
    """All attention-check questions (optionally filtered to one phase), ordered."""
    qs = list(_cfg().get("questions", []))
    if phase is not None:
        qs = [q for q in qs if q.get("phase") == phase]
    return sorted(qs, key=lambda q: (q.get("phase", ""), q.get("order", 0)))


def _by_id() -> dict[str, dict]:
    return {q["question_id"]: q for q in _cfg().get("questions", [])}


def _question_or_422(question_id: str) -> dict:
    q = _by_id().get(question_id)
    if q is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"unknown attention-check question_id '{question_id}'",
        )
    return q


def _normalize(s: str | None) -> str:
    return (s or "").strip().lower()


def compute_is_correct(question: dict, answer: str | None) -> bool:
    """Correct if the answer is the option number, one of the accepted spoken/typed
    forms, or an 'option N'/'N.'-style answer whose number matches."""
    a = _normalize(answer)
    if not a:
        return False
    correct = _normalize(question.get("correct_answer"))
    if a == correct:
        return True
    accepted = {_normalize(x) for x in question.get("accepted_answers", [])}
    if a in accepted:
        return True
    m = re.match(r"^\s*(?:option\s*)?(\d)\b", a)
    if m and m.group(1) == correct:
        return True
    return False


def _find(db: Session, session_id: str, question_id: str) -> AttentionCheckResponse | None:
    return db.scalar(
        select(AttentionCheckResponse).where(
            AttentionCheckResponse.session_id == session_id,
            AttentionCheckResponse.question_id == question_id,
        )
    )


def list_responses(db: Session, session: StudySession) -> list[AttentionCheckResponse]:
    return db.scalars(
        select(AttentionCheckResponse)
        .where(AttentionCheckResponse.session_id == session.session_id)
        .order_by(AttentionCheckResponse.attention_check_id)
    ).all()


def log_response(
    db: Session, session: StudySession, payload
) -> AttentionCheckResponse:
    """Upsert the (session, question) response. Validates the question_id against
    the config and computes is_correct there; the caller cannot assert correctness."""
    q = _question_or_422(payload.question_id)
    is_correct = compute_is_correct(q, payload.participant_answer)
    now = now_utc()
    session_time_ms = (
        payload.session_time_ms
        if payload.session_time_ms is not None
        else compute_session_time_ms(session, now)
    )
    raw_json = json.dumps(
        {
            "choices": q.get("choices", []),
            "accepted_answers": q.get("accepted_answers", []),
            "order": q.get("order"),
        }
    )

    row = _find(db, session.session_id, payload.question_id)
    created = row is None
    if created:
        row = AttentionCheckResponse(
            session_id=session.session_id,
            participant_id=session.participant_id,
            phase=q["phase"],
            question_id=q["question_id"],
            question_text=q["text"],
            correct_answer=str(q["correct_answer"]),
            participant_answer=payload.participant_answer,
            is_correct=int(is_correct),
            source=payload.source,
            operator=payload.operator,
            notes=payload.notes,
            raw_json=raw_json,
            timestamp_utc=now.isoformat(),
            session_time_ms=session_time_ms,
            created_at=now.isoformat(),
            updated_at=now.isoformat(),
        )
        db.add(row)
    else:
        row.phase = q["phase"]
        row.question_text = q["text"]
        row.correct_answer = str(q["correct_answer"])
        row.participant_answer = payload.participant_answer
        row.is_correct = int(is_correct)
        row.source = payload.source
        row.operator = payload.operator
        row.notes = payload.notes
        row.raw_json = raw_json
        row.updated_at = now.isoformat()

    db.flush()
    record_timeline_event(
        db,
        session=session,
        source="attention_check",
        type="attention_check_logged" if created else "attention_check_updated",
        payload={
            "question_id": q["question_id"],
            "phase": q["phase"],
            "participant_answer": payload.participant_answer,
            "is_correct": bool(is_correct),
            "source": payload.source,
        },
        ref_table="attention_check_responses",
        ref_id=str(row.attention_check_id),
        now=now,
    )
    db.commit()
    db.refresh(row)
    return row
