"""Log config"""

import os
import json
import sys
import logging
import traceback
from loguru import logger
from pathlib import Path


class LogConfig:
    @staticmethod
    def resolve_log_path():
        """解析日志文件路径，优先使用环境变量 VIDEO_AGENT_LOG_DIR。"""
        env_log_dir = os.getenv("VIDEO_AGENT_LOG_DIR", "").strip()
        if env_log_dir:
            log_dir = Path(env_log_dir)
        else:
            log_dir = Path("logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        return str(log_dir / "app.log")

    @staticmethod
    def init_logger(project_root: str = None):
        """初始化JSON格式日志配置

        Args:
            project_root: 项目根目录路径（用于生成相对路径）
        """
        # 获取项目根目录（如果未指定则自动推断）
        if not project_root:
            project_root = str(Path(__file__).parent.parent.parent)

        def formatter(record):
            """自定义JSON格式化函数"""

            # 时间格式化（保留毫秒）
            timestamp = record["time"].strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

            # 获取相对路径
            abs_path = record["file"].path
            try:
                rel_path = os.path.relpath(abs_path, start=project_root)
            except ValueError:
                rel_path = abs_path

            # 构建调用位置信息
            caller = f"{rel_path}:{record['line']}"

            # 异常堆栈处理
            stacktrace = ""
            exception = record.get("exception")
            if exception:
                stacktrace = "".join(
                    traceback.format_exception(
                        exception.value,  # 获取实际的异常对象
                        limit=None,
                        chain=True,
                    )
                )
            # 构建完整日志结构
            log_data = {
                "level": record["level"].name,
                "time": timestamp,
                "caller": caller,
                "msg": record["message"],
                "stacktrace": stacktrace,
                # "tid": record["extra"].get("tid", ""),
                "event": record["extra"].get("event", ""),
                # "biz_monitor_ctx": record["extra"].get("biz_monitor_ctx", {}),
            }
            record["extra"]["_json_"] = json.dumps(log_data, ensure_ascii=False)
            record["extra"]["caller"] = caller
        
        console_format = (
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level:<5}</level> | "
            "<cyan>{extra[caller]}</cyan> | "
            "<level>{message}</level>\n"
            "{exception}"
        )

        # 清除默认配置并添加新配置
        logger.remove()
        
        log_path = LogConfig.resolve_log_path()

        logger.add(
            sink=log_path,
            format=lambda _: "{extra[_json_]}\n",
            rotation="500 MB",
            retention="7 days",
            compression="zip",
            level="INFO",
            enqueue=True,  # 线程安全
            backtrace=True,  # 记录异常堆栈
            diagnose=True,  # 显示变量值
        )

        logger.configure(patcher=formatter)

        logger.add(
            sys.stdout,
            format=console_format,
            level="INFO",
            colorize=True,
            backtrace=True,
            diagnose=True,
        )


try:
    # 初始化日志
    LogConfig.init_logger()
    logger.info("Logger init...")

except Exception as e:
    logger.error(f"Failed init logger: {str(e)}")
