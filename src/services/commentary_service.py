import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List

from src.model.llm.qwen_chat import QwenLLMClient


class CommentaryService:
    """Core service for commentary/info-flow ad generation.

    The first implementation supports template/demo_info mode. Direct video
    material analysis can be added behind `build_material_summary`.
    """

    def build_material_summary(
        self, demo_info: List[Dict[str, Any]], user_demand: str
    ) -> str:
        return json.dumps(
            {"user_demand": user_demand, "demo_info": demo_info},
            ensure_ascii=False,
            indent=2,
        )

    def generate_script(
        self,
        material_summary: str,
        user_demand: str,
        model: str = "qwen-max-latest",
        temperature: float = 0.7,
    ) -> List[Dict[str, Any]]:
        api_key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("DMXAPI_KEY")
        if not api_key:
            return self._fallback_script(material_summary)

        client = QwenLLMClient(api_key=api_key, model=model)
        system_prompt = (
            "你是一位资深视频解说和信息流广告文案专家。"
            "请根据素材结构和用户需求生成结构化文案。"
            "demo 中有几个 segment，输出也必须有同样数量的 segment。"
            "只输出 JSON 数组，每个元素包含 segment_index 和 subtitles。"
        )
        user_prompt = f"# 用户需求\n{user_demand}\n\n# 素材结构\n{material_summary}"
        result = client.completions_with_json(
            user_content=user_prompt,
            system_content=system_prompt,
            temperature=temperature,
        )
        content = result.get("content") if isinstance(result, dict) else result
        if isinstance(content, dict) and "segments" in content:
            content = content["segments"]
        if not isinstance(content, list):
            raise ValueError("LLM script result must be a JSON array")
        return content

    def synthesize_tts_stub(
        self,
        script_result: List[Dict[str, Any]],
        output_dir: str | Path,
        voice_type: str,
        speed_ratio: float,
    ) -> Dict[str, Any]:
        """Deterministic TTS placeholder.

        This keeps the graph executable without requiring paid TTS credentials.
        Replace this method with the real ByteDance/CosyVoice adapter when
        enabling production TTS.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        text_parts = [item.get("subtitles", "") for item in script_result]
        timestamps: List[Dict[str, Any]] = []
        cursor = 0.0
        seconds_per_char = 0.22 / max(speed_ratio, 0.1)
        for text in text_parts:
            duration = max(len(self._normalize_text(text)) * seconds_per_char, 0.8)
            timestamps.append(
                {
                    "start": round(cursor, 3),
                    "end": round(cursor + duration, 3),
                    "text": text,
                }
            )
            cursor += duration + 0.15

        audio_file = output_dir / "tts_placeholder.mp3"
        audio_file.touch(exist_ok=True)
        return {
            "audio_file": str(audio_file),
            "timestamps": timestamps,
            "total_duration": round(cursor, 3),
            "voice_type": voice_type,
            "speed_ratio": speed_ratio,
            "stub": True,
        }

    def check_duration(
        self, total_duration: float, target_duration: float | None
    ) -> Dict[str, Any]:
        if not target_duration or target_duration <= 0:
            return {"status": "not_required", "ratio": None}
        ratio = total_duration / target_duration
        if 0.9 <= ratio <= 1.1:
            status = "ok"
        elif ratio > 1.1:
            status = "too_long"
        else:
            status = "too_short"
        return {"status": status, "ratio": ratio, "target_duration": target_duration}

    def align_video_info(
        self,
        script_result: List[Dict[str, Any]],
        demo_info: List[Dict[str, Any]],
        timestamps: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        script_with_folder = self._merge_folder(script_result, demo_info)
        script_with_time = self._merge_timestamps(script_with_folder, timestamps, demo_info)
        return self._smooth_gaps(script_with_time)

    def generate_bgm(self, user_demand: str) -> Dict[str, Any]:
        if "紧张" in user_demand or "高能" in user_demand:
            return {"type": "紧张背景音"}
        if "广告" in user_demand or "卖点" in user_demand:
            return {"type": "轻松背景音"}
        return {"type": "舒缓背景音"}

    def generate_overlay(self, timestamps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [
            {
                "id": f"overlay_{idx}",
                "start": item.get("start", 0),
                "duration": 1.0,
                "type": "高亮框",
                "position": "center",
            }
            for idx, item in enumerate(timestamps[:3])
        ]

    def generate_sound(self) -> List[Dict[str, Any]]:
        return []

    def _fallback_script(self, material_summary: str) -> List[Dict[str, Any]]:
        try:
            payload = json.loads(material_summary)
            demo_info = payload.get("demo_info", [])
        except Exception:
            demo_info = []
        result = []
        for idx, item in enumerate(demo_info, 1):
            subtitle = item.get("subtitles") or item.get("subtitle") or ""
            result.append(
                {
                    "segment_index": idx,
                    "subtitles": subtitle or f"第 {idx} 段解说内容。",
                }
            )
        return result

    def _merge_folder(
        self, script: List[Dict[str, Any]], demo_info: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        result = []
        for idx, item in enumerate(script):
            merged = dict(item)
            if idx < len(demo_info):
                merged["folder"] = demo_info[idx].get("folder", "")
            result.append(merged)
        return result

    def _merge_timestamps(
        self,
        script: List[Dict[str, Any]],
        timestamps: List[Dict[str, Any]],
        demo_info: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if not timestamps:
            return script

        script_parts = [self._normalize_text(item.get("subtitles", "")) for item in script]
        total_script_chars = sum(len(part) for part in script_parts)
        if total_script_chars == 0:
            return script

        chars = []
        for ts_idx, ts in enumerate(timestamps):
            normalized = self._normalize_text(ts.get("text", ""))
            for char_idx, char in enumerate(normalized):
                chars.append(
                    {
                        "sentence_idx": ts_idx,
                        "char_idx": char_idx,
                        "sentence_length": len(normalized),
                    }
                )
        if not chars:
            return script

        result = []
        cursor = 0
        for idx, item in enumerate(script):
            text = script_parts[idx]
            if not text:
                duration = self._demo_duration(demo_info, idx)
                start = result[-1]["end"] if result else 0.0
                result.append({**item, "start": start, "end": start + duration, "duration": duration})
                continue

            start_pos = cursor
            end_pos = cursor + len(text) - 1
            cursor += len(text)

            start_time = self._map_start_time(start_pos, total_script_chars, chars, timestamps)
            end_time = self._map_end_time(end_pos, total_script_chars, chars, timestamps)
            result.append(
                {
                    **item,
                    "start": round(start_time, 3),
                    "end": round(end_time, 3),
                    "duration": round(max(end_time - start_time, 0), 3),
                }
            )
        return result

    def _smooth_gaps(self, script: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not script:
            return script
        result = []
        for idx, item in enumerate(script):
            current = dict(item)
            if idx == 0:
                current["start"] = 0.0
            else:
                current["start"] = result[-1]["end"]

            if idx + 1 < len(script):
                gap = script[idx + 1].get("start", current["end"]) - current["end"]
                if gap > 0:
                    current["end"] = round(current["end"] + gap / 2, 3)
            current["duration"] = round(max(current["end"] - current["start"], 0), 3)
            result.append(current)
        return result

    def _map_start_time(
        self,
        script_pos: int,
        total_script_chars: int,
        chars: List[Dict[str, Any]],
        timestamps: List[Dict[str, Any]],
    ) -> float:
        char = self._mapped_char(script_pos, total_script_chars, chars)
        sentence_idx = char["sentence_idx"]
        pos_ratio = char["char_idx"] / max(char["sentence_length"], 1)
        if pos_ratio < 0.5:
            return float(timestamps[sentence_idx]["start"])
        return float(timestamps[min(sentence_idx + 1, len(timestamps) - 1)]["start"])

    def _map_end_time(
        self,
        script_pos: int,
        total_script_chars: int,
        chars: List[Dict[str, Any]],
        timestamps: List[Dict[str, Any]],
    ) -> float:
        char = self._mapped_char(script_pos, total_script_chars, chars)
        sentence_idx = char["sentence_idx"]
        pos_ratio = char["char_idx"] / max(char["sentence_length"], 1)
        if pos_ratio < 0.5:
            return float(timestamps[max(sentence_idx - 1, 0)]["end"])
        return float(timestamps[sentence_idx]["end"])

    def _mapped_char(
        self, script_pos: int, total_script_chars: int, chars: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        ratio = script_pos / max(total_script_chars, 1)
        idx = max(0, min(int(ratio * len(chars)), len(chars) - 1))
        return chars[idx]

    def _normalize_text(self, text: str) -> str:
        return re.sub(r"[，。！？、；：,.!?;:\s]", "", text or "")

    def _demo_duration(self, demo_info: List[Dict[str, Any]], idx: int) -> float:
        if idx >= len(demo_info):
            return 1.0
        start = float(demo_info[idx].get("start", 0))
        end = float(demo_info[idx].get("end", start + 1.0))
        return max(end - start, 0.1)

