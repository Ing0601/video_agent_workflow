"""
视频切分节点

负责根据时间戳切片方案将视频物理切分成多个片段。
"""
from pathlib import Path
from typing import Any, Dict, List

from ..utils.ffmpeg_utils import get_ffmpeg_path
from ..utils.process_utils import run_command
from ..logger.logging import logger


class VideoSplitter:
    """视频切分节点"""
    
    def split_video(
        self,
        video_path: str,
        slices: List[Dict[str, Any]],
        output_dir: Path
    ) -> List[Dict[str, Any]]:
        """
        根据切片方案分割视频
        
        Args:
            video_path: 原始视频路径
            slices: 切片方案列表 [{"start": 0.0, "end": 5.0, "content": "..."}, ...]
            output_dir: 输出目录
            
        Returns:
            视频片段信息列表
        """
        try:
            video_path = Path(video_path)
            segments = []
            
            for idx, slice_info in enumerate(slices):
                # 解析时间（兼容数字和字符串）
                start_time = float(str(slice_info['start']).rstrip(','))
                end_time = float(str(slice_info['end']).rstrip(','))
                duration = end_time - start_time
                
                # 生成输出路径
                segment_filename = f"{video_path.stem}_slice{idx:03d}{video_path.suffix}"
                segment_path = output_dir / segment_filename
                
                # FFmpeg 切分命令
                cmd = [
                    get_ffmpeg_path(),
                    '-ss', str(start_time),
                    '-i', str(video_path),
                    '-t', str(duration),
                    '-c', 'copy',
                    '-avoid_negative_ts', '1',
                    '-y',
                    str(segment_path)
                ]
                
                logger.info(f"切分片段 {idx+1}/{len(slices)}: {start_time:.2f}s - {end_time:.2f}s (时长: {duration:.2f}s)")
                
                result = run_command(cmd, capture_output=True, text=True)
                
                if result.returncode != 0:
                    logger.error(f"切分视频片段失败: {result.stderr}")
                    continue
                
                segments.append({
                    "segment_index": idx,
                    "segment_path": str(segment_path),
                    "start_time": start_time,
                    "end_time": end_time,
                    "duration": duration,
                    "content_summary": slice_info.get("content", "")
                })
            
            logger.info(f"✓ 成功切分 {len(segments)}/{len(slices)} 个视频片段")
            return segments
            
        except Exception as e:
            import traceback
            logger.error(f"视频切分异常: {e}")
            logger.error(f"堆栈:\n{traceback.format_exc()}")
            return []
