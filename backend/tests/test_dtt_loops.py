"""dtt_loops generation tests (Phase 6, P0.6 piece 1).

At session start the six dtt_loops rows are materialized from the session's
pb_order_group using the Latin square confirmed against bst-study
logic/latin_square.py: baseline pinned to odd loops (1,3,5); PR/NR/AR rotate
through even loops (2,4,6) per the 3-config cyclic square. Loops are generated
once and never overwritten (raw-data immutability).
"""

import pytest

# Expected even-loop function_class per pb_order_group (the exact study table).
EXPECTED_EVEN = {
    1: {2: "NR", 4: "PR", 6: "AR"},
    2: {2: "AR", 4: "NR", 6: "PR"},
    3: {2: "PR", 4: "AR", 6: "NR"},
}


def _started_session(client, protocol_id, group, sid, pid):
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
    return client.get(f"/sessions/{sid}/loops").json()


@pytest.mark.parametrize("group", [1, 2, 3])
def test_start_generates_six_loops_per_group(client, protocol_id, group):
    loops = _started_session(client, protocol_id, group, f"G{group}_S1", f"G{group}P")
    assert len(loops) == 6
    assert [lp["loop_index"] for lp in loops] == [1, 2, 3, 4, 5, 6]
    by_index = {lp["loop_index"]: lp for lp in loops}

    # baseline pinned to odd positions
    for odd in (1, 3, 5):
        assert by_index[odd]["function_class"] == "baseline"
        assert by_index[odd]["is_problem"] == "0"

    # PR/NR/AR rotate through even positions per the order-group table
    for even, fclass in EXPECTED_EVEN[group].items():
        assert by_index[even]["function_class"] == fclass
        assert by_index[even]["is_problem"] == "1"

    # SD bound positionally; between-subject factors denormalized onto the loop
    for lp in loops:
        assert lp["sd_id"] == f"sd_{lp['loop_index']}"
        assert lp["sequence_position"] == lp["loop_index"]
        assert lp["pb_order_group"] == group
        assert lp["support_condition"] == 1


def test_loops_are_generated_once_and_not_overwritten(client, protocol_id):
    # Start materializes loops; lifecycle steps that follow must not duplicate or
    # mutate them. Capture loop_ids, run pause/resume/stop, and re-read.
    sid, pid = "IMMUT_S1", "IMMUTP"
    first = _started_session(client, protocol_id, 2, sid, pid)
    first_ids = [lp["loop_id"] for lp in first]
    first_classes = [lp["function_class"] for lp in first]

    client.post(f"/sessions/{sid}/pause")
    client.post(f"/sessions/{sid}/resume")
    client.post(f"/sessions/{sid}/stop")

    again = client.get(f"/sessions/{sid}/loops").json()
    assert [lp["loop_id"] for lp in again] == first_ids
    assert [lp["function_class"] for lp in again] == first_classes


def test_start_writes_dtt_loops_generated_timeline_event(client, protocol_id):
    sid = "TL_S1"
    _started_session(client, protocol_id, 3, sid, "TLP")
    tl = client.get(f"/sessions/{sid}/timeline", params={"format": "json"}).json()
    ev = [e for e in tl if e["type"] == "dtt_loops_generated"]
    assert len(ev) == 1
    assert ev[0]["payload"]["pb_order_group"] == 3
    assert len(ev[0]["payload"]["loops"]) == 6


def test_session_without_order_group_generates_no_loops(client, protocol_id):
    client.post("/participants", json={"participant_id": "NOG"})
    client.post(
        "/sessions",
        json={
            "session_id": "NOG_S1",
            "participant_id": "NOG",
            "scenario_type": "bst_dtt",
            "protocol_id": protocol_id,
        },
    )
    client.post("/sessions/NOG_S1/start")
    assert client.get("/sessions/NOG_S1/loops").json() == []
