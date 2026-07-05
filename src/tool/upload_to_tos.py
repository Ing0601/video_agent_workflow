from .base import BaseTool
from ..config.config import load_tos_config
from ..logger import logger
from typing import Dict, Any, Optional
import os
import tos
import time
from ..tool.types import ToolExeResult

class UploadToTOS(BaseTool):
    def __init__(self):
        super().__init__()
        self.name = "UploadToTOS"
        self.description = "Upload a local media file (video/audio/image) to TOS/object storage and return a stable URI plus basic metadata for downstream processing (e.g., VLM analysis, transcoding, caching)."
        self.parameters = {
            "type": "object",
            "properties": {
                "local_path": {"type": "string", "description": "The local path to the file to upload (e.g., /mnt/data/input.mp4)."},
            },
            "required": ["local_path"],
        }
    
    async def execute(
        self, 
        local_path: str,
        introduction: Optional[str] = None,
        folder: str = "files",
        max_retries: int = 3,
        **kwargs
    ) -> ToolExeResult:

        validation = self.validate_params(
            local_path=local_path,
            introduction=introduction,
        )
        if not validation["success"]:
            return ToolExeResult(
                success=False,
                error=validation["error"],
            )

        tos_config = load_tos_config()
        ak = tos_config["access_key"]
        sk = tos_config["secret_key"]
        endpoint = tos_config["endpoint"]
        region = tos_config["region"]
        bucket_name = tos_config["bucket_name"]

        if not ak or not sk or not bucket_name:
            logger.error("Missing required TOS configuration")
            return ToolExeResult(
                success=False,
                error="Missing required TOS configuration",
            )
        
        object_key = f"{folder}/{os.path.basename(local_path)}"

        # 重试循环
        for attempt in range(max_retries):
            client = None
            try:
                # 创建客户端（每次重试都创建新的）
                client = tos.TosClientV2(ak, sk, endpoint, region)

                with open(local_path, "rb") as f:
                    client.put_object(bucket_name, object_key, content=f.read())

                file_url = f"https://{bucket_name}.{endpoint}/{object_key}"
                logger.info(f"✓ 文件上传成功: {file_url}")
                return ToolExeResult(
                    success=True,
                    result={"file_url": file_url},
                )

            except tos.exceptions.TosClientError as e:
                error_msg = f"TOS客户端错误: {e.message}"
                if "SSL" in str(e.cause) or "timeout" in str(e.message).lower():
                    # SSL 或超时错误，值得重试
                    if attempt < max_retries - 1:
                        wait_time = (attempt + 1) * 2  # 递增等待时间：2秒、4秒、6秒
                        logger.error(f"⚠ {error_msg}，{wait_time}秒后重试 ({attempt + 1}/{max_retries})...")
                        time.sleep(wait_time)
                        continue
                    else:
                        logger.error(f"✗ {error_msg}，已达最大重试次数")
                else:
                    logger.error(f"✗ {error_msg}, 原因: {e.cause}")
                    break
                    
            except tos.exceptions.TosServerError as e:
                logger.error(f"✗ TOS服务端错误, 错误码: {e.code}; 请求ID: {e.request_id}; 错误信息: {e.message}")
                break
                
            except FileNotFoundError:
                logger.error(f"✗ 文件不存在: {local_path}")
                break
                
            except Exception as e:
                error_msg = f"文件上传失败: {e}"
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 2
                    logger.error(f"⚠ {error_msg}，{wait_time}秒后重试 ({attempt + 1}/{max_retries})...")
                    time.sleep(wait_time)
                    continue
                else:
                    logger.error(f"✗ {error_msg}，已达最大重试次数")
                    
            finally:
                # 清理客户端连接
                if client:
                    try:
                        client.close()
                    except:
                        pass
        
        return ToolExeResult(
            success=False,
            error="File upload failed after max retries",
        )