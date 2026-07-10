"""DTT trial interaction-flow ingestion (Phase 2).

A trial may carry the within-trial flow (the robot's TrialState machine) as an
ordered list of steps. The trial row and its dtt_performance_events rows are
written in ONE transaction and never updated afterwards.

A robot only knows the loop it just ran, so phase_key / sd_id / target_skill are
derived server-side from the loop + the participant's Latin-square order group;
a declared trial_name is checked against that mapping so the two repos cannot
drift silently.
"""

import csv
from pathlib import Path

import pytest

from app.core.config import settings


@pytest.fixture
def exports_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "EXPORTS_DIR", tmp_path)
    return tmp_path


def _session(client, protocol_id, sid="TF_S1", pid="TFP", pb_order_group=1):
    client.post("/participants", json={"participant_id": pid})
    client.post("/sessions", json={
        "session_id": sid, "participant_id": pid, "scenario_type": "bst_dtt",
        "protocol_id": protocol_id, "pb_order_group": pb_order_group, "support_condition": 1,
    })
    client.post(f"/sessions/{sid}/start")
    return sid


# The correct-first-try flow, and the full error-correction flow.
CORRECT_FLOW = [
    {"step_index": 1, "step_label": "sd", "actor": "user", "outcome": "recognized"},
    {"step_index": 2, "step_label": "kid_behavior_1", "actor": "kid", "outcome": "emitted"},
    {"step_index": 3, "step_label": "reinforcement", "actor": "user", "outcome": "delivered"},
    {"step_index": 4, "step_label": "feedback", "actor": "trainer"},
]
EC_FLOW = [
    {"step_index": 1, "step_label": "sd", "actor": "user", "outcome": "recognized"},
    {"step_index": 2, "step_label": "kid_behavior_1", "actor": "kid", "outcome": "no_response"},
    {"step_index": 3, "step_label": "prompting", "actor": "user", "outcome": "delivered"},
    {"step_index": 4, "step_label": "kid_behavior_2", "actor": "kid", "outcome": "emitted"},
    {"step_index": 5, "step_label": "hp_sd", "actor": "user", "outcome": "recognized"},
    {"step_index": 6, "step_label": "kid_behavior_hp", "actor": "kid", "outcome": "emitted"},
    {"step_index": 7, "step_label": "retry_sd", "actor": "user", "outcome": "recognized"},
    {"step_index": 8, "step_label": "kid_behavior_retry", "actor": "kid", "outcome": "emitted"},
    {"step_index": 9, "step_label": "reinforcement", "actor": "user", "outcome": "delivered"},
    {"step_index": 10, "step_label": "feedback", "actor": "trainer"},
]


def _robot_trial(loop_index, steps, **overrides):
    """What the robot posts: the loop it ran, the outcome, and the flow.
    No platform vocabulary (phase/sd_id/skill) is hardcoded robot-side."""
    payload = {
        "loop_index": loop_index,
        "response_correctness": "correct",
        "reinforcement_delivered": True,
        "error_correction_delivered": False,
        "steps": steps,
    }
    payload.update(overrides)
    return payload


# --- derivation ---------------------------------------------------------------

def test_phase_sd_and_skill_are_derived_when_omitted(client, protocol_id):
    sid = _session(client, protocol_id, pb_order_group=1)
    r = client.post(f"/sessions/{sid}/trials", json=_robot_trial(2, EC_FLOW,
                                                                 response_correctness="no_response",
                                                                 reinforcement_delivered=False,
                                                                 error_correction_delivered=True))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["phase_key"] == "rehearsal"          # only phase in the protocol
    assert body["sd_id"] == "sd_2"                    # positional cell for loop 2
    assert body["target_skill"] == "reception"        # group 1 loop 2 -> Receptive Instruction
    assert body["instruction"] == "Nod your head."


def test_derivation_follows_the_order_group(client, protocol_id):
    """Same loop cell, different order group -> different named SD and skill."""
    sid = _session(client, protocol_id, sid="TF_G3", pid="TFP3", pb_order_group=3)
    body = client.post(f"/sessions/{sid}/trials", json=_robot_trial(2, CORRECT_FLOW)).json()
    assert body["target_skill"] == "labeling"        # group 3 loop 2 -> Tacting and Labeling
    assert body["instruction"] == "What am I holding?"


def test_explicit_fields_still_win(client, protocol_id):
    sid = _session(client, protocol_id)
    body = client.post(f"/sessions/{sid}/trials", json=_robot_trial(
        1, CORRECT_FLOW, phase_key="rehearsal", sd_id="sd_1", target_skill="manding")).json()
    assert body["sd_id"] == "sd_1" and body["target_skill"] == "manding"


