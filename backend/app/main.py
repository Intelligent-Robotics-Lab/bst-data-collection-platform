"""FastAPI application entrypoint.

On startup: ensure data directories exist and create all tables (SQLite,
create_all is idempotent). Run with:
    uvicorn app.main:app --host $API_HOST --port $API_PORT
from the backend/ directory.
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import (
    exports,
    health,
    launch,
    notes,
    participants,
    perception,
    protocols,
    questionnaires,
    recordings,
    robot_events,
    self_reports,
    sessions,
    sync,
    tablet,
    trials,
)
from app.core.config import settings
from app.db import base as db_base  # noqa: F401  (registers all models on metadata)
from app.db.session import SessionLocal, engine
from app.models import Base
from app.services.backup import backup_database
from app.services.protocol import register_protocols
from app.services.questionnaire import register_questionnaires

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_directories()
    # Back up the existing DB BEFORE create_all so we capture the pre-run state.
    backup_database(reason="startup")
    Base.metadata.create_all(bind=engine)
    # Register protocol configs (additive/idempotent) so the trial API can
    # validate against them and the experimenter can discover protocol_ids.
    db = SessionLocal()
    try:
        register_protocols(db)
        # Register questionnaire configs (additive/idempotent) so the tablet can
        # render them and the experimenter can discover questionnaire keys.
        register_questionnaires(db)
    finally:
        db.close()
    yield


app = FastAPI(
    title="BST Data Collection Platform",
    version=settings.PLATFORM_VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(participants.router)
app.include_router(protocols.router)
app.include_router(sessions.router)
app.include_router(notes.router)
app.include_router(robot_events.router)
app.include_router(trials.router)
app.include_router(recordings.router)
app.include_router(questionnaires.router)
app.include_router(questionnaires.responses_router)
app.include_router(self_reports.router)
app.include_router(perception.router)
app.include_router(exports.router)
app.include_router(sync.router)
app.include_router(launch.router)
app.include_router(tablet.router)

# Minimal participant-intake UI (interim; superseded by the React+Vite app in a
# later phase). Served at /ui/.
app.mount("/ui", StaticFiles(directory=str(STATIC_DIR), html=True), name="ui")


@app.get("/", tags=["system"])
def root() -> dict:
    return {
        "name": "BST Data Collection Platform",
        "version": settings.PLATFORM_VERSION,
        "docs": "/docs",
        "intake_ui": "/ui/",
    }
