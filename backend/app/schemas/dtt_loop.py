"""Pydantic schema for reading generated dtt_loops rows."""

from typing import Optional

from pydantic import BaseModel, ConfigDict


class DttLoopRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    loop_id: int
    session_id: str
    participant_id: str
    loop_index: int
    sequence_position: Optional[int] = None
    function_class: str
    sd_id: Optional[str] = None
    is_problem: Optional[str] = None
    support_condition: Optional[int] = None
    pb_order_group: Optional[int] = None
    created_at: str
