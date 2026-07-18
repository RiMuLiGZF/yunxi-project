"""
后端工厂（Backend Factory）
=========================

统一的后端创建入口，支持根据配置创建不同类型的存储后端。

使用方式：
    from shared.data_access.backends import create_backend, BackendType

    # 创建内存后端
    backend = create_backend(BackendType.MEMORY)

    # 创建 SQLite 后端
    backend = create_backend(BackendType.SQLITE, db_path="data/app.db")

    # 创建 JSON 后端
    backend = create_backend(BackendType.JSON, data_dir="data/json")
"""

from __future__ import annotations

import os
from enum import Enum
from typing import Any, Dict, Optional

from ..base import BackendFactory


class BackendType(str, Enum):
    """后端类型枚举"""
    MEMORY = "memory"
    SQLITE = "sqlite"
    JSON = "json"


def create_backend(backend_type: BackendType, **kwargs: Any) -> BackendFactory:
    """
    创建存储后端。

    Args:
        backend_type: 后端类型
        **kwargs: 后端特定参数

    Returns:
        后端实例

    Raises:
        ValueError: 不支持的后端类型
    """
    if backend_type == BackendType.MEMORY:
        from .memory_backend import MemoryBackend
        return MemoryBackend()

    elif backend_type == BackendType.SQLITE:
        from .sqlite_backend import SQLiteBackend
        db_path = kwargs.get("db_path", ":memory:")
        return SQLiteBackend(db_path=db_path)

    elif backend_type == BackendType.JSON:
        from .json_backend import JSONBackend
        data_dir = kwargs.get("data_dir", "./data/json")
        return JSONBackend(data_dir=data_dir)

    else:
        raise ValueError(f"Unsupported backend type: {backend_type}")


# 全局单例缓存
_backend_instances: Dict[str, BackendFactory] = {}


def get_backend_factory(
    backend_type: Optional[BackendType] = None,
    **kwargs: Any,
) -> BackendFactory:
    """
    获取后端工厂单例。

    从环境变量 YUNXI_DATA_BACKEND 读取默认后端类型：
      - memory: 内存后端
      - sqlite: SQLite 后端（默认）
      - json: JSON 文件后端

    Args:
        backend_type: 后端类型，None 表示从环境变量读取
        **kwargs: 后端参数

    Returns:
        后端实例
    """
    if backend_type is None:
        env_backend = os.getenv("YUNXI_DATA_BACKEND", "sqlite").lower()
        try:
            backend_type = BackendType(env_backend)
        except ValueError:
            backend_type = BackendType.SQLITE

    # 构建缓存 key
    key_parts = [backend_type.value]
    for k, v in sorted(kwargs.items()):
        key_parts.append(f"{k}={v}")
    cache_key = "|".join(key_parts)

    if cache_key not in _backend_instances:
        _backend_instances[cache_key] = create_backend(backend_type, **kwargs)

    return _backend_instances[cache_key]


def reset_backend_factory() -> None:
    """重置后端工厂缓存（测试用）"""
    _backend_instances.clear()
