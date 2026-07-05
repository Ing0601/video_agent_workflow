from typing import Any, Dict, List, Optional, TypedDict


class WorkflowError(TypedDict, total=False):
    node: str
    error_type: str
    message: str
    retryable: bool
    raw_error: str
    created_at: str


class BaseVideoState(TypedDict, total=False):
    task_id: str
    task_type: str
    input_video: str
    input_videos: Any
    work_dir: str
    output_dir: str
    intermediate_dir: str
    current_node: str
    progress: float
    logs: List[str]
    errors: List[WorkflowError]
    warnings: List[str]
    config: Dict[str, Any]
    started_at: str
    finished_at: str
    final_result: Dict[str, Any]

