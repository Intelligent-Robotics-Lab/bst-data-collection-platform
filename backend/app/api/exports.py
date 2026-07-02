"""Session export API (P0.11).

POST triggers a read-only export of one session (raw per-table dumps + joined
analysis frames + data dictionary) to EXPORTS_DIR and records a provenance row.
GET lists the export-registry rows for the session.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.system import Export
from app.schemas.export import ExportRead, ExportResult
from app.services.export import export_session
from app.services.session_service import get_session_or_404

router = APIRouter(prefix="/sessions/{session_id}/export", tags=["exports"])


@router.post("", response_model=ExportResult, status_code=status.HTTP_201_CREATED)
def create_export(session_id: str, db: Session = Depends(get_db)):
    return export_session(db, session_id)


@router.get("", response_model=list[ExportRead])
def list_exports(session_id: str, db: Session = Depends(get_db)):
    get_session_or_404(db, session_id)
    return db.scalars(
        select(Export)
        .where(Export.session_id == session_id)
        .order_by(Export.export_id)
    ).all()
