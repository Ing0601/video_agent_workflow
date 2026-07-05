"""
视频片段字幕分组和格式化模块

提供通用的字幕处理功能：
1. 将ASR识别的字幕句子分配到视频片段中
2. 格式化字幕文本
"""

from typing import Any, Dict, List
from ..logger.logging import logger


class SubtitleGrouper:
    """字幕分组器：将ASR字幕分配到视频片段"""
    
    def insert_asr_to_segments(
        self,
        segments: List[Dict[str, Any]],
        utterances: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        将ASR字幕插入到对应的时间片段中
        
        每句话只插入到重叠时间最长的那个片段中
        
        Args:
            segments: 视频片段列表，每个片段包含：
                - segment_index: 片段索引
                - start_time: 开始时间（秒）
                - end_time: 结束时间（秒）
            utterances: ASR句子信息列表，每个元素包含：
                - start_time: 开始时间（毫秒）
                - end_time: 结束时间（毫秒）
                - text: 文本内容
                - speaker: 说话人ID（可选）
            
        Returns:
            更新后的segments，每个segment增加 "subtitle" 字段
        """
        try:
            sentences_in_seconds = []
            for idx, sentence in enumerate(utterances):
                sentences_in_seconds.append({
                    "id": idx,
                    "start": sentence["start_time"] / 1000.0,
                    "end":   sentence["end_time"]   / 1000.0,
                    "text": sentence.get("text", ""),
                    "speaker": sentence.get("speaker") or "unknown"
                })
            
            # 第一步：为每个句子找到最佳匹配的片段（重叠时间最长的片段）
            sentence_to_segment = {}  # {sentence_id: segment_index}
            
            for sentence in sentences_in_seconds:
                sent_id = sentence["id"]
                sent_start = sentence["start"]
                sent_end = sentence["end"]
                
                best_segment_idx = None
                max_overlap_duration = 0
                
                for segment in segments:
                    segment_idx = segment["segment_index"]
                    segment_start = segment["start_time"]
                    segment_end = segment["end_time"]
                    
                    # 计算重叠时间
                    overlap_start = max(segment_start, sent_start)
                    overlap_end = min(segment_end, sent_end)
                    overlap_duration = max(0, overlap_end - overlap_start)
                    
                    # 找到重叠时间最长的片段
                    if overlap_duration > max_overlap_duration:
                        max_overlap_duration = overlap_duration
                        best_segment_idx = segment_idx
                
                # 只有当有实际重叠时才分配（避免完全不重叠的句子）
                if max_overlap_duration > 0:
                    sentence_to_segment[sent_id] = best_segment_idx
            
            # 第二步：为每个片段收集分配给它的句子
            segment_sentences = {seg["segment_index"]: [] for seg in segments}
            
            for sentence in sentences_in_seconds:
                sent_id = sentence["id"]
                if sent_id in sentence_to_segment:
                    segment_idx = sentence_to_segment[sent_id]
                    segment_sentences[segment_idx].append(sentence)
            
            # 第三步：为每个片段格式化字幕
            formatter = SubtitleFormatter()
            for segment in segments:
                segment_idx = segment["segment_index"]
                assigned_sentences = segment_sentences[segment_idx]
                
                # 按时间排序
                assigned_sentences.sort(key=lambda x: x["start"])
                
                # 格式化字幕
                subtitle = formatter.format_subtitle(assigned_sentences)
                segment["subtitle"] = subtitle
                
                logger.debug(
                    f"片段 {segment_idx}: {segment['start_time']:.2f}s-{segment['end_time']:.2f}s, "
                    f"分配到 {len(assigned_sentences)} 个句子"
                )
            
            total_matched = sum(1 for seg in segments if seg.get("subtitle"))
            logger.info(f"✓ 成功为 {total_matched}/{len(segments)} 个片段插入ASR字幕")
            
            return segments
            
        except Exception as e:
            import traceback
            logger.error(f"插入ASR字幕异常: {e}")
            logger.error(f"堆栈:\n{traceback.format_exc()}")
            return segments


class SubtitleFormatter:
    """字幕格式化器：将句子列表格式化为可读文本"""
    
    def format_subtitle(self, sentences: List[Dict[str, Any]]) -> str:
        """
        格式化字幕文本
        
        同一speaker连续句子合并，不同speaker用分号分隔
        格式: "speaker 1: xxx; speaker 2: yyy"
        
        Args:
            sentences: 句子列表（已按时间排序），每个元素包含：
                - text: 文本内容
                - speaker: 说话人ID
        
        Returns:
            格式化后的字幕文本
        """
        if not sentences:
            return ""
        
        result_parts = []
        current_speaker = None
        current_texts = []
        
        for sentence in sentences:
            speaker_raw = sentence.get("speaker") or "unknown"
            text = sentence.get("text", "").strip()
            
            if not text:
                continue
            
            # 格式化speaker: 如果是纯数字，添加"speaker "前缀
            if isinstance(speaker_raw, str) and speaker_raw.isdigit():
                speaker = f"speaker {speaker_raw}"
            else:
                speaker = speaker_raw
            
            if speaker == current_speaker:
                # 同一speaker，合并文本
                current_texts.append(text)
            else:
                # 不同speaker，先保存之前的
                if current_speaker is not None and current_texts:
                    combined_text = " ".join(current_texts)
                    result_parts.append(f"{current_speaker}: {combined_text}")
                
                current_speaker = speaker
                current_texts = [text]
        
        if current_speaker is not None and current_texts:
            combined_text = " ".join(current_texts)
            result_parts.append(f"{current_speaker}: {combined_text}")
        
        # 用分号连接不同speaker的文本
        return "; ".join(result_parts)
