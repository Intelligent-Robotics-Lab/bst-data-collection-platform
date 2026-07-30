"""Pre-session preflight gate tests (P0.12).

Covers the check logic (run_preflight) and the start-time enforcement: a blocking
failure refuses the start unless overridden, and the override is logged.
"""

import pytest

from app.core.config import settings
from app.services import preflight as pf


_STREAMING_GATEWAY = {
    "session": {"connected": True, "pipeline_state": "playing"},
    "video": {"forwarded_frame_count": 1500, "last_sample_timestamp_utc": "2026-07-17T12:00:00Z"},
    "audio": {"forwarded_audio_chunk_count": 900, "last_sample_timestamp_utc": "2026-07-17T12:00:00Z"},
}
_DISCONNECTED_GATEWAY = {
    "session": {"connected": False, "pipeline_state": None, "last_error": "gateway link lost"},
    "video": {"forwarded_frame_count": 0},
    "audio": {"forwarded_audio_chunk_count": 0},
}
_IDLE_GATEWAY = {
    "session": {"connected": True, "pipeline_state": "playing"},
    "video": {"forwarded_frame_count": 0, "last_sample_timestamp_utc": None},
    "audio": {"forwarded_audio_chunk_count": 0, "last_sample_timestamp_utc": None},
}


class _FakeSource:
    """Stand-in for HttpPollingSource in the perception reachability check.

    ``gateway`` is the parsed /debug/gateway-status body the source returns
    (default: a connected, actively streaming gateway); use ``_MISSING`` to model
    a None return (endpoint absent/unreachable)."""

    _MISSING = object()

    def __init__(self, *_a, healthy=True, gateway=None, **_k):
        self._healthy = healthy
        self._gateway = _STREAMING_GATEWAY if gateway is None else gateway

    def health(self):
        return self._healthy

    def gateway_status(self):
        return None if self._gateway is self._MISSING else self._gateway

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


# --- camera AVAILABILITY probe: the device can exist but be held by another
#     process (a leftover ffmpeg); a mere existence check gave a false green.

class _FakeProc:
    def __init__(self, returncode=0, stderr=b""):
        self.returncode = returncode
        self.stderr = stderr


def _use_real_camera_probe(monkeypatch):
    """Recording on, real (non-test) source, device path that exists so the probe
    reaches the actual capture step."""
    monkeypatch.setattr(settings, "RECORDING_ENABLED", True)
    monkeypatch.setattr(settings, "RECORDING_USE_TEST_SOURCE", False)
    monkeypatch.setattr(settings, "RECORDING_VIDEO_DEVICE", "/dev/null")  # exists on Linux
    monkeypatch.setattr(settings, "PERCEPTION_ENABLED", False)


def test_busy_camera_blocks_even_though_the_device_exists(monkeypatch):
    """THE regression: the device file exists but a leftover ffmpeg holds it, so
    the capture probe fails with EBUSY. Must be a blocking fail, not a green pass."""
    _use_real_camera_probe(monkeypatch)
    busy_err = (b"[video4linux2,v4l2 @ 0x1] Could not enqueue buffer\n"
                b"[video4linux2,v4l2 @ 0x1] ioctl(VIDIOC_STREAMON): Device or resource busy\n")
    monkeypatch.setattr(pf.subprocess, "run", lambda *a, **k: _FakeProc(1, busy_err))
    report = pf.run_preflight()
    cam = _by_id(report)["camera"]
    assert cam["status"] == "fail" and cam["required"] is True
    assert "busy" in cam["detail"].lower()
    assert "camera" in {c["id"] for c in report["blocking"]}
    assert report["ready"] is False


def test_available_camera_passes_the_probe(monkeypatch):
    _use_real_camera_probe(monkeypatch)
    monkeypatch.setattr(pf.subprocess, "run", lambda *a, **k: _FakeProc(0, b"frame=1"))
    cam = _by_id(pf.run_preflight())["camera"]
    assert cam["status"] == "pass"
    assert cam["label"] == "Camera available"


def test_camera_probe_timeout_blocks(monkeypatch):
    _use_real_camera_probe(monkeypatch)

    def _timeout(*a, **k):
        raise pf.subprocess.TimeoutExpired(cmd="ffmpeg", timeout=8)

    monkeypatch.setattr(pf.subprocess, "run", _timeout)
    cam = _by_id(pf.run_preflight())["camera"]
    assert cam["status"] == "fail" and "timed out" in cam["detail"].lower()


