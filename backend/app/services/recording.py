"""Server-side A/V recording service (P0.8).

Wraps the Day-1 verified ffmpeg capture behind the session lifecycle: recording
starts when a session starts and stops when it stops. The verified command is
NVENC ``h264_nvenc`` + ``-pix_fmt yuv420p`` at ~5 Mbps 1080p30, MJPEG video from
the Brio (``/dev/video0``) and ALSA audio (``hw:CARD=BRIO,DEV=0``) each with
``-thread_queue_size 1024``, and ``-vsync passthrough`` (ffmpeg 4.4, NOT the 5.x
``-fps_mode``). Every part of that command lives in settings so the lab can swap
devices / point at the mounted SSD with no code change.

Two non-negotiables, both about never losing an unrepeatable session:

* Stop is ALWAYS graceful: send ``q`` to ffmpeg's stdin so the mp4 trailer is
  written. A killed recording is a corrupt, unplayable file. SIGTERM is a last
  resort only if ffmpeg ignores ``q``; SIGKILL only if it ignores SIGTERM.
* A recording failure is logged, never raised. If ffmpeg cannot start (no camera,
  device busy) the session must keep running; we write a ``media_recordings`` row
  with status='failed' and a ``recording_failed`` timeline event, and return.

Active ffmpeg handles live in an in-process registry keyed by session_id (the lab
runs one session at a time in one uvicorn process, like the tablet assignment
slot). Persistence is the ``media_recordings`` table.
"""

from __future__ import annotations

import logging
import shlex
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.timeutil import now_utc
from app.models.session import StudySession
from app.models.signals import MediaRecording
from app.services.timeline import compute_session_time_ms, record_timeline_event

logger = logging.getLogger("bst.recording")


class RecordingError(Exception):
    """A recording could not start/run. Logged to media_recordings, never raised
    out of the lifecycle."""


class _Active:
    """An in-flight ffmpeg recording for one session."""

    __slots__ = ("process", "recording_id", "file_path", "log_file")

    def __init__(self, process, recording_id, file_path, log_file):
        self.process = process
        self.recording_id = recording_id
        self.file_path = file_path
        self.log_file = log_file


_lock = threading.Lock()
_active: dict[str, _Active] = {}


# --- command assembly --------------------------------------------------------


def build_ffmpeg_command(output_path: Path) -> list[str]:
    """Assemble the capture command from settings. Defaults reproduce the Day-1
    verified Brio/NVENC command; RECORDING_USE_TEST_SOURCE swaps the hardware
    inputs for a synthetic lavfi A/V source (dev/CI) while keeping every encoder
    flag identical."""
    s = settings
    cmd: list[str] = [s.RECORDING_FFMPEG_BIN, "-hide_banner", "-y"]

    if s.RECORDING_USE_TEST_SOURCE:
        # Synthetic A/V: same downstream flags, no camera/GPU needed.
        cmd += ["-f", "lavfi", "-i", f"testsrc=size={s.RECORDING_VIDEO_SIZE}:rate={s.RECORDING_FRAMERATE}"]
        cmd += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000"]
    else:
        # Brio video (MJPEG); big thread queue to absorb USB bursts.
        cmd += [
            "-thread_queue_size", str(s.RECORDING_THREAD_QUEUE_SIZE),
            "-f", s.RECORDING_VIDEO_INPUT_FORMAT,
            "-input_format", s.RECORDING_VIDEO_INPUT_PIXEL,
            "-video_size", s.RECORDING_VIDEO_SIZE,
            "-framerate", str(s.RECORDING_FRAMERATE),
            "-i", s.RECORDING_VIDEO_DEVICE,
        ]
        # ALSA audio, pinned by card name; its own thread queue.
        cmd += [
            "-thread_queue_size", str(s.RECORDING_THREAD_QUEUE_SIZE),
            "-f", s.RECORDING_AUDIO_INPUT_FORMAT,
            "-i", s.RECORDING_AUDIO_DEVICE,
        ]

    cmd += [
        "-c:v", s.RECORDING_VIDEO_CODEC,
        "-b:v", s.RECORDING_VIDEO_BITRATE,
        "-pix_fmt", s.RECORDING_PIX_FMT,
        "-vsync", s.RECORDING_VSYNC,
        "-c:a", s.RECORDING_AUDIO_CODEC,
        "-b:a", s.RECORDING_AUDIO_BITRATE,
        str(output_path),
    ]
    return cmd


