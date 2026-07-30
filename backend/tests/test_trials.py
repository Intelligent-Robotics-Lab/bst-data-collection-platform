"""DTT trial-logging tests (P0.5).

A trial validates against the session's assigned protocol config (bst_dtt_v1
v1.0.0, registered via the protocol_id fixture). Config-membership and range/FK
problems must return a clean 422, never a DB 500.

The real protocol has one phase (`rehearsal`), skills named after the SD types,
no step decomposition, and NO prompt-level hierarchy (error correction is a fixed
prompting -> hp_sd -> retry_sd sequence), so `prompt_level` is optional.
"""


def _running_session(client, protocol_id, pid="P050", sid="P050_S1", pb_order_group=1):
    client.post("/participants", json={"participant_id": pid})
    client.post(
        "/sessions",
        json={
            "session_id": sid,
            "participant_id": pid,
            "scenario_type": "bst_dtt",
            "protocol_id": protocol_id,
            "pb_order_group": pb_order_group,
        },
    )
    # starting the session materializes the six dtt_loops rows trials reference
    client.post(f"/sessions/{sid}/start")
    return sid


def _valid_trial(**overrides):
    payload = {
        "loop_index": 1,
        "sd_id": "sd_1",
        "phase_key": "rehearsal",
        "target_skill": "manding",
        "response_correctness": "correct",
        # prompt_level intentionally omitted: this protocol has no hierarchy
        "reinforcement_delivered": True,
        "error_correction_delivered": False,
    }
    payload.update(overrides)
    return payload


def test_log_trial_writes_row_and_timeline(client, protocol_id):
    sid = _running_session(client, protocol_id)
    r = client.post(f"/sessions/{sid}/trials", json=_valid_trial())
    assert r.status_code == 201, r.text
    body = r.json()
    # loop_index and sd_id are first-class on the trial
    assert body["loop_index"] == 1
    assert body["sd_id"] == "sd_1"
    assert body["trial_number"] == 1
    assert body["phase_key"] == "rehearsal"
    assert body["target_skill"] == "manding"
    # instruction is the REAL SD wording of the named SD occupying this loop for
    # the participant's order group (group 1, loop 1 -> "Manding")
    assert body["instruction"] == "What do you want to work for?"
    assert body["prompt_level"] is None  # optional, not supplied

    tl = client.get(f"/sessions/{sid}/timeline", params={"format": "json"}).json()
    assert any(
        e["type"] == "trial_logged"
        and e["payload"]["sd_id"] == "sd_1"
        and e["payload"]["loop_index"] == 1
        for e in tl
    )


def test_trial_number_auto_increments_and_lists_in_order(client, protocol_id):
    sid = _running_session(client, protocol_id)
    for sd in ("sd_1", "sd_2", "sd_3"):
        assert client.post(f"/sessions/{sid}/trials", json=_valid_trial(sd_id=sd)).status_code == 201
    trials = client.get(f"/sessions/{sid}/trials").json()
    assert [t["trial_number"] for t in trials] == [1, 2, 3]
    assert [t["sd_id"] for t in trials] == ["sd_1", "sd_2", "sd_3"]


def test_trial_unknown_phase_is_422(client, protocol_id):
    sid = _running_session(client, protocol_id)
    r = client.post(f"/sessions/{sid}/trials", json=_valid_trial(phase_key="nope"))
    assert r.status_code == 422, r.text
    assert "phase_key" in r.json()["detail"]


def test_trial_unknown_sd_is_422(client, protocol_id):
    sid = _running_session(client, protocol_id)
    r = client.post(f"/sessions/{sid}/trials", json=_valid_trial(sd_id="sd_99"))
    assert r.status_code == 422, r.text
    assert "sd_id" in r.json()["detail"]


def test_trial_unknown_skill_is_422(client, protocol_id):
    sid = _running_session(client, protocol_id)
    r = client.post(f"/sessions/{sid}/trials", json=_valid_trial(target_skill="skill_z"))
    assert r.status_code == 422, r.text
    assert "target_skill" in r.json()["detail"]


def test_prompt_level_is_optional(client, protocol_id):
    """This protocol has no prompt hierarchy: omitting prompt_level is valid."""
    sid = _running_session(client, protocol_id)
    payload = _valid_trial()
    assert "prompt_level" not in payload
    assert client.post(f"/sessions/{sid}/trials", json=payload).status_code == 201


