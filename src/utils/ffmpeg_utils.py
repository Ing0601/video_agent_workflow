"""
FFmpeg 工具模块 - 提供 FFmpeg/FFprobe 路径获取和检测功能
"""

import os
import sys
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Optional, List
import logging
from .process_utils import run_command, get_subprocess_kwargs

logger = logging.getLogger(__name__)


class FFmpegUtils:
    """FFmpeg 工具类 - 统一管理 FFmpeg 和 FFprobe 的路径"""
    
    _ffmpeg_path_cache: Optional[str] = None
    _ffprobe_path_cache: Optional[str] = None
    
    @staticmethod
    def _get_project_root() -> Path:
        """
        获取项目根目录
        
        优先级:
        1. 打包后环境: sys._MEIPASS (PyInstaller)
        2. 开发环境: 向上查找直到找到 ffmpeg 目录
        """
        if getattr(sys, 'frozen', False):
            # 打包后的临时目录
            return Path(sys._MEIPASS)
        
        # 开发环境: 从当前文件向上查找
        current = Path(__file__).resolve()
        
        # 向上查找，直到找到包含 ffmpeg 目录的根目录
        for parent in [current] + list(current.parents):
            ffmpeg_dir = parent / 'ffmpeg'
            if ffmpeg_dir.exists() and ffmpeg_dir.is_dir():
                return parent
        
        # 如果找不到，返回当前文件所在目录的根目录（最多往上3层）
        return current.parents[2] if len(current.parents) >= 3 else current.parent
    
    @staticmethod
    def _find_executable(name: str, exe_name: str) -> Optional[str]:
        """
        查找可执行文件路径
        
        Args:
            name: 基础名称 (如 'ffmpeg', 'ffprobe')
            exe_name: Windows 下的可执行文件名 (如 'ffmpeg.exe', 'ffprobe.exe')
        
        Returns:
            可执行文件的完整路径，如果找不到则返回 None
        
        优先级:
        1. 项目内 ffmpeg 目录（根据操作系统选择 .exe 或无扩展名）
        2. 系统 PATH 环境变量
        """
        system = platform.system()
        binary_name = exe_name if system == "Windows" else name
        
        # 1. 优先查找项目内的 ffmpeg 目录
        try:
            project_root = FFmpegUtils._get_project_root()
            ffmpeg_dir = project_root / 'ffmpeg'
            
            if ffmpeg_dir.exists():
                # 尝试带扩展名的版本 (Windows)
                binary_path = ffmpeg_dir / binary_name
                if binary_path.exists() and os.access(binary_path, os.X_OK):
                    logger.debug(f"找到项目内 {name}: {binary_path}")
                    return str(binary_path)
                
                # 尝试不带扩展名的版本 (Linux/Mac 或 Git 检出)
                binary_path_no_ext = ffmpeg_dir / name
                if binary_path_no_ext.exists() and os.access(binary_path_no_ext, os.X_OK):
                    logger.debug(f"找到项目内 {name}: {binary_path_no_ext}")
                    return str(binary_path_no_ext)
        except Exception as e:
            logger.warning(f"查找项目内 {name} 时出错: {e}")
        
        # 2. 尝试系统 PATH
        system_path = shutil.which(name)
        if system_path:
            logger.debug(f"找到系统 PATH 中的 {name}: {system_path}")
            return system_path
        
        # 3. 都找不到
        logger.warning(f"未找到 {name}，请确保:")
        logger.warning(f"  1. 项目 ffmpeg 目录中有 {binary_name}")
        logger.warning(f"  2. 或系统 PATH 中已安装 {name}")
        return None
    
    @staticmethod
    def get_ffmpeg_path() -> str:
        """
        获取 FFmpeg 可执行文件路径
        
        Returns:
            FFmpeg 路径，如果找不到则返回 'ffmpeg' (尝试使用系统默认)
        """
        if FFmpegUtils._ffmpeg_path_cache is None:
            path = FFmpegUtils._find_executable('ffmpeg', 'ffmpeg.exe')
            FFmpegUtils._ffmpeg_path_cache = path if path else 'ffmpeg'
        
        return FFmpegUtils._ffmpeg_path_cache
    
    @staticmethod
    def get_ffprobe_path() -> str:
        """
        获取 FFprobe 可执行文件路径
        
        Returns:
            FFprobe 路径，如果找不到则返回 'ffprobe' (尝试使用系统默认)
        """
        if FFmpegUtils._ffprobe_path_cache is None:
            path = FFmpegUtils._find_executable('ffprobe', 'ffprobe.exe')
            FFmpegUtils._ffprobe_path_cache = path if path else 'ffprobe'
        
        return FFmpegUtils._ffprobe_path_cache
    
    @staticmethod
    def reset_cache():
        """重置路径缓存（用于测试或环境变化）"""
        FFmpegUtils._ffmpeg_path_cache = None
        FFmpegUtils._ffprobe_path_cache = None
    
    @staticmethod
    def check_availability() -> dict:
        """
        检查 FFmpeg 和 FFprobe 的可用性
        
        Returns:
            包含检查结果的字典
        """
        result = {
            'ffmpeg': {
                'available': False,
                'path': None,
                'version': None
            },
            'ffprobe': {
                'available': False,
                'path': None,
                'version': None
            }
        }
        
        # 检查 ffmpeg
        ffmpeg_path = FFmpegUtils.get_ffmpeg_path()
        try:
            output = run_command(
                [ffmpeg_path, '-version'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if output.returncode == 0:
                result['ffmpeg']['available'] = True
                result['ffmpeg']['path'] = ffmpeg_path
                # 提取版本号
                version_line = output.stdout.split('\n')[0]
                result['ffmpeg']['version'] = version_line
        except Exception as e:
            logger.debug(f"FFmpeg 不可用: {e}")
        
        # 检查 ffprobe
        ffprobe_path = FFmpegUtils.get_ffprobe_path()
        try:
            output = run_command(
                [ffprobe_path, '-version'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if output.returncode == 0:
                result['ffprobe']['available'] = True
                result['ffprobe']['path'] = ffprobe_path
                # 提取版本号
                version_line = output.stdout.split('\n')[0]
                result['ffprobe']['version'] = version_line
        except Exception as e:
            logger.debug(f"FFprobe 不可用: {e}")
        
        return result
    
    @staticmethod
    def run_ffmpeg_command(command: List[str]) -> bool:
        """
        执行FFmpeg命令
        
        Args:
            command: FFmpeg命令及参数列表，例如 ['ffmpeg', '-i', 'input.mp4', 'output.mp4']
            
        Returns:
            True 表示执行成功，False 表示执行失败
        """
        try:
            logger.debug(f"执行FFmpeg命令: {' '.join(command)}")
            
            result = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace'
            )
            
            if result.returncode == 0:
                logger.debug("FFmpeg命令执行成功")
                return True
            else:
                logger.error(f"FFmpeg命令执行失败，返回码: {result.returncode}")
                logger.error(f"FFmpeg stderr: {result.stderr[-2000:]}")  # 只输出最后2000字符避免日志过长
                return False
                
        except FileNotFoundError:
            logger.error(f"FFmpeg可执行文件未找到: {command[0]}")
            return False
        except PermissionError:
            logger.error(f"没有权限执行FFmpeg: {command[0]}")
            return False
        except Exception as e:
            logger.error(f"执行FFmpeg命令时发生未知错误: {e}")
            return False
    
    def add_subtitle(video_path: str, subtitle_path: str, output_path: str) -> bool:
        """
        添加字幕到视频中
        
        Args:
            video_path: 视频文件路径
            subtitle_path: 字幕文件路径
            output_path: 输出文件路径
        """
        command = [
            FFmpegUtils.get_ffmpeg_path(),
            '-y',
            '-i', video_path,
            '-vf', f'subtitles={subtitle_path}',
            '-c:a', 'copy',
            output_path
        ]
        return FFmpegUtils.run_ffmpeg_command(command)


# 便捷函数
def get_ffmpeg_path() -> str:
    """获取 FFmpeg 路径（便捷函数）"""
    return FFmpegUtils.get_ffmpeg_path()


def get_ffprobe_path() -> str:
    """获取 FFprobe 路径（便捷函数）"""
    return FFmpegUtils.get_ffprobe_path()

def run_ffmpeg_command(command: List[str]) -> bool:
    """执行 FFmpeg 命令（便捷函数）"""
    return FFmpegUtils.run_ffmpeg_command(command)


def add_subtitle(video_path: str, subtitle_path: str, output_path: str) -> bool:
    """
    添加字幕到视频中
    
    Args:
        video_path: 视频文件路径
        subtitle_path: 字幕文件路径
        output_path: 输出文件路径
    """
    return FFmpegUtils.add_subtitle(video_path, subtitle_path, output_path)