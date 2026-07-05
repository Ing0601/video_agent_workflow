import json
from datetime import datetime
from typing import Any, Dict


def workflow_event(
    event: str,
    task_id: str,
    node: str | None = None,
    message: str | None = None,
    **payload: Any,
) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "event": event,
        "task_id": task_id,
        "timestamp": datetime.utcnow().isoformat(),
    }
    if node:
        data["node"] = node
    if message:
        data["message"] = message
    data.update(payload)
    return data


def sse_pack(data: Dict[str, Any]) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

