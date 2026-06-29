"""A/V recording service tests (P0.8).

Recording follows the session lifecycle (start on start, graceful stop on stop)
and writes media_recordings rows + timeline events. A failure to start is a
logged row, never a crashed session. The happy-path test spawns real ffmpeg with
a synthetic lavfi source (no camera/GPU) and asserts a playable mp4 with audio.
"""

import shutil
import subprocess
import time
from pathlib import Path

import pytest

from app.core.config import settings
from app.services.recording import build_ffmpeg_command


def _create(client, pid, sid):
    client.post("/participants", json={"participant_id": pid})
    r = client.post(
        "/sessions",
        json={"session_id": sid, "participant_id": pid, "scenario_type": "bst_dtt"},
    )
    assert r.status_code == 201, r.text
    return sid


# --- command assembly (pure; no subprocess) ---------------------------------


def test_command_builder_uses_day1_verified_flags(monkeypatch):
    monkeypatch.setattr(settings, "RECORDING_USE_TEST_SOURCE", False)
    cmd = build_ffmpeg_command(Path("/tmp/out.mp4"))

    assert "h264_nvenc" in cmd
    assert "-vsync" in cmd and "passthrough" in cmd
    assert "-fps_mode" not in cmd  # 5.x syntax must NOT appear on ffmpeg 4.4
    assert cmd[cmd.index("-pix_fmt") + 1] == "yuv420p"
    assert cmd.count("-thread_queue_size") == 2 and "1024" in cmd  # video + audio
    assert "/dev/video0" in cmd
    assert "hw:CARD=BRIO,DEV=0" in cmd
    assert "mjpeg" in cmd
    assert cmd[-1] == "/tmp/out.mp4"


def test_command_builder_test_source_swaps_inputs_keeps_encoder(monkeypatch):
    monkeypatch.setattr(settings, "RECORDING_USE_TEST_SOURCE", True)
    cmd = build_ffmpeg_command(Path("/tmp/out.mp4"))

    assert "lavfi" in cmd
    assert any("testsrc" in c for c in cmd)
    assert any("sine" in c for c in cmd)
    assert "/dev/video0" not in cmd
    # encoder flags are identical to the real command
    assert "-vsync" in cmd and cmd[cmd.index("-pix_fmt") + 1] == "yuv420p"


# --- lifecycle behavior ------------------------------------------------------


def test_recording_disabled_is_noop(client):
    """Default (RECORDING_ENABLED=false): no ffmpeg, no rows, session runs."""
    sid = _create(client, "P700", "P700_S1")
    r = client.post(f"/sessions/{sid}/start")
    assert r.status_code == 200 and r.json()["state"] == "running"
    assert client.get(f"/sessions/{sid}/recordings").json() == []


def test_recording_start_failure_is_logged_not_fatal(client, monkeypatch):
    """A missing camera must NOT crash the session: it logs a failed recording
    row + a recording_failed timeline event, and the session keeps running."""
    monkeypatch.setattr(settings, "RECORDING_ENABLED", True)
    monkeypatch.setattr(settings, "RECORDING_USE_TEST_SOURCE", False)
    monkeypatch.setattr(settings, "RECORDING_VIDEO_DEVICE", "/nonexistent/video999")

    sid = _create(client, "P701", "P701_S1")
    r = client.post(f"/sessions/{sid}/start")
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "running"  # session survived the recording failure

    recs = client.get(f"/sessions/{sid}/recordings").json()
    assert len(recs) == 1
    assert recs[0]["status"] == "failed"
    assert "not found" in (recs[0]["error_text"] or "")

    tl = client.get(f"/sessions/{sid}/timeline", params={"format": "json"}).json()
    assert any(e["type"] == "recording_failed" for e in tl)
    assert not any(e["type"] == "recording_started" for e in tl)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_recording_happy_path_produces_playable_mp4(client, monkeypatch, tmp_path):
    """End-to-end: start a session -> ffmpeg records a synthetic A/V test source
    -> graceful stop ('q') finalizes the mp4 -> the file is playable and has both
    a video and an audio stream."""
    monkeypatch.setattr(settings, "RECORDING_ENABLED", True)
    monkeypatch.setattr(settings, "RECORDING_USE_TEST_SOURCE", True)
    monkeypatch.setattr(settings, "RECORDING_VIDEO_CODEC", "libx264")  # no GPU in CI
    monkeypatch.setattr(settings, "RECORDING_VIDEO_SIZE", "320x240")
    monkeypatch.setattr(settings, "RECORDING_FRAMERATE", 15)
    monkeypatch.setattr(settings, "RECORDINGS_DIR", tmp_path / "rec")
    monkeypatch.setattr(settings, "LOGS_DIR", tmp_path / "logs")

    sid = _create(client, "P702", "P702_S1")
    assert client.post(f"/sessions/{sid}/start").status_code == 200

    recs = client.get(f"/sessions/{sid}/recordings").json()
    assert len(recs) == 1 and recs[0]["status"] == "recording"
    file_path = Path(recs[0]["file_path"])

    time.sleep(1.2)  # let ffmpeg capture a real second-plus of A/V
    assert client.post(f"/sessions/{sid}/stop").status_code == 200

    recs = client.get(f"/sessions/{sid}/recordings").json()
    assert recs[0]["status"] == "completed"
    assert recs[0]["duration_ms"] and recs[0]["duration_ms"] > 0

    assert file_path.exists() and file_path.stat().st_size > 0

    tl = client.get(f"/sessions/{sid}/timeline", params={"format": "json"}).json()
    assert any(e["type"] == "recording_started" for e in tl)
    assert any(e["type"] == "recording_stopped" for e in tl)

    if shutil.which("ffprobe"):
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
             "-of", "csv=p=0", str(file_path)],
            capture_output=True, text=True,
        )
        assert "video" in out.stdout, out.stdout
        assert "audio" in out.stdout, out.stdout
