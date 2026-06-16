"""Session create/lifecycle tests, including the dangling-FK regression."""


def _make_participant(client, pid="P003"):
    r = client.post("/participants", json={"participant_id": pid})
    assert r.status_code == 201
    return pid


def test_create_session_with_zero_protocol_id_is_clean_4xx(client):
    """Regression: protocol_id=0 (a dangling FK) must return a clean 4xx, not 500."""
    _make_participant(client)
    r = client.post(
        "/sessions",
        json={
            "session_id": "P003_S1",
            "participant_id": "P003",
            "scenario_type": "bst_dtt",
            "protocol_id": 0,
        },
    )
    assert 400 <= r.status_code < 500, r.text
    assert r.status_code != 500
    assert "protocol_id" in r.json()["detail"]


def test_create_session_with_nonexistent_protocol_id_is_clean_4xx(client):
    _make_participant(client)
    r = client.post(
        "/sessions",
        json={
            "session_id": "P003_S2",
            "participant_id": "P003",
            "scenario_type": "bst_dtt",
            "protocol_id": 999999,
        },
    )
    assert r.status_code == 422, r.text
    assert "protocol_id" in r.json()["detail"]


def test_create_session_without_protocol_id_succeeds(client):
    _make_participant(client)
    r = client.post(
        "/sessions",
        json={
            "session_id": "P003_S3",
            "participant_id": "P003",
            "scenario_type": "bst_dtt",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["state"] == "created"
    assert r.json()["protocol_id"] is None


def test_create_session_with_unknown_participant_is_clean_4xx(client):
    r = client.post(
        "/sessions",
        json={
            "session_id": "PX_S1",
            "participant_id": "NOPE",
            "scenario_type": "bst_dtt",
        },
    )
    assert r.status_code == 400, r.text
    assert "participant_id" in r.json()["detail"]


def test_lifecycle_and_illegal_transition(client):
    _make_participant(client)
    client.post(
        "/sessions",
        json={"session_id": "P003_S4", "participant_id": "P003", "scenario_type": "bst_dtt"},
    )
    assert client.post("/sessions/P003_S4/start").json()["state"] == "running"
    assert client.post("/sessions/P003_S4/pause").json()["state"] == "paused"
    # illegal: cannot start a paused session
    assert client.post("/sessions/P003_S4/start").status_code == 409
    assert client.post("/sessions/P003_S4/resume").json()["state"] == "running"
    assert client.post("/sessions/P003_S4/stop").json()["state"] == "stopped"
    assert client.post("/sessions/P003_S4/complete").json()["state"] == "completed"

    tl = client.get("/sessions/P003_S4/timeline", params={"format": "json"}).json()
    assert [e["type"] for e in tl] == [
        "session_created",
        "session_started",
        "session_paused",
        "session_resumed",
        "session_stopped",
        "session_completed",
    ]
