"""Participant progress derivation (from sync gates + session state)."""

import pytest


def _session(client, protocol_id, sid="PG_S1", pid="PGP", group=1, start=True):
    client.post("/participants", json={"participant_id": pid})
    client.post("/sessions", json={
        "session_id": sid, "participant_id": pid, "scenario_type": "bst_dtt",
        "protocol_id": protocol_id, "pb_order_group": group, "support_condition": 1,
    })
    if start:
        client.post(f"/sessions/{sid}/start")
    return sid


def _prog(client, sid):
    return client.get(f"/sessions/{sid}/progress").json()


def test_created_session_is_pre_session(client, protocol_id):
    sid = _session(client, protocol_id, start=False)
    p = _prog(client, sid)
    assert p["phase"] == "pre_session" and p["active"] is False
    assert "questionnaires" in p["message"].lower()


def test_running_but_robot_not_registered_is_pre_session(client, protocol_id):
    """Session running while the participant fills pre-questionnaires, before the
    robot has registered its run."""
    sid = _session(client, protocol_id)
    p = _prog(client, sid)
    assert p["phase"] == "pre_session" and p["active"] is False


def test_tutorial_once_robot_registers(client, protocol_id):
    sid = _session(client, protocol_id)
    client.post(f"/sessions/{sid}/sync/register")   # robot begins
    p = _prog(client, sid)
    assert p["phase"] == "tutorial"
    assert p["phase_index"] == 0 and p["active"] is True


def test_active_phases_carry_no_message(client, protocol_id):
    """Research validity: the tablet shows no affective/encouraging text during
    the interaction."""
    sid = _session(client, protocol_id)
    client.post(f"/sessions/{sid}/sync/register")
    for stage in ("tutorial", "instruction", "modeling"):
        assert _prog(client, sid)["message"] == ""
        client.post(f"/sessions/{sid}/sync/stage-complete", json={"stage": stage})
    assert _prog(client, sid)["phase"] == "rehearsal"
    assert _prog(client, sid)["message"] == ""


def test_phase_advances_with_stage_gates(client, protocol_id):
    sid = _session(client, protocol_id)
    client.post(f"/sessions/{sid}/sync/stage-complete", json={"stage": "tutorial"})
    assert _prog(client, sid)["phase"] == "instruction"   # tutorial done -> in instruction
    client.post(f"/sessions/{sid}/sync/stage-complete", json={"stage": "instruction"})
    assert _prog(client, sid)["phase"] == "modeling"
    client.post(f"/sessions/{sid}/sync/stage-complete", json={"stage": "modeling"})
    assert _prog(client, sid)["phase"] == "rehearsal"     # modeling done -> rehearsal


def test_rehearsal_round_tracks_loop_gates(client, protocol_id):
    sid = _session(client, protocol_id)
    for stage in ("tutorial", "instruction", "modeling"):
        client.post(f"/sessions/{sid}/sync/stage-complete", json={"stage": stage})
    client.post(f"/sessions/{sid}/sync/kid-response-complete", json={"loop_index": 1})
    p = _prog(client, sid)
    assert p["phase"] == "rehearsal" and p["round"] == 1 and p["rounds_total"] == 6

    client.post(f"/sessions/{sid}/sync/feedback-delivered", json={"loop_index": 1})
    client.post(f"/sessions/{sid}/sync/kid-response-complete", json={"loop_index": 4})
    assert _prog(client, sid)["round"] == 4  # highest loop reached


def test_completed_session_is_complete(client, protocol_id):
    sid = _session(client, protocol_id)
    client.post(f"/sessions/{sid}/stop")
    client.post(f"/sessions/{sid}/complete")
    p = _prog(client, sid)
    assert p["phase"] == "complete" and p["round"] == 6


# --- the tablet-facing /progress (current session) ---------------------------

def test_current_progress_with_no_sessions_is_pre_session(client):
    p = client.get("/progress").json()
    assert p["phase"] == "pre_session" and p["session_id"] is None


def test_current_progress_prefers_the_running_session(client, protocol_id):
    old = _session(client, protocol_id, sid="OLD_S1", pid="OLDP")
    client.post(f"/sessions/{old}/stop")
    client.post(f"/sessions/{old}/complete")
    new = _session(client, protocol_id, sid="NEW_S1", pid="NEWP")  # running
    client.post(f"/sessions/{new}/sync/stage-complete", json={"stage": "tutorial"})

    p = client.get("/progress").json()
    assert p["session_id"] == "NEW_S1"
    assert p["phase"] == "instruction"
