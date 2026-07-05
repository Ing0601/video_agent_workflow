from .base import BaseTool
from ..logger import logger
from typing import Optional
import asyncio
from functools import partial

from ..tool.types import ToolExeResult
from ..model.llm.qwen_vlm import QwenVLM


class MediaAnalyze(BaseTool):
    def __init__(self):
        super().__init__()
        self.name = "MediaAnalyze"
        self.description = "Analyze an image or video based on a user query."
        self.parameters = {
            "type": "object",
            "properties": {
                "media_url": {
                    "type": "string",
                    "description": "URL of the image or video to be analyzed"
                },
                "user_query": {
                    "type": "string",
                    "description": "User's question or analysis request about the image or video"
                },
                "media_type": {
                    "type": "string",
                    "enum": ["image", "video"],
                    "description": "Type of the media: image or video"
                }
            },
            "required": ["media_url", "user_query", "media_type"]
        }

        # 延迟初始化，避免服务启动阶段因缺失 DASHSCOPE_API_KEY 直接崩溃。
        self.vlm = None

    def _get_vlm(self) -> QwenVLM:
        if self.vlm is None:
            self.vlm = QwenVLM()
        return self.vlm

    async def execute(
        self,
        media_url: str,
        user_query: str,
        media_type: str,
        introduction: Optional[str] = None,
        max_retries: int = 3,
        **kwargs
    ) -> ToolExeResult:

        # ---------- 参数校验 ----------
        validation = self.validate_params(
            media_url=media_url,
            user_query=user_query,
            media_type=media_type,
            introduction=introduction,
        )
        if not validation["success"]:
            return ToolExeResult(success=False, error=validation["error"])

        if not media_url.startswith("http") or not media_url.lower().endswith(
            (".jpg", ".jpeg", ".png", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".mkv")
        ):
            return ToolExeResult(success=False, error="Media URL is not valid")

        if not user_query.strip():
            return ToolExeResult(success=False, error="User query is not valid")

        if media_type not in ("image", "video"):
            return ToolExeResult(
                success=False,
                error=f"Media type must be 'image' or 'video', got '{media_type}'",
            )

        # ---------- 执行 ----------
        for attempt in range(max_retries):
            try:
                loop = asyncio.get_running_loop()

                # ⭐ 关键修复点：用 partial 封装关键字参数
                func = partial(
                    self._get_vlm().call_model,
                    media_url=media_url,
                    prompt=user_query,
                    media_type=media_type,
                )

                response = await loop.run_in_executor(None, func)

                # print("="*80)
                # print("MediaAnalyze response: ", response)
                # print("="*80)

#                 response = """
#   "description": "A close-up portrait of a small, fluffy orange tabby kitten sitting upright and looking directly at the camera with wide, curious greenish-yellow eyes. The kitten has prominent white whiskers, a pink nose, and soft fur with subtle striped markings. Its ears are perked up attentively. The background is softly blurred (bokeh effect), suggesting an indoor or rustic setting—possibly wooden planks or flooring—with warm, natural lighting that highlights the kitten’s fur texture and expressive face.",
#   "subject": "Kitten",
#   "species": "Domestic cat (Felis catus)",
#   "coloration": "Orange tabby with white chest and chin",
#   "expression": "Alert, curious, innocent",
#   "style": "High-detail, photorealistic (likely AI-generated or professionally photographed)"
# """
                # print("="*80)
                # print("response: ", response)
                # print("="*80)
                logger.info("MediaAnalyze executed successfully")

                return ToolExeResult(
                    success=True,
                    result={"analysis_result": response},
                )

            except Exception as e:
                error_msg = f"Media analyze failed: {e}"

                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 2
                    logger.error(
                        f"⚠ {error_msg}，{wait_time}s 后重试 "
                        f"({attempt + 1}/{max_retries})"
                    )
                    await asyncio.sleep(wait_time)
                else:
                    logger.exception("MediaAnalyze failed after max retries")
                    return ToolExeResult(success=False, error=error_msg)

        return ToolExeResult(
            success=False,
            error="Media analyze failed after max retries",
        )
