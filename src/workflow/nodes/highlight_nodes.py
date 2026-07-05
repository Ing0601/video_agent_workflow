from __future__ import annotations

import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from src.services import DraftService, HighlightService
from src.utils.count_tokens import aggregate_usage
from src.workflow.runtime import TaskStorage
from src.workflow.states import HighlightState


def _append_log(state: HighlightState, message: str) -> list[str]:
    return [*state.get("logs", []), message]


def _task_storage(state: HighlightState) -> TaskStorage:
    output_dir = state.get("output_dir") or state.get("work_dir") or "output/langgraph"
    return TaskStorage(output_dir)


def init_highlight_task(state: HighlightState) -> Dict[str, Any]:
    task_id = state.get("task_id") or f"highlight_{uuid.uuid4().hex[:12]}"
    output_dir = state.get("output_dir") or state.get("config", {}).get("output_base_dir")
    if not output_dir:
        output_dir = "output/langgraph"
    storage = TaskStorage(output_dir)
    task_dir = storage.task_dir(task_id)
    update = {
        "task_id": task_id,
        "task_type": "highlight",
        "output_dir": output_dir,
        "intermediate_dir": str(task_dir / "intermediates"),
        "current_node": "init_task",
        "progress": 0.02,
        "logs": _append_log(state, f"初始化高光任务: {task_id}"),
        "started_at": state.get("started_at") or datetime.utcnow().isoformat(),
        "usage": state.get("usage", []),
    }
    storage.save_json(task_id, "config.json", {**state, **update})
    return update


def collect_videos_node(state: HighlightState) -> Dict[str, Any]:
    service = HighlightService()
    video_files = service.collect_videos(state["input_videos"])
    if not video_files:
        raise ValueError(f"No valid videos found: {state.get('input_videos')}")

    storage = _task_storage(state)
    videos = {}
    for video_path in video_files:
        stem = Path(video_path).stem
        video_output_dir = Path(state["intermediate_dir"]) / stem
        result_dir = video_output_dir / "result"
        result_dir.mkdir(parents=True, exist_ok=True)
        videos[video_path] = {
            "video_name": Path(video_path).name,
            "video_path": video_path,
            "output_dir": str(video_output_dir),
            "result_dir": str(result_dir),
            "success": True,
        }
    storage.save_json(state["task_id"], "intermediates/collected_videos.json", videos)
    return {
        "video_files": video_files,
        "videos": videos,
        "current_node": "collect_videos",
        "progress": 0.08,
        "logs": _append_log(state, f"收集到 {len(video_files)} 个视频"),
    }


def asr_transcribe_node(state: HighlightState) -> Dict[str, Any]:
    service = HighlightService()
    storage = _task_storage(state)
    videos = dict(state["videos"])
    for video_path, video_state in videos.items():
        try:
            video_state["video_duration"] = service.get_video_duration(video_path)
            asr_result = service.transcribe(video_path)
            if not asr_result.get("success"):
                raise RuntimeError(asr_result.get("error", "ASR failed"))
            video_state["asr_result"] = asr_result
            storage.save_json(
                state["task_id"],
                f"intermediates/{Path(video_path).stem}/step1_asr_result.json",
                asr_result,
            )
        except Exception as exc:
            video_state["success"] = False
            video_state["error"] = str(exc)

    return {
        "videos": videos,
        "usage": [*state.get("usage", []), *service.usage],
        "current_node": "asr_transcribe",
        "progress": 0.22,
        "logs": _append_log(state, "ASR 识别完成"),
    }


def content_clip_node(state: HighlightState) -> Dict[str, Any]:
    service = HighlightService()
    storage = _task_storage(state)
    config = state.get("config", {})
    videos = dict(state["videos"])
    for video_path, video_state in videos.items():
        if not video_state.get("success"):
            continue
        try:
            slicing_result = service.generate_slices(
                utterances=video_state["asr_result"]["utterances"],
                qwen_api_key=config.get("qwen_api_key"),
                qwen_model=config.get("qwen_model", "qwen3-max"),
                temperature=float(config.get("temperature", 0.7)),
            )
            if not slicing_result.get("success"):
                raise RuntimeError(slicing_result.get("error", "slice generation failed"))
            video_state["slicing_result"] = slicing_result
            video_state["slices"] = slicing_result["slices"]
            storage.save_json(
                state["task_id"],
                f"intermediates/{Path(video_path).stem}/step2_slicing_result.json",
                slicing_result,
            )
        except Exception as exc:
            video_state["success"] = False
            video_state["error"] = str(exc)

    return {
        "videos": videos,
        "usage": [*state.get("usage", []), *service.usage],
        "current_node": "content_clip",
        "progress": 0.38,
        "logs": _append_log(state, "LLM 切片完成"),
    }


def split_and_group_node(state: HighlightState) -> Dict[str, Any]:
    service = HighlightService()
    storage = _task_storage(state)
    videos = dict(state["videos"])
    for video_path, video_state in videos.items():
        if not video_state.get("success"):
            continue
        try:
            video_segments = service.split_and_group(
                video_path=video_path,
                slices=video_state["slices"],
                output_dir=video_state["output_dir"],
                utterances=video_state["asr_result"].get("utterances", []),
            )
            if not video_segments:
                raise RuntimeError("video split failed")
            video_state["video_segments"] = video_segments
            storage.save_json(
                state["task_id"],
                f"intermediates/{Path(video_path).stem}/step3_video_segments.json",
                {"success": True, "segments": video_segments},
            )
        except Exception as exc:
            video_state["success"] = False
            video_state["error"] = str(exc)

    return {
        "videos": videos,
        "current_node": "split_and_group",
        "progress": 0.52,
        "logs": _append_log(state, "视频切分和字幕归组完成"),
    }


