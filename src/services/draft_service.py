import json
from pathlib import Path
from typing import Any, Dict, List

from src.workflow.highlight_draft import ShortDramaProcessor


class DraftService:
    def create_highlight_draft(
        self,
        highlight_results: List[Dict[str, Any]],
        base_config: Dict[str, Any],
        draft_output_dir: str,
        goal_times: List[int],
    ) -> Dict[str, Any]:
        processor = ShortDramaProcessor()
        total_plans = processor.process(
            highlight_results=highlight_results,
            goal_times=goal_times,
            output_dir=draft_output_dir,
            convert_to_draft=True,
            config=base_config,
        )
        return {"total_plans": total_plans, "draft_output_dir": draft_output_dir}

    def create_commentary_draft_stub(
        self,
        video_info: List[Dict[str, Any]],
        audio_file: str,
        timestamps: List[Dict[str, Any]],
        output_dir: str,
        draft_name: str,
    ) -> str:
        """Write a draft manifest placeholder for first-stage backend integration."""
        draft_dir = Path(output_dir) / draft_name
        draft_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "draft_name": draft_name,
            "audio_file": audio_file,
            "timestamps": timestamps,
            "video_info": video_info,
            "note": "Placeholder draft manifest. Replace with Jianying converter integration.",
        }
        with (draft_dir / "draft_manifest.json").open("w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        return str(draft_dir)
