import base64
import os
import uuid
import shutil
from typing import Optional, Union, List

import dashscope
from ...config.config import VLM_TEMP_DIR
from ...logger import logger
from ...utils.media_utils import extract_frames, is_video_file


class QwenVLM:
    """Qwen VLM model caller class using the official dashscope SDK."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "qwen3-vl-plus",
        base_http_api_url: Optional[str] = None,
    ):
        """Initializes the Qwen VLM model client.

        Args:
            api_key: API key, defaults to DASHSCOPE_API_KEY environment variable.
            model: Name of the model to use.
            base_http_api_url: API base URL for switching regions (e.g., Singapore region).
        """
        self.api_key = api_key or os.getenv("DASHSCOPE_API_KEY")
        self.model = model

        if not self.api_key:
            raise ValueError("API key not set. Please set DASHSCOPE_API_KEY")

        if base_http_api_url:
            dashscope.base_http_api_url = base_http_api_url

    @staticmethod
    def _encode_file_to_base64(file_path: str) -> str:
        """将本地文件转换为 Base64 编码的字符串。
        
        Args:
            file_path: 本地文件路径。
            
        Returns:
            Base64 编码的字符串。
        """
        with open(file_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    
    @staticmethod
    def _get_image_format(file_path: str) -> str:
        """根据文件扩展名获取图片格式。
        
        Args:
            file_path: 文件路径。
            
        Returns:
            图片格式（png/jpeg/jpg/webp等）。
        """
        ext = os.path.splitext(file_path)[1].lower()
        format_map = {
            ".png": "png",
            ".jpg": "jpeg",
            ".jpeg": "jpeg",
            ".webp": "webp",
            ".gif": "gif",
            ".bmp": "bmp",
        }
        return format_map.get(ext, "jpeg")
    
    def _prepare_media_content(
        self, 
        media_input: Union[str, List[str]], 
        media_type: str,
        fps: float = 2.0,
        temp_dir: Optional[str] = None
    ) -> tuple[dict, List[str]]:
        """准备媒体内容，支持URL和本地文件路径两种形式。
        
        Args:
            media_input: 媒体输入，可以是：
                - URL字符串（以 http:// 或 https:// 开头）
                - 本地文件路径（自动转换为Base64）
                - 对于视频：本地视频文件路径（自动抽帧）或图片路径列表（多帧）
            media_type: 媒体类型 "video" 或 "image"
            fps: 视频帧采样率
            temp_dir: 临时目录路径，用于存储抽取的帧，默认使用项目根目录下的 temp_dir/vlm_frames/
            
        Returns:
            tuple[dict, List[str]]: 
                - 构建好的媒体内容字典
                - 临时文件路径列表（调用方可选择清理）
        """
        temp_files: List[str] = []
        
        if media_type == "image":
            # 图片处理
            if media_input.startswith(("http://", "https://")):
                # URL形式
                return {"image": media_input}, temp_files
            else:
                # 本地文件路径，转换为Base64
                if not os.path.exists(media_input):
                    raise FileNotFoundError(f"Image file not found: {media_input}")
                base64_data = self._encode_file_to_base64(media_input)
                img_format = self._get_image_format(media_input)
                return {"image": f"data:image/{img_format};base64,{base64_data}"}, temp_files
        
        elif media_type == "video":
            # 视频处理
            if isinstance(media_input, list):
                # 多帧图片列表（本地路径转Base64视频形式）
                video_frames = []
                for frame_path in media_input:
                    if not os.path.exists(frame_path):
                        raise FileNotFoundError(f"Video frame not found: {frame_path}")
                    # 本地文件，转换为Base64
                    base64_data = self._encode_file_to_base64(frame_path)
                    img_format = self._get_image_format(frame_path)
                    video_frames.append(f"data:image/{img_format};base64,{base64_data}")
                return {"video": video_frames}, temp_files
            
            elif media_input.startswith(("http://", "https://")):
                # URL形式（支持fps）
                return {"video": media_input, "fps": fps}, temp_files
            else:
                # 单个本地视频文件路径，自动抽帧
                if not os.path.exists(media_input):
                    raise FileNotFoundError(f"Video file not found: {media_input}")
                
                if not is_video_file(media_input):
                    raise ValueError(f"Not a supported video file: {media_input}")
                
                # 为每个任务创建唯一的子目录，避免并发冲突
                _temp_dir = temp_dir or VLM_TEMP_DIR
                task_id = uuid.uuid4().hex[:8]
                task_dir = os.path.join(_temp_dir, task_id)
                os.makedirs(task_dir, exist_ok=True)
                
                logger.info(f"从视频中抽帧: {media_input}, fps={fps}, 任务目录: {task_dir}")
                frame_paths = extract_frames(
                    video_path=media_input,
                    output_dir=task_dir,
                    fps=fps
                )
                
                if not frame_paths:
                    raise RuntimeError(f"Failed to extract frames from video: {media_input}")
                
                logger.info(f"成功抽取 {len(frame_paths)} 帧")
                
                # 记录任务目录（用于后续清理整个目录）
                temp_files.append(task_dir)
                
                # 将抽取的帧转换为Base64格式
                video_frames = []
                for frame_path in frame_paths:
                    base64_data = self._encode_file_to_base64(frame_path)
                    img_format = self._get_image_format(frame_path)
                    video_frames.append(f"data:image/{img_format};base64,{base64_data}")
                
                return {"video": video_frames}, temp_files
        
        return {}, temp_files

    def call_model(
        self, 
        media_input: Union[str, List[str]], 
        prompt: str, 
        media_type: str = "video", 
        fps: float = 2.0,
        temp_dir: Optional[str] = None,
        cleanup_temp: bool = True
    ) -> dict:
        """Calls Qwen VLM model to analyze video or image.

        Args:
            media_input: 媒体输入，支持多种形式：
                1. URL字符串（以 http:// 或 https:// 开头）
                2. 本地图片文件路径（自动转换为Base64）
                3. 本地视频文件路径（自动抽帧并转换为Base64）
                4. 图片路径列表（多帧视频，自动转Base64）
            prompt: Analysis prompt.
            media_type: Media type, either "video" or "image", defaults to "video".
            fps: Video frame sampling rate（视频帧采样率）
            temp_dir: 临时目录路径，用于存储抽取的帧，默认使用项目根目录下的 temp_dir/vlm_frames/
            cleanup_temp: 识别完成后是否自动删除抽取的临时帧文件，默认 True

        Returns:
            dict: {"content": str, "usage": dict}，包含模型输出和用量信息。

        Raises:
            ValueError: If unsupported media type is provided.
            FileNotFoundError: If local file path does not exist.
            Exception: If model call fails.
        """
        if media_type not in ["video", "image"]:
            raise ValueError(
                f"Unsupported media type: {media_type}, only 'video' or 'image' are supported"
            )

        temp_files: List[str] = []
        
        try:
            logger.debug(f"Calling Qwen VLM model: {self.model}")
            logger.debug(f"{media_type.upper()} input type: {type(media_input)}")

            # 准备媒体内容
            media_content, temp_files = self._prepare_media_content(media_input, media_type, fps, temp_dir)
            
            # 构建消息
            content = [media_content, {"text": prompt}]
            messages = [{"role": "user", "content": content}]

            response = dashscope.MultiModalConversation.call(
                api_key=self.api_key,
                model=self.model,
                messages=messages,
                response_format={"type": "json_object"},
            )

            if response.status_code == 200:
                result_text = response.output.choices[0].message.content[0]["text"]
                logger.debug(f"Raw model response length: {len(result_text)}")
                usage = {
                    "model": self.model,
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                    "total_tokens": response.usage.total_tokens,
                }
                # 清理临时文件/目录
                if cleanup_temp and temp_files:
                    for tmp in temp_files:
                        try:
                            if os.path.isdir(tmp):
                                shutil.rmtree(tmp)
                                logger.debug(f"已删除临时目录: {tmp}")
                            else:
                                os.remove(tmp)
                                logger.debug(f"已删除临时文件: {tmp}")
                        except Exception as e:
                            logger.warning(f"删除临时文件/目录失败: {tmp}，原因: {e}")
                return {"content": result_text, "usage": usage}
            else:
                error_msg = (
                    f"Model call failed, status code: {response.status_code}, "
                    f"error message: {response.message}"
                )
                logger.error(error_msg)
                raise Exception(error_msg)

        except Exception as e:
            # 即使出错也尝试清理临时文件/目录
            if cleanup_temp and temp_files:
                for tmp in temp_files:
                    try:
                        if os.path.isdir(tmp):
                            shutil.rmtree(tmp)
                            logger.debug(f"已删除临时目录: {tmp}")
                        else:
                            os.remove(tmp)
                            logger.debug(f"已删除临时文件: {tmp}")
                    except Exception as cleanup_error:
                        logger.warning(f"删除临时文件/目录失败: {tmp}，原因: {cleanup_error}")
            
            logger.error(f"Qwen VLM model call failed: {e}")
            raise