def test_missing_ffmpeg_blocks(monkeypatch):
    _use_real_camera_probe(monkeypatch)

    def _no_ffmpeg(*a, **k):
        raise FileNotFoundError()

    monkeypatch.setattr(pf.subprocess, "run", _no_ffmpeg)
    cam = _by_id(pf.run_preflight())["camera"]
    assert cam["status"] == "fail" and "ffmpeg not found" in cam["detail"].lower()


def test_probe_camera_unit(monkeypatch):
    """The probe helper directly: available vs busy vs absent."""
    monkeypatch.setattr(pf.subprocess, "run", lambda *a, **k: _FakeProc(0, b""))
    assert pf._probe_camera("/dev/null")[0] == "pass"
    monkeypatch.setattr(pf.subprocess, "run",
                        lambda *a, **k: _FakeProc(1, b"ioctl(VIDIOC_STREAMON): Device or resource busy"))
    st, detail = pf._probe_camera("/dev/null")
    assert st == "fail" and "busy" in detail.lower()
    assert pf._probe_camera("/dev/does_not_exist_999")[0] == "fail"


def test_perception_unreachable_blocks(monkeypatch):
    monkeypatch.setattr(settings, "RECORDING_ENABLED", True)
    monkeypatch.setattr(settings, "RECORDING_USE_TEST_SOURCE", True)
    monkeypatch.setattr(settings, "PERCEPTION_ENABLED", True)
    monkeypatch.setattr(pf, "HttpPollingSource", lambda *a, **k: _FakeSource(healthy=False))
    report = pf.run_preflight()
    assert _by_id(report)["perception_reachable"]["status"] == "fail"
    assert "perception_reachable" in {c["id"] for c in report["blocking"]}


def _perception_up(monkeypatch, gateway):
    """Recording OK + orchestrator /health OK, with a given gateway payload."""
    monkeypatch.setattr(settings, "RECORDING_ENABLED", True)
    monkeypatch.setattr(settings, "RECORDING_USE_TEST_SOURCE", True)
    monkeypatch.setattr(settings, "PERCEPTION_ENABLED", True)
    monkeypatch.setattr(
        pf, "HttpPollingSource",
        lambda *a, **k: _FakeSource(healthy=True, gateway=gateway),
    )


def test_gateway_disconnected_blocks_even_when_health_is_green(monkeypatch):
    # The reported bug: /health returns 200 (reachable=pass) but the media gateway
    # is disconnected, so the session would record no perception data.
    _perception_up(monkeypatch, _DISCONNECTED_GATEWAY)
    report = pf.run_preflight()
    checks = _by_id(report)
    assert checks["perception_reachable"]["status"] == "pass"
    gw = checks["perception_gateway"]
    assert gw["status"] == "fail" and gw["required"] is True
    assert "perception_gateway" in {c["id"] for c in report["blocking"]}
    assert report["ready"] is False


def test_gateway_connected_and_streaming_passes(monkeypatch):
    _perception_up(monkeypatch, _STREAMING_GATEWAY)
    gw = _by_id(pf.run_preflight())["perception_gateway"]
    assert gw["status"] == "pass"


def test_gateway_connected_but_no_samples_warns_not_blocks(monkeypatch):
    # Link up but nothing forwarded yet: advisory, never blocking.
    _perception_up(monkeypatch, _IDLE_GATEWAY)
    report = pf.run_preflight()
    gw = _by_id(report)["perception_gateway"]
    assert gw["status"] == "warn" and gw["required"] is False
    assert "perception_gateway" not in {c["id"] for c in report["blocking"]}


def test_gateway_endpoint_absent_warns_not_blocks(monkeypatch):
    # Older orchestrator without /debug/gateway-status: cannot verify, so advise.
    _perception_up(monkeypatch, _FakeSource._MISSING)
    report = pf.run_preflight()
    gw = _by_id(report)["perception_gateway"]
    assert gw["status"] == "warn" and gw["required"] is False
    assert "perception_gateway" not in {c["id"] for c in report["blocking"]}


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
