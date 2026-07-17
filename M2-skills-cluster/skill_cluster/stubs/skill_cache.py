from __future__ import annotations

"""【DEPRECATED】技能缓存已迁移.

本模块已迁移至 :mod:`skill_cluster.core.cache`，
请使用 ``from skill_cluster.core.cache import SkillCache`` 的新路径导入。

为保持向后兼容，本文件保留为存根，从新路径重新导出所有符号，
并在首次导入时发出 DeprecationWarning。
"""

import warnings

warnings.warn(
    "skill_cluster.skill_cache 已迁移至 skill_cluster.core.cache，"
    "请更新 import 路径",
    DeprecationWarning,
    stacklevel=2,
)

from skill_cluster.core.cache import (
    L1MemoryCache,
    L2DiskCache,
    SQLiteL2Cache,
    SkillCache,
)

__all__ = [
    "SkillCache",
    "L1MemoryCache",
    "L2DiskCache",
    "SQLiteL2Cache",
]
