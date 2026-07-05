from typing import Any, Dict, List

from .base_state import BaseVideoState


class CommentaryState(BaseVideoState, total=False):
    mode: str
    alignment_strategy: str
    demo_info_path: str
    demo_info: List[Dict[str, Any]]
    material_path: Dict[str, str]
    material_summary: str
    material_summary_path: str
    user_demand: str
    script_result: List[Dict[str, Any]]
    script_result_path: str
    voice_type: str
    speed_ratio: float
    tts_type: str
    audio_file: str
    timestamps: List[Dict[str, Any]]
    total_duration: float
    tts_result_path: str
    target_duration: float
    duration_check: Dict[str, Any]
    rewrite_count: int
    video_info: List[Dict[str, Any]]
    video_info_path: str
    bgm_result: Dict[str, Any]
    overlay_result: Any
    sound_result: Any
    draft_name: str
    draft_path: str
