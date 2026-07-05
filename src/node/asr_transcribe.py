import traceback
from typing import Any, Dict

from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep_log, retry_if_exception_type
import logging

from ..model.asr import ASR
from ..logger.logging import logger


class ASRTranscriber:
    """
    ASR 转录节点

    负责将视频/音频文件转录为文本和 utterances，
    与具体的工作流解耦。usage 信息放在返回值中，由上层 workflow 负责收集。

    网络异常时自动指数退避重试（最多 3 次，等待 1s → 2s → 4s）。
    业务失败（ASR 返回 status != success）不重试。
    """

    def transcribe_video(self, video_path: str) -> Dict[str, Any]:
        """
        对单个视频/音频文件进行 ASR 转录。

        内部使用 ByteDance ASR，tos_config 自动从 .env 读取。
        网络异常时自动指数退避重试。

        Args:
            video_path: 本地视频或音频文件路径（也支持 http/https URL）

        Returns:
            {
                "success": bool,
                "video_path": str,        # 输入路径原样透传
                "text": str,              # 完整识别文本
                "utterances": [...],      # 句子信息，时间单位为毫秒
                                          # [{"text": str, "start_time": int,
                                          #   "end_time": int, "speaker": str}, ...]
                "usage": {...},           # ASR usage 信息（由上层 workflow 收集）
                "error": str              # 仅 success=False 时存在
            }
        """
        try:
            asr = ASR(provider='bytedance')
            logger.info(f"开始ASR识别: {video_path}")

            # 网络异常时自动重试，业务失败（status!=success）由下方逻辑处理，不触发重试
            results = self._transcribe_with_retry(asr, video_path)

            if not results:
                logger.error("ASR识别失败，未返回结果")
                return {"success": False, "error": "ASR returned empty results"}

            item = results[0]
            if item.get("status") != "success":
                # 业务失败不重试
                error = item.get("error", "unknown error")
                logger.error(f"ASR识别失败（业务错误）: {error}")
                return {"success": False, "error": str(error)}

            transcription = item.get("transcription", {})
            result_body = transcription.get("result", {})

            text = result_body.get("text", "")
            utterances = result_body.get("utterances", [])
            usage = transcription.get("usage", {})

            logger.info(f"ASR识别完成，识别到 {len(utterances)} 个句子")

            return {
                "success": True,
                "video_path": str(video_path),
                "text": text,
                "utterances": utterances,
                "usage": usage,
            }

        except Exception as e:
            logger.error(f"ASR识别异常（重试已耗尽）: {e}")
            logger.error(f"堆栈:\n{traceback.format_exc()}")
            return {"success": False, "error": str(e)}

    @staticmethod
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),  # 1s → 2s → 4s
        retry=retry_if_exception_type(Exception),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def _transcribe_with_retry(asr: ASR, video_path: str):
        """带指数退避重试的 transcribe 调用（仅处理网络/服务异常）"""
        return asr.transcribe([str(video_path)])


