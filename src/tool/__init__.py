from .base import BaseTool
from .upload_to_tos import UploadToTOS
from .media_analyze import MediaAnalyze
from typing import List, Dict, Any


TOOLS = {
    "UploadToTOS": UploadToTOS(),
    "MediaAnalyze": MediaAnalyze(),
}

AVAILABLE_TOOLS = {
    "main_agent": [
        ("UploadToTOS", UploadToTOS()),
        ("MediaAnalyze", MediaAnalyze()),
    ],
}

def get_tool_schema(agent_type: str) -> List[Dict[str, Any]]:
    if agent_type not in AVAILABLE_TOOLS:
        raise ValueError(f"Invalid agent type: {agent_type}")
    return [tool[1].get_schema() for tool in AVAILABLE_TOOLS[agent_type]]

async def execute_tool(tool_name: str, **kwargs) -> Dict[str, Any]:
    if tool_name not in TOOLS:
        return {
            "success": False,
            "error": f"Unknown tool: {tool_name}",
            "available_tools": list(TOOLS.keys()),
        }

    tool = TOOLS[tool_name]
    result = await tool.execute(**kwargs)
    return result
