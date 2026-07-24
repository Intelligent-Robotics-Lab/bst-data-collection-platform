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


def test_rehearsal_sd_plan_is_ordered_named_and_prompted(client, protocol_id):
    """The tablet's delivery guide: six positions, each with the named skill (from
    pb_order_group) and the SD prompt (from the protocol config)."""
    sid = _session(client, protocol_id, group=1)
    for stage in ("tutorial", "instruction", "modeling"):
        client.post(f"/sessions/{sid}/sync/stage-complete", json={"stage": stage})
    p = _prog(client, sid)
    assert p["phase"] == "rehearsal"
    plan = p["rehearsal_sds"]
    assert [s["number"] for s in plan] == [1, 2, 3, 4, 5, 6]
    # group 1 mapping (positions 1/3/5 baseline, 2/4/6 the problem SDs)
    assert [s["name"] for s in plan] == [
        "Manding", "Receptive Instruction", "Imitation",
        "Tacting and Labeling", "Emotion Labeling", "Receptive Expression",
    ]
    # SD wording is carried from the protocol config
    assert plan[1]["prompt"] == "Can you shake your head?"
    assert plan[0]["sd_type"] == "Manding"


def test_next_sd_starts_at_one_and_advances_strictly(client, protocol_id):
    sid = _session(client, protocol_id, group=1)
    for stage in ("tutorial", "instruction", "modeling"):
        client.post(f"/sessions/{sid}/sync/stage-complete", json={"stage": stage})
    # start of rehearsal: deliver SD 1
    assert _prog(client, sid)["next_sd"] == 1

    # mid-loop-1 (child responded, feedback not yet) still points at 1
    client.post(f"/sessions/{sid}/sync/kid-response-complete", json={"loop_index": 1})
    assert _prog(client, sid)["next_sd"] == 1
    # loop 1 fully completes -> advances to 2 (strictly one step)
    client.post(f"/sessions/{sid}/sync/feedback-delivered", json={"loop_index": 1})
    assert _prog(client, sid)["next_sd"] == 2

    # finish all six -> no next SD to deliver
    for loop in range(2, 7):
        client.post(f"/sessions/{sid}/sync/kid-response-complete", json={"loop_index": loop})
        client.post(f"/sessions/{sid}/sync/feedback-delivered", json={"loop_index": loop})
    assert _prog(client, sid)["next_sd"] is None


def _complete_loop(client, sid, loop):
    client.post(f"/sessions/{sid}/sync/kid-response-complete", json={"loop_index": loop})
    client.post(f"/sessions/{sid}/sync/feedback-delivered", json={"loop_index": loop})


def test_out_of_order_completion_points_to_earliest_gap(client, protocol_id):
    """SDs done out of order: the completed SET (not a count) drives done-marking,
    and next_sd is the earliest SD not yet done -- steering back to the gap."""
    sid = _session(client, protocol_id, group=1)
    for stage in ("tutorial", "instruction", "modeling"):
        client.post(f"/sessions/{sid}/sync/stage-complete", json={"stage": stage})

    # complete 1 then 3 (skip 2)
    _complete_loop(client, sid, 1)
    _complete_loop(client, sid, 3)
    p = _prog(client, sid)
    assert p["completed_sds"] == [1, 3]      # the actual set, not [1, 2]
    assert p["next_sd"] == 2                  # earliest gap, not 4
    assert p["rounds_done"] == 2              # count kept for compat

    # complete 5 too -> still points back to 2
    _complete_loop(client, sid, 5)
    p = _prog(client, sid)
    assert p["completed_sds"] == [1, 3, 5]
    assert p["next_sd"] == 2

    # fill the gaps -> pointer moves forward again
    _complete_loop(client, sid, 2)
    assert _prog(client, sid)["next_sd"] == 4  # 1,2,3,5 done -> earliest gap is 4


def test_completed_sds_starts_empty_and_points_to_one(client, protocol_id):
    sid = _session(client, protocol_id, group=1)
    for stage in ("tutorial", "instruction", "modeling"):
        client.post(f"/sessions/{sid}/sync/stage-complete", json={"stage": stage})
    p = _prog(client, sid)
    assert p["completed_sds"] == [] and p["next_sd"] == 1


def test_rehearsal_sd_plan_falls_back_to_numbers_without_group(client, protocol_id):
    """No pb_order_group: the plan still has six numbered slots, names/prompts null
    (the tablet then shows a bare number)."""
    client.post("/participants", json={"participant_id": "NGP"})
    client.post("/sessions", json={
        "session_id": "NG_S1", "participant_id": "NGP", "scenario_type": "bst_dtt",
        "protocol_id": protocol_id, "support_condition": 1,
    })
    client.post("/sessions/NG_S1/start")
    for stage in ("tutorial", "instruction", "modeling"):
        client.post("/sessions/NG_S1/sync/stage-complete", json={"stage": stage})
    plan = _prog(client, "NG_S1")["rehearsal_sds"]
    assert [s["number"] for s in plan] == [1, 2, 3, 4, 5, 6]
    assert all(s["name"] is None and s["prompt"] is None for s in plan)


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