def test_trial_prompt_level_rejected_when_protocol_defines_none(client, protocol_id):
    sid = _running_session(client, protocol_id)
    r = client.post(f"/sessions/{sid}/trials", json=_valid_trial(prompt_level="independent"))
    assert r.status_code == 422, r.text
    assert "prompt_level" in r.json()["detail"]


def test_trial_steps_rejected_when_skill_defines_none(client, protocol_id):
    """The real protocol has no step decomposition, so any step ID is unknown."""
    sid = _running_session(client, protocol_id)
    r = client.post(f"/sessions/{sid}/trials", json=_valid_trial(missed_steps=["step_99"]))
    assert r.status_code == 422, r.text
    assert "step_99" in r.json()["detail"]


def test_instruction_resolves_named_sd_per_order_group(client, protocol_id):
    """The SD wording depends on which named SD the Latin square puts in a loop:
    group 1 loop 2 -> Receptive Instruction; group 3 loop 2 -> Tacting and Labeling."""
    sid1 = _running_session(client, protocol_id, pid="G1", sid="G1_S1", pb_order_group=1)
    r1 = client.post(f"/sessions/{sid1}/trials",
                     json=_valid_trial(loop_index=2, sd_id="sd_2", target_skill="reception",
                                       response_correctness="no_response"))
    assert r1.status_code == 201, r1.text
    assert r1.json()["instruction"] == "Please shake your head."

    sid3 = _running_session(client, protocol_id, pid="G3", sid="G3_S1", pb_order_group=3)
    r3 = client.post(f"/sessions/{sid3}/trials",
                     json=_valid_trial(loop_index=2, sd_id="sd_2", target_skill="labeling",
                                       response_correctness="no_response"))
    assert r3.status_code == 201, r3.text
    assert r3.json()["instruction"] == "What am I holding?"


def test_trial_loop_index_out_of_range_is_422(client, protocol_id):
    sid = _running_session(client, protocol_id)
    assert client.post(f"/sessions/{sid}/trials", json=_valid_trial(loop_index=7)).status_code == 422


def test_trial_loop_index_without_generated_loops_is_422(client, protocol_id):
    # A session started without a pb_order_group generates no dtt_loops, so a
    # loop-indexed trial must 422 against the real (empty) loop set, not pass a
    # bare 1-6 range check.
    client.post("/participants", json={"participant_id": "P052"})
    client.post(
        "/sessions",
        json={
            "session_id": "P052_S1",
            "participant_id": "P052",
            "scenario_type": "bst_dtt",
            "protocol_id": protocol_id,
        },
    )
    client.post("/sessions/P052_S1/start")
    assert client.get("/sessions/P052_S1/loops").json() == []
    r = client.post("/sessions/P052_S1/trials", json=_valid_trial(loop_index=1))
    assert r.status_code == 422, r.text
    assert "dtt_loops" in r.json()["detail"]


def test_trial_bad_correctness_enum_is_422(client, protocol_id):
    sid = _running_session(client, protocol_id)
    assert client.post(f"/sessions/{sid}/trials", json=_valid_trial(response_correctness="maybe")).status_code == 422


def test_trial_on_session_without_protocol_is_422(client):
    client.post("/participants", json={"participant_id": "P051"})
    client.post("/sessions", json={"session_id": "P051_S1", "participant_id": "P051", "scenario_type": "bst_dtt"})
    client.post("/sessions/P051_S1/start")
    r = client.post("/sessions/P051_S1/trials", json=_valid_trial())
    assert r.status_code == 422, r.text
    assert "protocol" in r.json()["detail"]


def test_trial_on_unknown_session_is_404(client, protocol_id):
    assert client.post("/sessions/NOPE/trials", json=_valid_trial()).status_code == 404


def test_protocols_listing_and_config(client, protocol_id):
    protos = client.get("/protocols").json()
    assert any(p["protocol_id"] == protocol_id and p["protocol_key"] == "bst_dtt_v1" for p in protos)
    cfg = client.get(f"/protocols/{protocol_id}/config").json()
    assert cfg["version"] == "1.2.0"
    assert {s["sd_id"] for s in cfg["sds"]} >= {"sd_1", "sd_6"}
    # no prompt hierarchy; error correction is a fixed sequence instead
    assert cfg["prompt_levels"] == []
    assert cfg["ec_sequence"] == ["prompting", "hp_sd", "retry_sd"]
    assert {e["name"] for e in cfg["named_sds"]} >= {"Manding", "Receptive Expression"}
