"""Live monitor mirror: robot pushes its monitor_state, tablet reads it."""

import pytest


@pytest.fixture(autouse=True)
def _reset_monitor():
    # The monitor store is a module singleton; reset it so tests are independent.
    from app.services import monitor
    monitor._state.update({"revision": 0, "updated_at": None, "monitor": None})
    yield


def test_monitor_starts_empty(client):
    m = client.get("/monitor").json()
    assert m["monitor"] is None and m["revision"] == 0


def test_push_then_read_roundtrips_and_bumps_revision(client):
    state = {
        "screen": "rehearsal",
        "trial_name": "Receptive Instruction",
        "trial_state": "PROMPTING",
        "trial_sd_number": 2,
        "completed_sd_numbers": [1],
    }
    r = client.post("/monitor", json=state)
    assert r.status_code == 200, r.text
    assert r.json()["revision"] == 1

    m = client.get("/monitor").json()
    assert m["monitor"]["trial_name"] == "Receptive Instruction"
    assert m["monitor"]["trial_state"] == "PROMPTING"
    assert m["updated_at"] is not None

    # a second push overwrites and bumps the revision
    r2 = client.post("/monitor", json={"screen": "rehearsal", "trial_state": "REINFORCEMENT"})
    assert r2.json()["revision"] == 2
    assert client.get("/monitor").json()["monitor"]["trial_state"] == "REINFORCEMENT"


def test_starting_a_session_clears_a_stale_mirror(client):
    """A new session must not inherit the SD/trial_state a previous one left in
    the process-global mirror; starting clears it so the tablet begins fresh."""
    client.post("/participants", json={"participant_id": "P009"})
    client.post("/sessions", json={"session_id": "P009_S1", "participant_id": "P009"})

    # Previous session left an SD-6 feedback frame lingering in the mirror.
    client.post("/monitor", json={"trial_name": "SD-6", "trial_state": "FEEDBACK",
                                  "trial_sd_number": 6})
    assert client.get("/monitor").json()["monitor"]["trial_sd_number"] == 6

    assert client.post("/sessions/P009_S1/start").json()["state"] == "running"

    # The tablet now reads a fresh mirror (no stale Current SD / Trial State).
    assert client.get("/monitor").json()["monitor"] is None

    # Ending the session also clears whatever SD it stopped on.
    client.post("/monitor", json={"trial_name": "SD-3", "trial_sd_number": 3})
    client.post("/sessions/P009_S1/stop")
    assert client.get("/monitor").json()["monitor"] is None
