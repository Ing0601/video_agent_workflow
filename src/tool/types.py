from pydantic import BaseModel, Field
from typing import Any,Optional,List

class FunctionCall:
    def __init__(self, name="", arguments=""):
        self.name = name
        self.arguments = arguments

    def to_dict(self):
        return {"name": self.name, "arguments": self.arguments}

class ToolCall:
    def __init__(self, id="", type="",name="", arguments=""):
        self.id = id
        self.type = type
        self.function = FunctionCall(name=name, arguments=arguments)

    def to_dict(self):
        return {"id": self.id, "type": self.type, "function": self.function.to_dict()}

class ToolCallMessage:
    def __init__(self, content="", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []

class ToolCallChoice:
    def __init__(self, content="", tool_calls=None):
        self.message = ToolCallMessage(content=content, tool_calls=tool_calls)

class ToolCallResponse:
    def __init__(self, content="", tool_calls=None):
        self.choices = [ToolCallChoice(content=content, tool_calls=tool_calls)]


class ToolExeResult(BaseModel):
    """Tool execution result"""
    success: bool = Field(..., description="Success or failure")
    error: Optional[str] = Field(None, description="Error message")
    result: Any = Field(..., description="Result")

class ToolCallResult(BaseModel):
    """Tool call result after the tool is executed"""
    tool_call_id: str = Field(..., description="Tool call ID")
    function_name: str = Field(..., description="Function name")
    result: ToolExeResult = Field(..., description="Tool execution result")
