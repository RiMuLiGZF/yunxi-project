from __future__ import annotations

"""【DEPRECATED】中间件管道已迁移.

本模块已迁移至 :mod:`skill_cluster.core.middleware`，
请使用 ``from skill_cluster.core.middleware import ...`` 的新路径导入。

为保持向后兼容，本文件保留为存根，从新路径重新导出所有符号，
并在首次导入时发出 DeprecationWarning。
"""

import warnings

warnings.warn(
    "skill_cluster.middleware 已迁移至 skill_cluster.core.middleware，"
    "请更新 import 路径",
    DeprecationWarning,
    stacklevel=2,
)

from skill_cluster.core.middleware import (
    Middleware,
    MiddlewarePipeline,
    cache_middleware,
    event_middleware,
    idempotent_middleware,
    logging_middleware,
    metrics_middleware,
    resilient_middleware,
)

__all__ = [
    "MiddlewarePipeline",
    "Middleware",
    "cache_middleware",
    "event_middleware",
    "resilient_middleware",
    "metrics_middleware",
    "logging_middleware",
    "idempotent_middleware",
]
