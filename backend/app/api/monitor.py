"""Live experiment-monitor API.

  POST /monitor   robot pushes its current monitor_state (fire-and-forget)
  GET  /monitor   tablet reads it (same-origin) to show Current SD + Trial State

Ephemeral UI-routing state, not research data (the measurements are the
self-reports / trials / perception). Accepts the robot's monitor_state shape
verbatim; the tablet uses trial_name and trial_state.
"""

from typing import Any

from fastapi import APIRouter, Body

from app.services.monitor import get_monitor, set_monitor

router = APIRouter(tags=["monitor"])


@router.post("/monitor")
def push_monitor(monitor: dict[str, Any] = Body(...)) -> dict:
    return set_monitor(monitor)


@router.get("/monitor")
def read_monitor() -> dict:
    return get_monitor()
