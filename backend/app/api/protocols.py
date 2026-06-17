"""Registered-protocols API.

Read-only discovery of the DTT protocol configs registered at startup. The
experimenter assigns a session's protocol_id from this list; the trial API
validates against the parsed config. Config content is participant-independent.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.dtt import DttProtocol
from app.schemas.protocol import ProtocolRead
from app.services.protocol import get_protocol_config

router = APIRouter(prefix="/protocols", tags=["protocols"])


@router.get("", response_model=list[ProtocolRead])
def list_protocols(db: Session = Depends(get_db)):
    return db.scalars(select(DttProtocol).order_by(DttProtocol.protocol_id)).all()


@router.get("/{protocol_id}/config")
def get_config(protocol_id: int, db: Session = Depends(get_db)) -> dict:
    """Return the parsed protocol config (phases, sds, prompt_levels, skill steps)."""
    cfg = get_protocol_config(db, protocol_id)
    if cfg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no registered protocol with protocol_id {protocol_id}",
        )
    return cfg
