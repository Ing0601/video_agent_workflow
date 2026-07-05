import uvicorn
from loguru import logger
import sys
import signal
import asyncio
import uvloop
from pathlib import Path

# 插入项目根路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.api.app import create_app
from src.logger.logging import LogConfig


# 使用 uvloop 作为事件循环
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

LogConfig.init_logger()

def signal_handler(signum, frame):
    """信号处理器"""
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    sys.exit(0)

def main():
    """主函数: 启动FastAPI服务器"""
    
    # 注册信号处理器
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    port = 8000
    logger.info("Starting FastAPI server on address: http://0.0.0.0:{}".format(port))
    try:
        app = create_app()

        # 启动服务器
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=port,
            limit_concurrency=300,
            log_level="error",
        )
    except KeyboardInterrupt:
        logger.info("Shutting down FastAPI server...")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error starting FastAPI server: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
