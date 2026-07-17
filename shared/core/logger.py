"""
云汐系统日志工具
统一日志管理，支持多级别输出

.. note::
   本模块为向后兼容层，已迁移至 ``shared.core.observability``。
   新代码请直接使用 ``from shared.core.observability import get_logger``。

   旧的 ``get_logger`` 函数仍然可用，内部会转发到新的统一日志系统。
"""

import logging
from typing import Optional

# 优先使用 observability 新实现，回退到原始简单实现
try:
    from .observability import get_logger as _new_get_logger
    _NEW_LOGGER = True
except ImportError:
    _NEW_LOGGER = False


_loggers = {}


def get_logger(name: str = "yunxi", level: str = "INFO") -> logging.Logger:
    """获取日志记录器（单例模式，向后兼容）

    优先使用统一日志系统（UnifiedLogger），返回底层 logging.Logger 实例，
    确保与旧代码完全兼容。

    Args:
        name: 日志记录器名称
        level: 日志级别

    Returns:
        logging.Logger 实例
    """
    if _NEW_LOGGER:
        # 使用新的统一日志系统，返回底层 logging.Logger 实例
        unified_logger = _new_get_logger(name, level=level)
        return unified_logger.get_logger()

    # 回退到原始简单实现
    if name in _loggers:
        return _loggers[name]

    import sys
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