# --- the cross-repo drift guard ----------------------------------------------

def test_trial_name_matching_the_latin_square_is_accepted(client, protocol_id):
    sid = _session(client, protocol_id, pb_order_group=1)
    r = client.post(f"/sessions/{sid}/trials",
                    json=_robot_trial(2, CORRECT_FLOW, trial_name="Receptive Instruction"))
    assert r.status_code == 201, r.text


def test_trial_name_disagreeing_with_the_latin_square_is_422(client, protocol_id):
    """If the robot thinks loop 2 of group 1 is 'Manding', the repos have drifted."""
    sid = _session(client, protocol_id, pb_order_group=1)
    r = client.post(f"/sessions/{sid}/trials",
                    json=_robot_trial(2, CORRECT_FLOW, trial_name="Manding"))
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert "does not match" in detail and "Receptive Instruction" in detail


# --- the interaction flow -----------------------------------------------------

def test_steps_are_persisted_in_order_and_readable(client, protocol_id):
    sid = _session(client, protocol_id)
    trial_id = client.post(f"/sessions/{sid}/trials", json=_robot_trial(1, CORRECT_FLOW)).json()["trial_id"]
    steps = client.get(f"/sessions/{sid}/trials/{trial_id}/steps").json()
    assert [s["step_index"] for s in steps] == [1, 2, 3, 4]
    assert [s["step_label"] for s in steps] == ["sd", "kid_behavior_1", "reinforcement", "feedback"]
    assert steps[0]["outcome"] == "recognized"
    assert all(s["trial_id"] == trial_id and s["session_time_ms"] is not None for s in steps)


def test_error_correction_path_is_recoverable_from_the_steps(client, protocol_id):
    sid = _session(client, protocol_id)
    trial_id = client.post(f"/sessions/{sid}/trials", json=_robot_trial(
        2, EC_FLOW, response_correctness="no_response", reinforcement_delivered=False,
        error_correction_delivered=True)).json()["trial_id"]
    labels = [s["step_label"] for s in client.get(f"/sessions/{sid}/trials/{trial_id}/steps").json()]
    # the fixed EC sequence: prompting -> hp_sd -> retry_sd
    assert labels.index("prompting") < labels.index("hp_sd") < labels.index("retry_sd")


def test_steps_are_optional(client, protocol_id):
    """An operator-logged trial carries no flow."""
    sid = _session(client, protocol_id)
    body = client.post(f"/sessions/{sid}/trials", json={
        "loop_index": 1, "response_correctness": "correct",
        "reinforcement_delivered": True, "error_correction_delivered": False,
    }).json()
    assert client.get(f"/sessions/{sid}/trials/{body['trial_id']}/steps").json() == []


def test_step_detail_is_stored_verbatim(client, protocol_id):
    sid = _session(client, protocol_id)
    steps = [{"step_index": 1, "step_label": "sd", "actor": "user",
              "outcome": "not_recognized", "detail": {"asr": "nod you head", "attempt": 2}}]
    tid = client.post(f"/sessions/{sid}/trials", json=_robot_trial(1, steps)).json()["trial_id"]
    row = client.get(f"/sessions/{sid}/trials/{tid}/steps").json()[0]
    assert '"attempt": 2' in row["raw_json"]


def test_duplicate_step_index_is_422(client, protocol_id):
    sid = _session(client, protocol_id)
    dupes = [{"step_index": 1, "step_label": "sd"}, {"step_index": 1, "step_label": "feedback"}]
    r = client.post(f"/sessions/{sid}/trials", json=_robot_trial(1, dupes))
    assert r.status_code == 422
    assert "duplicate step_index" in r.json()["detail"]


def test_unknown_step_label_is_422(client, protocol_id):
    sid = _session(client, protocol_id)
    r = client.post(f"/sessions/{sid}/trials",
                    json=_robot_trial(1, [{"step_index": 1, "step_label": "tea_break"}]))
    assert r.status_code == 422


def test_steps_written_atomically_with_the_trial(client, protocol_id):
    """A rejected trial must leave no orphan steps behind."""
    sid = _session(client, protocol_id, pb_order_group=1)
    r = client.post(f"/sessions/{sid}/trials",
                    json=_robot_trial(2, CORRECT_FLOW, trial_name="Manding"))  # drift -> 422
    assert r.status_code == 422
    assert client.get(f"/sessions/{sid}/trials").json() == []


