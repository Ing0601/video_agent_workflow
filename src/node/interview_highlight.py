"""
访谈类精华音频理解分析节点

基于 ASR 字幕分析，识别访谈类音频中的精华内容片段
"""
import json
import os
from typing import Any, Dict, List
import traceback
import logging

from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep_log, retry_if_exception_type

from ..model.llm.qwen_chat import QwenLLMClient
from ..logger.logging import logger


class ValidationError(Exception):
    """验证失败异常，用于触发重试"""
    pass


class InterviewHighlight:
    """
    节点： 访谈类精华音频理解分析
    输入： 访谈类ASR文本，话题切分结果(可选)
    输出： 访谈类精华部分时间戳列表（含duration字段）
    """
    def __init__(self):
        self.logger = logger

    def highlight_audio_content(
        self,
        goal_duration: float,
        system_prompt: str,
        utterances: List[Dict[str, Any]],
        topic_slices: List[Dict[str, Any]] = None,
        user_prompt_template: str = None,
        api_key: str = None,
        model: str = "qwen3-max",
        temperature: float = 0.7
    ) -> Dict[str, Any]:
        """
        分析访谈类音频文本精华内容

        网络异常时自动指数退避重试（最多 3 次，等待 1s → 2s → 4s）。
        验证失败（_validate_highlight 不通过）时也会重试。

        Args:
            goal_duration: 目标精华音频时长（秒）
            utterances: ASR 识别的 utterances 列表（时间单位：毫秒）
                       [{"start_time": 0, "end_time": 1000, "text": "...", "speaker": "..."}, ...]
            topic_slices: 话题切分结果（可选）
                          [{"start": 0, "end": 1000, "content": "..."}, ...]
            system_prompt: 系统提示词
            user_prompt_template: 用户提示词模板（可选，默认使用标准模板）
            api_key: Qwen API密钥（可选，默认从环境变量获取）
            model: Qwen模型名称
            temperature: LLM温度参数

        Returns:
            {
                "success": bool,
                "highlight_slices": [  # 精华音频片段（时间单位：秒）
                    {"start": 0.0, "end": 10.0, "duration": 10.0, "content": "..."},
                    ...
                ],
                "usage": {...},  # LLM usage 信息
                "error": str     # 仅 success=False 时存在
            }
        """
        try:
            if not utterances:
                logger.error("utterances 为空")
                return {
                    "success": False,
                    "error": "No utterances provided"
                }

            # 1. 格式化 utterances (毫秒 -> 秒)
            formatted_text = InterviewHighlight._format_utterances(utterances)

            # 2. 格式化话题切分结果（如果有）
            topic_text = ""
            if topic_slices:
                topic_text = InterviewHighlight._format_topic_slices(topic_slices)

            # 3. 构建用户提示词（使用默认模板或自定义模板）
            if user_prompt_template is None:
                user_prompt = f"""请分析以下访谈音频字幕，识别其中的精华内容片段。

目标精华时长：{goal_duration}秒
{topic_text}
字幕内容：
{formatted_text}

请严格按照JSON格式输出精华片段列表。"""
            else:
                user_prompt = user_prompt_template.format(
                    goal_duration=goal_duration,
                    topic_text=topic_text,
                    formatted_text=formatted_text
                )

            # 4. 初始化 LLM 客户端
            api_key = api_key or os.getenv("DASHSCOPE_API_KEY")
            llm_client = QwenLLMClient(api_key=api_key, model=model)

            # 5. 调用 LLM（带重试机制）
            logger.info("调用LLM分析访谈精华内容...")
            llm_result = self._generate_highlights_with_retry(
                llm_client=llm_client,
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                temperature=temperature
            )

            if llm_result is None:
                logger.error("LLM返回结果为空")
                return {
                    "success": False,
                    "error": "LLM returned None"
                }

            # 6. 提取内容和 usage
            if isinstance(llm_result, dict) and "content" in llm_result:
                highlights = llm_result.get("content")
                usage = llm_result.get("usage")
            else:
                highlights = llm_result
                usage = None

            logger.info(f"✓ 成功生成 {len(highlights)} 个精华片段")

            return {
                "success": True,
                "highlight_slices": highlights,
                "usage": usage
            }

        except Exception as e:
            logger.error(f"精华内容分析异常（重试已耗尽）: {e}")
            logger.error(f"堆栈:\n{traceback.format_exc()}")
            return {
                "success": False,
                "error": str(e)
            }

    @staticmethod
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),  # 1s → 2s → 4s
        retry=retry_if_exception_type((Exception,)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def _generate_highlights_with_retry(
        llm_client: QwenLLMClient,
        user_prompt: str,
        system_prompt: str,
        temperature: float
    ) -> Dict[str, Any]:
        """
        带指数退避重试的 LLM 调用和验证
        """
        # 调用 LLM
        llm_result = llm_client.completions_with_json(
            user_content=user_prompt,
            system_content=system_prompt,
            temperature=temperature
        )

        if llm_result is None:
            raise ValidationError("LLM returned None")

        # 提取内容
        if isinstance(llm_result, dict) and "content" in llm_result:
            highlights = llm_result.get("content")
            usage = llm_result.get("usage")
        else:
            highlights = llm_result
            usage = None

        # 验证结果格式
        if not isinstance(highlights, list) or len(highlights) == 0:
            raise ValidationError(f"Invalid LLM response format: expected list, got {type(highlights)}")

        # 验证每个精华片段
        validated_highlights = []
        invalid_count = 0
        for idx, highlight in enumerate(highlights):
            if InterviewHighlight._validate_highlight_static(highlight, idx):
                validated_highlights.append(highlight)
            else:
                invalid_count += 1

        # 如果没有任何有效片段，触发重试
        if not validated_highlights:
            raise ValidationError(f"No valid highlights after validation (all {len(highlights)} failed)")

        # 如果有效片段比例过低（少于50%），也触发重试
        if len(validated_highlights) < len(highlights) * 0.5:
            raise ValidationError(
                f"Too many invalid highlights: {invalid_count}/{len(highlights)} failed validation"
            )

        # 返回结果时保留 usage 信息
        if usage:
            return {
                "content": validated_highlights,
                "usage": usage
            }
        return validated_highlights

    @staticmethod
    def _format_utterances(utterances: List[Dict[str, Any]]) -> str:
        """
        将 ASR utterances 格式化为 JSON 字符串供 LLM 分析
        时间单位从毫秒转换为秒

        Args:
            utterances: ASR 返回的 utterances 列表

        Returns:
            JSON 格式字符串，时间单位为秒（保留两位小数）
        """
        converted = []
        for utt in utterances:
            item = {
                "start": round(utt.get("start_time", 0) / 1000.0, 2),
                "end": round(utt.get("end_time", 0) / 1000.0, 2),
                "text": utt.get("text", ""),
            }
            if "speaker" in utt:
                item["speaker"] = utt["speaker"]
            converted.append(item)

        return json.dumps(converted, ensure_ascii=False, indent=2)

    @staticmethod
    def _format_topic_slices(topic_slices: List[Dict[str, Any]]) -> str:
        """
        将话题切分结果格式化为字符串

        Args:
            topic_slices: 话题切分结果列表

        Returns:
            格式化的话题切分字符串
        """
        if not topic_slices:
            return ""

        formatted = []
        for idx, topic in enumerate(topic_slices):
            start = topic.get("start", 0)
            end = topic.get("end", 0)
            content = topic.get("content", "")
            formatted.append(f"话题{idx + 1}: [{start:.2f}s - {end:.2f}s] {content}")

        return "话题切分结果：\n" + "\n".join(formatted) + "\n"

    @staticmethod
    def _validate_highlight_static(highlight: Dict[str, Any], index: int) -> bool:
        """
        验证单个精华片段的必需字段

        Args:
            highlight: 精华片段信息
            index: 片段索引

        Returns:
            是否有效
        """
        required_fields = ['start', 'end', 'duration', 'content']

        # 检查必需字段
        for field in required_fields:
            if field not in highlight:
                logger.warning(f"精华片段 {index} 缺少字段 '{field}': {highlight}")
                return False

        # 检查时间有效性
        start = highlight.get("start", 0)
        end = highlight.get("end", 0)
        duration = highlight.get("duration", 0)
        if start < 0 or end <= start:
            logger.warning(f"精华片段 {index} 时间范围无效: start={start}, end={end}")
            return False

        # 检查 duration 是否与 start/end 一致
        expected_duration = end - start
        if abs(duration - expected_duration) > 1:
            logger.warning(f"精华片段 {index} duration 与 start/end 不匹配: duration={duration}, expected={expected_duration}")
            return False

        return True