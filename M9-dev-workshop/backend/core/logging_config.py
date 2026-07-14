"""云汐 M9 开发者工坊 - 统一日志配置

提供结构化日志支持，支持分级输出、文件滚动、请求ID追踪。
"""

import logging
import sys
from pathlib import Path
from typing import Optional
import os

# 日志格式
LOG_FORMAT = "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

def setup_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    log_dir: Optional[str] = None,
) -> None:
    """初始化日志系统

    Args:
        level: 日志级别 (DEBUG/INFO/WARNING/ERROR/CRITICAL)
        log_file: 日志文件名（可选）
        log_dir: 日志目录（可选）
    """
    root_logger = logging.getLogger("m9")
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # 避免重复添加 handler
    if root_logger.handlers:
        return

    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

    # 控制台 handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # 文件 handler（按天滚动）
    if log_dir and log_file:
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        file_path = log_path / log_file

        from logging.handlers import TimedRotatingFileHandler
        file_handler = TimedRotatingFileHandler(
            str(file_path),
            when="midnight",
            interval=1,
            backupCount=30,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

def get_logger(name: str) -> logging.Logger:
    """获取命名 logger

    Args:
        name: logger 名称（通常使用模块名）
    """
    # 统一前缀为 m9
    full_name = f"m9.{name}" if not name.startswith("m9.") else name
    logger = logging.getLogger(full_name)
    return logger
