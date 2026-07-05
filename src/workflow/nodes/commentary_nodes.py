from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from src.services import CommentaryService, DraftService
from src.workflow.runtime import TaskStorage
from src.workflow.states import CommentaryState


def _append_log(state: CommentaryState, message: str) -> list[str]:
    return [*state.get("logs", []), message]


def _storage(state: CommentaryState) -> TaskStorage:
    return TaskStorage(state.get("output_dir") or state.get("work_dir") or "output/langgraph")


def init_commentary_task(state: CommentaryState) -> Dict[str, Any]:
    task_id = state.get("task_id") or f"commentary_{uuid.uuid4().hex[:12]}"
    output_dir = state.get("output_dir") or "output/langgraph"
    storage = TaskStorage(output_dir)
    task_dir = storage.task_dir(task_id)
    return {
        "task_id": task_id,
        "task_type": "commentary",
        "output_dir": output_dir,
        "intermediate_dir": str(task_dir / "intermediates"),
        "current_node": "init_task",
        "progress": 0.03,
        "started_at": state.get("started_at") or datetime.utcnow().isoformat(),
        "logs": _append_log(state, f"初始化解说词任务: {task_id}"),
        "rewrite_count": state.get("rewrite_count", 0),
    }


def analyze_material_node(state: CommentaryState) -> Dict[str, Any]:
    service = CommentaryService()
    demo_info = state.get("demo_info")
    if not demo_info and state.get("demo_info_path"):
        with open(state["demo_info_path"], "r", encoding="utf-8") as f:
            demo_info = json.load(f)
    if not demo_info:
        raise ValueError("commentary graph first version requires demo_info or demo_info_path")

    material_summary = service.build_material_summary(
        demo_info=demo_info, user_demand=state.get("user_demand", "")
    )
    path = _storage(state).save_json(
        state["task_id"],
        "intermediates/material_summary.json",
        {"material_summary": material_summary, "demo_info": demo_info},
    )
    return {
        "demo_info": demo_info,
        "material_summary": material_summary,
        "material_summary_path": path,
        "current_node": "analyze_material",
        "progress": 0.15,
        "logs": _append_log(state, "素材结构分析完成"),
    }


def generate_script_node(state: CommentaryState) -> Dict[str, Any]:
    service = CommentaryService()
    config = state.get("config", {})
    script = service.generate_script(
        material_summary=state["material_summary"],
        user_demand=state.get("user_demand", ""),
        model=config.get("script_model", "qwen-max-latest"),
        temperature=float(config.get("temperature", 0.7)),
    )
    path = _storage(state).save_json(
        state["task_id"], "intermediates/script_result.json", script
    )
    return {
        "script_result": script,
        "script_result_path": path,
        "current_node": "generate_script",
        "progress": 0.3,
        "logs": _append_log(state, f"生成 {len(script)} 段解说文案"),
    }


def synthesize_tts_node(state: CommentaryState) -> Dict[str, Any]:
    service = CommentaryService()
    result = service.synthesize_tts_stub(
        script_result=state["script_result"],
        output_dir=Path(state["intermediate_dir"]) / "tts",
        voice_type=state.get("voice_type", "BV411_streaming"),
        speed_ratio=float(state.get("speed_ratio", 1.2)),
    )
    path = _storage(state).save_json(
        state["task_id"], "intermediates/tts_result.json", result
    )
    return {
        "audio_file": result["audio_file"],
        "timestamps": result["timestamps"],
        "total_duration": result["total_duration"],
        "tts_result_path": path,
        "current_node": "synthesize_tts",
        "progress": 0.45,
        "logs": _append_log(state, f"TTS 生成完成，时长 {result['total_duration']:.2f}s"),
    }


def check_tts_duration_node(state: CommentaryState) -> Dict[str, Any]:
    service = CommentaryService()
    check = service.check_duration(
        total_duration=float(state.get("total_duration", 0)),
        target_duration=state.get("target_duration"),
    )
    return {
        "duration_check": check,
        "current_node": "check_tts_duration",
        "progress": 0.52,
        "logs": _append_log(state, f"TTS 时长检查: {check['status']}"),
    }


def align_video_info_node(state: CommentaryState) -> Dict[str, Any]:
    service = CommentaryService()
    video_info = service.align_video_info(
        script_result=state["script_result"],
        demo_info=state["demo_info"],
        timestamps=state["timestamps"],
    )
    path = _storage(state).save_json(
        state["task_id"], "intermediates/video_info.json", video_info
    )
    return {
        "video_info": video_info,
        "video_info_path": path,
        "current_node": "align_video_info",
        "progress": 0.65,
        "logs": _append_log(state, "文案、TTS、视频片段时间轴对齐完成"),
    }


def generate_bgm_node(state: CommentaryState) -> Dict[str, Any]:
    bgm = CommentaryService().generate_bgm(state.get("user_demand", ""))
    return {
        "bgm_result": bgm,
        "current_node": "generate_bgm",
        "progress": 0.73,
        "logs": _append_log(state, "BGM 配置生成完成"),
    }


def generate_overlay_node(state: CommentaryState) -> Dict[str, Any]:
    overlay = CommentaryService().generate_overlay(state.get("timestamps", []))
    return {
        "overlay_result": overlay,
        "current_node": "generate_overlay",
        "progress": 0.8,
        "logs": _append_log(state, "贴纸配置生成完成"),
    }


def generate_sound_node(state: CommentaryState) -> Dict[str, Any]:
    sound = CommentaryService().generate_sound()
    return {
        "sound_result": sound,
        "current_node": "generate_sound",
        "progress": 0.86,
        "logs": _append_log(state, "音效配置生成完成"),
    }


def create_commentary_draft_node(state: CommentaryState) -> Dict[str, Any]:
    draft_path = DraftService().create_commentary_draft_stub(
        video_info=state["video_info"],
        audio_file=state["audio_file"],
        timestamps=state["timestamps"],
        output_dir=state.get("output_dir") or "output/langgraph",
        draft_name=state.get("draft_name", "解说前贴"),
    )
    return {
        "draft_path": draft_path,
        "current_node": "create_jianying_draft",
        "progress": 0.94,
        "logs": _append_log(state, f"剪映草稿 manifest 已生成: {draft_path}"),
    }


def finish_commentary_node(state: CommentaryState) -> Dict[str, Any]:
    final_result = {
        "success": True,
        "message": "Commentary workflow completed",
        "context_updates": {
            "script_result": state.get("script_result"),
            "audio_file": state.get("audio_file"),
            "video_info": state.get("video_info"),
            "draft_path": state.get("draft_path"),
        },
    }
    _storage(state).save_json(state["task_id"], "state.latest.json", {**state, "final_result": final_result})
    return {
        "final_result": final_result,
        "current_node": "finish",
        "progress": 1.0,
        "finished_at": datetime.utcnow().isoformat(),
        "logs": _append_log(state, "解说词 LangGraph workflow 完成"),
    }
