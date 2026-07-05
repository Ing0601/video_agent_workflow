import os
from .upload_to_tos import UploadToTOS
from .media_analyze import MediaAnalyze
from .task import Task
from .todo import TodoWrite
from typing import List, Dict, Any

TOOLS = {
    "UploadToTOS": UploadToTOS(),
    "MediaAnalyze": MediaAnalyze(),
    "TodoWrite": TodoWrite(),
    "Task": Task(),
}

AVAILABLE_TOOLS = {
    "main_agent": [
        ("UploadToTOS", UploadToTOS()),
        ("MediaAnalyze", MediaAnalyze()),
        ("TodoWrite", TodoWrite()),
        ("Task", Task()),

    ],
    "analyzer_agent": [
        ("UploadToTOS", UploadToTOS()),
        ("MediaAnalyze", MediaAnalyze()),
        ("TodoWrite", TodoWrite()),
    ],
}

def get_tool_schema(agent_type) -> List[Dict[str, Any]]:
    if agent_type not in AVAILABLE_TOOLS:
        raise ValueError(f"Invalid agent type: {agent_type}")
    return [tool[1].get_schema() for tool in AVAILABLE_TOOLS[agent_type]]

class registor():
    def __init__(self):
        pass



