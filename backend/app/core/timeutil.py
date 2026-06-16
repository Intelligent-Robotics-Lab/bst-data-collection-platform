"""Time helpers. The server clock is the single source of truth for the
research record (see product_plan.md section 3: no cross-machine clock sync)."""

from datetime import datetime, timezone


def now_utc_iso() -> str:
    """Current UTC time as an ISO-8601 string with offset, e.g.
    '2026-06-16T18:30:00.123456+00:00'. Stored as TEXT throughout."""
    return datetime.now(timezone.utc).isoformat()
