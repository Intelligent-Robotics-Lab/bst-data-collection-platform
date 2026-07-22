"""Expanded post-trial/pre-feedback rehearsal self-report.

The 6 rehearsal (post_kid_response) slots collect a child-behavior checklist plus
TWO PAD+emotion sets, persisted as two rows: referent 'child_behavior' (how the
child's behavior made the participant feel, carrying the checklist) and
'self_handling' (how they felt about how they handled it). Baseline and
post-feedback slots keep the single 'overall' form (see test_self_reports.py).
"""

import csv
import json
from pathlib import Path

import pytest

from app.core.config import settings
from app.models.signals import ParticipantSelfReport


def _running(client, pid="RH1", sid="RH1_S1"):
    client.post("/participants", json={"participant_id": pid})
    client.post(
        "/sessions",
        json={"session_id": sid, "participant_id": pid, "scenario_type": "bst_dtt"},
    )
    client.post(f"/sessions/{sid}/start")
    return sid


def _ctx(**over):
    p = {
        "loop_index": 2,
        "phase": "rehearsal",
        "timepoint": "post",
        "function_class": "NR",
        "before_after_robot_action": "after",
    }
    p.update(over)
    return p


def _body(**over):
    b = {
        **_ctx(),
        "child_behaviors": ["vocalization", "disruption"],
        "child_behavior_affect": {"pleasure": -3, "arousal": 2, "dominance": -1, "emotion_category": "fear"},
        "self_handling_affect": {"pleasure": 1, "arousal": 0, "dominance": 2, "emotion_category": "happy"},
    }
    b.update(over)
    return b


def _url(sid):
    return f"/sessions/{sid}/self-reports/rehearsal"


# --- the two-row write -------------------------------------------------------

def test_writes_two_rows_with_referents_affect_and_checklist(client):
    sid = _running(client)
    r = client.post(_url(sid), json=_body())
    assert r.status_code == 201, r.text
    rows = r.json()
    assert isinstance(rows, list) and len(rows) == 2

    by_ref = {row["referent"]: row for row in rows}
    assert set(by_ref) == {"child_behavior", "self_handling"}

    child = by_ref["child_behavior"]
    assert (child["pleasure"], child["arousal"], child["dominance"]) == (-3, 2, -1)
    assert child["emotion_category"] == "fear"
    # the checklist attaches to the child_behavior row only
    assert child["child_behaviors"] == ["vocalization", "disruption"]

    handling = by_ref["self_handling"]
    assert (handling["pleasure"], handling["arousal"], handling["dominance"]) == (1, 0, 2)
    assert handling["emotion_category"] == "happy"
    assert handling["child_behaviors"] is None

    # both share the same slot context
    for row in rows:
        assert row["loop_index"] == 2 and row["phase"] == "rehearsal"
        assert row["function_class"] == "NR" and row["source"] == "sr"

    # exactly two rows land in the table (listed in insertion order)
    listed = client.get(f"/sessions/{sid}/self-reports").json()
    assert [x["referent"] for x in listed] == ["child_behavior", "self_handling"]


def test_raw_json_and_timeline_tag_both_rows(client, _session_factory):
    sid = _running(client)
    assert client.post(_url(sid), json=_body()).status_code == 201

    db = _session_factory()
    try:
        rows = db.query(ParticipantSelfReport).order_by(ParticipantSelfReport.self_report_id).all()
        metas = {row.referent: json.loads(row.raw_json) for row in rows}
    finally:
        db.close()
    for ref in ("child_behavior", "self_handling"):
        assert metas[ref]["instrument"] == "SAM-9"
        assert metas[ref]["referent"] == ref
    assert metas["child_behavior"]["child_behaviors"] == ["vocalization", "disruption"]
    assert metas["self_handling"]["child_behaviors"] is None

    tl = client.get(f"/sessions/{sid}/timeline", params={"format": "json"}).json()
    submits = [e for e in tl if e["type"] == "self_report_submitted"]
    refs = {e["payload"]["referent"] for e in submits}
    assert {"child_behavior", "self_handling"} <= refs
    child_ev = next(e for e in submits if e["payload"]["referent"] == "child_behavior")
    assert child_ev["payload"]["child_behaviors"] == ["vocalization", "disruption"]


# --- checklist validation ----------------------------------------------------

def test_none_is_exclusive(client):
    sid = _running(client)
    r = client.post(_url(sid), json=_body(child_behaviors=["none", "vocalization"]))
    assert r.status_code == 422


def test_none_alone_is_ok(client):
    sid = _running(client)
    r = client.post(_url(sid), json=_body(child_behaviors=["none"]))
    assert r.status_code == 201, r.text
    child = next(x for x in r.json() if x["referent"] == "child_behavior")
    assert child["child_behaviors"] == ["none"]


