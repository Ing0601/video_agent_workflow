from typing import Any, Dict, List, TypedDict

from .base_state import BaseVideoState


class HighlightVideoState(TypedDict, total=False):
    video_name: str
    video_path: str
    output_dir: str
    result_dir: str
    video_duration: float
    asr_result: Dict[str, Any]
    slicing_result: Dict[str, Any]
    slices: List[Dict[str, Any]]
    video_segments: List[Dict[str, Any]]
    analyzed_segments: List[Dict[str, Any]]
    selected_indices: List[int]
    highlights: List[Dict[str, Any]]
    success: bool
    error: str


class HighlightState(BaseVideoState, total=False):
    video_files: List[str]
    videos: Dict[str, HighlightVideoState]
    highlight_results: List[Dict[str, Any]]
    highlight_result_path: str
    usage: List[Dict[str, Any]]
    raw_usage: List[Dict[str, Any]]
    generate_draft: bool
    draft_config: Dict[str, Any]
    draft_path: str

