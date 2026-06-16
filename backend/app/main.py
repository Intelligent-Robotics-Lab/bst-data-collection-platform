"""FastAPI application entrypoint.

On startup: ensure data directories exist and create all tables (SQLite,
create_all is idempotent). Run with:
    uvicorn app.main:app --host $API_HOST --port $API_PORT
from the backend/ directory.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health, participants
from app.core.config import settings
from app.db import base as db_base  # noqa: F401  (registers all models on metadata)
from app.db.session import engine
from app.models import Base


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_directories()
    Base.metadata.create_all(bind=engine)
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


@app.get("/", tags=["system"])
def root() -> dict:
    return {
        "name": "BST Data Collection Platform",
        "version": settings.PLATFORM_VERSION,
        "docs": "/docs",
    }
