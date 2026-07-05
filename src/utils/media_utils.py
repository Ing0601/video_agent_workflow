import os
import subprocess
from pathlib import Path
from typing import Optional, List, Union

from .ffmpeg_utils import get_ffmpeg_path
from .process_utils import run_command
from ..logger.logging import logger

# 支持抽取音频的视频扩展名
_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".flv", ".wmv", ".webm", ".m4v", ".ts", ".mts"}


def time_to_seconds(time_str: Union[str, int, float]) -> float:
    """将时间字符串转换为秒数。

    支持格式:
        - "MM:SS": 分钟:秒
        - "HH:MM:SS": 小时:分钟:秒
        - "SS.S": 秒数（可带小数）
        - 直接传入数字（int或float）

    Args:
        time_str: 时间字符串或数字

    Returns:
        float: 转换后的秒数
    """
    # 如果已经是数字，直接返回
    if isinstance(time_str, (int, float)):
        return float(time_str)
    
    if ':' in time_str:
        parts = time_str.split(':')
        if len(parts) == 2:  # MM:SS
            return int(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 3:  # HH:MM:SS
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    else:
        # 直接是秒数
        return float(time_str)


def is_video_file(file_path: str) -> bool:
    """判断文件是否为支持的视频格式。

    Args:
        file_path: 文件路径

    Returns:
        bool: 是视频文件返回 True，否则返回 False
    """
    return Path(file_path).suffix.lower() in _VIDEO_EXTENSIONS


def extract_audio_from_video_with_ffmpeg(
    video_path: str,
    audio_path: str,
    sample_rate: int = 16000,
    channels: int = 1,
    timeout: int = 120,
) -> bool:
    """使用 ffmpeg 从视频中抽取音频。

    Args:
        video_path: 视频文件路径
        audio_path: 输出音频文件路径
        sample_rate: 采样率，默认 16000
        channels: 声道数，默认 1（单声道）
        timeout: ffmpeg 命令超时时间（秒），默认 120

    Returns:
        bool: 抽取成功返回 True，否则返回 False
    """
    if not is_video_file(video_path):
        raise ValueError(f"不支持的视频格式: {video_path}")
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"视频文件不存在: {video_path}")

    os.makedirs(os.path.dirname(os.path.abspath(audio_path)), exist_ok=True)

    try:
        ffmpeg_executable = get_ffmpeg_path()

        cmd = [
            ffmpeg_executable,
            "-i", video_path,
            "-ar", str(sample_rate),
            "-ac", str(channels),
            "-acodec", "pcm_s16le",
            audio_path,
            "-loglevel", "error",
            "-y",
            "-nostdin",
        ]

        run_command(cmd, timeout=timeout, check=True)

        if not os.path.exists(audio_path) or os.path.getsize(audio_path) == 0:
            logger.error(f"音频抽取失败：输出文件为空或不存在: {video_path}")
            logger.error(f"  可能原因：视频文件不包含音频轨道")
            return False

        return True

    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg 错误: {video_path}")
        if e.stderr:
            logger.error(f"  错误详情: {e.stderr}")
        logger.error(f"  可能原因:")
        logger.error(f"  1. 视频文件无音频轨道")
        logger.error(f"  2. 音频编码格式不支持")
        logger.error(f"  3. 文件已损坏")
        return False
    except subprocess.TimeoutExpired:
        logger.error(f"音频抽取超时 (>{timeout}s): {video_path}")
        return False
    except Exception as e:
        logger.error(f"音频抽取异常: {video_path}，原因: {e}")
        return False


