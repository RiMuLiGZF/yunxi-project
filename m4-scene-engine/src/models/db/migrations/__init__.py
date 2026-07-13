"""数据库迁移注册模块.

集中管理所有迁移定义，按版本号顺序排列。
"""

from __future__ import annotations

from .v1_initial import migration_v1

# 所有迁移列表，按版本号升序排列
MIGRATIONS = [
    migration_v1,
]

__all__ = [
    "MIGRATIONS",
    "migration_v1",
]
