import os
from pathlib import Path
from typing import Any, Dict, List

from src.model.llm.qwen_chat import QwenLLMClient
from src.node.asr_transcribe import ASRTranscriber
from src.node.collect_videos import VideoCollector
from src.node.content_clipper import ContentClipper
from src.node.group_segments import SubtitleGrouper
from src.node.segment_analyzer import SegmentAnalyzer
from src.node.video_splitter import VideoSplitter
from src.utils.video_utils import VideoUtils
from src.workflow.highlight_async import HighlightWorkflowAsync


class HighlightService:
    """Service wrapper around the existing highlight primitives."""

    def __init__(self) -> None:
        self.video_collector = VideoCollector()
        self.asr_transcriber = ASRTranscriber()
        self.content_clipper = ContentClipper()
        self.video_splitter = VideoSplitter()
        self.subtitle_grouper = SubtitleGrouper()
        self.segment_analyzer = SegmentAnalyzer()
        self.prompt_builder = HighlightWorkflowAsync()
        self.usage: List[Dict[str, Any]] = []

    def collect_videos(self, input_videos: Any) -> List[str]:
        return self.video_collector.collect(input_videos)

    def get_video_duration(self, video_path: str) -> float:
        return float(VideoUtils.get_video_duration_seconds(video_path))

    def transcribe(self, video_path: str) -> Dict[str, Any]:
        result = self.asr_transcriber.transcribe_video(video_path)
        self._collect_usage(result)
        return result

    def generate_slices(
        self,
        utterances: List[Dict[str, Any]],
        qwen_api_key: str | None,
        qwen_model: str,
        temperature: float,
    ) -> Dict[str, Any]:
        result = self.content_clipper.generate_slices(
            utterances=utterances,
            system_prompt=self.prompt_builder._build_slicing_system_prompt(),
            api_key=qwen_api_key,
            model=qwen_model,
            temperature=temperature,
        )
        self._collect_usage(result)
        return result

    def split_and_group(
        self,
        video_path: str,
        slices: List[Dict[str, Any]],
        output_dir: str | Path,
        utterances: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        segments = self.video_splitter.split_video(video_path, slices, Path(output_dir))
        return self.subtitle_grouper.insert_asr_to_segments(segments, utterances)

    def analyze_segments(
        self,
        segments: List[Dict[str, Any]],
        fps: float,
        max_workers: int,
    ) -> List[Dict[str, Any]]:
        analyzed = self.segment_analyzer.analyze_segments(
            segments=segments,
            prompt=self.prompt_builder._build_segment_analysis_prompt(),
            fps=fps,
            max_workers=max_workers,
        )
        for segment in analyzed:
            usage = segment.get("vlm_usage")
            if usage:
                self.usage.append(usage)
        return analyzed

    def select_highlights(
        self,
        analyzed_segments: List[Dict[str, Any]],
        qwen_api_key: str | None,
        qwen_model: str,
        temperature: float,
        batch_size: int,
    ) -> List[int]:
        if not analyzed_segments:
            return []

        api_key = qwen_api_key or os.getenv("DASHSCOPE_API_KEY")
        llm_client = QwenLLMClient(api_key=api_key, model=qwen_model)
        selected_indices: List[int] = []

        for batch_idx in range(0, len(analyzed_segments), batch_size):
            batch_segments = analyzed_segments[batch_idx : batch_idx + batch_size]
            segments_for_llm = [
                {
                    "segment_index": seg["segment_index"],
                    "content_summary": seg.get("content_summary", ""),
                    "subtitle": seg.get("subtitle", ""),
                    "scene_description": seg.get("visual_analysis", {}).get(
                        "scene_description", ""
                    ),
                }
                for seg in batch_segments
            ]
            llm_result = llm_client.completions_with_json(
                user_content=self.prompt_builder._build_selection_user_prompt(
                    segments_for_llm
                ),
                system_content=self.prompt_builder._build_selection_system_prompt(),
                temperature=temperature,
            )
            if not llm_result:
                continue
            if isinstance(llm_result, dict) and "content" in llm_result:
                content = llm_result.get("content") or {}
                usage = llm_result.get("usage")
                if usage:
                    self.usage.append(usage)
            else:
                content = llm_result

            selected = content.get("selected_indices", [])
            if isinstance(selected, list):
                selected_indices.extend(int(idx) for idx in selected)

        return sorted(set(selected_indices))

    def build_highlights(
        self, analyzed_segments: List[Dict[str, Any]], selected_indices: List[int]
    ) -> List[Dict[str, Any]]:
        segment_map = {seg["segment_index"]: seg for seg in analyzed_segments}
        highlights: List[Dict[str, Any]] = []
        for seg_idx in selected_indices:
            segment = segment_map.get(seg_idx)
            if not segment:
                continue
            content_summary = segment.get("content_summary", "").strip()
            scene_description = (
                segment.get("visual_analysis", {}).get("scene_description", "").strip()
            )
            if content_summary and scene_description:
                reason = f"{content_summary} + {scene_description}"
            else:
                reason = content_summary or scene_description or "高光片段"
            highlights.append(
                {
                    "start": f"{segment['start_time']:.1f}",
                    "end": f"{segment['end_time']:.1f}",
                    "reason": reason,
                }
            )
        return highlights

    def _collect_usage(self, result: Dict[str, Any]) -> None:
        usage = result.get("usage")
        if usage:
            self.usage.append(usage)

