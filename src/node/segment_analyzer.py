import os
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep_log, retry_if_exception_type

from ..model.llm.qwen_vlm import QwenVLM
from ..logger.logging import logger


class SegmentAnalyzer:
    """
    节点：视频分段视觉理解分析
    输入：分段信息列表（每个分段包含路径、时间戳等）
    输出：分析后的分段列表（包含视觉理解结果、usage等）
    """
    def __init__(self, vlm_api_key: Optional[str] = None, vlm_model: str = "qwen3-vl-plus"):
        self.logger = logger
        self.vlm_api_key = vlm_api_key or os.getenv("DASHSCOPE_API_KEY")
        self.vlm_model = vlm_model

    def analyze_segments(
        self, 
        segments: List[Dict[str, Any]], 
        prompt: str,
        fps: float = 2.0, 
        max_workers: int = 3
    ) -> List[Dict[str, Any]]:
        """
        并发分析所有分段，返回分析结果列表
        
        Args:
            segments: 视频分段信息列表
            prompt: VLM 分析提示词
            fps: 帧率
            max_workers: 最大并发数
            
        Returns:
            分析结果列表
        """
        def analyze_single_segment(segment: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            idx = segment.get("segment_index")
            segment_path = segment.get("segment_path")
            try:
                self.logger.info(f"开始分析片段 {idx+1}/{len(segments)}: {Path(segment_path).name}")
                
                # 调用带重试机制的 VLM 分析
                result = self._analyze_segment_with_retry(
                    segment=segment,
                    prompt=prompt,
                    fps=fps
                )
                return result
            except Exception as e:
                import traceback
                self.logger.error(f"片段 {idx+1} 分析异常（重试已耗尽）: {e}")
                self.logger.error(f"堆栈:\n{traceback.format_exc()}")
                return None
        results = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_segment = {executor.submit(analyze_single_segment, seg): seg for seg in segments}
            for future in as_completed(future_to_segment):
                result = future.result()
                if result is not None:
                    results.append(result)
        results.sort(key=lambda x: x["segment_index"])
        self.logger.info(f"✓ 成功分析 {len(results)}/{len(segments)} 个片段")
        return results
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),  # 1s → 2s → 4s
        retry=retry_if_exception_type((Exception,)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def _analyze_segment_with_retry(
        self,
        segment: Dict[str, Any],
        prompt: str,
        fps: float
    ) -> Dict[str, Any]:
        """
        带指数退避重试的 VLM 分析
        
        网络异常或分析失败时触发重试（最多 3 次，等待 1s → 2s → 4s）
        
        Args:
            segment: 视频分段信息
            prompt: VLM 分析提示词
            fps: 帧率
            
        Returns:
            分析结果字典
            
        Raises:
            ValueError: VLM返回内容为空或无法解析
            Exception: 网络异常或其他错误
        """
        idx = segment.get("segment_index")
        segment_path = segment.get("segment_path")
        
        # 初始化 VLM 客户端
        qwen_vlm = QwenVLM(api_key=self.vlm_api_key, model=self.vlm_model)
        self.logger.info(f"调用Qwen VLM分析片段 {idx+1}（本地文件，自动抽帧）...")
        
        # 调用 VLM
        vlm_response = qwen_vlm.call_model(
            media_input=segment_path,
            prompt=prompt,
            media_type="video",
            fps=fps
        )
        
        # 提取内容和 usage
        if isinstance(vlm_response, dict):
            vlm_content = vlm_response.get("content")
            vlm_usage = vlm_response.get("usage")
        else:
            vlm_content = vlm_response
            vlm_usage = None
        
        # 验证返回内容
        if not vlm_content:
            raise ValueError("VLM返回内容为空")
        
        # 解析 JSON
        try:
            analysis_result = json.loads(vlm_content)
        except json.JSONDecodeError as e:
            raise ValueError(f"VLM返回内容无法解析为JSON: {e}")
        
        # 返回完整结果
        return {
            "segment_index": idx,
            "segment_path": segment_path,
            "start_time": segment.get("start_time"),
            "end_time": segment.get("end_time"),
            "duration": segment.get("duration"),
            "content_summary": segment.get("content_summary", ""),
            "subtitle": segment.get("subtitle", ""),
            "visual_analysis": analysis_result,
            "vlm_usage": vlm_usage
        }
