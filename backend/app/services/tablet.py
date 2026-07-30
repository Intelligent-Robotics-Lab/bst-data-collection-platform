"""Push-to-tablet assignment store (P0.6).

The participant tablet shows exactly the form the experimenter has pushed. The
assignment is ephemeral UI-routing state (which screen is live now), NOT research
data -- the responses themselves are persisted in their own tables -- so it lives
in memory rather than the DB. The lab runs one tablet at a time, so a single
current slot is sufficient.

Each push bumps a monotonic ``revision`` so the tablet's poll loop can detect a
new form and switch without participant action.
"""

from __future__ import annotations

import threading
import time

from app.core.timeutil import now_utc_iso

_lock = threading.Lock()

# Monotonic timestamp of the tablet's last poll of /tablet/assignment. Used by
# the preflight gate to tell whether a tablet is actually connected (it polls
# every ~1.5s). None until the first poll.
_last_poll_monotonic: float | None = None


def mark_tablet_poll() -> None:
    global _last_poll_monotonic
    with _lock:
        _last_poll_monotonic = time.monotonic()


def seconds_since_tablet_poll() -> float | None:
    """Seconds since the tablet last polled, or None if it never has."""
    with _lock:
        if _last_poll_monotonic is None:
            return None
    return time.monotonic() - _last_poll_monotonic
_state: dict = {
    "revision": 0,
    "form_type": "idle",  # idle | questionnaire | self_report
    "session_id": None,
    "questionnaire_key": None,
    "questionnaire_version": None,
    "self_report_context": None,
    "message": None,
    "pushed_at": None,
}


def get_assignment() -> dict:
    with _lock:
        return dict(_state)


def set_assignment(
    *,
    form_type: str,
    session_id: str | None = None,
    questionnaire_key: str | None = None,
    questionnaire_version: str | None = None,
    self_report_context: dict | None = None,
    message: str | None = None,
) -> dict:
    with _lock:
        _state.update(
            {
                "revision": _state["revision"] + 1,
                "form_type": form_type,
                "session_id": session_id,
                "questionnaire_key": questionnaire_key,
                "questionnaire_version": questionnaire_version,
                "self_report_context": self_report_context,
                "message": message,
                "pushed_at": now_utc_iso(),
            }
        )
        return dict(_state)


def clear_assignment() -> dict:
    return set_assignment(form_type="idle", message="Waiting for the next form.")
