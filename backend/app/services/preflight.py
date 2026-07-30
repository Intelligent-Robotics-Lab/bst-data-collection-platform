"""Pre-session preflight gate (P0.12).

Real, machine-verified checks that gate session start, so a session cannot
silently run blind. Two pilots lost unrepeatable data because the old console
"checklist" was decorative tick-boxes: one ran with RECORDING_ENABLED=false (no
video), one with PERCEPTION_ENABLED=false (no perception). These checks verify
the actual runtime state instead.

Each check is one of:
  pass    - verified good
  warn    - advisory; never blocks (e.g. the tablet may connect a moment later)
  fail    - broken
  na      - not applicable (e.g. camera check when recording is disabled)

A check that is ``required`` and ``fail`` is BLOCKING: the platform refuses to
start the session unless the operator overrides, and the override is logged to
the timeline. Read-only: this module verifies state, it never changes it.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from app.core.config import settings
from app.services.perception_source import HttpPollingSource
from app.services.tablet import seconds_since_tablet_poll


def _check(id, label, category, status, required, detail):
    return {
        "id": id,
        "label": label,
        "category": category,
        "status": status,
        "required": required,
        "detail": detail,
    }


def _recording_checks() -> list[dict]:
    enabled = settings.RECORDING_ENABLED
    checks = [
        _check(
            "recording_enabled",
            "Recording enabled",
            "recording",
            "pass" if enabled else "fail",
            required=True,
            detail=(
                "RECORDING_ENABLED=true"
                if enabled
                else "RECORDING_ENABLED is false -- this session will capture NO video"
            ),
        )
    ]

    if not enabled:
        checks.append(_check("camera", "Camera present", "recording", "na", False,
                             "skipped (recording disabled)"))
        checks.append(_check("audio", "Audio device present", "recording", "na", False,
                             "skipped (recording disabled)"))
        return checks

    if settings.RECORDING_USE_TEST_SOURCE:
        checks.append(_check("camera", "Camera (test source)", "recording", "pass", True,
                             "RECORDING_USE_TEST_SOURCE=true (synthetic A/V)"))
        return checks

    # Real capture: the camera device must exist.
    device = settings.RECORDING_VIDEO_DEVICE
    cam_ok = Path(device).exists()
    checks.append(_check(
        "camera", "Camera present", "recording",
        "pass" if cam_ok else "fail", required=True,
        detail=(f"{device} present" if cam_ok else f"{device} not found"),
    ))

    # Audio: best-effort. We can confirm the configured ALSA card is enumerated
    # (catches "not plugged in"), but cannot fully verify access from here, so a
    # missing card is a WARNING, not a hard block. A capture with a bad audio
    # device still records video and is flagged 'failed' at stop.
    checks.append(_audio_check())
    return checks


def _audio_check() -> dict:
    device = settings.RECORDING_AUDIO_DEVICE  # e.g. "hw:CARD=BRIO,DEV=0"
    card = None
    if "CARD=" in device:
        card = device.split("CARD=", 1)[1].split(",", 1)[0]
    cards_file = Path("/proc/asound/cards")
    if card is None or not cards_file.exists():
        return _check("audio", "Audio device present", "recording", "warn", False,
                      f"could not verify audio device '{device}'")
    try:
        listed = cards_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return _check("audio", "Audio device present", "recording", "warn", False,
                      "could not read /proc/asound/cards")
    if card in listed:
        return _check("audio", "Audio device present", "recording", "pass", False,
                      f"ALSA card '{card}' present")
    return _check("audio", "Audio device present", "recording", "warn", False,
                  f"ALSA card '{card}' not found (recording may have no audio)")


def _perception_checks() -> list[dict]:
    enabled = settings.PERCEPTION_ENABLED
    checks = [
        _check(
            "perception_enabled",
            "Perception enabled",
            "perception",
            "pass" if enabled else "fail",
            required=True,
            detail=(
                "PERCEPTION_ENABLED=true"
                if enabled
                else "PERCEPTION_ENABLED is false -- this session will record NO perception data"
            ),
        )
    ]
    if not enabled:
        checks.append(_check("perception_reachable", "Perception orchestrator reachable",
                             "perception", "na", False, "skipped (perception disabled)"))
        checks.append(_check("perception_gateway", "Perception gateway streaming",
                             "perception", "na", False, "skipped (perception disabled)"))
        return checks

    source = HttpPollingSource(
        settings.PERCEPTION_BASE_URL, settings.PERCEPTION_HTTP_TIMEOUT_MS / 1000.0
    )
    try:
        reachable = source.health()
        checks.append(_check(
            "perception_reachable", "Perception orchestrator reachable", "perception",
            "pass" if reachable else "fail", required=True,
            detail=(
                f"GET {settings.PERCEPTION_BASE_URL}/health OK"
                if reachable
                else f"{settings.PERCEPTION_BASE_URL}/health did not return 200"
            ),
        ))
        # /health only proves the orchestrator process is alive; its media gateway
        # can be disconnected (or connected but forwarding no samples) while
        # /health still returns 200 -- a session would then run and record NO
        # perception data despite a green checklist. Only meaningful to probe when
        # the orchestrator itself answered.
        if reachable:
            checks.append(_perception_gateway_check(source))
    finally:
        source.close()
    return checks


def _perception_gateway_check(source) -> dict:
    """Verify the orchestrator's media gateway is actually connected and streaming,
    using the same /debug/gateway-status signal its live dashboard shows.

    - gateway absent/unreachable/unparseable -> WARN (non-contract debug endpoint;
      an older orchestrator may not expose it, so we advise rather than block).
    - session.connected false -> FAIL (blocking): perception is dead; no data will
      be recorded even though /health is green.
    - connected but zero frames/audio forwarded yet -> WARN: link is up but nothing
      is streaming; the operator should confirm on /debug/live before starting.
    """
    data = source.gateway_status()
    if data is None:
        return _check("perception_gateway", "Perception gateway streaming", "perception",
                      "warn", False,
                      "could not read /debug/gateway-status; cannot verify the media gateway")

    session = data.get("session") or {}
    if not session.get("connected"):
        return _check(
            "perception_gateway", "Perception gateway streaming", "perception",
            "fail", required=True,
            detail=(
                "orchestrator is up but its media gateway is DISCONNECTED "
                f"(pipeline_state={session.get('pipeline_state')!r}, "
                f"last_error={session.get('last_error')!r}) -- "
                "NO perception data will be recorded"
            ),
        )

    video = data.get("video") or {}
    audio = data.get("audio") or {}
    frames = video.get("forwarded_frame_count") or 0
    chunks = audio.get("forwarded_audio_chunk_count") or 0
    last_sample = video.get("last_sample_timestamp_utc") or audio.get("last_sample_timestamp_utc")
    if not last_sample and not frames and not chunks:
        return _check(
            "perception_gateway", "Perception gateway streaming", "perception",
            "warn", False,
            "gateway session connected but 0 frames / 0 audio chunks forwarded so "
            "far (no samples seen); perception may not be streaming -- confirm on "
            "/debug/live before starting",
        )

    return _check(
        "perception_gateway", "Perception gateway streaming", "perception",
        "pass", required=True,
        detail=(
            f"gateway connected; {frames} frames / {chunks} audio chunks forwarded "
            f"(last sample {last_sample})"
        ),
    )


def _storage_check() -> dict:
    path = settings.recordings_dir
    try:
        path.mkdir(parents=True, exist_ok=True)
        free_gb = shutil.disk_usage(path).free / (1024 ** 3)
    except OSError as exc:
        return _check("disk_free", "Recordings storage", "storage", "fail", True,
                      f"cannot stat {path}: {exc}")
    need = settings.PREFLIGHT_MIN_FREE_GB
    ok = free_gb >= need
    return _check(
        "disk_free", "Recordings storage", "storage",
        "pass" if ok else "fail", required=True,
        detail=f"{free_gb:.1f} GB free at {path} (need >= {need:.0f} GB)",
    )


def _tablet_check() -> dict:
    since = seconds_since_tablet_poll()
    window = settings.PREFLIGHT_TABLET_STALE_S
    if since is None:
        return _check("tablet_connected", "Tablet connected", "tablet", "warn", False,
                      "no tablet has polled yet (open the tablet page)")
    if since <= window:
        return _check("tablet_connected", "Tablet connected", "tablet", "pass", False,
                      f"tablet polled {since:.0f}s ago")
    return _check("tablet_connected", "Tablet connected", "tablet", "warn", False,
                  f"tablet last polled {since:.0f}s ago (> {window:.0f}s; may be disconnected)")


def run_preflight() -> dict:
    """Run every check and summarize. Read-only."""
    checks: list[dict] = []
    checks += _recording_checks()
    checks += _perception_checks()
    checks.append(_storage_check())
    checks.append(_tablet_check())

    blocking = [c for c in checks if c["required"] and c["status"] == "fail"]
    return {
        "ready": not blocking,
        "blocking": blocking,
        "counts": {
            "pass": sum(1 for c in checks if c["status"] == "pass"),
            "warn": sum(1 for c in checks if c["status"] == "warn"),
            "fail": sum(1 for c in checks if c["status"] == "fail"),
            "na": sum(1 for c in checks if c["status"] == "na"),
        },
        "checks": checks,
    }
