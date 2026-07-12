"""
云汐系统 - 统一日志模块
结构化 JSON 日志，统一格式
"""

import sys
import logging
from typing import Optional


def get_logger(name: str = "yunxi", level: Optional[str] = None) -> logging.Logger:
    """
    获取统一格式的 logger

    Args:
        name: logger 名称
        level: 日志级别，默认从环境变量读取

    Returns:
        配置好的 logger
    """
    logger = logging.getLogger(name)

    # 避免重复添加 handler
    if logger.handlers:
        return logger

    # 确定日志级别
    if level is None:
        try:
            from .config import get_config
            level = get_config().log_level
        except Exception:
            level = "info"

    level_map = {
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warning": logging.WARNING,
        "error": logging.ERROR,
        "critical": logging.CRITICAL,
    }
    log_level = level_map.get(level.lower(), logging.INFO)
    logger.setLevel(log_level)

    # 控制台输出 handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)

    # 格式化器
    formatter = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    logger.propagate = False

    return logger
