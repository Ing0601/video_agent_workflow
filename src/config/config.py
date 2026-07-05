import os
from pathlib import Path
from typing import Dict, Any
from dotenv import load_dotenv

load_dotenv()

# 项目根目录（config.py 位于 src/config/，向上两级即为项目根）
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# ASR 音频临时目录（用于存放 ffmpeg 抽取的临时音频文件）
ASR_TEMP_DIR = str(PROJECT_ROOT / "temp_dir" / "asr_audio")

# VLM 帧临时目录（用于存放从视频中提取的帧）
VLM_TEMP_DIR = str(PROJECT_ROOT / "temp_dir" / "vlm_frames")

# 云函数环境
# ASR_TEMP_DIR = "/tmp/asr_audio"
# VLM_TEMP_DIR = "/tmp/vlm_frames"

def load_tos_config() -> Dict[str, Any]:
    """Loads TOS configuration.

    Returns:
        TOS configuration dictionary.

    Raises:
        ValueError: When required environment variables are missing.
    """
    tos_config = {
        "access_key": os.getenv("TOS_ACCESS_KEY"),
        "secret_key": os.getenv("TOS_SECRET_KEY"),
        "endpoint": os.getenv("TOS_ENDPOINT", "tos-cn-beijing.volces.com"),
        "region": os.getenv("TOS_REGION", "cn-beijing"),
        "bucket_name": os.getenv("TOS_BUCKET_NAME"),
    }

    # Validate required configuration
    required_keys = ["access_key", "secret_key", "bucket_name"]
    missing_keys = [key for key in required_keys if not tos_config.get(key)]

    if missing_keys:
        env_vars = {
            "access_key": "TOS_ACCESS_KEY",
            "secret_key": "TOS_SECRET_KEY",
            "bucket_name": "TOS_BUCKET_NAME",
        }
        missing_vars = [env_vars[key] for key in missing_keys]
        raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

    return tos_config