"""Pre-session preflight gate tests (P0.12).

Covers the check logic (run_preflight) and the start-time enforcement: a blocking
failure refuses the start unless overridden, and the override is logged.
"""

import pytest

from app.core.config import settings
from app.services import preflight as pf


class _FakeSource:
    """Stand-in for HttpPollingSource in the perception reachability check."""

    def __init__(self, *_a, healthy=True, **_k):
        self._healthy = healthy

    def health(self):
        return self._healthy

    def close(self):
        pass


def _by_id(report):
    return {c["id"]: c for c in report["checks"]}


# --- run_preflight: check logic ----------------------------------------------

def test_disabled_recording_and_perception_are_blocking(monkeypatch):
    monkeypatch.setattr(settings, "RECORDING_ENABLED", False)
    monkeypatch.setattr(settings, "PERCEPTION_ENABLED", False)
    report = pf.run_preflight()
    checks = _by_id(report)
    assert checks["recording_enabled"]["status"] == "fail"
    assert checks["perception_enabled"]["status"] == "fail"
    # camera / reachability are N/A when their subsystem is off
    assert checks["camera"]["status"] == "na"
    assert checks["perception_reachable"]["status"] == "na"
    assert report["ready"] is False
    assert {c["id"] for c in report["blocking"]} >= {"recording_enabled", "perception_enabled"}


def test_all_green_is_ready(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "RECORDING_ENABLED", True)
    monkeypatch.setattr(settings, "RECORDING_USE_TEST_SOURCE", True)  # camera check -> pass
    monkeypatch.setattr(settings, "PERCEPTION_ENABLED", True)
    monkeypatch.setattr(pf, "HttpPollingSource", lambda *a, **k: _FakeSource(healthy=True))
    monkeypatch.setattr(settings, "RECORDINGS_DIR", tmp_path)  # plenty of free space
    monkeypatch.setattr(settings, "PREFLIGHT_MIN_FREE_GB", 0.0)
    monkeypatch.setattr(pf, "seconds_since_tablet_poll", lambda: 2.0)  # tablet connected

    report = pf.run_preflight()
    assert report["ready"] is True
    assert report["blocking"] == []
    assert _by_id(report)["tablet_connected"]["status"] == "pass"


def test_missing_camera_blocks_when_recording_on(monkeypatch):
    monkeypatch.setattr(settings, "RECORDING_ENABLED", True)
    monkeypatch.setattr(settings, "RECORDING_USE_TEST_SOURCE", False)
    monkeypatch.setattr(settings, "RECORDING_VIDEO_DEVICE", "/dev/does_not_exist_999")
    monkeypatch.setattr(settings, "PERCEPTION_ENABLED", False)
    report = pf.run_preflight()
    cam = _by_id(report)["camera"]
    assert cam["status"] == "fail" and cam["required"] is True
    assert "camera" in {c["id"] for c in report["blocking"]}


def test_perception_unreachable_blocks(monkeypatch):
    monkeypatch.setattr(settings, "RECORDING_ENABLED", True)
    monkeypatch.setattr(settings, "RECORDING_USE_TEST_SOURCE", True)
    monkeypatch.setattr(settings, "PERCEPTION_ENABLED", True)
    monkeypatch.setattr(pf, "HttpPollingSource", lambda *a, **k: _FakeSource(healthy=False))
    report = pf.run_preflight()
    assert _by_id(report)["perception_reachable"]["status"] == "fail"
    assert "perception_reachable" in {c["id"] for c in report["blocking"]}


def test_low_disk_blocks(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "RECORDINGS_DIR", tmp_path)
    monkeypatch.setattr(settings, "PREFLIGHT_MIN_FREE_GB", 1_000_000.0)  # more than any disk
    report = pf.run_preflight()
    assert _by_id(report)["disk_free"]["status"] == "fail"
    assert "disk_free" in {c["id"] for c in report["blocking"]}


def test_tablet_is_advisory_never_blocking(monkeypatch):
    monkeypatch.setattr(pf, "seconds_since_tablet_poll", lambda: None)  # never polled
    report = pf.run_preflight()
    tab = _by_id(report)["tablet_connected"]
    assert tab["status"] == "warn" and tab["required"] is False
    assert "tablet_connected" not in {c["id"] for c in report["blocking"]}


# --- GET /preflight ----------------------------------------------------------

def test_preflight_endpoint_returns_report(client, monkeypatch):
    monkeypatch.setattr(settings, "RECORDING_ENABLED", False)
    monkeypatch.setattr(settings, "PERCEPTION_ENABLED", False)
    r = client.get("/preflight")
    assert r.status_code == 200
    body = r.json()
    assert body["ready"] is False
    assert any(c["id"] == "recording_enabled" for c in body["checks"])


# --- start enforcement -------------------------------------------------------

def _session(client, sid="PF_S1", pid="PFP"):
    client.post("/participants", json={"participant_id": pid})
    client.post("/sessions", json={"session_id": sid, "participant_id": pid, "scenario_type": "bst_dtt"})
    return sid


def _block(monkeypatch):
    """Force the start-time gate to report a blocking failure."""
    report = {
        "ready": False,
        "blocking": [{"id": "recording_enabled", "label": "Recording enabled",
                      "category": "recording", "status": "fail", "required": True,
                      "detail": "RECORDING_ENABLED is false"}],
        "counts": {}, "checks": [],
    }
    monkeypatch.setattr("app.api.sessions.run_preflight", lambda: report)


def test_start_is_refused_when_a_required_check_fails(client, monkeypatch):
    sid = _session(client)
    _block(monkeypatch)
    r = client.post(f"/sessions/{sid}/start")
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert detail["failed"] == ["recording_enabled"]
    # the session did not start
    assert client.get(f"/sessions/{sid}").json()["state"] == "created"


def test_override_starts_and_logs_to_timeline(client, monkeypatch):
    sid = _session(client)
    _block(monkeypatch)
    r = client.post(f"/sessions/{sid}/start",
                    params={"override": True, "override_operator": "op1", "override_reason": "no camera today"})
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "running"

    tl = client.get(f"/sessions/{sid}/timeline", params={"format": "json"}).json()
    ev = next(e for e in tl if e["type"] == "preflight_overridden")
    assert ev["payload"]["failed"] == ["recording_enabled"]
    assert ev["payload"]["operator"] == "op1"
    assert ev["payload"]["reason"] == "no camera today"
    # ordered before session_started
    types = [e["type"] for e in tl]
    assert types.index("preflight_overridden") < types.index("session_started")


def test_start_proceeds_normally_when_preflight_is_clean(client, monkeypatch):
    sid = _session(client)
    monkeypatch.setattr("app.api.sessions.run_preflight",
                        lambda: {"ready": True, "blocking": [], "counts": {}, "checks": []})
    r = client.post(f"/sessions/{sid}/start")
    assert r.status_code == 200 and r.json()["state"] == "running"
    tl = client.get(f"/sessions/{sid}/timeline", params={"format": "json"}).json()
    assert not any(e["type"] == "preflight_overridden" for e in tl)
