"""Session export service (Phase 6, P0.11).

Two layers, both written to ``EXPORTS_DIR/<session_id>/export_<ts>/``:

Part A - raw per-table dumps (fidelity layer). One file per table/concept,
faithful to the source rows: column names and order come straight from the
model, values are emitted verbatim (no transformation). This is the source of
truth. CSV for tabular rows; JSONL for the JSON-bearing streams (perception
events, timeline) where embedded payloads round-trip losslessly to nested JSON.

Part B - joined analysis-ready frames (convenience layer). Derived ENTIRELY from
the raw rows by joining, so a row can be analyzed under the 2 (support) x 3
(function) design without manual joins. Columns native to the base row keep
their name (raw); columns pulled in via join are prefixed with their source
table (``loop__``, ``session__``); computed columns are prefixed ``derived__``.

Raw-data immutability (CLAUDE.md): this service only READS source tables. The
sole write is one provenance row in ``exports`` (the export registry, not a
research table) plus files under EXPORTS_DIR.
"""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.timeutil import now_utc
from app.models.dtt import DttLoop, DttTrial
from app.models.fidelity import FidelityScore
from app.models.participant import Participant
from app.models.questionnaire import QuestionnaireResponse, QuestionnaireScore
from app.models.session import StudySession
from app.models.signals import (
    MediaRecording,
    ParticipantSelfReport,
    PerceptionEvent,
)
from app.models.sync import SyncGate
from app.models.system import Export, SessionTimelineEvent
from app.services.data_dictionary import write_data_dictionary
from app.services.dtt_loops import resolve_named_sd
from app.services.session_service import get_session_or_404
from app.services.timeline import serialize_timeline_event

logger = logging.getLogger("bst.export")


# --- low-level writers -------------------------------------------------------

def _table_columns(model) -> list[str]:
    """Column names in declared order, straight from the model table."""
    return [c.name for c in model.__table__.columns]


def _row_dict(obj, columns: list[str]) -> dict:
    return {c: getattr(obj, c) for c in columns}


