"""Participant-facing experiment progress (derived from sync gates).

The participant tablet shows, between forms, a calm progress view: which phase
of the session they are in (Tutorial -> Instruction -> Modeling -> Rehearsal) and
how many of the six rehearsal rounds are done. This is DERIVED from the sync
gates the robot already opens (no robot change) plus the session state -- it is
read-only and never shows internal trial states or ASR transcripts.

Phase is the furthest milestone reached, read monotonically: a stage's baseline
gate opens when that stage COMPLETES, so e.g. the tutorial gate being present
means tutorial is done and the participant is now in Instruction.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.session import StudySession
from app.models.sync import SyncGate
from app.models.system import SessionTimelineEvent
from app.services.dtt_loops import resolve_named_sd
from app.services.protocol import get_protocol_config

# Participant-facing phases, in order.
PHASES = [
    {"key": "tutorial", "label": "Tutorial"},
    {"key": "instruction", "label": "Instruction"},
    {"key": "modeling", "label": "Modeling"},
    {"key": "rehearsal", "label": "Rehearsal"},
]
_PHASE_INDEX = {p["key"]: i for i, p in enumerate(PHASES)}
REHEARSAL_ROUNDS = 6

# IMPORTANT (research validity): the tablet must NOT show affective/encouraging
# content during the interaction. The study measures the participant's emotional
# response to the ROBOT's emotional induction; a tablet message like "great work"
# would confound that. So active phases carry NO message -- only neutral progress.
# Messages appear only before the interaction (pre-forms) and after it (thanks).
_MESSAGES = {
    "pre_session": (
        "Please take a few minutes to complete some questionnaires. "
        "Your session with the robot will begin soon."
    ),
    "complete": (
        "Thank you for taking part in this study. "
        "We truly appreciate your time and participation."
    ),
}


def _current_session(db: Session) -> StudySession | None:
    """The session the tablet should reflect: the active (running/paused) one,
    else the most recently created (to show 'complete' right after a session)."""
    running = db.scalar(
        select(StudySession)
        .where(StudySession.state.in_(("running", "paused")))
        .order_by(StudySession.created_at.desc())
        .limit(1)
    )
    if running is not None:
        return running
    return db.scalar(select(StudySession).order_by(StudySession.created_at.desc()).limit(1))


def _base(session, phase, **over) -> dict:
    out = {
        "session_id": session.session_id if session else None,
        "state": session.state if session else None,
        "phase": phase,
        "phase_label": next((p["label"] for p in PHASES if p["key"] == phase), None),
        "phase_index": _PHASE_INDEX.get(phase, -1),
        "phases": PHASES,
        "round": 0,
        "rounds_done": 0,
        "rounds_total": REHEARSAL_ROUNDS,
        # Non-active phases show a message; active phases show none (see note above).
        "message": _MESSAGES.get(phase, ""),
        # 'active' means an interaction phase is in progress (drives the progress
        # visuals vs a waiting/thanks screen).
        "active": phase in ("tutorial", "instruction", "modeling", "rehearsal"),
    }
    out.update(over)
    return out


def _robot_started(db: Session, session_id: str) -> bool:
    """True once BST has registered its run (its first act). Distinguishes the
    pre-session window (participant filling questionnaires, robot not started)
    from the tutorial actually running."""
    return db.scalar(
        select(SessionTimelineEvent.event_id)
        .where(
            SessionTimelineEvent.session_id == session_id,
            SessionTimelineEvent.type == "bst_session_registered",
        )
        .limit(1)
    ) is not None


def _rehearsal_sd_plan(db: Session, session: StudySession) -> list[dict]:
    """The ordered SD-delivery guide the tablet shows in rehearsal: for each
    position 1..6, the named skill the participant delivers to the child and its
    SD prompt. Position -> named SD is deterministic from pb_order_group; the SD
    wording/type comes from the session's protocol config (cached load). Pure
    read; when the group or config is missing, name/prompt come back None and the
    tablet falls back to a bare number."""
    group = session.pb_order_group
    cfg = get_protocol_config(db, session.protocol_id) if session.protocol_id else None
    by_name = {sd.get("name"): sd for sd in (cfg or {}).get("named_sds", [])}
    plan = []
    for n in range(1, REHEARSAL_ROUNDS + 1):
        name = resolve_named_sd(group, n)
        meta = by_name.get(name, {})
        plan.append(
            {
                "number": n,
                "name": name,
                "sd_type": meta.get("sd_type"),
                "target_skill": meta.get("target_skill"),
                "prompt": meta.get("sd"),
            }
        )
    return plan


def compute_progress(db: Session, session: StudySession) -> dict:
    gates = db.scalars(
        select(SyncGate).where(SyncGate.session_id == session.session_id)
    ).all()
    stage_keys = {g.stage_key for g in gates if g.scope == "stage" and g.stage_key}
    loop_gates = [g for g in gates if g.scope == "loop"]
    current_round = max((g.loop_index for g in loop_gates if g.loop_index), default=0)
    rounds_done = len(
        {g.loop_index for g in loop_gates if g.checkpoint == "post_feedback" and g.loop_index}
    )

    state = session.state
    if state == "completed":
        return _base(session, "complete", round=REHEARSAL_ROUNDS, rounds_done=REHEARSAL_ROUNDS)
    if state in ("created", None) or (not gates and not _robot_started(db, session.session_id)):
        # Session not started, or running but the robot has not begun yet: the
        # participant is completing the pre-session questionnaires.
        return _base(session, "pre_session")

    if loop_gates or "modeling" in stage_keys:
        phase = "rehearsal"
    elif "instruction" in stage_keys:
        phase = "modeling"
    elif "tutorial" in stage_keys:
        phase = "instruction"
    else:
        phase = "tutorial"  # robot started, first stage in progress

    if phase == "rehearsal":
        # The SD to deliver NOW, strictly chronological: it points to trial N for
        # the whole of loop N and only advances to N+1 once loop N fully completes
        # (a post_feedback gate). Starts at 1, never jumps or goes backward. None
        # once all six are delivered.
        next_sd = rounds_done + 1 if rounds_done < REHEARSAL_ROUNDS else None
        return _base(
            session,
            "rehearsal",
            round=current_round,
            rounds_done=rounds_done,
            next_sd=next_sd,
            rehearsal_sds=_rehearsal_sd_plan(db, session),
        )
    return _base(session, phase)


def current_progress(db: Session) -> dict:
    """Progress for the current session, or a pre-session view if none."""
    session = _current_session(db)
    if session is None:
        return _base(None, "pre_session")
    return compute_progress(db, session)
