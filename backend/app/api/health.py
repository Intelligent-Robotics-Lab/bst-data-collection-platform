"""Liveness and version endpoints."""

from fastapi import APIRouter

from app.core.config import settings

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/version")
def version() -> dict:
    return {
        "name": "BST Data Collection Platform",
        "version": settings.PLATFORM_VERSION,
    }
