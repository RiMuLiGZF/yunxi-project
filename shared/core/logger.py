"""
云汐系统日志工具
统一日志管理，支持多级别输出
"""

import logging
import sys
from typing import Optional


_loggers = {}


def get_logger(name: str = "yunxi", level: str = "INFO") -> logging.Logger:
    """获取日志记录器（单例模式）

    Args:
        name: 日志记录器名称
        level: 日志级别

    Returns:
        logging.Logger 实例
    """
    if name in _loggers:
        return _loggers[name]

    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # 避免重复添加 handler
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    _loggers[name] = logger
    return logger
