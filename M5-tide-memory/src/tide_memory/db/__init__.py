"""
数据库迁移模块

提供版本化的数据库迁移管理，支持 L1/L2/L3 + growth 等多个独立数据库。

使用方式::

    from tide_memory.db import DatabaseMigrator, get_migrator

    # 获取 L1 数据库的迁移器
    migrator = get_migrator("l1", "./data/memory/l1_shallow.db")
    migrator.migrate()

    # 检查迁移状态
    status = migrator.validate()
"""

from __future__ import annotations

import threading
from typing import Dict, Optional

from .migration import DatabaseMigrator, Migration

# 全局 migrator 缓存（按 db_path 索引）
_migrators: Dict[str, DatabaseMigrator] = {}
_migrators_lock = threading.Lock()


def get_migrator(
    db_name: str,
    db_path: str,
    migrations: Optional[list] = None,
) -> DatabaseMigrator:
    """
    获取指定数据库的迁移器实例（按 db_path 缓存）

    为不同的数据库文件创建独立的 migrator 实例，同一 db_path 返回同一实例。

    Args:
        db_name: 数据库名称标识（用于日志，如 "l1", "l2", "l3", "growth"）
        db_path: 数据库文件路径
        migrations: 预注册的迁移列表（仅首次创建时生效）

    Returns:
        DatabaseMigrator 实例
    """
    # 使用规范化后的路径作为 key
    import os
    key = os.path.abspath(db_path)

    with _migrators_lock:
        if key not in _migrators:
            _migrators[key] = DatabaseMigrator(db_path, migrations)
        elif migrations:
            # 如果已有实例但调用方传入了迁移列表，补充注册
            for m in migrations:
                if m.version not in _migrators[key]._migrations:
                    _migrators[key].register_migration(m)
        return _migrators[key]


def clear_migrators() -> None:
    """
    清空全局 migrator 缓存（主要用于测试）
    """
    with _migrators_lock:
        _migrators.clear()


__all__ = [
    "DatabaseMigrator",
    "Migration",
    "get_migrator",
    "clear_migrators",
]
