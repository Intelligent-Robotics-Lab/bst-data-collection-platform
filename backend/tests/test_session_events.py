"""Tests for experimenter notes and robot events (Phase 3, protocol-independent)."""


def _running_session(client, pid="P020", sid="P020_S1"):
    client.post("/participants", json={"participant_id": pid})
    client.post("/sessions", json={"session_id": sid, "participant_id": pid, "scenario_type": "bst_dtt"})
    client.post(f"/sessions/{sid}/start")
    return sid


def test_add_note_writes_row_and_timeline(client):
    sid = _running_session(client)
    r = client.post(f"/sessions/{sid}/notes", json={"text": "participant looked away", "loop_index": 2})
    assert r.status_code == 201, r.text
    assert r.json()["text"] == "participant looked away"

    assert [n["text"] for n in client.get(f"/sessions/{sid}/notes").json()] == ["participant looked away"]
    tl = client.get(f"/sessions/{sid}/timeline", params={"format": "json"}).json()
    assert any(e["type"] == "note_added" and e["payload"]["text"] == "participant looked away" for e in tl)


def test_note_bad_loop_index_is_422(client):
    sid = _running_session(client)
    assert client.post(f"/sessions/{sid}/notes", json={"text": "x", "loop_index": 7}).status_code == 422


def test_note_unknown_trial_id_is_422_not_500(client):
    sid = _running_session(client)
    r = client.post(f"/sessions/{sid}/notes", json={"text": "x", "trial_id": 999999})
    assert r.status_code == 422, r.text
    assert "trial_id" in r.json()["detail"]


def test_note_empty_text_is_422(client):
    sid = _running_session(client)
    assert client.post(f"/sessions/{sid}/notes", json={"text": ""}).status_code == 422


def test_add_robot_event_writes_row_and_timeline(client):
    sid = _running_session(client)
    r = client.post(
        f"/sessions/{sid}/robot-events",
        json={"role": "trainer", "utterance_or_action": "Say hello", "condition": "high_support",
              "script_version": "v1", "loop_index": 1, "payload": {"gesture": "wave"}},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["role"] == "trainer"
    assert '"gesture"' in body["payload_json"]

    tl = client.get(f"/sessions/{sid}/timeline", params={"format": "json"}).json()
    assert any(e["type"] == "robot_event" and e["payload"]["role"] == "trainer" for e in tl)


def test_robot_event_bad_role_is_422(client):
    sid = _running_session(client)
    assert client.post(f"/sessions/{sid}/robot-events", json={"role": "narrator"}).status_code == 422


def test_note_on_unknown_session_is_404(client):
    assert client.post("/sessions/NOPE/notes", json={"text": "x"}).status_code == 404