def _write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    """Write a CSV with a header even when there are zero rows (so pandas always
    gets a well-formed frame). None -> empty cell."""
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _write_jsonl(path: Path, objects: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for obj in objects:
            fh.write(json.dumps(obj, ensure_ascii=False))
            fh.write("\n")


def _maybe_json(value):
    """Parse a stored JSON string back to an object for JSONL output (lossless
    round-trip). Non-JSON / null stays as-is."""
    if value is None or not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return value


def _support_label(support_condition) -> str | None:
    if support_condition == 1:
        return "supportive"
    if support_condition == 0:
        return "neutral"
    return None


# --- Part A: raw dumps -------------------------------------------------------

def _write_raw_dumps(db: Session, session: StudySession, out: Path) -> tuple[list[str], dict]:
    """Write the faithful per-table dumps. Returns (file names, row counts)."""
    sid = session.session_id
    files: list[str] = []
    counts: dict = {}

    def csv_dump(name: str, model, rows: list) -> None:
        cols = _table_columns(model)
        _write_csv(out / name, cols, [_row_dict(r, cols) for r in rows])
        files.append(name)
        counts[model.__tablename__] = len(rows)

    # participants: the one participant for this session (faithful single row)
    participants = db.scalars(
        select(Participant).where(Participant.participant_id == session.participant_id)
    ).all()
    csv_dump("participants.csv", Participant, participants)

    csv_dump("sessions.csv", StudySession, [session])

    loops = db.scalars(
        select(DttLoop).where(DttLoop.session_id == sid).order_by(DttLoop.loop_index)
    ).all()
    csv_dump("dtt_loops.csv", DttLoop, loops)

    trials = db.scalars(
        select(DttTrial).where(DttTrial.session_id == sid).order_by(DttTrial.trial_number)
    ).all()
    csv_dump("dtt_trials.csv", DttTrial, trials)

    q_responses = db.scalars(
        select(QuestionnaireResponse)
        .where(QuestionnaireResponse.session_id == sid)
        .order_by(QuestionnaireResponse.response_id)
    ).all()
    csv_dump("questionnaire_responses.csv", QuestionnaireResponse, q_responses)

    q_scores = db.scalars(
        select(QuestionnaireScore)
        .where(QuestionnaireScore.session_id == sid)
        .order_by(QuestionnaireScore.score_id)
    ).all()
    csv_dump("questionnaire_scores.csv", QuestionnaireScore, q_scores)

    self_reports = db.scalars(
        select(ParticipantSelfReport)
        .where(ParticipantSelfReport.session_id == sid)
        .order_by(ParticipantSelfReport.self_report_id)
    ).all()
    csv_dump("self_reports.csv", ParticipantSelfReport, self_reports)

    recordings = db.scalars(
        select(MediaRecording)
        .where(MediaRecording.session_id == sid)
        .order_by(MediaRecording.recording_id)
    ).all()
    csv_dump("media_recordings.csv", MediaRecording, recordings)

    # sync gates: the BST<->platform barriers; override rows (closed_by='override')
    # are the skipped-by-override markers, distinguishable here and in the timeline.
    gates = db.scalars(
        select(SyncGate).where(SyncGate.session_id == sid).order_by(SyncGate.gate_id)
    ).all()
    csv_dump("sync_gates.csv", SyncGate, gates)

    # fidelity_scores: human ABA/BST fidelity ratings, one row per scored loop.
    fidelity = db.scalars(
        select(FidelityScore)
        .where(FidelityScore.session_id == sid)
        .order_by(FidelityScore.loop_index)
    ).all()
    csv_dump("fidelity_scores.csv", FidelityScore, fidelity)

    # perception_events: JSONL, raw_payload parsed back to nested JSON
    perception = db.scalars(
        select(PerceptionEvent)
        .where(PerceptionEvent.session_id == sid)
        .order_by(PerceptionEvent.event_id)
    ).all()
    pcols = _table_columns(PerceptionEvent)
    perception_objs = []
    for ev in perception:
        d = _row_dict(ev, pcols)
        d["raw_payload"] = _maybe_json(d.get("raw_payload"))
        perception_objs.append(d)
    _write_jsonl(out / "perception_events.jsonl", perception_objs)
    files.append("perception_events.jsonl")
    counts["perception_events"] = len(perception)

    # timeline: JSONL spine, payload parsed (serialize_timeline_event)
    timeline = db.scalars(
        select(SessionTimelineEvent)
        .where(SessionTimelineEvent.session_id == sid)
        .order_by(SessionTimelineEvent.event_id)
    ).all()
    _write_jsonl(out / "session_timeline.jsonl", [serialize_timeline_event(e) for e in timeline])
    files.append("session_timeline.jsonl")
    counts["session_timeline_events"] = len(timeline)

    return files, counts


# --- Part B: joined analysis frames -----------------------------------------

# Column order for the trial analysis frame. Raw trial columns first, then
# columns derived via join, then computed columns. Documented in the data dict.
_ANALYSIS_TRIAL_RAW = [
    "trial_id",
    "session_id",
    "participant_id",
    "trial_number",
    "loop_index",
    "protocol_id",
    "phase_key",
    "sd_id",
    "target_skill",
    "instruction",
    "response_correctness",
    "prompt_level",
    "reinforcement_delivered",
    "error_correction_delivered",
    "deviation_flag",
    "response_latency_ms",
    "timestamp_utc",
    "session_time_ms",
]
_ANALYSIS_TRIAL_JOINED = [
    "loop__function_class",
    "loop__sd_id",
    "loop__is_problem",
    "loop__sequence_position",
    "session__support_condition",
    "session__pb_order_group",
    "session__scenario_type",
]
_ANALYSIS_TRIAL_DERIVED = [
    "derived__support_label",
    "derived__named_sd",
]

_ANALYSIS_SR_RAW = [
    "self_report_id",
    "session_id",
    "participant_id",
    "trial_id",
    "loop_index",
    "sequence_position",
    "phase",
    "timepoint",
    "function_class",
    "is_problem",
    "before_after_robot_action",
    "source",
    "pleasure",
    "arousal",
    "dominance",
    "confidence",
    "frustration",
    "engagement",
    "perceived_challenge",
    "perceived_support",
    "cognitive_load",
    "timestamp_utc",
    "session_time_ms",
]
_ANALYSIS_SR_JOINED = [
    "loop__function_class",
    "loop__sd_id",
    "session__support_condition",
    "session__pb_order_group",
]
_ANALYSIS_SR_DERIVED = [
    "derived__support_label",
    "derived__named_sd",
]


def _write_analysis_frames(db: Session, session: StudySession, out: Path) -> list[str]:
    sid = session.session_id
    support = session.support_condition
    group = session.pb_order_group
    support_label = _support_label(support)

    loops_by_index = {
        lp.loop_index: lp
        for lp in db.scalars(select(DttLoop).where(DttLoop.session_id == sid)).all()
    }

    # analysis_trials: each trial + its loop + its session factors
    trials = db.scalars(
        select(DttTrial).where(DttTrial.session_id == sid).order_by(DttTrial.trial_number)
    ).all()
    trial_rows = []
    for t in trials:
        loop = loops_by_index.get(t.loop_index)
        row = {c: getattr(t, c) for c in _ANALYSIS_TRIAL_RAW}
        row.update(
            {
                "loop__function_class": loop.function_class if loop else None,
                "loop__sd_id": loop.sd_id if loop else None,
                "loop__is_problem": loop.is_problem if loop else None,
                "loop__sequence_position": loop.sequence_position if loop else None,
                "session__support_condition": support,
                "session__pb_order_group": group,
                "session__scenario_type": session.scenario_type,
                "derived__support_label": support_label,
                "derived__named_sd": resolve_named_sd(group, t.loop_index),
            }
        )
        trial_rows.append(row)
    _write_csv(
        out / "analysis_trials.csv",
        _ANALYSIS_TRIAL_RAW + _ANALYSIS_TRIAL_JOINED + _ANALYSIS_TRIAL_DERIVED,
        trial_rows,
    )

    # analysis_self_reports: each self-report + session/loop/phase context
    reports = db.scalars(
        select(ParticipantSelfReport)
        .where(ParticipantSelfReport.session_id == sid)
        .order_by(ParticipantSelfReport.self_report_id)
    ).all()
    sr_rows = []
    for r in reports:
        loop = loops_by_index.get(r.loop_index)
        row = {c: getattr(r, c) for c in _ANALYSIS_SR_RAW}
        row.update(
            {
                "loop__function_class": loop.function_class if loop else None,
                "loop__sd_id": loop.sd_id if loop else None,
                "session__support_condition": support,
                "session__pb_order_group": group,
                "derived__support_label": support_label,
                "derived__named_sd": resolve_named_sd(group, r.loop_index),
            }
        )
        sr_rows.append(row)
    _write_csv(
        out / "analysis_self_reports.csv",
        _ANALYSIS_SR_RAW + _ANALYSIS_SR_JOINED + _ANALYSIS_SR_DERIVED,
        sr_rows,
    )

    return ["analysis_trials.csv", "analysis_self_reports.csv"]


# --- orchestration -----------------------------------------------------------

def export_session(db: Session, session_id: str, exports_dir: Path | None = None) -> dict:
    """Export one session's raw dumps + analysis frames + data dictionary.

    Returns a manifest dict (also persisted as session_summary.json and recorded
    in the ``exports`` table). READ-only against all source tables.
    """
    session = get_session_or_404(db, session_id)

    base = exports_dir or settings.exports_dir
    ts = now_utc().strftime("%Y%m%dT%H%M%S_%fZ")
    out = base / session_id / f"export_{ts}"
    out.mkdir(parents=True, exist_ok=True)

    raw_files, counts = _write_raw_dumps(db, session, out)
    analysis_files = _write_analysis_frames(db, session, out)
    write_data_dictionary(out / "DATA_DICTIONARY.md")

    files = raw_files + analysis_files + ["DATA_DICTIONARY.md", "session_summary.json"]

    exported_at = now_utc().isoformat()
    summary = {
        "session_id": session.session_id,
        "participant_id": session.participant_id,
        "scenario_type": session.scenario_type,
        "support_condition": session.support_condition,
        "support_label": _support_label(session.support_condition),
        "pb_order_group": session.pb_order_group,
        "protocol_id": session.protocol_id,
        "state": session.state,
        "start_timestamp_utc": session.start_timestamp_utc,
        "stop_timestamp_utc": session.stop_timestamp_utc,
        "completed_at": session.completed_at,
        "platform_version": session.platform_version or settings.PLATFORM_VERSION,
        "exported_at_utc": exported_at,
        "export_dir": str(out),
        "row_counts": counts,
        "files": files,
    }
    (out / "session_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Provenance row (export registry; not a research table).
    export_row = Export(
        session_id=session.session_id,
        scope="session",
        export_dir=str(out),
        files_json=json.dumps(files),
        status="completed",
        platform_version=settings.PLATFORM_VERSION,
        completed_at=exported_at,
    )
    db.add(export_row)
    db.commit()
    db.refresh(export_row)

    logger.info("exported session %s -> %s (%d files)", session_id, out, len(files))
    return {
        "export_id": export_row.export_id,
        "session_id": session.session_id,
        "scope": "session",
        "export_dir": str(out),
        "status": "completed",
        "files": files,
        "row_counts": counts,
        "completed_at": exported_at,
    }
