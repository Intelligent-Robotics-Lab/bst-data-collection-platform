"""BST<->platform synchronization gate service (Phase 7, P0.13).

Implements the gate state machine the BST robot run waits on. A gate is a barrier
keyed by (session_id, gate_key); gate_key canonically encodes scope/ref/checkpoint.

  open  : a gate opens on stage_complete / sd_delivered / feedback_delivered.
  close : a gate closes on EITHER the matching self-report being submitted
          (closed_by='self_report') OR an operator override (closed_by='override').
  poll  : go_ahead returns proceed=false ONLY while an open gate is unsatisfied;
          true once it is closed (or was never opened).

Self-report -> checkpoint matching (the close-by-self-report rule):
  * stage 'baseline'      : a participant_self_reports row with phase == stage_key
  * loop  'post_sd'       : a row with that loop_index and phase == 'rehearsal'
  * loop  'post_feedback' : a row with that loop_index and phase == 'feedback'

Operator override writes a 'self_report_gate_overridden' timeline marker so an
analyst sees the measurement was skipped-by-override, not missing-by-error. Every
open/close also writes a timeline event, so the gate trail survives in exports.

READ-mostly against research tables: this service only inserts/updates sync_gates
rows and timeline events; it never mutates self-reports or other raw data.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.timeutil import now_utc
from app.models.session import StudySession
from app.models.signals import ParticipantSelfReport
from app.models.sync import SyncGate
from app.services.session_service import get_session_or_404
from app.services.timeline import record_timeline_event

logger = logging.getLogger("bst.sync_gate")

STAGES = ("tutorial", "instruction", "modeling")
STAGE_CHECKPOINT = "baseline"
LOOP_CHECKPOINTS = ("post_sd", "post_feedback")
# self-report phase that satisfies each loop checkpoint
LOOP_CHECKPOINT_PHASE = {"post_sd": "rehearsal", "post_feedback": "feedback"}


def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)


# --- gate identity -----------------------------------------------------------

def resolve_gate_identity(
    *, scope: str, stage_key: str | None, loop_index: int | None, checkpoint: str
) -> dict:
    """Validate and canonicalize a gate identity. Returns the normalized fields +
    gate_key, or raises a clean 422. The single place gate keys are formed."""
    if scope == "stage":
        if stage_key not in STAGES:
            raise _unprocessable(f"stage must be one of {STAGES}; got {stage_key!r}")
        if checkpoint != STAGE_CHECKPOINT:
            raise _unprocessable(
                f"stage gates use checkpoint '{STAGE_CHECKPOINT}'; got {checkpoint!r}"
            )
        if loop_index is not None:
            raise _unprocessable("stage gates must not carry a loop_index")
        return {
            "scope": "stage",
            "stage_key": stage_key,
            "loop_index": None,
            "checkpoint": STAGE_CHECKPOINT,
            "gate_key": f"stage:{stage_key}:{STAGE_CHECKPOINT}",
        }
    if scope == "loop":
        if loop_index is None or not (1 <= loop_index <= 6):
            raise _unprocessable(f"loop gates need loop_index in 1..6; got {loop_index!r}")
        if checkpoint not in LOOP_CHECKPOINTS:
            raise _unprocessable(
                f"loop gates use checkpoint in {LOOP_CHECKPOINTS}; got {checkpoint!r}"
            )
        if stage_key is not None:
            raise _unprocessable("loop gates must not carry a stage_key")
        return {
            "scope": "loop",
            "stage_key": None,
            "loop_index": loop_index,
            "checkpoint": checkpoint,
            "gate_key": f"loop:{loop_index}:{checkpoint}",
        }
    raise _unprocessable(f"scope must be 'stage' or 'loop'; got {scope!r}")


def _find_gate(db: Session, session_id: str, gate_key: str) -> SyncGate | None:
    return db.scalar(
        select(SyncGate).where(
            SyncGate.session_id == session_id, SyncGate.gate_key == gate_key
        )
    )


def _has_matching_self_report(db: Session, session_id: str, ident: dict) -> bool:
    """True if a submitted self-report satisfies this checkpoint (the
    close-by-self-report rule)."""
    q = select(ParticipantSelfReport.self_report_id).where(
        ParticipantSelfReport.session_id == session_id
    )
    if ident["scope"] == "stage":
        q = q.where(ParticipantSelfReport.phase == ident["stage_key"])
    else:
        q = q.where(
            ParticipantSelfReport.loop_index == ident["loop_index"],
            ParticipantSelfReport.phase == LOOP_CHECKPOINT_PHASE[ident["checkpoint"]],
        )
    return db.scalar(q.limit(1)) is not None


def _gate_dict(gate: SyncGate) -> dict:
    return {
        "gate_id": gate.gate_id,
        "session_id": gate.session_id,
        "gate_key": gate.gate_key,
        "scope": gate.scope,
        "stage_key": gate.stage_key,
        "loop_index": gate.loop_index,
        "checkpoint": gate.checkpoint,
        "status": gate.status,
        "closed_by": gate.closed_by,
        "override_operator": gate.override_operator,
        "override_reason": gate.override_reason,
        "opened_at": gate.opened_at,
        "closed_at": gate.closed_at,
    }


# --- open --------------------------------------------------------------------

def open_gate(db: Session, session: StudySession, ident: dict) -> SyncGate:
    """Open (create if absent) the gate for an identity. Idempotent: an existing
    gate is returned untouched, so a re-sent trigger never reopens a gate already
    satisfied or overridden (raw-data / measurement integrity)."""
    gate = _find_gate(db, session.session_id, ident["gate_key"])
    if gate is not None:
        return gate

    now = now_utc()
    gate = SyncGate(
        session_id=session.session_id,
        gate_key=ident["gate_key"],
        scope=ident["scope"],
        stage_key=ident["stage_key"],
        loop_index=ident["loop_index"],
        checkpoint=ident["checkpoint"],
        status="open",
        opened_at=now.isoformat(),
    )
    db.add(gate)
    db.flush()

    record_timeline_event(
        db,
        session=session,
        source="sync",
        type="self_report_gate_opened",
        payload={
            "gate_key": gate.gate_key,
            "scope": gate.scope,
            "stage_key": gate.stage_key,
            "loop_index": gate.loop_index,
            "checkpoint": gate.checkpoint,
        },
        ref_table="sync_gates",
        ref_id=str(gate.gate_id),
        now=now,
    )
    db.commit()
    db.refresh(gate)
    return gate


def _close_gate(
    db: Session,
    session: StudySession,
    gate: SyncGate,
    *,
    closed_by: str,
    operator: str | None = None,
    reason: str | None = None,
) -> SyncGate:
    now = now_utc()
    gate.status = "closed"
    gate.closed_by = closed_by
    gate.closed_at = now.isoformat()
    if closed_by == "override":
        gate.override_operator = operator
        gate.override_reason = reason

    event_type = (
        "self_report_gate_overridden"
        if closed_by == "override"
        else "self_report_gate_closed"
    )
    record_timeline_event(
        db,
        session=session,
        source="sync",
        type=event_type,
        payload={
            "gate_key": gate.gate_key,
            "scope": gate.scope,
            "stage_key": gate.stage_key,
            "loop_index": gate.loop_index,
            "checkpoint": gate.checkpoint,
            "closed_by": closed_by,
            "operator": operator,
            "reason": reason,
        },
        ref_table="sync_gates",
        ref_id=str(gate.gate_id),
        now=now,
    )
    db.commit()
    db.refresh(gate)
    return gate


# --- poll / go-ahead ---------------------------------------------------------

def go_ahead(db: Session, session: StudySession, ident: dict) -> dict:
    """Poll a gate. proceed=false only while an open gate is unsatisfied. If a
    matching self-report now exists, the gate is lazily closed (closed_by=
    'self_report') and proceed flips true. A gate that was never opened does not
    block (proceed=true, gate_found=false): BST opens before it polls."""
    gate = _find_gate(db, session.session_id, ident["gate_key"])
    if gate is None:
        return {"proceed": True, "gate_found": False, "gate": None}

    if gate.status == "closed":
        return {"proceed": True, "gate_found": True, "gate": _gate_dict(gate)}

    if _has_matching_self_report(db, session.session_id, ident):
        gate = _close_gate(db, session, gate, closed_by="self_report")
        return {"proceed": True, "gate_found": True, "gate": _gate_dict(gate)}

    return {"proceed": False, "gate_found": True, "gate": _gate_dict(gate)}


def override_gate(
    db: Session,
    session: StudySession,
    ident: dict,
    *,
    operator: str | None,
    reason: str | None,
) -> SyncGate:
    """Operator releases a gate. Creates the gate first if it was not opened yet,
    then closes it by override (idempotent if already closed by override). Writes
    the 'self_report_gate_overridden' marker."""
    gate = _find_gate(db, session.session_id, ident["gate_key"])
    if gate is None:
        gate = open_gate(db, session, ident)

    if gate.status == "closed" and gate.closed_by == "override":
        return gate  # idempotent

    return _close_gate(
        db, session, gate, closed_by="override", operator=operator, reason=reason
    )


# --- session-level markers ---------------------------------------------------

def register_session(db: Session, session: StudySession) -> dict:
    """Bind a BST run to this platform session. Returns the between-subjects
    mapping so BST can confirm configuration<->pb_order_group and
    feedback_style<->support_condition alignment."""
    now = now_utc()
    support_label = (
        "supportive"
        if session.support_condition == 1
        else "neutral"
        if session.support_condition == 0
        else None
    )
    record_timeline_event(
        db,
        session=session,
        source="sync",
        type="bst_session_registered",
        payload={
            "pb_order_group": session.pb_order_group,
            "support_condition": session.support_condition,
        },
        ref_table="sessions",
        ref_id=session.session_id,
        now=now,
    )
    db.commit()
    return {
        "session_id": session.session_id,
        "participant_id": session.participant_id,
        "scenario_type": session.scenario_type,
        "state": session.state,
        "pb_order_group": session.pb_order_group,
        "support_condition": session.support_condition,
        "support_label": support_label,
    }


def complete_session(db: Session, session: StudySession) -> dict:
    """BST signals DTT finished. Writes a marker and returns gate counts. Does not
    change the session lifecycle state (the operator/platform owns that)."""
    gates = db.scalars(
        select(SyncGate).where(SyncGate.session_id == session.session_id)
    ).all()
    open_gates = [g.gate_key for g in gates if g.status == "open"]
    overridden = [g.gate_key for g in gates if g.closed_by == "override"]

    now = now_utc()
    record_timeline_event(
        db,
        session=session,
        source="sync",
        type="bst_session_complete",
        payload={
            "total_gates": len(gates),
            "open_gates": open_gates,
            "overridden_gates": overridden,
        },
        ref_table="sessions",
        ref_id=session.session_id,
        now=now,
    )
    db.commit()
    return {
        "session_id": session.session_id,
        "total_gates": len(gates),
        "open_gates": open_gates,
        "closed_gates": [g.gate_key for g in gates if g.status == "closed"],
        "overridden_gates": overridden,
    }


# --- helpers used by the API for the three openers ---------------------------

def open_stage_gate(db: Session, session: StudySession, stage_key: str) -> SyncGate:
    ident = resolve_gate_identity(
        scope="stage", stage_key=stage_key, loop_index=None, checkpoint="baseline"
    )
    return open_gate(db, session, ident)


def open_loop_gate(
    db: Session, session: StudySession, loop_index: int, checkpoint: str
) -> SyncGate:
    ident = resolve_gate_identity(
        scope="loop", stage_key=None, loop_index=loop_index, checkpoint=checkpoint
    )
    return open_gate(db, session, ident)
