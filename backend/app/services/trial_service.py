"""DTT trial logging service (P0.5).

A trial is validated against the session's assigned protocol config: phase_key,
target skill, sd_id, prompt_level, and every missed/extra step ID must exist in
the config. Bad references return a clean 422 (the protocol_id lesson), never a
DB 500. trial_number auto-increments per session. Each trial also writes a
session_timeline_events row.
"""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.timeutil import now_utc
from app.models.dtt import DttLoop, DttPerformanceEvent, DttPhase, DttTrial
from app.services.dtt_loops import resolve_named_sd
from app.models.session import StudySession
from app.services.protocol import get_protocol_config
from app.services.timeline import compute_session_time_ms, record_timeline_event


def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)


def _named_sd_entry(cfg: dict, session: StudySession, loop_index: int | None) -> dict | None:
    """The config entry for the named SD occupying this loop for the session's
    order group, or None when the mapping is unavailable."""
    if loop_index is None or session.pb_order_group is None:
        return None
    name = resolve_named_sd(session.pb_order_group, loop_index)
    if not name:
        return None
    for entry in cfg.get("named_sds") or []:
        if entry.get("name") == name:
            return entry
    return None


def _resolve_defaults(cfg: dict, session: StudySession, payload) -> tuple[str, str, str]:
    """Fill in phase_key / sd_id / target_skill when the caller omits them.

    The robot knows only the loop it just ran; everything else is derivable from
    the protocol config plus the participant's Latin-square order group. Keeping
    the derivation here (rather than hardcoded robot-side) is what stops the two
    repos drifting apart."""
    phase_key = payload.phase_key
    if phase_key is None:
        phases = cfg.get("phases", []) or []
        if len(phases) != 1:
            raise _unprocessable(
                "phase_key is required: the protocol defines "
                f"{len(phases)} phases, so it cannot be inferred"
            )
        phase_key = phases[0]["phase_key"]

    sd_id = payload.sd_id
    if sd_id is None:
        sd_id = f"sd_{payload.loop_index}"  # positional cell, mirrors dtt_loops.sd_id

    target_skill = payload.target_skill
    if target_skill is None:
        entry = _named_sd_entry(cfg, session, payload.loop_index)
        if entry is None or not entry.get("target_skill"):
            raise _unprocessable(
                "target_skill is required: it could not be resolved from the named "
                f"SD for loop {payload.loop_index} (is pb_order_group set?)"
            )
        target_skill = entry["target_skill"]

    return phase_key, sd_id, target_skill


def _guard_trial_name(session: StudySession, payload) -> None:
    """A caller-declared trial_name must match the named SD the Latin square puts
    in this loop. This catches robot/platform drift at ingest instead of silently
    mislabeling a trial."""
    if not payload.trial_name or session.pb_order_group is None:
        return
    expected = resolve_named_sd(session.pb_order_group, payload.loop_index)
    if expected and payload.trial_name != expected:
        raise _unprocessable(
            f"trial_name '{payload.trial_name}' does not match the named SD for loop "
            f"{payload.loop_index} of pb_order_group {session.pb_order_group} "
            f"(expected '{expected}')"
        )


def _step_session_time_ms(session: StudySession, step, fallback: datetime) -> tuple[str, int]:
    """(timestamp_utc, session_time_ms) for a step, preferring the robot's clock."""
    when = fallback
    if step.timestamp_utc:
        try:
            when = datetime.fromisoformat(step.timestamp_utc)
        except ValueError:
            when = fallback
    return when.isoformat(), compute_session_time_ms(session, when)


def _add_steps(db: Session, session: StudySession, trial: DttTrial, steps, now: datetime) -> int:
    """Append the within-trial interaction flow as dtt_performance_events rows.
    Append-only: written once, alongside the trial, never updated."""
    if not steps:
        return 0
    indices = [s.step_index for s in steps]
    if len(set(indices)) != len(indices):
        raise _unprocessable(f"duplicate step_index in steps: {sorted(indices)}")

    for step in sorted(steps, key=lambda s: s.step_index):
        ts, session_time_ms = _step_session_time_ms(session, step, now)
        db.add(
            DttPerformanceEvent(
                trial_id=trial.trial_id,
                session_id=session.session_id,
                participant_id=session.participant_id,
                step_index=step.step_index,
                step_label=step.step_label,
                outcome=step.outcome,
                timestamp_utc=ts,
                session_time_ms=session_time_ms,
                raw_json=json.dumps(step.detail) if step.detail else None,
            )
        )
    db.flush()
    return len(steps)


def _named_sd_text(cfg: dict, session: StudySession, loop_index: int | None) -> str | None:
    """The real SD wording for the named SD occupying this loop, e.g. loop 2 of
    order group 1 -> "Receptive Instruction" -> "Please shake your head.".

    Which named SD sits in a loop depends on the participant's pb_order_group
    (the Latin square), so this cannot come from the positional sd_id alone.
    Returns None when the mapping is unavailable (no group, no loop, or a
    protocol config without named_sds -- e.g. the old placeholder)."""
    if loop_index is None or session.pb_order_group is None:
        return None
    name = resolve_named_sd(session.pb_order_group, loop_index)
    if not name:
        return None
    for entry in cfg.get("named_sds") or []:
        if entry.get("name") == name:
            return entry.get("sd")
    return None


