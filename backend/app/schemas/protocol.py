"""Pydantic schema for the registered-protocols listing."""

from typing import Optional

from pydantic import BaseModel, ConfigDict


class ProtocolRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    protocol_id: int
    protocol_key: str
    version: str
    title: Optional[str] = None
