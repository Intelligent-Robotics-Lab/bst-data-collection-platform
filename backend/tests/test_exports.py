"""Session export tests (Phase 6, P0.11).

Validates the raw per-table dumps (fidelity layer), the joined analysis frames
(convenience layer, 2x3-ready), the generated data dictionary, and that exports
are READ-only (source rows untouched; re-export never overwrites).

Frames are validated with the stdlib csv/json readers (no pandas dependency in
the app); an analyst loads the same CSVs in pandas.
"""

import csv
import json
from pathlib import Path

import pytest

from app.core.config import settings
from app.models.questionnaire import QuestionnaireResponse
from app.models.signals import (
    MediaRecording,
    ParticipantSelfReport,
    PerceptionEvent,
)


@pytest.fixture
def exports_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "EXPORTS_DIR", tmp_path)
    return tmp_path


def _read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _build_session(client, factory, protocol_id, group=1, sid="EXP_S1", pid="EXPP"):
    """A realistic session: started (loops generated), one trial on the even
    loop 2 (a challenge loop), plus a self-report, perception event, recording,
    and questionnaire response inserted directly."""
    client.post("/participants", json={"participant_id": pid})
    client.post(
        "/sessions",
        json={
            "session_id": sid,
            "participant_id": pid,
            "scenario_type": "bst_dtt",
            "protocol_id": protocol_id,
            "support_condition": 1,
            "pb_order_group": group,
        },
    )
    client.post(f"/sessions/{sid}/start")
    client.post(
        f"/sessions/{sid}/trials",
        json={
            "loop_index": 2,
            "sd_id": "sd_2",
            "phase_key": "rehearsal",
            "target_skill": "reception",
            "response_correctness": "correct",
            "reinforcement_delivered": True,
            "error_correction_delivered": False,
        },
    )

    db = factory()
    try:
        db.add(
            ParticipantSelfReport(
                session_id=sid,
                participant_id=pid,
                loop_index=2,
                phase="rehearsal",
                timepoint="pre",
                function_class="NR",
                is_problem="1",
                source="sr",
                before_after_robot_action="before",
                pleasure=2,
                arousal=-2,
                timestamp_utc="2026-06-29T00:00:01Z",
                session_time_ms=1000,
            )
        )
        db.add(
            PerceptionEvent(
                session_id=sid,
                participant_id=pid,
                task="emotion",
                source="ml",
                backend_name="hsemotion",
                received_timestamp_utc="2026-06-29T00:00:02Z",
                session_time_ms=2000,
                detected_label="happy",
                confidence=0.91,
                valence=0.4,
                arousal=0.2,
                connection_status="ok",
                raw_payload=json.dumps({"label": "happy", "scores": [0.91, 0.09]}),
            )
        )
        db.add(
            MediaRecording(
                session_id=sid,
                participant_id=pid,
                file_path=f"/data/recordings/{sid}.mp4",
                file_name=f"{sid}.mp4",
                status="completed",
                codec="h264_nvenc",
                container="mp4",
                resolution="1920x1080",
                fps=30,  # REQUESTED; actual may differ
            )
        )
        db.add(
            QuestionnaireResponse(
                session_id=sid,
                participant_id=pid,
                questionnaire_key="erq",
                questionnaire_version="1.0",
                item_id="erq_1",
                response_numeric=5,
                timepoint="pre",
            )
        )
        db.commit()
    finally:
        db.close()
    return sid, pid


def test_export_writes_all_files(client, _session_factory, protocol_id, exports_tmp):
    sid, _ = _build_session(client, _session_factory, protocol_id)
    r = client.post(f"/sessions/{sid}/export")
    assert r.status_code == 201, r.text
    body = r.json()

    expected = {
        "participants.csv",
        "sessions.csv",
        "dtt_loops.csv",
        "dtt_trials.csv",
        "questionnaire_responses.csv",
        "questionnaire_scores.csv",
        "self_reports.csv",
        "media_recordings.csv",
        "perception_events.jsonl",
        "session_timeline.jsonl",
        "analysis_trials.csv",
        "analysis_self_reports.csv",
        "DATA_DICTIONARY.md",
        "session_summary.json",
    }
    assert expected.issubset(set(body["files"]))

    out = Path(body["export_dir"])
    for name in expected:
        assert (out / name).exists(), f"missing {name}"


def test_raw_dumps_are_faithful(client, _session_factory, protocol_id, exports_tmp):
    sid, pid = _build_session(client, _session_factory, protocol_id, group=1)
    out = Path(client.post(f"/sessions/{sid}/export").json()["export_dir"])

    participants = _read_csv(out / "participants.csv")
    assert [p["participant_id"] for p in participants] == [pid]

    sessions = _read_csv(out / "sessions.csv")
    assert len(sessions) == 1
    assert sessions[0]["support_condition"] == "1"
    assert sessions[0]["pb_order_group"] == "1"

    loops = _read_csv(out / "dtt_loops.csv")
    assert len(loops) == 6
    by_idx = {int(lp["loop_index"]): lp for lp in loops}
    assert by_idx[1]["function_class"] == "baseline"
    assert by_idx[2]["function_class"] == "NR"  # group 1, even loop 2
    assert by_idx[2]["sd_id"] == "sd_2"

    perception = _read_jsonl(out / "perception_events.jsonl")
    assert len(perception) == 1
    # raw_payload round-trips to nested JSON, not a string
    assert perception[0]["raw_payload"]["label"] == "happy"

    timeline = _read_jsonl(out / "session_timeline.jsonl")
    assert any(e["type"] == "dtt_loops_generated" for e in timeline)


