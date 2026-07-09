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


# --- stop-time integrity (a 'completed' row must mean a real file) -----------


class _FakeStdin:
    def write(self, b): pass
    def flush(self): pass
    def close(self): pass


class _FakeProc:
    """Stand-in for the ffmpeg Popen. exited=True => already dead before stop."""

    def __init__(self, rc=0, exited=False):
        self._rc = rc if exited else None
        self._rc_after = rc
        self.stdin = _FakeStdin()

    def poll(self):
        return self._rc

    def wait(self, timeout=None):
        self._rc = self._rc_after
        return self._rc


class _FakeLog:
    def close(self): pass


def _running_recording(client, _session_factory, sid, pid, file_path):
    from app.models.signals import MediaRecording

    client.post("/participants", json={"participant_id": pid})
    client.post("/sessions", json={"session_id": sid, "participant_id": pid, "scenario_type": "bst_dtt"})
    db = _session_factory()
    rec = MediaRecording(
        session_id=sid, participant_id=pid, recording_type="av",
        file_path=str(file_path), status="recording",
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return db, rec


def _stop_with(client, _session_factory, tmp_path, monkeypatch, *, sid, pid, exited, rc, playable):
    """Drive stop_session_recording with a fake ffmpeg and a stubbed file probe."""
    from app.services import recording
    from app.services.session_service import get_session_or_404

    monkeypatch.setattr(recording, "probe_playable", lambda p: playable)
    path = tmp_path / f"{sid}.mp4"
    db, rec = _running_recording(client, _session_factory, sid, pid, path)
    recording._active[sid] = recording._Active(
        _FakeProc(rc=rc, exited=exited), rec.recording_id, path, _FakeLog()
    )
    return recording.stop_session_recording(db, get_session_or_404(db, sid))


def test_stop_failed_when_ffmpeg_died_and_no_playable_file(client, _session_factory, tmp_path, monkeypatch):
    """The pilot bug: ffmpeg died on its own (audio device failed just after
    start) and produced nothing playable -> 'failed', never a false 'completed'."""
    out = _stop_with(client, _session_factory, tmp_path, monkeypatch,
                     sid="R_S1", pid="RP1", exited=True, rc=1, playable=False)
    assert out.status == "failed"
    assert "exited on its own" in out.error_text
    assert "no playable file" in out.error_text


def test_stop_interrupted_when_ffmpeg_died_but_file_is_playable(client, _session_factory, tmp_path, monkeypatch):
    """A backend killed with SIGINT: ffmpeg exits on its own but finalizes the
    mp4. The video is usable, so this is 'interrupted' -- not 'failed'."""
    out = _stop_with(client, _session_factory, tmp_path, monkeypatch,
                     sid="R_S2", pid="RP2", exited=True, rc=255, playable=True)
    assert out.status == "interrupted"
    assert "finalized and playable" in out.error_text


def test_stop_failed_when_clean_exit_but_no_playable_file(client, _session_factory, tmp_path, monkeypatch):
    out = _stop_with(client, _session_factory, tmp_path, monkeypatch,
                     sid="R_S3", pid="RP3", exited=False, rc=0, playable=False)
    assert out.status == "failed"
    assert "no playable file" in out.error_text


def test_stop_completed_when_clean_exit_and_playable(client, _session_factory, tmp_path, monkeypatch):
    out = _stop_with(client, _session_factory, tmp_path, monkeypatch,
                     sid="R_S4", pid="RP4", exited=False, rc=0, playable=True)
    assert out.status == "completed"
    assert not out.error_text


# --- probe_playable against real files ---------------------------------------


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
                    reason="ffmpeg/ffprobe not installed")
def test_probe_playable_detects_finalized_vs_truncated(tmp_path):
    from app.services.recording import probe_playable

    good = tmp_path / "good.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=64x64:rate=10",
         "-t", "0.3", "-pix_fmt", "yuv420p", str(good)], check=True,
    )
    assert probe_playable(good) is True

    # a SIGKILLed capture looks like this: bytes on disk, but no moov atom
    truncated = tmp_path / "truncated.mp4"
    truncated.write_bytes(good.read_bytes()[:512])
    assert probe_playable(truncated) is False

    assert probe_playable(tmp_path / "missing.mp4") is False


# --- crash recovery: startup reconciliation + graceful shutdown ---------------


def test_reconcile_stale_recording_playable_becomes_interrupted(client, _session_factory, tmp_path, monkeypatch):
    from app.services import recording

    monkeypatch.setattr(recording, "_pids_holding", lambda p: [])
    monkeypatch.setattr(recording, "probe_playable", lambda p: True)
    db, rec = _running_recording(client, _session_factory, "R_S5", "RP5", tmp_path / "a.mp4")

    out = recording.reconcile_stale_recordings(db)
    assert [r.recording_id for r in out] == [rec.recording_id]
    db.refresh(rec)
    assert rec.status == "interrupted"
    assert "reconciled at startup" in rec.error_text
    assert rec.stop_timestamp_utc  # closed out


def test_reconcile_stale_recording_unplayable_becomes_failed(client, _session_factory, tmp_path, monkeypatch):
    from app.services import recording

    monkeypatch.setattr(recording, "_pids_holding", lambda p: [])
    monkeypatch.setattr(recording, "probe_playable", lambda p: False)
    db, rec = _running_recording(client, _session_factory, "R_S6", "RP6", tmp_path / "b.mp4")

    recording.reconcile_stale_recordings(db)
    db.refresh(rec)
    assert rec.status == "failed"
    assert "no playable file" in rec.error_text


def test_reconcile_sigints_an_orphaned_recorder(client, _session_factory, tmp_path, monkeypatch):
    """An ffmpeg that outlived its backend is SIGINTed (it finalizes the mp4),
    not left running or SIGKILLed."""
    from app.services import recording

    signalled = []
    holders = [4242]
    monkeypatch.setattr(recording, "_pids_holding", lambda p: list(holders))
    monkeypatch.setattr(recording, "probe_playable", lambda p: True)

    def fake_kill(pid, sig):
        signalled.append((pid, sig))
        holders.clear()  # it exits after the SIGINT

    monkeypatch.setattr(recording.os, "kill", fake_kill)
    db, rec = _running_recording(client, _session_factory, "R_S7", "RP7", tmp_path / "c.mp4")

    recording.reconcile_stale_recordings(db)
    import signal as _signal
    assert signalled == [(4242, _signal.SIGINT)]
    db.refresh(rec)
    assert rec.status == "interrupted"


def test_reconcile_noop_when_nothing_stale(client, _session_factory):
    from app.services import recording
    db = _session_factory()
    assert recording.reconcile_stale_recordings(db) == []


def test_shutdown_gracefully_stops_active_recordings(client, _session_factory, tmp_path, monkeypatch):
    from app.services import recording

    monkeypatch.setattr(recording, "probe_playable", lambda p: True)
    path = tmp_path / "live.mp4"
    db, rec = _running_recording(client, _session_factory, "R_S8", "RP8", path)
    proc = _FakeProc(rc=0, exited=False)  # still running
    recording._active["R_S8"] = recording._Active(proc, rec.recording_id, path, _FakeLog())

    recording.shutdown_active_recordings(session_factory=_session_factory)

    assert "R_S8" not in recording._active  # handle released
    db.refresh(rec)
    assert rec.status == "completed"  # finalized via the graceful 'q' path


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
