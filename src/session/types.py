from pydantic import BaseModel, Field
from typing import List, Dict, Any
from ..event.events import Event


class Session(BaseModel):
    """Session model"""
    session_id: str = Field(..., description="Session ID")
    user_id: str = Field(..., description="User ID")
    events: List[Event] = Field(default_factory=list, description="Events")
    state: Dict[str, Any] = Field(default_factory=dict, description="State")
    model_config = {"arbitrary_types_allowed": True}
    last_updated_time: float = 0