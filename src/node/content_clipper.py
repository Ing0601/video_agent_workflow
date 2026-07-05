"""
内容切片节点

基于 ASR 字幕分析生成视频切片方案
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
    """切片验证失败异常，用于触发重试"""
    pass


class ContentClipper:
    """内容切片节点 - 基于字幕分析生成视频切片方案"""
    
    def generate_slices(
        self,
        utterances: List[Dict[str, Any]],
        system_prompt: str,
        user_prompt_template: str = None,
        api_key: str = None,
        model: str = "qwen3-max",
        temperature: float = 0.7
    ) -> Dict[str, Any]:
        """
        生成视频切片方案
        
        网络异常时自动指数退避重试（最多 3 次，等待 1s → 2s → 4s）。
        验证失败（_validate_slice 不通过）时也会重试。
        
        Args:
            utterances: ASR 识别的 utterances 列表（时间单位：毫秒）
                       [{"start_time": 0, "end_time": 1000, "text": "...", "speaker": "..."}, ...]
            system_prompt: 系统提示词
            user_prompt_template: 用户提示词模板（可选，默认使用标准模板）
            api_key: Qwen API密钥（可选，默认从环境变量获取）
            model: Qwen模型名称
            temperature: LLM温度参数
            
        Returns:
            {
                "success": bool,
                "slices": [  # 切片方案（时间单位：秒）
                    {"start": 0.0, "end": 5.0, "content": "..."},
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
            formatted_text = ContentClipper._format_utterances(utterances)
            
            # 2. 构建用户提示词（使用默认模板或自定义模板）
            if user_prompt_template is None:
                user_prompt = f"""请分析以下字幕句子信息，按照要求生成切片方案：

{formatted_text}

请严格按照JSON格式输出切片方案。"""
            else:
                user_prompt = user_prompt_template.format(formatted_text=formatted_text)
            
            # 3. 初始化 LLM 客户端
            api_key = api_key or os.getenv("DASHSCOPE_API_KEY")
            llm_client = QwenLLMClient(api_key=api_key, model=model)
            
            # 4. 调用 LLM（带重试机制）
            logger.info("调用LLM生成切片方案...")
            llm_result = self._generate_slices_with_retry(
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
            
            # 5. 提取内容和 usage
            if isinstance(llm_result, dict) and "content" in llm_result:
                slices = llm_result.get("content")
                usage = llm_result.get("usage")
            else:
                slices = llm_result
                usage = None
            
            logger.info(f"✓ 成功生成 {len(slices)} 个有效切片")
            
            return {
                "success": True,
                "slices": slices,
                "usage": usage
            }
            
        except Exception as e:
            logger.error(f"切片生成异常（重试已耗尽）: {e}")
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
    def _generate_slices_with_retry(
        llm_client: QwenLLMClient,
        user_prompt: str,
        system_prompt: str,
        temperature: float
    ) -> Dict[str, Any]:
        """
        带指数退避重试的 LLM 调用和验证
        
        网络异常或验证失败时触发重试
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
            slices = llm_result.get("content")
            usage = llm_result.get("usage")
        else:
            slices = llm_result
            usage = None
        
        # 验证结果格式
        if not isinstance(slices, list) or len(slices) == 0:
            raise ValidationError(f"Invalid LLM response format: expected list, got {type(slices)}")
        
        # 验证每个切片
        validated_slices = []
        invalid_count = 0
        for idx, slice_info in enumerate(slices):
            if ContentClipper._validate_slice_static(slice_info, idx):
                validated_slices.append(slice_info)
            else:
                invalid_count += 1
        
        # 如果没有任何有效切片，触发重试
        if not validated_slices:
            raise ValidationError(f"No valid slices after validation (all {len(slices)} slices failed)")
        
        # 如果有效切片比例过低（少于50%），也触发重试
        if len(validated_slices) < len(slices) * 0.5:
            raise ValidationError(
                f"Too many invalid slices: {invalid_count}/{len(slices)} failed validation"
            )
        
        # 返回结果时保留 usage 信息
        if usage:
            return {
                "content": validated_slices,
                "usage": usage
            }
        return validated_slices
    
    @staticmethod
    def _format_utterances(utterances: List[Dict[str, Any]]) -> str:
        """
        将 ASR utterances 格式化为 JSON 字符串供 LLM 分析
        时间单位从毫秒转换为秒
        
        Args:
            utterances: ASR 返回的 utterances 列表
                       [{"start_time": 0, "end_time": 1000, "text": "...", "speaker": "..."}, ...]
                       
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
    def _validate_slice_static(slice_info: Dict[str, Any], index: int) -> bool:
        """
        验证单个切片的必需字段
        
        Args:
            slice_info: 切片信息
            index: 切片索引
            
        Returns:
            是否有效
        """
        required_fields = ['start', 'end', 'content']
        
        # 检查必需字段
        for field in required_fields:
            if field not in slice_info:
                logger.warning(f"切片 {index} 缺少字段 '{field}': {slice_info}")
                return False
        
        return True
