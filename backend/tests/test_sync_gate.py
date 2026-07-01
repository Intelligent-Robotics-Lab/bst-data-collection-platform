"""BST<->platform sync gate tests (Phase 7, P0.13).

Exercises the gate state machine over the API (no operator UI yet): register,
the three openers (stage_complete / kid_response_complete / feedback_delivered), go_ahead
polling, close-by-self-report, operator override (+ exported marker), keying
independence, idempotency, and validation.
"""

import csv
import json
from pathlib import Path

import pytest

from app.core.config import settings


@pytest.fixture
def exports_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "EXPORTS_DIR", tmp_path)
    return tmp_path


def _session(client, protocol_id, sid="SY_S1", pid="SYP", group=1, support=1):
    client.post("/participants", json={"participant_id": pid})
    client.post(
        "/sessions",
        json={
            "session_id": sid,
            "participant_id": pid,
            "scenario_type": "bst_dtt",
            "protocol_id": protocol_id,
            "support_condition": support,
            "pb_order_group": group,
        },
    )
    client.post(f"/sessions/{sid}/start")
    return sid


def _go(client, sid, **params):
    return client.get(f"/sessions/{sid}/sync/go-ahead", params=params).json()


def _assignment(client):
    return client.get("/tablet/assignment").json()


# --- register ----------------------------------------------------------------

def test_register_returns_between_subject_mapping(client, protocol_id):
    sid = _session(client, protocol_id, group=2, support=0)
    r = client.post(f"/sessions/{sid}/sync/register")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pb_order_group"] == 2
    assert body["support_condition"] == 0
    assert body["support_label"] == "neutral"


# --- stage (baseline) gate ---------------------------------------------------

