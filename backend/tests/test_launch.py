"""Robot launch-handoff tests (Operator Console v2).

Verifies the launch config mirrors the canonical Stage-1 session data, the start
guard, the prepare/start/ack/error state machine, and that status reads are safe
when nothing has been prepared yet.
"""


def _created_session(client, protocol_id, sid="LX_S1", pid="LXP", group=1, support=1):
    """A created-but-not-started session."""
    client.post("/participants", json={"participant_id": pid})
    client.post(
        "/sessions",
        json={
            "session_id": sid,
            "participant_id": pid,
            "scenario_type": "bst_dtt",
            "protocol_id": protocol_id,
            "pb_order_group": group,
            "support_condition": support,
        },
    )
    return sid


def _running_session(client, protocol_id, **kw):
    sid = _created_session(client, protocol_id, **kw)
    client.post(f"/sessions/{sid}/start")
    return sid


def test_launch_config_matches_canonical_session(client, protocol_id):
    sid = _running_session(client, protocol_id, group=3, support=0)
    r = client.get(f"/sessions/{sid}/launch/config")
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["session_id"] == sid
    assert c["participant_id"] == "LXP"
    assert c["pb_order_group"] == 3
    assert c["support_condition"] == 0
    assert c["support_label"] == "neutral"
    assert c["scenario_type"] == "bst_dtt"
    assert c["platform_base"].startswith("http")  # from the request URL


def test_status_is_safe_when_nothing_prepared(client, protocol_id):
    sid = _running_session(client, protocol_id)
    r = client.get(f"/sessions/{sid}/launch/status")
    assert r.status_code == 200
    assert r.json()["status"] == "none"  # console renders this without crashing


def test_start_requires_existing_and_running_session(client, protocol_id):
    # missing session -> 404
    assert client.post("/sessions/NOPE/launch/start").status_code == 404
    # created but not started -> 422 (not running)
    sid = _created_session(client, protocol_id, sid="LX_NR", pid="LXNR")
    r = client.post(f"/sessions/{sid}/launch/start")
    assert r.status_code == 422, r.text
    assert "running" in r.json()["detail"]


def test_launch_state_machine_prepare_start_ack(client, protocol_id):
    sid = _running_session(client, protocol_id)
    assert client.post(f"/sessions/{sid}/launch/prepare").json()["status"] == "prepared"
    # BST fetches config then acks -> waiting
    client.get(f"/sessions/{sid}/launch/config")
    assert client.post(f"/sessions/{sid}/launch/ack", json={"phase": "config_received"}).json()["status"] == "waiting"
    # operator start -> start_requested
    st = client.post(f"/sessions/{sid}/launch/start").json()
    assert st["status"] == "start_requested" and st["start_requested_at"]
    assert st["requested_by"] == "console"
    # BST acks started
    done = client.post(f"/sessions/{sid}/launch/ack", json={"phase": "started"}).json()
    assert done["status"] == "started" and done["started_at"]


def test_launch_error_path(client, protocol_id):
    sid = _running_session(client, protocol_id)
    client.post(f"/sessions/{sid}/launch/prepare")
    r = client.post(f"/sessions/{sid}/launch/error", json={"message": "furhat not reachable"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "error"
    assert body["error_text"] == "furhat not reachable"
    # and it is auditable on the timeline
    tl = client.get(f"/sessions/{sid}/timeline", params={"format": "json"}).json()
    assert any(e["type"] == "launch_error" for e in tl)


def test_launch_config_unknown_session_is_404(client):
    assert client.get("/sessions/GHOST/launch/config").status_code == 404
