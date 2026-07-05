import os
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional, Dict, Any, Union, Tuple

from ...config.config import ASR_TEMP_DIR
from ...logger import logger


# 支持的视频扩展名
_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".flv", ".wmv", ".webm", ".m4v", ".ts", ".mts"}
# 支持的音频扩展名（可直接上传，无需抽取）
_AUDIO_EXTENSIONS = {".opus", ".wav", ".mp3", ".spx", ".ogg", ".amr", ".aac", ".m4a"}


class BaseASR(ABC):
    """语音识别服务基类"""
    
    def __init__(self, *args, **kwargs):
        """
        初始化ASR实例
        
        不同的ASR服务有不同的认证参数：
        - ByteDanceASR: app_id, access_token
        - QwenASR: api_key, region
        """
        pass

    # ------------------------------------------------------------------
    # 本地文件预处理：将本地路径/文件夹转换为 TOS URL
    # ------------------------------------------------------------------

    @staticmethod
    def _is_local_file(path: str) -> bool:
        """判断是否为本地文件路径（非 http/https URL）"""
        return not path.startswith("http://") and not path.startswith("https://")

    @staticmethod
    def _collect_media_files(folder: str) -> List[str]:
        """
        扫描文件夹，返回所有支持的媒体文件路径列表（视频 + 音频）
        
        Args:
            folder: 文件夹路径
            
        Returns:
            媒体文件路径列表，按文件名排序
        """
        supported_exts = _VIDEO_EXTENSIONS | _AUDIO_EXTENSIONS
        files = []
        for f in sorted(Path(folder).iterdir()):
            if f.is_file() and f.suffix.lower() in supported_exts:
                files.append(str(f))
        return files

    def prepare_file_urls(
        self,
        file_paths_or_urls: Union[str, List[str]],
        tos_config: Optional[dict] = None,
        temp_dir: Optional[str] = None,
    ) -> Tuple[List[str], List[str]]:
        """
        将本地文件路径/文件夹/URL 统一转换为可供 ASR 使用的 URL 列表。

        处理逻辑：
        - 输入为 http/https URL → 直接透传
        - 输入为本地文件夹    → 扫描其中所有 mp3/mp4 等媒体文件，逐一处理
        - 输入为本地视频文件  → ffmpeg 抽取音频为临时 wav → 上传 TOS → 返回 URL
        - 输入为本地音频文件  → 直接上传 TOS → 返回 URL

        上传到 TOS 需要提供 tos_config，包含：
            access_key, secret_key, endpoint, region, bucket_name

        Args:
            file_paths_or_urls: 单个路径/URL 或其列表（可混合）
            tos_config: TOS 配置字典，处理本地文件时必须提供
            temp_dir: 存放 ffmpeg 临时音频文件的目录，默认使用项目根目录下的 temp_dir/

        Returns:
            Tuple[List[str], List[str]]:
                - urls: 最终可用的 URL 列表（与输入顺序一一对应，展开文件夹）
                - temp_files: 本次生成的临时文件路径列表（调用方可选择清理）
        """
        from ...utils.upload_files import upload_file_tos
        from ...config.config import load_tos_config
        from ...utils.media_utils import extract_audio_from_video_with_ffmpeg

        if isinstance(file_paths_or_urls, str):
            file_paths_or_urls = [file_paths_or_urls]

        # 展开文件夹
        expanded: List[str] = []
        for item in file_paths_or_urls:
            if self._is_local_file(item) and os.path.isdir(item):
                found = self._collect_media_files(item)
                if not found:
                    logger.warning(f"文件夹中未找到支持的媒体文件: {item}")
                else:
                    logger.info(f"扫描文件夹 {item}，找到 {len(found)} 个媒体文件")
                expanded.extend(found)
            else:
                expanded.append(item)

        # 有本地文件时，确保 tos_config 就绪（优先用传入的，否则自动从 .env 读取）
        has_local = any(self._is_local_file(p) and not os.path.isdir(p) for p in expanded)
        if has_local and tos_config is None:
            tos_config = load_tos_config()

        urls: List[str] = []
        temp_files: List[str] = []

        for path in expanded:
            # URL 直接透传
            if not self._is_local_file(path):
                urls.append(path)
                continue

            # 本地文件：校验存在性
            if not os.path.exists(path):
                raise FileNotFoundError(f"本地文件不存在: {path}")

            suffix = Path(path).suffix.lower()

            if suffix in _VIDEO_EXTENSIONS:
                # 视频文件：抽取音频为临时 wav
                _temp_dir = temp_dir or ASR_TEMP_DIR
                os.makedirs(_temp_dir, exist_ok=True)
                stem = Path(path).stem
                # 使用 UUID 避免并发时的文件名冲突
                unique_id = uuid.uuid4().hex[:8]
                audio_path = os.path.join(_temp_dir, f"{stem}_asr_audio_{unique_id}.wav")
                logger.info(f"正在从视频抽取音频: {path} → {audio_path}")
                success = extract_audio_from_video_with_ffmpeg(path, audio_path)
                if not success:
                    raise RuntimeError(f"音频抽取失败: {path}")
                temp_files.append(audio_path)
                upload_path = audio_path
            elif suffix in _AUDIO_EXTENSIONS:
                # 音频文件：直接上传
                upload_path = path
            else:
                raise ValueError(f"不支持的文件格式: {path}（支持: {_VIDEO_EXTENSIONS | _AUDIO_EXTENSIONS}）")

            # 上传到 TOS
            logger.info(f"正在上传文件到 TOS: {upload_path}")
            url = upload_file_tos(upload_path, tos_config, folder="asr_audio")
            if url is None:
                raise RuntimeError(f"文件上传 TOS 失败: {upload_path}")
            logger.info(f"上传成功: {url}")
            urls.append(url)

        return urls, temp_files
    
    @abstractmethod
    def transcribe(self, 
                  file_urls: Union[str, List[str]], 
                  **kwargs) -> List[Dict[str, Any]]:
        """
        对音频文件进行语音识别
        
        Args:
            file_urls: 音频文件URL，可以是单个URL字符串或URL列表
            **kwargs: 其他参数，由子类定义具体参数（如 language、debug 等）
            
        Returns:
            识别结果列表，每个元素包含文件URL和识别结果
        """
        pass
    
    def extract_text(self, transcription_result: Dict[str, Any]) -> str:
        """
        从识别结果中提取纯文本
        
        统一的数据格式：transcription.result.text
        
        Args:
            transcription_result: transcribe方法返回的结果
            
        Returns:
            提取的文本字符串
        """
        if transcription_result.get('status') != 'success':
            return ""
        
        transcription = transcription_result.get('transcription', {})
        if isinstance(transcription, dict) and 'result' in transcription:
            result = transcription['result']
            if isinstance(result, dict):
                return result.get('text', '')
        
        return ""