def test_stage_gate_blocks_until_baseline_self_report(client, protocol_id):
    sid = _session(client, protocol_id)
    # opens on stage_complete
    g = client.post(f"/sessions/{sid}/sync/stage-complete", json={"stage": "tutorial"})
    assert g.status_code == 201, g.text
    assert g.json()["gate_key"] == "stage:tutorial:baseline"
    assert g.json()["status"] == "open"

    # gate open -> proceed false
    res = _go(client, sid, scope="stage", stage="tutorial", checkpoint="baseline")
    assert res == {"proceed": False, "gate_found": True, "gate": res["gate"]}
    assert res["gate"]["status"] == "open"

    # baseline self-report (no loop_index) closes it
    r = client.post(
        f"/sessions/{sid}/self-reports",
        json={"phase": "tutorial", "timepoint": "post", "function_class": "baseline"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["loop_index"] is None  # baseline report has no loop

    res = _go(client, sid, scope="stage", stage="tutorial", checkpoint="baseline")
    assert res["proceed"] is True
    assert res["gate"]["status"] == "closed"
    assert res["gate"]["closed_by"] == "self_report"


# --- loop gates --------------------------------------------------------------

def test_loop_gates_post_kid_response_and_post_feedback(client, protocol_id):
    sid = _session(client, protocol_id, group=1)  # loop 2 = NR

    # post_kid_response opens (child has behaved, before feedback); a rehearsal self-report on loop 2 releases it
    client.post(f"/sessions/{sid}/sync/kid-response-complete", json={"loop_index": 2})
    assert _go(client, sid, scope="loop", loop_index=2, checkpoint="post_kid_response")["proceed"] is False
    client.post(
        f"/sessions/{sid}/self-reports",
        json={"loop_index": 2, "phase": "rehearsal", "timepoint": "pre", "function_class": "NR"},
    )
    assert _go(client, sid, scope="loop", loop_index=2, checkpoint="post_kid_response")["proceed"] is True

    # post_feedback is an independent gate: still open until its feedback report
    client.post(f"/sessions/{sid}/sync/feedback-delivered", json={"loop_index": 2})
    assert _go(client, sid, scope="loop", loop_index=2, checkpoint="post_feedback")["proceed"] is False
    client.post(
        f"/sessions/{sid}/self-reports",
        json={"loop_index": 2, "phase": "feedback", "timepoint": "post", "function_class": "NR"},
    )
    assert _go(client, sid, scope="loop", loop_index=2, checkpoint="post_feedback")["proceed"] is True


def test_keying_is_independent_across_loops_and_checkpoints(client, protocol_id):
    sid = _session(client, protocol_id)
    client.post(f"/sessions/{sid}/sync/kid-response-complete", json={"loop_index": 2})
    client.post(f"/sessions/{sid}/sync/kid-response-complete", json={"loop_index": 4})
    # close loop 2 post_kid_response only
    client.post(
        f"/sessions/{sid}/self-reports",
        json={"loop_index": 2, "phase": "rehearsal", "timepoint": "pre", "function_class": "NR"},
    )
    assert _go(client, sid, scope="loop", loop_index=2, checkpoint="post_kid_response")["proceed"] is True
    # loop 4 post_kid_response still blocked; loop 2 post_feedback never opened
    assert _go(client, sid, scope="loop", loop_index=4, checkpoint="post_kid_response")["proceed"] is False
    nf = _go(client, sid, scope="loop", loop_index=2, checkpoint="post_feedback")
    assert nf["proceed"] is True and nf["gate_found"] is False


# --- override ----------------------------------------------------------------

def test_override_releases_gate_and_marks_it(client, protocol_id, exports_tmp):
    sid = _session(client, protocol_id)
    client.post(f"/sessions/{sid}/sync/feedback-delivered", json={"loop_index": 6})
    assert _go(client, sid, scope="loop", loop_index=6, checkpoint="post_feedback")["proceed"] is False

    r = client.post(
        f"/sessions/{sid}/sync/override",
        json={
            "scope": "loop",
            "loop_index": 6,
            "checkpoint": "post_feedback",
            "operator": "experimenter1",
            "reason": "tablet froze",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "closed" and r.json()["closed_by"] == "override"

    # gate now releases without any self-report
    assert _go(client, sid, scope="loop", loop_index=6, checkpoint="post_feedback")["proceed"] is True

    # marker distinguishable in the timeline
    tl = client.get(f"/sessions/{sid}/timeline", params={"format": "json"}).json()
    overrides = [e for e in tl if e["type"] == "self_report_gate_overridden"]
    assert len(overrides) == 1
    assert overrides[0]["payload"]["gate_key"] == "loop:6:post_feedback"
    assert overrides[0]["payload"]["operator"] == "experimenter1"

    # and distinguishable in the export (sync_gates.csv, closed_by=override)
    out = Path(client.post(f"/sessions/{sid}/export").json()["export_dir"])
    rows = list(csv.DictReader((out / "sync_gates.csv").open(newline="")))
    overridden = [g for g in rows if g["closed_by"] == "override"]
    assert len(overridden) == 1
    assert overridden[0]["gate_key"] == "loop:6:post_feedback"
    assert overridden[0]["override_reason"] == "tablet froze"


def test_override_can_precede_open_and_is_idempotent(client, protocol_id):
    sid = _session(client, protocol_id)
    # override a gate that was never opened: it is created closed-by-override
    r1 = client.post(
        f"/sessions/{sid}/sync/override",
        json={"scope": "stage", "stage": "modeling", "checkpoint": "baseline"},
    )
    assert r1.json()["status"] == "closed" and r1.json()["closed_by"] == "override"
    # repeating is idempotent (same gate row)
    r2 = client.post(
        f"/sessions/{sid}/sync/override",
        json={"scope": "stage", "stage": "modeling", "checkpoint": "baseline"},
    )
    assert r2.json()["gate_id"] == r1.json()["gate_id"]


# --- idempotency / no-reopen -------------------------------------------------

def test_resend_opener_does_not_reopen_closed_gate(client, protocol_id):
    sid = _session(client, protocol_id)
    client.post(f"/sessions/{sid}/sync/kid-response-complete", json={"loop_index": 1})
    client.post(
        f"/sessions/{sid}/self-reports",
        json={"loop_index": 1, "phase": "rehearsal", "timepoint": "pre", "function_class": "baseline"},
    )
    # closed via self-report
    assert _go(client, sid, scope="loop", loop_index=1, checkpoint="post_kid_response")["proceed"] is True
    # a re-sent kid_response_complete (bst retry) must not reopen it
    again = client.post(f"/sessions/{sid}/sync/kid-response-complete", json={"loop_index": 1})
    assert again.json()["status"] == "closed"


# --- never-opened + validation ----------------------------------------------

def test_go_ahead_on_unopened_gate_proceeds(client, protocol_id):
    sid = _session(client, protocol_id)
    res = _go(client, sid, scope="loop", loop_index=3, checkpoint="post_kid_response")
    assert res == {"proceed": True, "gate_found": False, "gate": None}


def test_bad_gate_identities_are_422(client, protocol_id):
    sid = _session(client, protocol_id)
    # stage gate with a loop checkpoint
    assert client.post(
        f"/sessions/{sid}/sync/override",
        json={"scope": "stage", "stage": "tutorial", "checkpoint": "post_kid_response"},
    ).status_code == 422
    # loop gate missing loop_index
    assert client.post(
        f"/sessions/{sid}/sync/override",
        json={"scope": "loop", "checkpoint": "post_kid_response"},
    ).status_code == 422


def test_full_session_has_fifteen_gates(client, protocol_id):
    """3 baseline + 6 loops x 2 = 15 distinct gated barriers."""
    sid = _session(client, protocol_id)
    for stage in ("tutorial", "instruction", "modeling"):
        client.post(f"/sessions/{sid}/sync/stage-complete", json={"stage": stage})
    for loop in range(1, 7):
        client.post(f"/sessions/{sid}/sync/kid-response-complete", json={"loop_index": loop})
        client.post(f"/sessions/{sid}/sync/feedback-delivered", json={"loop_index": loop})
    summary = client.post(f"/sessions/{sid}/sync/complete").json()
    assert summary["total_gates"] == 15


# --- auto-push of the self-report form on gate open --------------------------

def test_stage_gate_auto_pushes_baseline_form(client, protocol_id):
    sid = _session(client, protocol_id)
    client.post(f"/sessions/{sid}/sync/stage-complete", json={"stage": "instruction"})
    a = _assignment(client)
    assert a["form_type"] == "self_report"
    assert a["session_id"] == sid
    assert a["self_report_context"] == {
        "phase": "instruction",
        "timepoint": "post",
        "function_class": "baseline",
        "before_after_robot_action": "na",
    }


def test_loop_gate_auto_push_resolves_function_class_from_dtt_loops(client, protocol_id):
    sid = _session(client, protocol_id, group=1)  # group 1: loop 2 = NR
    client.post(f"/sessions/{sid}/sync/kid-response-complete", json={"loop_index": 2})
    assert _assignment(client)["self_report_context"] == {
        "loop_index": 2,
        "phase": "rehearsal",
        "timepoint": "post",
        "function_class": "NR",  # resolved server-side, not sent by bst
        "before_after_robot_action": "after",
    }
    client.post(f"/sessions/{sid}/sync/feedback-delivered", json={"loop_index": 2})
    assert _assignment(client)["self_report_context"] == {
        "loop_index": 2,
        "phase": "feedback",
        "timepoint": "post",
        "function_class": "NR",
        "before_after_robot_action": "after",
    }


def test_auto_pushed_context_submits_and_closes_the_gate(client, protocol_id):
    # The pushed context must use the exact field names/values the submit endpoint
    # accepts: echo it straight back (as the tablet does) and it should 201 and
    # close the gate -- the guard against the earlier wrong-field-name 422s.
    sid = _session(client, protocol_id, group=1)
    client.post(f"/sessions/{sid}/sync/kid-response-complete", json={"loop_index": 2})
    ctx = _assignment(client)["self_report_context"]
    r = client.post(f"/sessions/{sid}/self-reports", json={**ctx, "pleasure": 2.0})
    assert r.status_code == 201, r.text
    assert _go(client, sid, scope="loop", loop_index=2, checkpoint="post_kid_response")["proceed"] is True


def test_override_does_not_auto_push(client, protocol_id):
    sid = _session(client, protocol_id)
    client.post("/tablet/clear")
    client.post(
        f"/sessions/{sid}/sync/override",
        json={"scope": "stage", "stage": "tutorial", "checkpoint": "baseline"},
    )
    assert _assignment(client)["form_type"] == "idle"  # override never pushes a form


def test_push_failure_is_non_fatal(client, protocol_id, monkeypatch):
    from app.services import sync_gate

    def boom(**kwargs):
        raise RuntimeError("tablet offline")

    monkeypatch.setattr(sync_gate, "set_assignment", boom)
    sid = _session(client, protocol_id, group=1)
    # gate still opens (201) and the robot still waits (proceed=false)
    r = client.post(f"/sessions/{sid}/sync/kid-response-complete", json={"loop_index": 2})
    assert r.status_code == 201, r.text
    assert _go(client, sid, scope="loop", loop_index=2, checkpoint="post_kid_response")["proceed"] is False
