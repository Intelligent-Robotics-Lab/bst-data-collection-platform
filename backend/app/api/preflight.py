"""Pre-session preflight gate API (P0.12).

  GET /preflight   run the checks and report readiness (read-only)

Session start enforces the same checks (see app/api/sessions.start): a blocking
failure refuses the start unless overridden, and the override is logged.
"""

from fastapi import APIRouter

from app.services.preflight import run_preflight

router = APIRouter(tags=["preflight"])


@router.get("/preflight")
def preflight() -> dict:
    return run_preflight()
