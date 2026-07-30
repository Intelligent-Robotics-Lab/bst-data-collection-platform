"""Attention-check logging tests.

The 12 instructional-stage comprehension questions (5 instruction + 7 modeling)
come from configs/attention_checks.yaml. The platform computes is_correct from
the answer + the config (option number, accepted spoken forms, or 'option N'),
upserts one row per (session, question), writes a timeline event, and exports it.
"""

import csv
from pathlib import Path

import pytest

from app.core.config import settings
from app.models.attention_check import AttentionCheckResponse


def _session(client, pid="AC1", sid="AC1_S1"):
    client.post("/participants", json={"participant_id": pid})
    client.post("/sessions", json={"session_id": sid, "participant_id": pid, "scenario_type": "bst_dtt"})
    return sid


def _log(client, sid, **body):
    return client.post(f"/sessions/{sid}/attention-checks", json=body)


# --- the question catalogue --------------------------------------------------

def test_questions_endpoint_lists_all_twelve(client):
    qs = client.get("/attention-checks/questions").json()
    assert len(qs) == 12
    by_phase = {}
    for q in qs:
        by_phase.setdefault(q["phase"], []).append(q)
    assert len(by_phase["instruction"]) == 5
    assert len(by_phase["modeling"]) == 7
    q1 = next(q for q in qs if q["question_id"] == "instruction_1")
    assert q1["text"] == "What are we learning about today?"
    assert q1["correct_answer"] == "1" and len(q1["choices"]) == 3


def test_questions_endpoint_filters_by_phase(client):
    assert len(client.get("/attention-checks/questions", params={"phase": "modeling"}).json()) == 7
    assert len(client.get("/attention-checks/questions", params={"phase": "instruction"}).json()) == 5
    # tutorial has none
    assert client.get("/attention-checks/questions", params={"phase": "tutorial"}).json() == []


# --- logging + correctness ---------------------------------------------------

def test_log_correct_option_number(client):
    sid = _session(client)
    r = _log(client, sid, question_id="instruction_1", participant_answer="1")
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["is_correct"] is True
    assert b["phase"] == "instruction"
    assert b["question_text"] == "What are we learning about today?"
    assert b["correct_answer"] == "1"
    assert b["source"] == "auto"  # default


def test_log_incorrect_option(client):
    sid = _session(client)
    b = _log(client, sid, question_id="instruction_1", participant_answer="2").json()
    assert b["is_correct"] is False


def test_correct_via_accepted_spoken_answer(client):
    sid = _session(client)
    # instruction_1 accepts 'structured'/'teaching' etc. as correct
    assert _log(client, sid, question_id="instruction_1", participant_answer="Structured").json()["is_correct"] is True
    # modeling_2 correct is option 3 ('identify'/'preferred')
    assert _log(client, sid, question_id="modeling_2", participant_answer="preferred").json()["is_correct"] is True


def test_correct_via_option_n_phrasing(client):
    sid = _session(client)
    assert _log(client, sid, question_id="instruction_2", participant_answer="Option 3").json()["is_correct"] is True
    assert _log(client, sid, question_id="instruction_2", participant_answer="3.").json()["is_correct"] is True


def test_unknown_question_id_is_422(client):
    sid = _session(client)
    assert _log(client, sid, question_id="nope_99", participant_answer="1").status_code == 422


def test_upsert_one_row_per_question(client, _session_factory):
    sid = _session(client)
    _log(client, sid, question_id="modeling_1", participant_answer="1")           # wrong (correct is 2)
    r = _log(client, sid, question_id="modeling_1", participant_answer="2", source="manual", operator="admin")
    assert r.json()["is_correct"] is True and r.json()["source"] == "manual" and r.json()["operator"] == "admin"
    # still exactly one row for that question
    listed = client.get(f"/sessions/{sid}/attention-checks").json()
    assert [x["question_id"] for x in listed] == ["modeling_1"]
    db = _session_factory()
    try:
        assert db.query(AttentionCheckResponse).count() == 1
    finally:
        db.close()


def test_list_and_timeline(client):
    sid = _session(client)
    _log(client, sid, question_id="instruction_1", participant_answer="1")
    _log(client, sid, question_id="modeling_7", participant_answer="3")
    listed = client.get(f"/sessions/{sid}/attention-checks").json()
    assert {x["question_id"] for x in listed} == {"instruction_1", "modeling_7"}
    tl = client.get(f"/sessions/{sid}/timeline", params={"format": "json"}).json()
    logged = [e for e in tl if e["type"] == "attention_check_logged"]
    assert any(e["payload"]["question_id"] == "instruction_1" and e["payload"]["is_correct"] is True for e in logged)


def test_unknown_session_is_404(client):
    assert _log(client, "NOPE", question_id="instruction_1", participant_answer="1").status_code == 404


# --- export ------------------------------------------------------------------

@pytest.fixture
def exports_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "EXPORTS_DIR", tmp_path)
    return tmp_path


def test_export_includes_attention_checks(client, exports_tmp):
    sid = _session(client)
    _log(client, sid, question_id="instruction_1", participant_answer="1")           # correct
    _log(client, sid, question_id="modeling_1", participant_answer="1")               # incorrect (correct is 2)

    out = Path(client.post(f"/sessions/{sid}/export").json()["export_dir"])
    # raw dump
    raw = list(csv.DictReader((out / "attention_check_responses.csv").open(newline="")))
    assert {r["question_id"] for r in raw} == {"instruction_1", "modeling_1"}
    by = {r["question_id"]: r for r in raw}
    assert by["instruction_1"]["is_correct"] == "1"
    assert by["modeling_1"]["is_correct"] == "0"
    # analysis frame carries session factors
    ana = list(csv.DictReader((out / "analysis_attention_checks.csv").open(newline="")))
    assert len(ana) == 2
    assert "session__pb_order_group" in ana[0] and "derived__support_label" in ana[0]