def test_trial_logged_timeline_event_records_the_step_count(client, protocol_id):
    sid = _session(client, protocol_id)
    client.post(f"/sessions/{sid}/trials", json=_robot_trial(1, CORRECT_FLOW, trial_name="Manding"))
    tl = client.get(f"/sessions/{sid}/timeline", params={"format": "json"}).json()
    ev = next(e for e in tl if e["type"] == "trial_logged")
    assert ev["payload"]["steps"] == 4
    assert ev["payload"]["trial_name"] == "Manding"


# --- export -------------------------------------------------------------------

# --- the shape the robot actually produces ------------------------------------

# Taken from a real capture (bst-study feedback_training_data/failed_hp_sd/...):
# trainer-side steps only (the child's behavior is scripted), and a state may
# REPEAT when an utterance is not recognized -- here hp_sd is attempted twice.
REAL_INTERACTION_HISTORY = [
    {"trial_state": "sd", "text": "What am I holding?", "recognized_as": "Tacting and Labeling", "successful": True},
    {"trial_state": "prompting", "text": "No. What am I holding?", "recognized_as": "Tacting and Labeling", "successful": True},
    {"trial_state": "reinforcement", "text": "Good job.", "recognized_as": "Tacting and Labeling", "successful": True},
    {"trial_state": "hp_sd", "text": "Can you dance?", "recognized_as": None, "successful": False},
    {"trial_state": "hp_sd", "text": "Shake your head.", "recognized_as": "SD_1", "successful": True},
    {"trial_state": "retry sd", "text": "What I hope", "recognized_as": None, "successful": False},
]


def _to_steps(history):
    """The exact transform the BST side performs (see dtt_trial_integration_spec)."""
    return [
        {
            "step_index": i,
            "step_label": str(e["trial_state"]).replace(" ", "_"),  # "retry sd" -> "retry_sd"
            "actor": "user",
            "outcome": "recognized" if e.get("successful") else "not_recognized",
            "detail": {"text": e.get("text"), "recognized_as": e.get("recognized_as")},
        }
        for i, e in enumerate(history, start=1)
    ]


def test_real_robot_interaction_history_is_ingestible(client, protocol_id):
    """Trainer-side labels only, a repeated state, and 'retry sd' -> 'retry_sd'."""
    sid = _session(client, protocol_id, pb_order_group=1)
    steps = _to_steps(REAL_INTERACTION_HISTORY)
    r = client.post(f"/sessions/{sid}/trials", json={
        "loop_index": 4, "trial_name": "Tacting and Labeling",
        "response_correctness": "no_response",
        "reinforcement_delivered": True, "error_correction_delivered": True,
        "steps": steps,
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["target_skill"] == "labeling"           # group 1 loop 4
    assert body["instruction"] == "What am I holding?"

    got = client.get(f"/sessions/{sid}/trials/{body['trial_id']}/steps").json()
    assert [s["step_label"] for s in got] == [
        "sd", "prompting", "reinforcement", "hp_sd", "hp_sd", "retry_sd"
    ]
    # the repeated hp_sd attempts are distinguishable by outcome
    hp = [s for s in got if s["step_label"] == "hp_sd"]
    assert [s["outcome"] for s in hp] == ["not_recognized", "recognized"]
    assert "Shake your head." in hp[1]["raw_json"]      # detail stored verbatim


def test_repeated_step_labels_are_allowed(client, protocol_id):
    """Only step_index must be unique; a trainer may retry the same state."""
    sid = _session(client, protocol_id)
    steps = [
        {"step_index": 1, "step_label": "sd", "actor": "user", "outcome": "not_recognized"},
        {"step_index": 2, "step_label": "sd", "actor": "user", "outcome": "recognized"},
        {"step_index": 3, "step_label": "reinforcement", "actor": "user"},
    ]
    r = client.post(f"/sessions/{sid}/trials", json=_robot_trial(1, steps))
    assert r.status_code == 201, r.text


def test_performance_events_are_exported(client, protocol_id, exports_tmp):
    sid = _session(client, protocol_id)
    client.post(f"/sessions/{sid}/trials", json=_robot_trial(1, CORRECT_FLOW))
    body = client.post(f"/sessions/{sid}/export").json()
    assert "dtt_performance_events.csv" in body["files"]
    assert body["row_counts"]["dtt_performance_events"] == 4

    rows = list(csv.DictReader((Path(body["export_dir"]) / "dtt_performance_events.csv").open()))
    assert [r["step_label"] for r in rows] == ["sd", "kid_behavior_1", "reinforcement", "feedback"]
