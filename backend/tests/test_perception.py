"""Perception ingestion tests (P0.9).

Parsing is checked against the REAL wrapped payload shapes from the live
orchestrator (asr_state.backend_result / emotion_state.prediction /
gesture_state.prediction), not the older flat shapes in the integration doc. The
HTTP source is verified GET-only (read-only contract) and outage-tolerant. The
lifecycle test drives real poller threads with an injected fake source.
"""

import time

import httpx
import pytest

from app.core.config import settings
from app.core.timeutil import now_utc
from app.models.session import StudySession
from app.models.signals import PerceptionEvent
from app.services import perception
from app.services.perception import store_reading
from app.services.perception_source import (
    HttpPollingSource,
    PerceptionReading,
    PerceptionSource,
    extract_fields,
)

# --- real wrapped payloads (captured live 2026-06-29) ------------------------

REAL_EMOTION = {
    "status": "ok",
    "emotion_state": {
        "frame_id": 9976,
        "server_ingest_timestamp": "2026-06-29T14:21:30.875449+00:00",
        "worker_finish_timestamp": "2026-06-29T14:21:30.917478+00:00",
        "active_model": "affect_hse_va",
        "face_detected": True,
        "bbox_xyxy": [428, 312, 535, 450],
        "prediction": {
            "timestamp_utc": "2026-06-29T14:21:30.875449+00:00",
            "task": "affect_dimensions",
            "backend_name": "affect_hse_va",
            "detected": True,
            "dominant_label": "angry",
            "confidence": 0.33771634101867676,
            "scores": {"angry": 0.337, "happy": 0.22, "neutral": 0.117},
            "valence": 0.06115180626511574,
            "arousal": 0.2653462886810303,
            "quadrant": "pleasant-active",
            "latency_ms": 11.86220208182931,
        },
    },
}

REAL_GESTURE = {
    "status": "ok",
    "gesture_state": {
        "frame_id": 9975,
        "server_ingest_timestamp": "2026-06-29T14:21:30.795732+00:00",
        "worker_finish_timestamp": "2026-06-29T14:21:30.900347+00:00",
        "active_model": "gesture_head_motion",
        "face_detected": True,
        "prediction": {
            "timestamp_utc": "2026-06-29T14:21:30.795732+00:00",
            "task": "gesture_recognition",
            "backend_name": "gesture_holistic_events",
            "instant_gesture": "none",
            "detected_gesture": "none",
            "confidence": 0.0,
            "motion": {"dx": -0.0001, "dy": 0.0028, "nod_state": "down"},
            "last_action": "shake_head",
            "face_detected": True,
            "latency_ms": 24.301119847223163,
        },
    },
}

REAL_ASR = {
    "status": "ok",
    "asr_state": {
        "chunk_id": 707,
        "server_ingest_timestamp": "2026-06-29T14:21:30.693798+00:00",
        "worker_finish_timestamp": "2026-06-29T14:21:30.908177+00:00",
        "active_model": "asr_riva",
        "backend_result": {
            "timestamp_utc": "2026-06-29T14:21:30.907334+00:00",
            "task": "speech_recognition",
            "backend_name": "asr_riva",
            "is_partial": False,
            "transcript": None,
            "latency_ms": None,
            "meta": {"language": "en-US", "raw_text": ""},
        },
    },
}


# --- extraction against the real shapes --------------------------------------


def test_extract_emotion_real_shape():
    f = extract_fields("emotion", REAL_EMOTION)
    assert f["detected_label"] == "angry"
    assert round(f["confidence"], 3) == 0.338
    assert round(f["valence"], 3) == 0.061
    assert round(f["arousal"], 3) == 0.265
    assert f["face_detected"] is True
    assert f["backend_name"] == "affect_hse_va"
    assert f["source_timestamp_utc"] == "2026-06-29T14:21:30.875449+00:00"


