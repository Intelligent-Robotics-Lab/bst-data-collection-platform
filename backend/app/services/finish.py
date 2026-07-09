"""Session finish / completeness check (Operator Console closeout).

Read-only. Computes an authoritative completeness report for the console's
end-of-session finish flow. Sessions are UNREPEATABLE, so the point of this is
to surface anything missing or abnormal BEFORE the operator finalizes, while the
participant is still present. Touches only source tables; writes nothing and
never mutates state.

The canonical fully-gated bst_dtt session has 15 gated self-report checkpoints:
3 instructional stage baselines (tutorial/instruction/modeling) + 6 loops x 2
checkpoints (post_kid_response, post_feedback). Each expected checkpoint is
resolved against the actual sync_gates row to one of:
  collected   -- gate closed by a self_report (data captured)
  overridden  -- gate closed by operator override (intentionally skipped)
  open        -- gate still open (robot was/ is waiting; NOT captured)
  not_fired   -- no gate row (robot never reached this checkpoint)
'missing' = open + not_fired (needs attention); 'overridden' is flagged
separately as an intentional skip.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.dtt import DttTrial
from app.models.questionnaire import Questionnaire, QuestionnaireResponse
from app.models.session import StudySession
from app.models.signals import MediaRecording, ParticipantSelfReport
from app.models.sync import SyncGate
from app.services.sync_gate import (
    LOOP_CHECKPOINT_PHASE,
    LOOP_CHECKPOINTS,
    STAGE_CHECKPOINT,
    STAGES,
)


def _expected_gates() -> list[dict]:
    """The 15 canonical gated checkpoints, in session order."""
    expected: list[dict] = []
    for stage in STAGES:
        expected.append(
            {
                "gate_key": f"stage:{stage}:{STAGE_CHECKPOINT}",
                "scope": "stage",
                "ref": stage,
                "checkpoint": STAGE_CHECKPOINT,
            }
        )
    for loop in range(1, 7):
        for checkpoint in LOOP_CHECKPOINTS:
            expected.append(
                {
                    "gate_key": f"loop:{loop}:{checkpoint}",
                    "scope": "loop",
                    "ref": loop,
                    "checkpoint": checkpoint,
                }
            )
    return expected


def _self_report_collected(db: Session, sid: str, exp: dict) -> bool:
    """True if a submitted self-report satisfies this checkpoint. Mirrors the
    gate's close-by-self-report rule (phase for a stage; loop_index + phase for a
    loop) so 'collected' is authoritative even before the robot's next go-ahead
    poll has lazily flipped the gate row to closed."""
    q = select(ParticipantSelfReport.self_report_id).where(
        ParticipantSelfReport.session_id == sid
    )
    if exp["scope"] == "stage":
        q = q.where(ParticipantSelfReport.phase == exp["ref"])
    else:
        q = q.where(
            ParticipantSelfReport.loop_index == exp["ref"],
            ParticipantSelfReport.phase == LOOP_CHECKPOINT_PHASE[exp["checkpoint"]],
        )
    return db.scalar(q.limit(1)) is not None


def _checkpoint_status(db: Session, sid: str, exp: dict, gate: SyncGate | None) -> str:
    """Resolve one expected checkpoint against the gate row AND the actual
    self-report data. Override wins (intentional skip); otherwise a matching
    self-report is 'collected' regardless of the gate's lazy-close state; then
    an open gate is 'open'; no gate at all is 'not_fired'."""
    if gate is not None and gate.closed_by == "override":
        return "overridden"
    if _self_report_collected(db, sid, exp):
        return "collected"
    if gate is not None and gate.status == "open":
        return "open"
    if gate is None:
        return "not_fired"
    return "closed"  # closed, not by override, yet no matching self-report (unusual)


def _questionnaire_status(db: Session, sid: str, timepoint: str) -> list[dict]:
    """Registered questionnaires for a timepoint + whether a finalized (non-draft)
    response exists for this session."""
    regs = db.scalars(
        select(Questionnaire)
        .where(Questionnaire.timepoint == timepoint)
        .order_by(Questionnaire.questionnaire_key)
    ).all()
    out: list[dict] = []
    for q in regs:
        submitted = (
            db.scalar(
                select(func.count())
                .select_from(QuestionnaireResponse)
                .where(
                    QuestionnaireResponse.session_id == sid,
                    QuestionnaireResponse.questionnaire_key == q.questionnaire_key,
                    QuestionnaireResponse.is_partial == 0,
                )
            )
            or 0
        ) > 0
        out.append({"key": q.questionnaire_key, "title": q.title, "submitted": submitted})
    return out


def compute_completeness(db: Session, session: StudySession) -> dict:
    """Authoritative, read-only completeness report for the finish flow."""
    sid = session.session_id

    # --- gated self-reports (via sync_gates) ---
    gates = {
        g.gate_key: g
        for g in db.scalars(select(SyncGate).where(SyncGate.session_id == sid)).all()
    }
    expected = _expected_gates()
    counts = {"collected": 0, "overridden": 0, "open": 0, "not_fired": 0, "closed": 0}
    detail: list[dict] = []
    for exp in expected:
        st = _checkpoint_status(db, sid, exp, gates.get(exp["gate_key"]))
        counts[st] = counts.get(st, 0) + 1
        detail.append({**exp, "status": st})
    missing = [d["gate_key"] for d in detail if d["status"] in ("open", "not_fired")]
    overridden = [d["gate_key"] for d in detail if d["status"] == "overridden"]
    gates_open = [d["gate_key"] for d in detail if d["status"] == "open"]

    sr_rows = (
        db.scalar(
            select(func.count())
            .select_from(ParticipantSelfReport)
            .where(ParticipantSelfReport.session_id == sid)
        )
        or 0
    )

    # --- questionnaires ---
    pre = _questionnaire_status(db, sid, "pre")
    post = _questionnaire_status(db, sid, "post")
    q_missing = [q["key"] for q in (pre + post) if not q["submitted"]]

    # --- DTT trials ---
    trials = (
        db.scalar(
            select(func.count()).select_from(DttTrial).where(DttTrial.session_id == sid)
        )
        or 0
    )

    # --- recording (last row is the session's A/V capture) ---
    recs = db.scalars(
        select(MediaRecording)
        .where(MediaRecording.session_id == sid)
        .order_by(MediaRecording.recording_id)
    ).all()
    if not recs:
        # No row at all: distinguish "recording was intentionally disabled"
        # (RECORDING_ENABLED=false -> the service returns before writing a row,
        # so no A/V was ever attempted, which is a valid config, not a failure)
        # from "recording was on but somehow produced no row" (a real anomaly).
        if not settings.RECORDING_ENABLED:
            recording = {
                "status": "disabled",
                "ok": True,
                "file_path": None,
                "recording_id": None,
                "error_text": None,
            }
        else:
            recording = {
                "status": "none",
                "ok": False,
                "file_path": None,
                "recording_id": None,
                "error_text": None,
            }
    else:
        last = recs[-1]
        recording = {
            "status": last.status,
            "ok": last.status == "completed",
            "file_path": last.file_path,
            "recording_id": last.recording_id,
            "error_text": last.error_text,
        }

    # --- warnings + readiness ---
    warnings: list[str] = []
    if session.state in ("running", "paused"):
        warnings.append(
            f"session is still '{session.state}'; recording/perception not yet stopped"
        )
    if missing:
        warnings.append(
            f"{len(missing)} gated self-report(s) missing (not collected): "
            + ", ".join(missing)
        )
    if overridden:
        warnings.append(
            f"{len(overridden)} gate(s) skipped by override: " + ", ".join(overridden)
        )
    if q_missing:
        warnings.append("questionnaire(s) not submitted: " + ", ".join(q_missing))
    if recording["status"] == "none":
        warnings.append(
            "recording is enabled but no recording row exists for this session"
        )
    elif not recording["ok"]:
        warnings.append(
            f"recording status is '{recording['status']}' (expected 'completed')"
        )
    # DTT trials are not logged through the console workflow (no trial-entry
    # panel in v1), so a count of 0 is informational -- shown in the report, not
    # raised as a "needs attention" warning. Re-add a check here if per-trial
    # logging becomes part of the operator workflow.

    # 'ready' means nothing is missing and A/V is safely captured, and the session
    # is already stopped/completed. It is advisory: the operator may still finalize
    # over warnings (an unrepeatable session with overrides is legitimately done),
    # but the UI makes them confirm explicitly.
    ready = (
        not missing
        and not q_missing
        and recording["ok"]
        and session.state in ("stopped", "completed")
    )

    return {
        "session_id": sid,
        "state": session.state,
        "self_reports": {
            "expected": len(expected),
            "collected": counts["collected"],
            "overridden": counts["overridden"],
            "open": counts["open"],
            "not_fired": counts["not_fired"],
            "rows": sr_rows,
            "missing": missing,
            "gates_open": gates_open,
            "detail": detail,
        },
        "questionnaires": {"pre": pre, "post": post, "missing": q_missing},
        "trials": {"count": trials},
        "recording": recording,
        "warnings": warnings,
        "ready": ready,
    }
