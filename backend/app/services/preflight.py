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
        return checks

    source = HttpPollingSource(
        settings.PERCEPTION_BASE_URL, settings.PERCEPTION_HTTP_TIMEOUT_MS / 1000.0
    )
    try:
        reachable = source.health()
    finally:
        source.close()
    checks.append(_check(
        "perception_reachable", "Perception orchestrator reachable", "perception",
        "pass" if reachable else "fail", required=True,
        detail=(
            f"GET {settings.PERCEPTION_BASE_URL}/health OK"
            if reachable
            else f"{settings.PERCEPTION_BASE_URL}/health did not return 200"
        ),
    ))
    return checks


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
