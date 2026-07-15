"""Live experiment-monitor mirror.

The fine within-trial detail the participant tablet shows during rehearsal --
the current SD (trial_name) and the current trial state (SD / Prompting /
Reinforcement / HP SD / Retry / Feedback) -- lives only in the robot's
monitor_state.json; the platform's sync gates are too coarse to reproduce it
(and would lag the SD by one). So the robot pushes its monitor state here and the
tablet reads it same-origin.

Ephemeral in-memory routing state (one interaction at a time), like the tablet
assignment slot -- not research data. Each push bumps a monotonic revision.
"""

from __future__ import annotations

import threading

from app.core.timeutil import now_utc_iso

_lock = threading.Lock()
_state: dict = {"revision": 0, "updated_at": None, "monitor": None}


def set_monitor(monitor: dict) -> dict:
    """Store the latest monitor state pushed by the robot (verbatim)."""
    with _lock:
        _state["revision"] += 1
        _state["updated_at"] = now_utc_iso()
        _state["monitor"] = monitor
        return dict(_state)


def get_monitor() -> dict:
    with _lock:
        return dict(_state)
