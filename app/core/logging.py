"""统一日志 - loguru 简化配置"""

import sys

from loguru import logger

from app.config import settings


def setup_logging() -> None:
    logger.remove()
    logger.add(
        sys.stderr,
        level="DEBUG" if settings.debug else "INFO",
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        ),
        enqueue=False,
    )
    # 写文件
    logger.add(
        "./logs/freight_{time:YYYY-MM-DD}.log",
        rotation="00:00",
        retention="30 days",
        compression="zip",
        level="INFO",
        enqueue=True,
    )


__all__ = ["logger", "setup_logging"]
