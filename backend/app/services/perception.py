"""Perception ingestion manager (P0.9).

Runs one background poller thread per task on its configured interval, started
when a session starts and stopped when it stops. Each poll writes one
``perception_events`` row -- including when the prediction is missing/low
confidence (signal quality is data) -- and, when the orchestrator is unreachable,
a 'down' gap-marker row plus a one-time ``perception_outage`` health event and a
timeline transition (outages are data, not crashes).

Threading model mirrors the recording service: the lab runs one session in one
uvicorn process. Each poller owns its own DB Session (Sessions are not
thread-safe) and its own ``PerceptionSource`` (so HTTP clients are not shared
across threads). The source is created via an injectable factory so a future
push source -- or a test fake -- drops in without touching this manager.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Callable

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.session import StudySession
from app.models.signals import PerceptionEvent
from app.models.system import SystemHealthEvent
from app.services.perception_source import HttpPollingSource, PerceptionReading, PerceptionSource
from app.services.timeline import compute_session_time_ms, record_timeline_event

logger = logging.getLogger("bst.perception")

SourceFactory = Callable[[], PerceptionSource]


def _to_int_bool(value: bool | None) -> int | None:
    return None if value is None else int(bool(value))


def store_reading(db: Session, session: StudySession, reading: PerceptionReading) -> PerceptionEvent:
    """Map one reading to a perception_events row and write it. Every reading is
    stored, including empty/low-confidence ones and 'down' gap markers."""
    now = reading.received_at
    event = PerceptionEvent(
        session_id=session.session_id,
        participant_id=session.participant_id,
        task=reading.task,
        source="ml",
        backend_name=reading.backend_name,
        source_timestamp_utc=reading.source_timestamp_utc,
        received_timestamp_utc=now.isoformat(),
        session_time_ms=compute_session_time_ms(session, now),
        detected_label=reading.detected_label,
        confidence=reading.confidence,
        valence=reading.valence,
        arousal=reading.arousal,
        transcript=reading.transcript,
        face_detected=_to_int_bool(reading.face_detected),
        latency_ms=reading.latency_ms,
        connection_status=reading.connection_status,
        raw_payload=json.dumps(reading.raw_payload) if reading.raw_payload is not None else None,
    )
    db.add(event)
    db.flush()
    return event


def _default_source_factory() -> PerceptionSource:
    return HttpPollingSource(
        settings.PERCEPTION_BASE_URL, settings.PERCEPTION_HTTP_TIMEOUT_MS / 1000.0
    )


class _Poller(threading.Thread):
    """One task, one interval. Polls, persists, and logs outage/recovery."""

    def __init__(self, session_id: str, task: str, interval_s: float, source: PerceptionSource):
        super().__init__(daemon=True, name=f"perception-{task}-{session_id}")
        self._session_id = session_id
        self._task = task
        self._interval = interval_s
        self._source = source
        # NOTE: not named _stop -- that shadows threading.Thread._stop(), which
        # Thread.join() calls internally.
        self._stop_event = threading.Event()
        self._link = "up"  # connection state; first failure logs a transition

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        try:
            while not self._stop_event.is_set():
                t0 = time.monotonic()
                reading = self._source.fetch(self._task)  # never raises
                self._persist(reading)
                # Respect the interval (don't hammer the orchestrator); subtract
                # the time already spent on the request.
                self._stop_event.wait(max(0.0, self._interval - (time.monotonic() - t0)))
        finally:
            self._source.close()

    def _persist(self, reading: PerceptionReading) -> None:
        db = SessionLocal()
        try:
            session = db.get(StudySession, self._session_id)
            if session is None:
                return
            store_reading(db, session, reading)
            self._log_transition(db, session, reading)
            if settings.PERCEPTION_TIMELINE_EVERY_READING:
                record_timeline_event(
                    db, session=session, source="perception", type="perception_reading",
                    payload={"task": self._task, "label": reading.detected_label,
                             "connection_status": reading.connection_status},
                    ref_table="perception_events", now=reading.received_at,
                )
            db.commit()
        except Exception:  # noqa: BLE001 -- a logging failure must not kill the poller
            logger.exception("perception persist failed (%s/%s)", self._task, self._session_id)
            db.rollback()
        finally:
            db.close()

    def _log_transition(self, db: Session, session: StudySession, reading: PerceptionReading) -> None:
        new = "down" if reading.connection_status == "down" else "up"
        if new == self._link:
            return
        self._link = new
        if new == "down":
            db.add(
                SystemHealthEvent(
                    session_id=session.session_id,
                    type="perception_outage",
                    severity="warning",
                    detail_json=json.dumps({"task": self._task, "error": reading.error}),
                    timestamp_utc=reading.received_at.isoformat(),
                )
            )
            record_timeline_event(
                db, session=session, source="perception", type="perception_outage_started",
                payload={"task": self._task, "error": reading.error},
                ref_table="system_health_events", now=reading.received_at,
            )
            logger.warning("perception outage (%s): %s", self._task, reading.error)
        else:
            record_timeline_event(
                db, session=session, source="perception", type="perception_recovered",
                payload={"task": self._task}, now=reading.received_at,
            )
            logger.info("perception recovered (%s)", self._task)


class PerceptionManager:
    """Owns the per-session poller threads. Injectable source factory for tests."""

    def __init__(self, source_factory: SourceFactory = _default_source_factory):
        self._lock = threading.Lock()
        self._pollers: dict[str, list[_Poller]] = {}
        self._source_factory = source_factory

    def start(self, session_id: str) -> list[str]:
        """Spawn the enabled task pollers for a session. No-op when perception is
        disabled or already running. Returns the tasks started."""
        if not settings.PERCEPTION_ENABLED:
            return []
        plan = [
            ("asr", settings.PERCEPTION_POLL_MS_ASR, settings.PERCEPTION_ASR_ENABLED),
            ("emotion", settings.PERCEPTION_POLL_MS_EMOTION, settings.PERCEPTION_EMOTION_ENABLED),
            ("gesture", settings.PERCEPTION_POLL_MS_GESTURE, settings.PERCEPTION_GESTURE_ENABLED),
        ]
        with self._lock:
            if session_id in self._pollers:
                return []
            pollers = [
                _Poller(session_id, task, interval_ms / 1000.0, self._source_factory())
                for task, interval_ms, enabled in plan
                if enabled
            ]
            self._pollers[session_id] = pollers
        for p in pollers:
            p.start()
        started = [p._task for p in pollers]
        logger.info("perception polling started for %s: %s", session_id, started)
        return started

    def stop(self, session_id: str) -> list[str]:
        with self._lock:
            pollers = self._pollers.pop(session_id, None)
        if not pollers:
            return []
        for p in pollers:
            p.stop()
        for p in pollers:
            p.join(timeout=3.0)
        stopped = [p._task for p in pollers]
        logger.info("perception polling stopped for %s: %s", session_id, stopped)
        return stopped


# Module-level singleton (one running process per lab station).
manager = PerceptionManager()


def start_session_perception(db: Session, session: StudySession) -> None:
    """Start perception polling for a session that just started. Never raises."""
    started = manager.start(session.session_id)
    if started:
        record_timeline_event(
            db, session=session, source="perception", type="perception_polling_started",
            payload={"tasks": started, "base_url": settings.PERCEPTION_BASE_URL},
            ref_table="sessions", ref_id=session.session_id,
        )
        db.commit()


def stop_session_perception(db: Session, session: StudySession) -> None:
    """Stop perception polling for a session. Never raises."""
    stopped = manager.stop(session.session_id)
    if stopped:
        record_timeline_event(
            db, session=session, source="perception", type="perception_polling_stopped",
            payload={"tasks": stopped}, ref_table="sessions", ref_id=session.session_id,
        )
        db.commit()
