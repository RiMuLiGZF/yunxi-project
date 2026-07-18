"""
存储后端（Storage Backends）
==========================

提供多种存储后端实现，统一通过 BaseRepository 接口访问。

支持的后端：
- SQLite: 关系型数据库，支持事务和复杂查询
- JSON: 文件存储，轻量级，适合小数据
- Memory: 内存存储，适合测试和缓存

使用方式：
    from shared.data_access.backends import create_backend, BackendType
    backend = create_backend(BackendType.SQLITE, db_path="data/test.db")
    repo = backend.create_repository(MyModel)
"""

from .factory import BackendType, create_backend, get_backend_factory
from .memory_backend import MemoryBackend, MemoryRepository, MemoryUnitOfWork
from .sqlite_backend import SQLiteBackend, SQLiteRepository, SQLiteUnitOfWork
from .json_backend import JSONBackend, JSONRepository, JSONUnitOfWork

__all__ = [
    # 工厂
    "BackendType",
    "create_backend",
    "get_backend_factory",
    # Memory
    "MemoryBackend",
    "MemoryRepository",
    "MemoryUnitOfWork",
    # SQLite
    "SQLiteBackend",
    "SQLiteRepository",
    "SQLiteUnitOfWork",
    # JSON
    "JSONBackend",
    "JSONRepository",
    "JSONUnitOfWork",
]
