import logging
import os
from typing import Dict, Any

import tos
import requests
from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep_log, retry_if_exception

from ..logger.logging import logger


def _is_retryable_client_error(e: Exception) -> bool:
    """TosClientError 中只有网络类错误值得重试"""
    if not isinstance(e, tos.exceptions.TosClientError):
        return False
    cause = str(getattr(e, 'cause', ''))
    msg = str(getattr(e, 'message', '')).lower()
    return "SSL" in cause or "timeout" in msg or "connection" in msg or "network" in msg


def _is_retryable_server_error(e: Exception) -> bool:
    """TosServerError 中只有 5xx 值得重试"""
    if not isinstance(e, tos.exceptions.TosServerError):
        return False
    return bool(e.code and str(e.code).startswith('5'))


def _is_retryable(e: Exception) -> bool:
    if isinstance(e, FileNotFoundError):
        return False  # 文件不存在，重试无意义
    if isinstance(e, tos.exceptions.TosClientError):
        return _is_retryable_client_error(e)
    if isinstance(e, tos.exceptions.TosServerError):
        return _is_retryable_server_error(e)
    return True  # 其他未知异常，允许重试


def upload_file_tos(file_path: str, tos_config: Dict[str, Any], folder: str = "files", max_retries: int = 5,
                    multipart_threshold: int = 50 * 1024 * 1024, part_size: int = 20 * 1024 * 1024):
    """
    上传文件到字节跳动云存储（支持分片上传和断点续传）

    Args:
        file_path: 文件路径
        tos_config: TOS配置字典，包含 access_key, secret_key, endpoint, region, bucket_name
        folder: 存储文件夹名称，默认为 "files"
        max_retries: 最大重试次数，默认5次
        multipart_threshold: 启用分片上传的文件大小阈值，默认50MB
        part_size: 分片大小，默认20MB（TOS官方推荐值）

    Returns:
        str: 上传成功后的文件URL，失败则返回None
    """
    ak = tos_config.get("access_key")
    sk = tos_config.get("secret_key")
    endpoint = tos_config.get("endpoint", "tos-cn-beijing.volces.com")
    region = tos_config.get("region", "cn-beijing")
    bucket_name = tos_config.get("bucket_name")

    if not ak or not sk or not bucket_name:
        print("TOS配置缺失: 需要access_key, secret_key, bucket_name")
        return None

    if not os.path.exists(file_path):
        print(f"文件不存在: {file_path}")
        return None

    object_key = f"{folder}/{os.path.basename(file_path)}"
    file_size = os.path.getsize(file_path)
    use_multipart = file_size >= multipart_threshold

    print(f"文件大小: {file_size / (1024*1024):.1f}MB, 使用{'分片' if use_multipart else '单次'}上传")

    @retry(
        stop=stop_after_attempt(max_retries),
        wait=wait_exponential(multiplier=2, min=2, max=30),  # 2s → 4s → 8s … 上限30s
        retry=retry_if_exception(_is_retryable),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def _do_upload():
        client = tos.TosClientV2(ak, sk, endpoint, region)
        try:
            if use_multipart:
                print(f"开始分片上传: {os.path.basename(file_path)}")
                client.upload_file(
                    bucket_name,
                    object_key,
                    file_path,
                    task_num=3,
                    part_size=part_size,
                    enable_checkpoint=True,
                )
            else:
                print(f"开始单次上传: {os.path.basename(file_path)}")
                with open(file_path, "rb") as f:
                    client.put_object(bucket_name, object_key, content=f.read())
        finally:
            try:
                client.close()
            except Exception:
                pass

    try:
        _do_upload()
        file_url = f"https://{bucket_name}.{endpoint}/{object_key}"
        print(f"文件上传成功: {file_url}")
        return file_url
    except tos.exceptions.TosClientError as e:
        print(f"TOS客户端错误: {e.message}, 原因: {e.cause}")
    except tos.exceptions.TosServerError as e:
        print(f"TOS服务端错误, 错误码: {e.code}, 请求ID: {e.request_id}, 信息: {e.message}")
    except FileNotFoundError:
        print(f"文件不存在: {file_path}")
    except Exception as e:
        print(f"文件上传失败: {e}")

    return None

def get_tos_public_url(local_path: str, tos_config: Dict[str, Any], mount_path: str = "/mnt/tos", 
                       tos_folder: str = "assets") -> str:
    """根据本地挂载路径生成 TOS 公开读 URL。
    
    适用于火山函数服务挂载 TOS 的场景，本地文件自动同步到 TOS，直接拼接公网 URL。
    
    Args:
        local_path: 本地文件路径，例如 "/mnt/tos/task123.jpg"
        tos_config: TOS配置字典，包含 endpoint, bucket_name
        mount_path: TOS 挂载的本地路径，默认 "/mnt/tos"
        tos_folder: TOS 中映射的文件夹路径，默认 "assets"
    
    Returns:
        str: TOS 公开读 URL，例如 "https://bucket.tos-cn-beijing.volces.com/assets/task123.jpg"
    
    Example:
        >>> config = {"endpoint": "tos-cn-beijing.volces.com", "bucket_name": "my-bucket"}
        >>> url = get_tos_public_url("/mnt/tos/task123.jpg", config)
        >>> print(url)
        https://my-bucket.tos-cn-beijing.volces.com/assets/task123.jpg
    """
    endpoint = tos_config.get("endpoint", "tos-cn-beijing.volces.com")
    bucket_name = tos_config.get("bucket_name")
    
    if not bucket_name:
        logger.error("TOS配置缺少 bucket_name")
        return ""
    
    filename = os.path.basename(local_path)
    
    object_key = f"{tos_folder}/{filename}"
    
    public_url = f"https://{bucket_name}.{endpoint}/{object_key}"
    
    logger.info(f"生成 TOS 公开读 URL: {public_url}")
    return public_url

def download_image(url: str, dest_path: str, timeout: int = 30) -> bool:
    """从URL下载图片到本地。

    Args:
        url: 图片URL
        dest_path: 保存路径
        timeout: 请求超时时间（秒），默认30

    Returns:
        bool: 下载成功返回 True，否则返回 False
    """
    try:
        os.makedirs(os.path.dirname(os.path.abspath(dest_path)), exist_ok=True)
        
        logger.info(f"开始下载图片: {url}")
        response = requests.get(url, stream=True, timeout=timeout)
        response.raise_for_status()
        
        with open(dest_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        
        if not os.path.exists(dest_path) or os.path.getsize(dest_path) == 0:
            logger.error(f"图片下载失败：文件为空或不存在: {dest_path}")
            return False
        
        logger.info(f"图片下载成功: {dest_path}")
        return True
        
    except requests.RequestException as e:
        logger.error(f"下载图片失败: {url}，错误: {e}")
        return False
    except Exception as e:
        logger.error(f"下载图片异常: {url}，原因: {e}")
        return False