def test_extract_gesture_real_shape():
    f = extract_fields("gesture", REAL_GESTURE)
    assert f["detected_label"] == "none"      # a real detection value, logged as-is
    assert f["confidence"] == 0.0             # low confidence is still data
    assert f["face_detected"] is True
    assert f["backend_name"] == "gesture_holistic_events"
    assert f["latency_ms"] and f["latency_ms"] > 0


def test_extract_asr_real_shape():
    f = extract_fields("asr", REAL_ASR)
    assert f["transcript"] is None            # null transcript is a valid reading
    assert f["detected_label"] is None
    assert f["face_detected"] is None         # audio task, no face
    assert f["backend_name"] == "asr_riva"
    assert f["source_timestamp_utc"] == "2026-06-29T14:21:30.907334+00:00"


def test_extract_tolerates_empty_payload():
    f = extract_fields("emotion", {})         # never raises on missing keys
    assert all(v is None for v in f.values())


# --- HTTP source: read-only + outage tolerant --------------------------------


def _mock_source(handler) -> HttpPollingSource:
    return HttpPollingSource("http://orch:8000", 2.0, transport=httpx.MockTransport(handler))


def test_http_source_is_get_only():
    """READ-ONLY contract: the source may only ever issue GET requests."""
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.url.path == "/state/emotion":
            return httpx.Response(200, json=REAL_EMOTION)
        return httpx.Response(200, json={"status": "ok"})

    src = _mock_source(handler)
    src.fetch("emotion")
    src.health()
    src.close()
    assert methods and set(methods) == {"GET"}


def test_http_source_parses_and_keeps_raw():
    src = _mock_source(lambda r: httpx.Response(200, json=REAL_EMOTION))
    reading = src.fetch("emotion")
    src.close()
    assert reading.connection_status == "ok"
    assert reading.detected_label == "angry"
    assert reading.raw_payload == REAL_EMOTION      # full payload preserved


def test_http_source_unreachable_is_down_not_crash():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    reading = _mock_source(handler).fetch("emotion")
    assert reading.connection_status == "down"
    assert reading.raw_payload is None
    assert "refused" in (reading.error or "")


def test_http_source_non_200_is_down():
    reading = _mock_source(lambda r: httpx.Response(503)).fetch("gesture")
    assert reading.connection_status == "down"
    assert "503" in (reading.error or "")


# --- persistence -------------------------------------------------------------


def _running_session(client, _session_factory, pid="P800", sid="P800_S1") -> str:
    client.post("/participants", json={"participant_id": pid})
    client.post("/sessions", json={"session_id": sid, "participant_id": pid, "scenario_type": "bst_dtt"})
    client.post(f"/sessions/{sid}/start")
    return sid


def test_store_reading_persists_all_fields(client, _session_factory):
    sid = _running_session(client, _session_factory)
    src = _mock_source(lambda r: httpx.Response(200, json=REAL_EMOTION))
    reading = src.fetch("emotion")

    db = _session_factory()
    try:
        store_reading(db, db.get(StudySession, sid), reading)
        db.commit()
    finally:
        db.close()

    rows = client.get(f"/sessions/{sid}/perception-events", params={"task": "emotion"}).json()
    assert len(rows) == 1
    row = rows[0]
    assert row["task"] == "emotion"
    assert row["detected_label"] == "angry"
    assert row["face_detected"] == 1            # bool -> 0/1 for the DB
    assert row["connection_status"] == "ok"
    assert row["source"] == "ml"
    assert row["source_timestamp_utc"] == "2026-06-29T14:21:30.875449+00:00"
    assert '"dominant_label": "angry"' in row["raw_payload"]  # raw JSON kept