def test_empty_checklist_is_422(client):
    sid = _running(client)
    assert client.post(_url(sid), json=_body(child_behaviors=[])).status_code == 422


def test_bad_behavior_value_is_422(client):
    sid = _running(client)
    assert client.post(_url(sid), json=_body(child_behaviors=["screaming"])).status_code == 422


def test_duplicate_behaviors_are_deduped(client):
    sid = _running(client)
    r = client.post(_url(sid), json=_body(child_behaviors=["vocalization", "vocalization", "disruption"]))
    assert r.status_code == 201, r.text
    child = next(x for x in r.json() if x["referent"] == "child_behavior")
    assert child["child_behaviors"] == ["vocalization", "disruption"]


# --- PAD/emotion validation on both sets -------------------------------------

def test_missing_second_set_is_422(client):
    sid = _running(client)
    body = _body()
    del body["self_handling_affect"]
    assert client.post(_url(sid), json=body).status_code == 422


def test_partial_affect_set_is_422(client):
    sid = _running(client)
    body = _body()
    del body["child_behavior_affect"]["dominance"]
    assert client.post(_url(sid), json=body).status_code == 422


def test_bad_emotion_in_a_set_is_422(client):
    sid = _running(client)
    body = _body()
    body["self_handling_affect"]["emotion_category"] = "ecstatic"
    assert client.post(_url(sid), json=body).status_code == 422


def test_out_of_range_pad_is_422(client):
    sid = _running(client)
    body = _body()
    body["child_behavior_affect"]["pleasure"] = 5
    assert client.post(_url(sid), json=body).status_code == 422


def test_phase_must_be_rehearsal(client):
    sid = _running(client)
    # a valid Phase enum, but not the rehearsal slot -> guarded 422 (not a 500)
    r = client.post(_url(sid), json=_body(**{"phase": "feedback"}))
    assert r.status_code == 422
    assert "rehearsal" in r.json()["detail"]


def test_unknown_session_is_404(client):
    assert client.post(_url("NOPE"), json=_body()).status_code == 404


# --- autosave draft (both sets + checklist round-trip) -----------------------

def _draft_params(ctx):
    keys = ("loop_index", "phase", "timepoint", "function_class",
            "is_problem", "sequence_position", "before_after_robot_action", "trial_id")
    return {k: ctx[k] for k in keys if k in ctx and ctx[k] is not None}


def test_autosave_restores_both_sets_and_checklist(client):
    sid = _running(client)
    ctx = _ctx()
    r = client.post(
        f"/sessions/{sid}/self-reports/autosave",
        json={
            **ctx,
            "child_behaviors": ["noncompliance"],
            "pleasure": -2, "arousal": 3, "emotion_category": "sad",
            "handling_pleasure": 4, "handling_dominance": -1,
            "handling_emotion_category": "contempt",
        },
    )
    assert r.status_code == 200, r.text

    got = client.get(f"/sessions/{sid}/self-reports/draft", params=_draft_params(ctx)).json()
    assert got["found"] is True
    # set A (child behavior)
    assert got["sliders"] == {"pleasure": -2, "arousal": 3, "dominance": None}
    assert got["emotion_category"] == "sad"
    # set B (self handling)
    assert got["handling_sliders"] == {"pleasure": 4, "arousal": None, "dominance": -1}
    assert got["handling_emotion_category"] == "contempt"
    # checklist
    assert got["child_behaviors"] == ["noncompliance"]


def test_submit_deletes_the_rehearsal_draft(client):
    sid = _running(client)
    ctx = _ctx()
    client.post(f"/sessions/{sid}/self-reports/autosave",
                json={**ctx, "pleasure": 1, "child_behaviors": ["disruption"]})
    assert client.get(f"/sessions/{sid}/self-reports/draft", params=_draft_params(ctx)).json()["found"] is True

    assert client.post(_url(sid), json=_body()).status_code == 201
    assert client.get(f"/sessions/{sid}/self-reports/draft", params=_draft_params(ctx)).json()["found"] is False


# --- export ------------------------------------------------------------------

@pytest.fixture
def exports_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "EXPORTS_DIR", tmp_path)
    return tmp_path


def test_export_carries_referent_and_child_behaviors(client, exports_tmp):
    sid = _running(client)
    assert client.post(_url(sid), json=_body()).status_code == 201

    out = Path(client.post(f"/sessions/{sid}/export").json()["export_dir"])
    rows = list(csv.DictReader((out / "analysis_self_reports.csv").open(newline="")))
    by_ref = {r["referent"]: r for r in rows}
    assert set(by_ref) == {"child_behavior", "self_handling"}
    # child_behaviors is emitted as its JSON list string on the child row, empty on the other
    assert json.loads(by_ref["child_behavior"]["child_behaviors"]) == ["vocalization", "disruption"]
    assert by_ref["self_handling"]["child_behaviors"] in ("", None)