def extract_frames(
    video_path: str,
    output_dir: str,
    fps: float = 1.0,
    start_time: float = 0,
    duration: Optional[float] = None,
    timeout: int = 120,
    auto_adjust: bool = True,
    min_frames: int = 4,
    max_frames: int = 2000,
) -> List[str]:
    """从视频中提取帧。

    Args:
        video_path: 视频文件路径
        output_dir: 输出目录路径
        fps: 提取帧率（每秒提取帧数），默认 1.0
        start_time: 开始时间（秒），默认 0
        duration: 持续时间（秒），None 表示到视频结尾
        timeout: ffmpeg 命令超时时间（秒），默认 120
        auto_adjust: 是否自动调整fps使帧数在 (min_frames, max_frames) 范围内，默认 True
        min_frames: 最小帧数，默认 4
        max_frames: 最大帧数，默认 2000

    Returns:
        List[str]: 提取的帧文件路径列表，失败返回空列表
    """
    from .video_utils import VideoUtils
    
    if not is_video_file(video_path):
        raise ValueError(f"不支持的视频格式: {video_path}")
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"视频文件不存在: {video_path}")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # 自动调整 fps 使帧数在 (min_frames, max_frames) 范围内
    if auto_adjust:
        try:
            video_duration = VideoUtils.get_video_duration_seconds(video_path)
            # 计算实际需要提取的时长
            actual_duration = video_duration - start_time
            if duration is not None:
                actual_duration = min(actual_duration, duration)
            
            if actual_duration > 0:
                estimated_frames = int(actual_duration * fps)

                if estimated_frames < min_frames:
                    # 帧数太少，提高 fps
                    fps = min_frames / actual_duration
                    logger.info(f"自动调整fps: 预估帧数({estimated_frames}) < {min_frames}，调整fps为 {fps:.2f}")
                elif estimated_frames > max_frames:
                    # 帧数太多，降低 fps
                    fps = max_frames / actual_duration
                    logger.info(f"自动调整fps: 预估帧数({estimated_frames}) > {max_frames}，调整fps为 {fps:.2f}")
            else:
                # 时长为0或负数，使用默认fps
                logger.warning(f"视频片段时长无效({actual_duration:.2f}s)，使用默认fps={fps}")
                auto_adjust = False
        except Exception as e:
            logger.warning(f"获取视频时长失败，跳过自动调整fps: {e}")

    try:
        ffmpeg_executable = get_ffmpeg_path()

        # 构建 FFmpeg 命令
        cmd = [
            ffmpeg_executable,
            "-ss", str(start_time),
            "-i", video_path,
        ]

        if duration is not None:
            cmd.extend(["-t", str(duration)])

        output_pattern = str(output_path / "frame_%04d.jpg")
        cmd.extend([
            "-vf", f"fps={fps}",
            "-loglevel", "error",
            "-y",
            "-nostdin",
            output_pattern,
        ])

        run_command(cmd, timeout=timeout, check=True)

        # 获取生成的帧文件列表
        frame_files = sorted(output_path.glob("frame_*.jpg"))
        
        if not frame_files:
            logger.error(f"帧提取失败：未生成任何帧文件: {video_path}")
            return []

        return [str(f) for f in frame_files]

    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg 错误: {video_path}")
        if e.stderr:
            logger.error(f"  错误详情: {e.stderr}")
        logger.error(f"  可能原因:")
        logger.error(f"  1. 视频文件损坏")
        logger.error(f"  2. 不支持的视频编码格式")
        logger.error(f"  3. 时间参数超出视频范围")
        return []
    except subprocess.TimeoutExpired:
        logger.error(f"帧提取超时 (>{timeout}s): {video_path}")
        return []
    except Exception as e:
        logger.error(f"帧提取异常: {video_path}，原因: {e}")
        return []

def split_image_into_grid(image_path: str, output_dir: str, rows: int = 3, cols: int = 3) -> List[str]:
    """将图片按网格均匀切分。

    Args:
        image_path: 输入图片路径
        output_dir: 输出目录
        rows: 行数，默认3
        cols: 列数，默认3

    Returns:
        List[str]: 切分后的图片路径列表（按从左到右、从上到下的顺序），失败返回空列表
    """
    try:
        from PIL import Image
        
        os.makedirs(output_dir, exist_ok=True)
        
        logger.info(f"开始切分图片: {image_path}，网格: {rows}x{cols}")
        img = Image.open(image_path).convert("RGB")
        width, height = img.size
        
        logger.info(f"图片尺寸: {width}x{height}")
        
        # 计算每个格子的基础宽高
        cell_w = width // cols
        cell_h = height // rows
        
        output_paths = []
        base_name = os.path.splitext(os.path.basename(image_path))[0]
        
        # 按行优先顺序切分（从左到右，从上到下）
        tile_index = 1
        for i in range(rows):
            for j in range(cols):
                # 计算切分边界，最后一列/行延伸到图片边界
                left = j * cell_w
                right = (j + 1) * cell_w if j < cols - 1 else width
                top = i * cell_h
                bottom = (i + 1) * cell_h if i < rows - 1 else height
                
                # 裁剪
                tile = img.crop((left, top, right, bottom))
                
                # 保存，文件名格式: 原文件名_1.jpg 到 原文件名_9.jpg
                output_path = os.path.join(output_dir, f"{base_name}_{tile_index}.jpg")
                tile.save(output_path, "JPEG", quality=95)
                output_paths.append(output_path)
                
                logger.info(f"保存切片 {tile_index}/{rows*cols}: {output_path} (尺寸: {right-left}x{bottom-top})")
                tile_index += 1
        
        logger.info(f"图片切分完成，共生成 {len(output_paths)} 张图片")
        return output_paths
        
    except ImportError:
        logger.error("缺少 Pillow 库，请安装: pip install Pillow")
        return []
    except Exception as e:
        logger.error(f"切分图片异常: {image_path}，原因: {e}")
        return []