def _bitrate_kbps(bitrate: str) -> int | None:
    """Parse an ffmpeg bitrate string ('5M', '5000k', '5000000') to kbps."""
    b = bitrate.strip().lower()
    try:
        if b.endswith("m"):
            return int(float(b[:-1]) * 1000)
        if b.endswith("k"):
            return int(float(b[:-1]))
        return int(int(b) / 1000)
    except ValueError:
        return None


def _confirm_devices() -> None:
    """Confirm the capture devices exist at runtime rather than assuming. Raises
    RecordingError (which becomes a logged failure) when the camera is absent."""
    if settings.RECORDING_USE_TEST_SOURCE:
        return
    video = Path(settings.RECORDING_VIDEO_DEVICE)
    if not video.exists():
        raise RecordingError(f"video device '{video}' not found")
    # ALSA audio is a logical name, not a path; ffmpeg's immediate-exit check
    # below catches a bad/busy audio device.


# --- lifecycle entry points --------------------------------------------------


def start_session_recording(db: Session, session: StudySession) -> MediaRecording | None:
    """Start recording for a session that just started. No-op when recording is
    disabled or already running for this session. Never raises."""
    if not settings.RECORDING_ENABLED:
        return None
    with _lock:
        if session.session_id in _active:
            return None

    now = now_utc()
    ts = now.strftime("%Y%m%dT%H%M%SZ")
    test_source = settings.RECORDING_USE_TEST_SOURCE
    file_name = f"{session.session_id}_{ts}.{settings.RECORDING_CONTAINER}"
    output_path = settings.recordings_dir / file_name
    cmd = build_ffmpeg_command(output_path)

    # Always create the row first (file_path is NOT NULL); a failure to start
    # then just flips its status to 'failed' with the error preserved.
    rec = MediaRecording(
        session_id=session.session_id,
        participant_id=session.participant_id,
        recording_type="av",
        device_name=None if test_source else settings.RECORDING_VIDEO_DEVICE,
        audio_device=None if test_source else settings.RECORDING_AUDIO_DEVICE,
        file_path=str(output_path),
        file_name=file_name,
        start_timestamp_utc=now.isoformat(),
        session_time_ms_at_start=compute_session_time_ms(session, now),
        status="pending",
        codec=settings.RECORDING_VIDEO_CODEC,
        container=settings.RECORDING_CONTAINER,
        resolution=settings.RECORDING_VIDEO_SIZE,
        fps=settings.RECORDING_FRAMERATE,
        bitrate_kbps=_bitrate_kbps(settings.RECORDING_VIDEO_BITRATE),
        pix_fmt=settings.RECORDING_PIX_FMT,
        ffmpeg_command=shlex.join(cmd),
    )
    db.add(rec)
    db.flush()

    try:
        settings.recordings_dir.mkdir(parents=True, exist_ok=True)
        settings.logs_dir.mkdir(parents=True, exist_ok=True)
        _confirm_devices()
        log_path = settings.logs_dir / f"ffmpeg_{session.session_id}_{ts}.log"
        log_file = open(log_path, "wb")
        proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=log_file, stderr=subprocess.STDOUT
        )
        # Catch an immediate exit (device busy, bad args) so it is logged as a
        # failed recording, not left as a stale 'recording' row.
        time.sleep(settings.RECORDING_START_SETTLE_S)
        if proc.poll() is not None:
            log_file.close()
            raise RecordingError(
                f"ffmpeg exited immediately (code {proc.returncode}); see {log_path}"
            )
    except Exception as exc:  # noqa: BLE001 -- a recording problem must never crash a session
        rec.status = "failed"
        rec.error_text = str(exc)
        rec.stop_timestamp_utc = now_utc().isoformat()
        record_timeline_event(
            db,
            session=session,
            source="recording",
            type="recording_failed",
            payload={
                "recording_id": rec.recording_id,
                "file_path": rec.file_path,
                "error": str(exc),
            },
            ref_table="media_recordings",
            ref_id=str(rec.recording_id),
        )
        db.commit()
        logger.warning("Recording failed to start for %s: %s", session.session_id, exc)
        return rec

    rec.status = "recording"
    with _lock:
        _active[session.session_id] = _Active(proc, rec.recording_id, output_path, log_file)
    record_timeline_event(
        db,
        session=session,
        source="recording",
        type="recording_started",
        payload={
            "recording_id": rec.recording_id,
            "file_path": rec.file_path,
            "codec": rec.codec,
            "device": rec.device_name,
        },
        ref_table="media_recordings",
        ref_id=str(rec.recording_id),
        now=now,
    )
    db.commit()
    logger.info("Recording started for %s -> %s", session.session_id, output_path)
    return rec


