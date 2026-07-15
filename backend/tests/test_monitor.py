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