def vlm_analyze_node(state: HighlightState) -> Dict[str, Any]:
    service = HighlightService()
    storage = _task_storage(state)
    config = state.get("config", {})
    videos = dict(state["videos"])
    for video_path, video_state in videos.items():
        if not video_state.get("success"):
            continue
        try:
            analyzed = service.analyze_segments(
                segments=video_state["video_segments"],
                fps=float(config.get("fps", 1.0)),
                max_workers=int(config.get("segment_vlm_workers", 3)),
            )
            if not analyzed:
                raise RuntimeError("VLM segment analysis failed")
            video_state["analyzed_segments"] = analyzed
            storage.save_json(
                state["task_id"],
                f"intermediates/{Path(video_path).stem}/step4_analyzed_segments.json",
                {"success": True, "segments": analyzed},
            )
        except Exception as exc:
            video_state["success"] = False
            video_state["error"] = str(exc)

    return {
        "videos": videos,
        "usage": [*state.get("usage", []), *service.usage],
        "current_node": "vlm_analyze",
        "progress": 0.72,
        "logs": _append_log(state, "VLM 片段分析完成"),
    }


def select_highlights_node(state: HighlightState) -> Dict[str, Any]:
    service = HighlightService()
    storage = _task_storage(state)
    config = state.get("config", {})
    videos = dict(state["videos"])
    highlight_results = []
    for video_path, video_state in videos.items():
        if not video_state.get("success"):
            continue
        try:
            selected = service.select_highlights(
                analyzed_segments=video_state["analyzed_segments"],
                qwen_api_key=config.get("qwen_api_key"),
                qwen_model=config.get("qwen_model", "qwen3-max"),
                temperature=float(config.get("temperature", 0.7)),
                batch_size=int(config.get("selection_batch_size", 5)),
            )
            highlights = service.build_highlights(
                video_state["analyzed_segments"], selected
            )
            video_state["selected_indices"] = selected
            video_state["highlights"] = highlights
            highlight_results.append(
                {
                    "id": len(highlight_results) + 1,
                    "success": True,
                    "video_name": video_state["video_name"],
                    "video_path": video_path,
                    "video_duration": video_state.get("video_duration", 0),
                    "highlights": highlights,
                }
            )
            storage.save_json(
                state["task_id"],
                f"intermediates/{Path(video_path).stem}/step5_selected_indices.json",
                {"success": True, "selected_indices": selected},
            )
        except Exception as exc:
            video_state["success"] = False
            video_state["error"] = str(exc)

    return {
        "videos": videos,
        "highlight_results": highlight_results,
        "usage": [*state.get("usage", []), *service.usage],
        "current_node": "select_highlights",
        "progress": 0.86,
        "logs": _append_log(state, f"筛选出 {len(highlight_results)} 个视频的高光结果"),
    }


def save_highlight_result_node(state: HighlightState) -> Dict[str, Any]:
    storage = _task_storage(state)
    highlight_results = state.get("highlight_results", [])
    result_path = storage.save_json(
        state["task_id"], "outputs/highlight_results.json", highlight_results
    )

    for video_state in state.get("videos", {}).values():
        output_dir = Path(video_state.get("output_dir", ""))
        if not output_dir.exists():
            continue
        try:
            for item in output_dir.iterdir():
                if item.is_file():
                    item.unlink()
                elif item.is_dir() and item.name != "result":
                    shutil.rmtree(item)
        except Exception:
            pass

    return {
        "highlight_result_path": result_path,
        "raw_usage": state.get("usage", []),
        "current_node": "save_highlight_result",
        "progress": 0.93,
        "logs": _append_log(state, f"高光结果已保存: {result_path}"),
    }


def maybe_generate_highlight_draft_node(state: HighlightState) -> Dict[str, Any]:
    if not state.get("generate_draft"):
        return {
            "current_node": "maybe_generate_draft",
            "progress": 0.97,
            "logs": _append_log(state, "跳过剪映草稿生成"),
        }

    config = state.get("draft_config", {})
    result = DraftService().create_highlight_draft(
        highlight_results=state.get("highlight_results", []),
        base_config=config.get("base_config", {}),
        draft_output_dir=config["draft_output_dir"],
        goal_times=config.get("goal_times", []),
    )
    return {
        "draft_path": result.get("draft_output_dir"),
        "current_node": "generate_highlight_draft",
        "progress": 0.98,
        "logs": _append_log(state, "剪映草稿生成完成"),
    }


def finish_highlight_node(state: HighlightState) -> Dict[str, Any]:
    final_result = {
        "success": bool(state.get("highlight_results")),
        "message": f"Generated highlight results for {len(state.get('highlight_results', []))} video(s)",
        "context_updates": {
            "highlight_results": state.get("highlight_results", []),
            "highlight_result_path": state.get("highlight_result_path"),
            "draft_path": state.get("draft_path"),
        },
        "usage": aggregate_usage(state.get("usage", [])),
        "raw_usage": state.get("usage", []),
    }
    storage = _task_storage(state)
    storage.save_json(state["task_id"], "state.latest.json", {**state, "final_result": final_result})
    return {
        "final_result": final_result,
        "current_node": "finish",
        "progress": 1.0,
        "finished_at": datetime.utcnow().isoformat(),
        "logs": _append_log(state, "高光 LangGraph workflow 完成"),
    }