def create_trial(db: Session, session: StudySession, payload) -> DttTrial:
    if session.protocol_id is None:
        raise _unprocessable(
            f"session '{session.session_id}' has no protocol assigned; cannot log a trial"
        )
    cfg = get_protocol_config(db, session.protocol_id)
    if cfg is None:
        raise _unprocessable("protocol config not found for this session")

    # loop_index must reference a real generated dtt_loops row for THIS session,
    # not merely fall in 1-6. Loops are materialized at session start from the
    # pb_order_group Latin square; a trial cannot reference a loop that was never
    # generated (e.g. a session started without a pb_order_group). Clean 422,
    # never a DB 500 (the protocol_id lesson).
    if payload.loop_index is not None:
        loop = db.scalar(
            select(DttLoop).where(
                DttLoop.session_id == session.session_id,
                DttLoop.loop_index == payload.loop_index,
            )
        )
        if loop is None:
            generated = db.scalars(
                select(DttLoop.loop_index)
                .where(DttLoop.session_id == session.session_id)
                .order_by(DttLoop.loop_index)
            ).all()
            available = (
                str(generated)
                if generated
                else "none (was the session started with a pb_order_group?)"
            )
            raise _unprocessable(
                f"loop_index {payload.loop_index} has no dtt_loops row for session "
                f"'{session.session_id}'; generated loops: {available}"
            )

    # A caller-declared trial_name must agree with the Latin square, and any
    # omitted phase/sd/skill is derived from the loop + order group.
    _guard_trial_name(session, payload)
    phase_key, sd_id, target_skill = _resolve_defaults(cfg, session, payload)

    # phase
    phases = {p["phase_key"]: p for p in cfg.get("phases", [])}
    phase = phases.get(phase_key)
    if phase is None:
        raise _unprocessable(f"unknown phase_key '{phase_key}'; valid: {sorted(phases)}")

    # target skill within the phase
    skills = {s["skill_id"]: s for s in phase.get("target_skills", [])}
    skill = skills.get(target_skill)
    if skill is None:
        raise _unprocessable(
            f"unknown target_skill '{target_skill}' for phase "
            f"'{phase_key}'; valid: {sorted(skills)}"
        )

    # sd_id
    sds = {s["sd_id"]: s for s in cfg.get("sds", [])}
    if sd_id not in sds:
        raise _unprocessable(f"unknown sd_id '{sd_id}'; valid: {sorted(sds)}")

    # prompt_level: optional. This protocol has no prompt hierarchy (error
    # correction is a fixed sequence), so it is only validated when supplied.
    if payload.prompt_level is not None:
        prompt_levels = cfg.get("prompt_levels", [])
        if payload.prompt_level not in prompt_levels:
            raise _unprocessable(
                f"unknown prompt_level '{payload.prompt_level}'; valid: {prompt_levels}"
            )

    # missed / extra steps validate against the skill's ordered step IDs
    valid_steps = set(skill.get("steps", []))
    for field_name, values in (
        ("missed_steps", payload.missed_steps),
        ("extra_steps", payload.extra_steps),
    ):
        if values:
            bad = [s for s in values if s not in valid_steps]
            if bad:
                raise _unprocessable(
                    f"unknown {field_name} {bad} for skill '{target_skill}'; "
                    f"valid steps: {sorted(valid_steps)}"
                )

    # resolve dtt_phase_id (provenance link) and a human-readable SD label
    phase_row = db.scalar(
        select(DttPhase).where(
            DttPhase.protocol_id == session.protocol_id,
            DttPhase.phase_key == phase_key,
        )
    )
    sd_label = _named_sd_text(cfg, session, payload.loop_index) or sds[sd_id].get("label")

    # auto trial_number per session
    last = db.scalar(
        select(func.max(DttTrial.trial_number)).where(
            DttTrial.session_id == session.session_id
        )
    )
    trial_number = (last or 0) + 1

    now = now_utc()
    trial = DttTrial(
        session_id=session.session_id,
        participant_id=session.participant_id,
        trial_number=trial_number,
        loop_index=payload.loop_index,
        protocol_id=session.protocol_id,
        dtt_phase_id=phase_row.phase_id if phase_row else None,
        phase_key=phase_key,
        sd_id=sd_id,
        target_skill=target_skill,
        instruction=sd_label,
        participant_response=payload.participant_response,
        response_correctness=payload.response_correctness,
        response_latency_ms=payload.response_latency_ms,
        prompt_level=payload.prompt_level,
        reinforcement_delivered=int(payload.reinforcement_delivered),
        error_correction_delivered=int(payload.error_correction_delivered),
        missed_steps_json=json.dumps(payload.missed_steps) if payload.missed_steps else None,
        extra_steps_json=json.dumps(payload.extra_steps) if payload.extra_steps else None,
        deviation_flag=int(payload.deviation_flag),
        notes=payload.notes,
        timestamp_utc=now.isoformat(),
        session_time_ms=compute_session_time_ms(session, now),
    )
    db.add(trial)
    db.flush()

    # The within-trial interaction flow, appended in the same transaction so a
    # trial and its steps are never half-written.
    step_count = _add_steps(db, session, trial, payload.steps, now)

    record_timeline_event(
        db,
        session=session,
        source="dtt",
        type="trial_logged",
        payload={
            "trial_id": trial.trial_id,
            "trial_number": trial.trial_number,
            "loop_index": trial.loop_index,
            "phase_key": trial.phase_key,
            "sd_id": trial.sd_id,
            "target_skill": trial.target_skill,
            "trial_name": payload.trial_name,
            "steps": step_count,
            "response_correctness": trial.response_correctness,
            "prompt_level": trial.prompt_level,
            "reinforcement_delivered": trial.reinforcement_delivered,
            "error_correction_delivered": trial.error_correction_delivered,
            "missed_steps": payload.missed_steps,
            "extra_steps": payload.extra_steps,
            "deviation_flag": trial.deviation_flag,
        },
        ref_table="dtt_trials",
        ref_id=str(trial.trial_id),
        now=now,
    )
    db.commit()
    db.refresh(trial)
    return trial
