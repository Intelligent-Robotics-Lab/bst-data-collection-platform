"""Test fixtures: a TestClient backed by an isolated in-memory SQLite DB.

Each test gets a fresh schema. The get_db dependency is overridden so tests
never touch the real data/bst.db. Foreign-key enforcement is on because the
PRAGMA listener in app.db.session is registered on the Engine class globally.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.session import get_db
from app.main import app
from app.models import Base
from app.services.protocol import register_protocols
from app.services.questionnaire import register_questionnaires


@pytest.fixture(autouse=True)
def _capture_off_by_default(monkeypatch):
    """Insulate tests from the developer's .env: recording and perception are OFF
    unless a test explicitly enables them (the lifecycle tests monkeypatch them on).

    Without this, RECORDING_ENABLED=true would spawn real ffmpeg on every session
    start, and PERCEPTION_ENABLED=true would poll the real orchestrator and add
    perception_polling_* timeline events -- making the suite depend on the host."""
    monkeypatch.setattr(settings, "RECORDING_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "PERCEPTION_ENABLED", False, raising=False)


@pytest.fixture
def _session_factory():
    """Fresh in-memory DB + schema, shared via a single connection (StaticPool).
    Yields a sessionmaker so multiple fixtures can hit the same in-memory DB."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # single shared connection for the in-memory DB
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    try:
        yield TestingSessionLocal
    finally:
        engine.dispose()


@pytest.fixture
def client(_session_factory):
    def override_get_db():
        db = _session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    # Plain TestClient (no context manager) so the lifespan does not run
    # create_all/ensure_directories against the real engine.
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def protocol_id(_session_factory):
    """Register the on-disk protocol configs into the test DB (mirrors startup)
    and return the registered protocol_id for the placeholder protocol."""
    db = _session_factory()
    try:
        protos = register_protocols(db)
        assert protos, "no protocol configs registered; expected bst_dtt_v1"
        return protos[0].protocol_id
    finally:
        db.close()


@pytest.fixture
def questionnaires(_session_factory):
    """Register the on-disk questionnaire configs into the test DB (mirrors
    startup). Returns the list of registered (key, version) tuples."""
    db = _session_factory()
    try:
        rows = register_questionnaires(db)
        assert rows, "no questionnaire configs registered; expected erq/bfi2s/etc."
        return [(r.questionnaire_key, r.version) for r in rows]
    finally:
        db.close()
