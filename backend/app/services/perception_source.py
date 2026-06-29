"""Perception signal source interface + HTTP polling implementation (P0.9).

This is the swap point named in perception_integration.md section 7: callers
depend on the ``PerceptionSource`` interface (one method to fetch a reading per
task), so a future WebSocket/LSL push source can replace polling without touching
the storage layer or the data model.

READ-ONLY CONTRACT: the polling source only ever issues HTTP GET against the
orchestrator's ``/state/*`` and ``/health`` endpoints. It never POSTs, never
mutates, never reconfigures the perception stack. The orchestrator is another
team's live system; we poll, log, and get out of the way.

Payload shapes are taken from the LIVE orchestrator (2026-06, backends
``asr_riva`` / ``affect_hse_va`` / ``gesture_holistic_events``), which wrap the
prediction differently from the older shapes sketched in the integration doc:

    /state/asr      -> {"status", "asr_state":     {..., "backend_result": {...}}}
    /state/emotion  -> {"status", "emotion_state": {..., "prediction":     {...}}}
    /state/gesture  -> {"status", "gesture_state": {..., "prediction":     {...}}}

We store the FULL response as raw_payload and extract a known subset defensively
(every field via .get, missing/null is logged as-is -- signal quality is data).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

import httpx

from app.core.timeutil import now_utc

# Wrapper key and nested-result key per task, from the live orchestrator.
_STATE_KEY = {"asr": "asr_state", "emotion": "emotion_state", "gesture": "gesture_state"}
_RESULT_KEY = {"asr": "backend_result", "emotion": "prediction", "gesture": "prediction"}
TASKS = ("asr", "emotion", "gesture")


@dataclass
class PerceptionReading:
    """One snapshot from one task. ``connection_status`` is ok | degraded | down;
    a 'down' reading is a gap marker (raw_payload None) written during an outage."""

    task: str
    connection_status: str
    received_at: datetime
    source_timestamp_utc: str | None = None
    backend_name: str | None = None
    detected_label: str | None = None
    confidence: float | None = None
    valence: float | None = None
    arousal: float | None = None
    transcript: str | None = None
    face_detected: bool | None = None
    latency_ms: float | None = None
    raw_payload: dict | None = None
    error: str | None = None


def extract_fields(task: str, payload: dict) -> dict:
    """Pull the known subset out of a real /state/<task> response. Tolerant of
    missing keys; returns only the extracted columns (raw payload kept separately)."""
    state = payload.get(_STATE_KEY.get(task), {}) or {}
    result = state.get(_RESULT_KEY.get(task), {}) or {}

    # face_detected lives on the *_state wrapper for video tasks; ASR has none.
    face = state.get("face_detected")
    if face is None:
        face = result.get("face_detected")

    detected_label = None
    if task == "emotion":
        detected_label = result.get("dominant_label")
    elif task == "gesture":
        detected_label = result.get("detected_gesture")

    return {
        "source_timestamp_utc": (
            result.get("timestamp_utc")
            or state.get("worker_finish_timestamp")
            or state.get("server_ingest_timestamp")
        ),
        "backend_name": result.get("backend_name") or state.get("active_model"),
        "detected_label": detected_label,
        "confidence": result.get("confidence"),
        "valence": result.get("valence"),
        "arousal": result.get("arousal"),
        "transcript": result.get("transcript"),
        "face_detected": face,
        "latency_ms": result.get("latency_ms"),
    }


class PerceptionSource(ABC):
    """A source of perception readings. ``fetch`` returns one reading for one task
    (never raises -- a failure is a 'down' reading). Polling is one implementation;
    a push (WebSocket/LSL) source can implement the same interface later."""

    @abstractmethod
    def fetch(self, task: str) -> PerceptionReading: ...

    def health(self) -> bool:  # pragma: no cover - overridden where meaningful
        return True

    def close(self) -> None:  # pragma: no cover - default no-op
        return None


class HttpPollingSource(PerceptionSource):
    """Polls the orchestrator's read-only state endpoints over localhost HTTP.

    GET-ONLY: the only HTTP methods this class can issue are ``client.get`` for a
    state endpoint and ``client.get`` for ``/health``. There is deliberately no
    code path that POSTs or mutates the orchestrator.
    """

    def __init__(self, base_url: str, timeout_s: float, transport: httpx.BaseTransport | None = None):
        self._base = base_url.rstrip("/")
        # transport injection is for tests (httpx.MockTransport); prod passes None.
        self._client = httpx.Client(timeout=timeout_s, transport=transport)

    def fetch(self, task: str) -> PerceptionReading:
        url = f"{self._base}/state/{task}"
        now = now_utc()
        try:
            resp = self._client.get(url)  # READ-ONLY
        except Exception as exc:  # noqa: BLE001 -- an outage is data, never a crash
            return PerceptionReading(task=task, connection_status="down", received_at=now, error=str(exc))
        if resp.status_code != 200:
            return PerceptionReading(
                task=task, connection_status="down", received_at=now,
                error=f"HTTP {resp.status_code}",
            )
        try:
            payload = resp.json()
        except Exception as exc:  # noqa: BLE001 -- malformed body is a degraded signal, logged
            return PerceptionReading(
                task=task, connection_status="degraded", received_at=now,
                error=f"non-JSON body: {exc}",
            )

        fields = extract_fields(task, payload)
        status_field = payload.get("status")
        conn = "ok" if status_field in (None, "ok") else "degraded"
        return PerceptionReading(
            task=task, connection_status=conn, received_at=now, raw_payload=payload, **fields
        )

    def health(self) -> bool:
        try:
            return self._client.get(f"{self._base}/health").status_code == 200  # READ-ONLY
        except Exception:  # noqa: BLE001
            return False

    def close(self) -> None:
        self._client.close()