def test_analysis_trials_frame_is_2x3_ready(client, _session_factory, protocol_id, exports_tmp):
    # group 1: loop 2 = Receptive Instruction (NR)
    sid, _ = _build_session(client, _session_factory, protocol_id, group=1)
    out = Path(client.post(f"/sessions/{sid}/export").json()["export_dir"])

    rows = _read_csv(out / "analysis_trials.csv")
    assert len(rows) == 1
    row = rows[0]
    # raw columns present
    assert row["loop_index"] == "2"
    assert row["sd_id"] == "sd_2"
    # derived-via-join
    assert row["loop__function_class"] == "NR"
    assert row["loop__sd_id"] == "sd_2"
    assert row["session__support_condition"] == "1"
    assert row["session__pb_order_group"] == "1"
    # computed
    assert row["derived__support_label"] == "supportive"
    assert row["derived__named_sd"] == "Receptive Instruction"


def test_named_sd_differs_by_order_group(client, _session_factory, protocol_id, exports_tmp):
    # Same positional sd_2 resolves to a different named SD / function across groups.
    sid3, _ = _build_session(client, _session_factory, protocol_id, group=3, sid="EXP_S3", pid="EXPP3")
    out3 = Path(client.post(f"/sessions/{sid3}/export").json()["export_dir"])
    row = _read_csv(out3 / "analysis_trials.csv")[0]
    assert row["loop__function_class"] == "PR"  # group 3, loop 2
    assert row["derived__named_sd"] == "Tacting and Labeling"


def test_analysis_self_reports_carry_context(client, _session_factory, protocol_id, exports_tmp):
    sid, _ = _build_session(client, _session_factory, protocol_id, group=1)
    out = Path(client.post(f"/sessions/{sid}/export").json()["export_dir"])
    rows = _read_csv(out / "analysis_self_reports.csv")
    assert len(rows) == 1
    row = rows[0]
    assert row["timepoint"] == "pre"
    assert row["before_after_robot_action"] == "before"
    assert row["session__support_condition"] == "1"
    assert row["loop__function_class"] == "NR"
    assert row["derived__support_label"] == "supportive"
    assert row["derived__named_sd"] == "Receptive Instruction"


def test_data_dictionary_documents_load_bearing_decisions(
    client, _session_factory, protocol_id, exports_tmp
):
    sid, _ = _build_session(client, _session_factory, protocol_id)
    out = Path(client.post(f"/sessions/{sid}/export").json()["export_dir"])
    text = (out / "DATA_DICTIONARY.md").read_text(encoding="utf-8")

    assert "1 = supportive" in text and "0 = neutral" in text
    assert "Positive" in text and "Negative" in text and "Automatic" in text
    assert "POSITIONAL" in text
    assert "single" in text.lower() and "hierarchy" in text.lower()
    assert "per-trial event" in text
    assert "REQUESTED" in text
    # the resolution table shows sd_2 differs across groups
    assert "Receptive Instruction (NR)" in text
    assert "Tacting and Labeling (PR)" in text


def test_session_summary_has_counts_and_label(client, _session_factory, protocol_id, exports_tmp):
    sid, _ = _build_session(client, _session_factory, protocol_id)
    out = Path(client.post(f"/sessions/{sid}/export").json()["export_dir"])
    summary = json.loads((out / "session_summary.json").read_text(encoding="utf-8"))
    assert summary["support_label"] == "supportive"
    assert summary["row_counts"]["dtt_loops"] == 6
    assert summary["row_counts"]["dtt_trials"] == 1
    assert summary["row_counts"]["perception_events"] == 1


def test_export_is_read_only_and_reexport_does_not_overwrite(
    client, _session_factory, protocol_id, exports_tmp
):
    sid, _ = _build_session(client, _session_factory, protocol_id)

    # capture source row counts before export
    before_loops = _loop_count(_session_factory, sid)
    before_trials = _trial_count(_session_factory, sid)

    first = client.post(f"/sessions/{sid}/export").json()
    second = client.post(f"/sessions/{sid}/export").json()

    # source rows untouched
    assert _loop_count(_session_factory, sid) == before_loops == 6
    assert _trial_count(_session_factory, sid) == before_trials == 1

    # distinct export dirs; both on disk
    assert first["export_dir"] != second["export_dir"]
    assert Path(first["export_dir"]).exists()
    assert Path(second["export_dir"]).exists()

    # two provenance rows recorded
    listing = client.get(f"/sessions/{sid}/export").json()
    assert len(listing) == 2
    assert {e["status"] for e in listing} == {"completed"}


# --- small DB count helpers (read-only) -------------------------------------

def _loop_count(factory, sid):
    from app.models.dtt import DttLoop

    db = factory()
    try:
        return db.query(DttLoop).filter(DttLoop.session_id == sid).count()
    finally:
        db.close()


def _trial_count(factory, sid):
    from app.models.dtt import DttTrial

    db = factory()
    try:
        return db.query(DttTrial).filter(DttTrial.session_id == sid).count()
    finally:
        db.close()