def test_low_confidence_and_missing_prediction_still_logged(client, _session_factory):
    sid = _running_session(client, _session_factory, pid="P801", sid="P801_S1")
    # confidence 0.0, no label -- a real low-signal reading, must NOT be dropped
    reading = PerceptionReading(
        task="gesture", connection_status="ok", received_at=now_utc(),
        detected_label=None, confidence=0.0, face_detected=False, raw_payload={"status": "ok"},
    )
    db = _session_factory()
    try:
        store_reading(db, db.get(StudySession, sid), reading)
        db.commit()
    finally:
        db.close()
    rows = client.get(f"/sessions/{sid}/perception-events", params={"task": "gesture"}).json()
    assert len(rows) == 1 and rows[0]["confidence"] == 0.0 and rows[0]["face_detected"] == 0


def test_down_gap_marker_is_logged(client, _session_factory):
    sid = _running_session(client, _session_factory, pid="P802", sid="P802_S1")
    reading = PerceptionReading(
        task="asr", connection_status="down", received_at=now_utc(), error="connection refused",
    )
    db = _session_factory()
    try:
        store_reading(db, db.get(StudySession, sid), reading)
        db.commit()
    finally:
        db.close()
    rows = client.get(f"/sessions/{sid}/perception-events", params={"task": "asr"}).json()
    assert len(rows) == 1
    assert rows[0]["connection_status"] == "down"
    assert rows[0]["raw_payload"] is None       # outage = gap marker, not silence


# --- lifecycle ---------------------------------------------------------------


class _FakeSource(PerceptionSource):
    """Yields a canned reading; no network."""

    def fetch(self, task: str) -> PerceptionReading:
        return PerceptionReading(
            task=task, connection_status="ok", received_at=now_utc(),
            source_timestamp_utc="2026-06-29T00:00:00+00:00", backend_name="fake",
            detected_label="happy", confidence=0.5, face_detected=True, raw_payload={"fake": True},
        )

    def close(self) -> None:
        return None


def test_perception_disabled_is_noop(client, _session_factory):
    """Default (PERCEPTION_ENABLED=false): no pollers, no rows."""
    sid = _running_session(client, _session_factory, pid="P803", sid="P803_S1")
    summary = client.get(f"/sessions/{sid}/perception-events/summary").json()
    assert all(t["count"] == 0 for t in summary["tasks"].values())


def test_perception_pollers_write_events(monkeypatch, tmp_path):
    """Real poller threads + injected fake source land rows. Uses a dedicated
    file-backed DB so each background thread gets its own connection (the shared
    in-memory StaticPool can't be written from multiple threads safely)."""
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from app.models import Base
    from app.models.participant import Participant

    engine = create_engine(
        f"sqlite:///{tmp_path / 'perc.db'}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    seed = TestSession()
    seed.add(Participant(participant_id="P804"))
    seed.add(StudySession(
        session_id="P804_S1", participant_id="P804", scenario_type="bst_dtt",
        state="running", start_timestamp_utc=now_utc().isoformat(),
    ))
    seed.commit()
    seed.close()

    monkeypatch.setattr(settings, "PERCEPTION_ENABLED", True)
    monkeypatch.setattr(settings, "PERCEPTION_ASR_ENABLED", False)
    monkeypatch.setattr(settings, "PERCEPTION_GESTURE_ENABLED", False)
    monkeypatch.setattr(settings, "PERCEPTION_EMOTION_ENABLED", True)
    monkeypatch.setattr(settings, "PERCEPTION_POLL_MS_EMOTION", 40)
    monkeypatch.setattr(perception, "SessionLocal", TestSession)
    monkeypatch.setattr(perception.manager, "_source_factory", lambda: _FakeSource())

    started = perception.manager.start("P804_S1")
    assert started == ["emotion"]  # only the enabled task
    time.sleep(0.3)
    perception.manager.stop("P804_S1")

    read = TestSession()
    try:
        rows = read.scalars(
            select(PerceptionEvent).where(PerceptionEvent.task == "emotion")
        ).all()
        assert len(rows) >= 2
        assert all(r.detected_label == "happy" and r.backend_name == "fake" for r in rows)
        assert all(r.face_detected == 1 for r in rows)
    finally:
        read.close()
    engine.dispose()
