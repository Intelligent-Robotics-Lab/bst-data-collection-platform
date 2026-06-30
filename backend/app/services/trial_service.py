"""DTT trial logging service (P0.5).

A trial is validated against the session's assigned protocol config: phase_key,
target skill, sd_id, prompt_level, and every missed/extra step ID must exist in
the config. Bad references return a clean 422 (the protocol_id lesson), never a
DB 500. trial_number auto-increments per session. Each trial also writes a
session_timeline_events row.
"""

from __future__ import annotations

import json

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.timeutil import now_utc
from app.models.dtt import DttLoop, DttPhase, DttTrial
from app.models.session import StudySession
from app.services.protocol import get_protocol_config
from app.services.timeline import compute_session_time_ms, record_timeline_event


def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)


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

    # phase
    phases = {p["phase_key"]: p for p in cfg.get("phases", [])}
    phase = phases.get(payload.phase_key)
    if phase is None:
        raise _unprocessable(
            f"unknown phase_key '{payload.phase_key}'; valid: {sorted(phases)}"
        )

    # target skill within the phase
    skills = {s["skill_id"]: s for s in phase.get("target_skills", [])}
    skill = skills.get(payload.target_skill)
    if skill is None:
        raise _unprocessable(
            f"unknown target_skill '{payload.target_skill}' for phase "
            f"'{payload.phase_key}'; valid: {sorted(skills)}"
        )

    # sd_id
    sds = {s["sd_id"]: s for s in cfg.get("sds", [])}
    if payload.sd_id not in sds:
        raise _unprocessable(f"unknown sd_id '{payload.sd_id}'; valid: {sorted(sds)}")

    # prompt_level
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
                    f"unknown {field_name} {bad} for skill '{payload.target_skill}'; "
                    f"valid steps: {sorted(valid_steps)}"
                )

    # resolve dtt_phase_id (provenance link) and a human-readable SD label
    phase_row = db.scalar(
        select(DttPhase).where(
            DttPhase.protocol_id == session.protocol_id,
            DttPhase.phase_key == payload.phase_key,
        )
    )
    sd_label = sds[payload.sd_id].get("label")

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
        phase_key=payload.phase_key,
        sd_id=payload.sd_id,
        target_skill=payload.target_skill,
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
