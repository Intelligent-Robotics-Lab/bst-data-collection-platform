"""Pydantic schemas for session export."""

from typing import Optional

from pydantic import BaseModel, ConfigDict


class ExportResult(BaseModel):
    """Manifest returned when a session export completes."""

    export_id: int
    session_id: str
    scope: str
    export_dir: str
    status: str
    files: list[str]
    row_counts: dict[str, int]
    completed_at: str


class ExportRead(BaseModel):
    """A persisted export-registry row (provenance)."""

    model_config = ConfigDict(from_attributes=True)

    export_id: int
    session_id: Optional[str] = None
    scope: str
    export_dir: str
    status: str
    platform_version: Optional[str] = None
    completed_at: Optional[str] = None
    created_at: str
