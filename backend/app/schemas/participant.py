"""Pydantic schemas for the participants API."""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

ConsentStatus = Literal["consented", "not_consented", "withdrawn"]
MediaConsent = Literal["granted", "denied", "withdrawn", "not_asked"]


class ParticipantCreate(BaseModel):
    participant_id: str = Field(..., examples=["P001"])
    consent_status: ConsentStatus = "not_consented"
    media_recording_consent: MediaConsent = "not_asked"
    notes: Optional[str] = None


class ParticipantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    participant_id: str
    consent_status: ConsentStatus
    media_recording_consent: MediaConsent
    notes: Optional[str] = None
    created_at: str