def stop_session_recording(db: Session, session: StudySession) -> MediaRecording | None:
    """Stop a session's recording gracefully (send 'q' so the mp4 trailer
    writes). No-op when nothing is recording for this session. Never raises."""
    with _lock:
        active = _active.pop(session.session_id, None)
    if active is None:
        return None

    proc = active.process
    # If ffmpeg already exited on its own before we asked it to stop, it died
    # mid-recording (e.g. a device that failed just after start) -- this is NOT a
    # clean finish, no matter what the timeline said during the session.
    already_exited = proc.poll() is not None
    status_final = "completed"
    error_text: str | None = None

    try:
        if not already_exited:
            # Graceful stop: 'q' on stdin tells ffmpeg to finalize the file.
            try:
                if proc.stdin is not None:
                    proc.stdin.write(b"q")
                    proc.stdin.flush()
                    proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass
            try:
                proc.wait(timeout=settings.RECORDING_STOP_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                # Last resort only. SIGTERM, then SIGKILL -- never SIGKILL first.
                logger.warning(
                    "ffmpeg ignored 'q' for %s; escalating to SIGTERM", session.session_id
                )
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
                status_final = "interrupted"
                error_text = "ffmpeg did not exit on 'q'; terminated (mp4 trailer may be partial)"
    finally:
        try:
            active.log_file.close()
        except Exception:  # noqa: BLE001
            pass

    # Research-integrity check: a 'completed' status must correspond to a real,
    # non-empty file from a clean ffmpeg exit. A process that died on its own, a
    # non-zero exit, or a missing/empty file is a FAILED capture -- we must never
    # record success for A/V that is not on disk (a gap is a logged failure row,
    # not a false success). This is what catches an early device failure that
    # slipped past the start-time settle check.
    returncode = proc.poll()
    out_path = Path(active.file_path)
    file_ok = out_path.exists() and out_path.stat().st_size > 0
    if already_exited:
        status_final = "failed"
        error_text = (
            f"ffmpeg exited on its own before stop (code {returncode}); no clean "
            "recording -- see the ffmpeg log in LOGS_DIR"
        )
    elif status_final == "completed" and returncode not in (0, None):
        status_final = "failed"
        error_text = f"ffmpeg exited with code {returncode}; see the ffmpeg log in LOGS_DIR"
    if status_final == "completed" and not file_ok:
        status_final = "failed"
        error_text = f"recording file missing or empty at stop ({out_path})"

    now = now_utc()
    rec = db.get(MediaRecording, active.recording_id)
    if rec is None:
        return None

    rec.stop_timestamp_utc = now.isoformat()
    rec.status = status_final
    if error_text:
        rec.error_text = error_text
    if rec.start_timestamp_utc:
        started = datetime.fromisoformat(rec.start_timestamp_utc)
        rec.duration_ms = max(0, int((now - started).total_seconds() * 1000))

    record_timeline_event(
        db,
        session=session,
        source="recording",
        type="recording_stopped",
        payload={
            "recording_id": rec.recording_id,
            "status": rec.status,
            "file_path": rec.file_path,
            "duration_ms": rec.duration_ms,
        },
        ref_table="media_recordings",
        ref_id=str(rec.recording_id),
        now=now,
    )
    db.commit()
    logger.info(
        "Recording stopped for %s (status=%s, %sms)",
        session.session_id,
        rec.status,
        rec.duration_ms,
    )
    return rec
