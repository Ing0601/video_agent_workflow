"""
视频处理工具模块 - 提供视频相关的处理功能
"""

import os
import random
from pathlib import Path
from typing import Optional, Dict, Any, List
from .ffmpeg_utils import get_ffmpeg_path, get_ffprobe_path
from .process_utils import run_command
from ..logger.logging import logger


class VideoUtils:
    """视频处理工具类"""
    
    @staticmethod
    def get_video_duration(video_path: str) -> str:
        """
        使用ffmpeg获取视频时长
        
        Args:
            video_path: 视频文件路径
            
        Returns:
            视频时长，格式为 HH:MM:SS，失败返回 "00:00:00"
        """
        try:
            cmd = [
                get_ffmpeg_path(),
                '-i', video_path,
                '-hide_banner'
            ]
            result = run_command(
                cmd,
                capture_output=True,
                text=True
            )
            output = result.stdout
            
            # 从ffmpeg输出中提取时长
            for line in output.split('\n'):
                if 'Duration:' in line:
                    # 格式: Duration: 00:01:30.45, start: 0.000000, bitrate: 1234 kb/s
                    duration_str = line.split('Duration:')[1].split(',')[0].strip()
                    # 取前8位 HH:MM:SS
                    duration = duration_str[:8]
                    logger.info(f"获取视频时长: {video_path} -> {duration}")
                    return duration
            
            logger.warning(f"无法从ffmpeg输出中提取时长: {video_path}")
            return "00:00:00"
            
        except Exception as e:
            logger.error(f"获取视频时长失败 {video_path}: {e}")
            return "00:00:00"
    
    @staticmethod
    def get_video_duration_seconds(video_path: str) -> float:
        """
        获取视频时长（秒）
        
        Args:
            video_path: 视频文件路径
            
        Returns:
            视频时长（秒），失败返回0.0
        """
        try:
            cmd = [
                get_ffprobe_path(),
                '-v', 'quiet',
                '-print_format', 'json',
                '-show_format',
                video_path
            ]
            result = run_command(
                cmd,
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                import json
                data = json.loads(result.stdout)
                duration = float(data['format']['duration'])
                logger.info(f"获取视频时长: {video_path} -> {duration}秒")
                return duration
            else:
                logger.warning(f"ffprobe获取时长失败: {result.stderr}")
                
        except Exception as e:
            logger.error(f"获取视频时长失败 {video_path}: {e}")
        
        # 如果ffprobe失败，尝试使用ffmpeg
        duration_str = VideoUtils.get_video_duration(video_path)
        return VideoUtils.duration_to_seconds(duration_str)
    
    @staticmethod
    def duration_to_seconds(duration_str: str) -> float:
        """
        将时长字符串转换为秒数
        
        Args:
            duration_str: 时长字符串，格式为 HH:MM:SS 或 HH:MM:SS.fff
            
        Returns:
            秒数
        """
        try:
            # 处理可能的格式：HH:MM:SS 或 HH:MM:SS.fff
            if '.' in duration_str:
                time_part, ms_part = duration_str.split('.')
                ms = float('0.' + ms_part)
            else:
                time_part = duration_str
                ms = 0.0
            
            # 解析 HH:MM:SS
            time_parts = time_part.split(':')
            if len(time_parts) == 3:
                hours = int(time_parts[0])
                minutes = int(time_parts[1])
                seconds = int(time_parts[2])
                total_seconds = hours * 3600 + minutes * 60 + seconds + ms
                return total_seconds
            else:
                logger.warning(f"时长格式不正确: {duration_str}")
                return 0.0
                
        except Exception as e:
            logger.error(f"时长转换失败 {duration_str}: {e}")
            return 0.0
    
    @staticmethod
    def seconds_to_duration(seconds: float) -> str:
        """
        将秒数转换为时长字符串
        
        Args:
            seconds: 秒数
            
        Returns:
            时长字符串，格式为 HH:MM:SS
        """
        try:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            secs = int(seconds % 60)
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        except:
            return "00:00:00"
    
    @staticmethod
    def get_video_info(video_path: str) -> Dict[str, Any]:
        """
        获取视频信息
        
        Args:
            video_path: 视频文件路径
            
        Returns:
            视频信息字典
        """
        video_path = Path(video_path)
        info = {
            "path": str(video_path),
            "name": video_path.name,
            "stem": video_path.stem,
            "size": 0,
            "duration": "00:00:00",
            "duration_seconds": 0.0,
            "exists": False
        }
        
        try:
            if video_path.exists():
                info["exists"] = True
                info["size"] = video_path.stat().st_size
                info["duration"] = VideoUtils.get_video_duration(str(video_path))
                info["duration_seconds"] = VideoUtils.get_video_duration_seconds(str(video_path))
                
        except Exception as e:
            logger.error(f"获取视频信息失败 {video_path}: {e}")
        
        return info
    
    @staticmethod
    def is_video_file(file_path: str) -> bool:
        """
        检查文件是否为视频文件
        
        Args:
            file_path: 文件路径
            
        Returns:
            是否为视频文件
        """
        video_extensions = {'.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv', 
                           '.MP4', '.AVI', '.MOV', '.MKV', '.FLV', '.WMV'}
        return Path(file_path).suffix in video_extensions
    
    @staticmethod
    def validate_video_file(video_path: str) -> bool:
        """
        验证视频文件是否有效
        
        Args:
            video_path: 视频文件路径
            
        Returns:
            视频文件是否有效
        """
        try:
            path = Path(video_path)
            
            # 检查文件是否存在
            if not path.exists():
                logger.error(f"视频文件不存在: {video_path}")
                return False
            
            # 检查是否为视频文件
            if not VideoUtils.is_video_file(video_path):
                logger.error(f"不是支持的视频文件格式: {video_path}")
                return False
            
            # 检查文件大小
            if path.stat().st_size == 0:
                logger.error(f"视频文件为空: {video_path}")
                return False
            
            # 尝试获取视频时长来验证文件完整性
            duration_seconds = VideoUtils.get_video_duration_seconds(video_path)
            if duration_seconds <= 0:
                logger.error(f"视频文件损坏或无法读取: {video_path}")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"验证视频文件失败 {video_path}: {e}")
            return False
    
    @staticmethod
    def get_keyframes_near_time(video_path: str, target_times: List[float]) -> Dict[float, float]:
        """
        获取目标时间点附近的关键帧位置
        
        Args:
            video_path: 视频文件路径
            target_times: 目标时间点列表（秒）
            
        Returns:
            字典，key为目标时间，value为最近的关键帧时间
        """
        try:
            # 使用ffprobe获取关键帧信息
            cmd = [
                get_ffprobe_path(),
                '-select_streams', 'v:0',
                '-show_entries', 'frame=key_frame,pkt_pts_time',
                '-of', 'csv=print_section=0',
                '-v', 'quiet',
                video_path
            ]
            
            result = run_command(
                cmd,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode != 0:
                logger.warning(f"无法获取关键帧信息: {result.stderr}")
                return {t: t for t in target_times}  # 返回原始时间
            
            # 解析关键帧时间
            keyframes = []
            for line in result.stdout.strip().split('\n'):
                if not line:
                    continue
                parts = line.split(',')
                if len(parts) >= 2:
                    is_keyframe = parts[0]
                    pts_time = parts[1]
                    if is_keyframe == '1' and pts_time != 'N/A':
                        try:
                            keyframes.append(float(pts_time))
                        except ValueError:
                            continue
            
            if not keyframes:
                logger.warning("未找到关键帧，使用原始时间")
                return {t: t for t in target_times}
            
            keyframes.sort()
            logger.info(f"找到 {len(keyframes)} 个关键帧")
            
            # 为每个目标时间找最近的关键帧
            result_dict = {}
            for target_time in target_times:
                # 找到最接近的关键帧
                closest_keyframe = min(keyframes, key=lambda x: abs(x - target_time))
                
                # 如果距离相同，取时间大的（你的要求）
                candidates = [kf for kf in keyframes if abs(kf - target_time) == abs(closest_keyframe - target_time)]
                if len(candidates) > 1:
                    closest_keyframe = max(candidates)
                
                result_dict[target_time] = closest_keyframe
                offset = closest_keyframe - target_time
                logger.info(f"  切分点 {target_time}s -> 关键帧 {closest_keyframe:.2f}s (偏差 {offset:+.2f}s)")
            
            return result_dict
            
        except Exception as e:
            logger.error(f"获取关键帧失败: {e}")
            return {t: t for t in target_times}
    
    @staticmethod
    def split_video_by_duration(video_path: str, 
                               segment_duration: int = 120,
                               overlap_seconds: float = 0,
                               output_dir: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        按时长拆分视频为多个片段
        
        Args:
            video_path: 视频文件路径
            segment_duration: 每个片段的时长（秒），默认120秒（2分钟）
            overlap_seconds: 每个片段的重叠时长（秒），默认0秒
            output_dir: 输出目录，默认为视频所在目录下的 temp_segments 文件夹
            
        Returns:
            片段信息列表，每个元素包含:
            {
                "segment_index": 片段索引（从0开始）,
                "segment_path": 片段文件路径,
                "start_time": 开始时间（秒）,
                "duration": 片段时长（秒）,
                "end_time": 结束时间（秒）
            }
        """
        try:
            video_path = Path(video_path)
            
            # 获取视频总时长
            total_duration = VideoUtils.get_video_duration_seconds(str(video_path))
            if total_duration <= 0:
                logger.error(f"无法获取视频时长: {video_path}")
                return []
            
            # 如果视频时长小于等于segment_duration，不需要拆分
            if total_duration <= segment_duration:
                logger.info(f"视频时长 {total_duration}秒 <= {segment_duration}秒，无需拆分")
                return []
            
            # 设置输出目录
            if output_dir is None:
                output_dir = video_path.parent / "temp_segments" / video_path.stem
            else:
                output_dir = Path(output_dir)
            
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # 计算需要拆分的片段数
            num_segments = int((total_duration + segment_duration - 1) // segment_duration)
            
            logger.info(f"视频总时长 {total_duration}秒，将拆分为 {num_segments} 个片段")
            logger.info(f"每个片段 {segment_duration}秒，重叠 {overlap_seconds}秒")
            
            segments = []
            
            for i in range(num_segments):
                # 直接使用固定间隔切分，ffmpeg -ss 配合 -c copy 会自动在关键帧处理
                start_time = max(0, i * segment_duration - overlap_seconds)
                end_time = min(total_duration, (i + 1) * segment_duration + overlap_seconds)
                current_duration = end_time - start_time
                
                # 生成片段文件名
                segment_filename = f"{video_path.stem}_seg{i:03d}{video_path.suffix}"
                segment_path = output_dir / segment_filename
                
                # 使用ffmpeg切分视频（关键帧切分 + 复制模式，速度快）
                # -ss 放在 -i 前面，让ffmpeg自动寻找关键帧
                # 使用 -to 指定结束时间（相对于-ss的偏移）
                cmd = [
                    get_ffmpeg_path(),
                    '-ss', str(start_time),
                    '-i', str(video_path),
                    '-to', str(current_duration),  # 相对时长
                    '-c', 'copy',  # 复制模式，不重新编码
                    '-avoid_negative_ts', '1',
                    '-y',
                    str(segment_path)
                ]
                
                logger.info(f"切分片段 {i+1}/{num_segments}: {start_time:.2f}s - {end_time:.2f}s (实际时长: {current_duration:.2f}s)")
                
                result = run_command(
                    cmd,
                    capture_output=True,
                    text=True
                )
                
                if result.returncode != 0:
                    logger.error(f"切分视频片段失败: {result.stderr}")
                    # 清理已生成的片段
                    VideoUtils.cleanup_segments(segments)
                    return []
                
                segment_info = {
                    "segment_index": i,
                    "segment_path": str(segment_path),
                    "start_time": start_time,  # 实际的关键帧位置, time_offset
                    "duration": current_duration,
                    "end_time": end_time
                }
                
                segments.append(segment_info)
                logger.info(f"  片段 {i+1} 创建成功: {segment_path}")
            
            logger.info(f"视频拆分完成，共 {len(segments)} 个片段（关键帧切分+复制模式）")
            return segments
            
        except Exception as e:
            logger.error(f"拆分视频失败 {video_path}: {e}")
            return []
    
    @staticmethod
    def cleanup_segments(segments: List[Dict[str, Any]]) -> None:
        """
        清理临时视频片段文件
        
        Args:
            segments: 片段信息列表
        """
        try:
            for segment in segments:
                segment_path = Path(segment.get("segment_path", ""))
                if segment_path.exists():
                    segment_path.unlink()
                    logger.info(f"已删除临时片段: {segment_path}")
            
            # 尝试删除空的临时目录
            if segments:
                first_segment_path = Path(segments[0]["segment_path"])
                temp_dir = first_segment_path.parent
                if temp_dir.exists() and not any(temp_dir.iterdir()):
                    temp_dir.rmdir()
                    logger.info(f"已删除空的临时目录: {temp_dir}")
                    
        except Exception as e:
            logger.warning(f"清理临时片段文件时出错: {e}")
    
    @staticmethod
    def adjust_timestamps(data: Any, time_offset: float) -> Any:
        """
        递归调整数据结构中的时间戳
        
        Args:
            data: 包含时间戳的数据结构（dict, list等）
            time_offset: 时间偏移量（秒）
            
        Returns:
            调整后的数据结构
        """
        if isinstance(data, dict):
            adjusted = {}
            for key, value in data.items():
                # 识别时间相关的字段
                if key in ['start', 'end', 'begin_time', 'end_time', 'start_time']:
                    if isinstance(value, (int, float)):
                        # 保持数字类型
                        adjusted[key] = value + time_offset
                    elif isinstance(value, str):
                        # 尝试转换字符串为数字，并保持数字类型
                        try:
                            # 清理字符串：去除空格和可能的逗号
                            cleaned_value = value.strip().rstrip(',')
                            num_value = float(cleaned_value)
                            # 重要：转换后保持数字类型，不要转回字符串
                            adjusted[key] = num_value + time_offset
                        except Exception as e:
                            logger.warning(f"无法转换时间字段 {key}='{value}' 为数字: {e}，保持原值")
                            adjusted[key] = value
                    else:
                        adjusted[key] = value
                else:
                    adjusted[key] = VideoUtils.adjust_timestamps(value, time_offset)
            return adjusted
        elif isinstance(data, list):
            return [VideoUtils.adjust_timestamps(item, time_offset) for item in data]
        else:
            return data
