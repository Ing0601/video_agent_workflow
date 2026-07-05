"""
Event System for the app.
Each user message, model response, tool response, and subagent interaction generates events.
"""

from re import S
from typing import Dict, Any, List, Optional
import uuid
import time
from pydantic import BaseModel, Field, ConfigDict
from ..tool.types import ToolCallResult


class EventType:
    """Event types for the app."""

    # agent
    USER_MESSAGE = "user_message"
    RESPONSE_CHUNK = "response_chunk"
    COMPLETE_CHOICE = "complete_choice"       # may be tool call completion
    COMPLETE_RESPONSE = "complete_response"   # final completion

    # tool
    TOOL_CALL = "tool_call"
    TOOL_RESPONSE = "tool_response"

    # task
    TASK_START = "task_start"
    TASK_COMPLETE = "task_complete"
    TASK_ERROR = "task_error"

    # error
    ERROR = "error"


class Event(BaseModel):
    """Event class"""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    type: str = Field(..., description="Type of the event")
    event_id: str = Field(..., description="Unique event identifier")
    user_id: str = Field(..., description="User ID")
    session_id: str = Field(..., description="Session ID")
    invocation_id: str = Field(..., description="Invocation ID")
    author: str = Field(..., description="Author of the event")
    timestamp: float = Field(..., description="Timestamp of the event")
    content: Optional[str] = Field(None, description="Event content")
    tool_calls: Optional[List[Dict[str, Any]]] = Field(None, description="Tool calls")
    tool_result: Optional[ToolCallResult] = Field(None, description="Tool results")
    finish_reason: Optional[str] = Field(None, description="Finish reason")
    model: Optional[str] = Field(None, description="Model name")
    usage: Optional[int] = Field(None, description="Usage")
    error: Optional[str] = Field(None, description="Error message")

    def to_dict(self):
        return self.model_dump_json()
