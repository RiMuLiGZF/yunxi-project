from __future__ import annotations

"""【DEPRECATED】技能注册中心已迁移.

本模块已迁移至 :mod:`skill_cluster.core.registry`，
请使用 ``from skill_cluster.core.registry import ...`` 的新路径导入。

为保持向后兼容，本文件保留为存根，从新路径重新导出所有符号，
并在首次导入时发出 DeprecationWarning。
"""

import warnings

warnings.warn(
    "skill_cluster.skill_registry 已迁移至 skill_cluster.core.registry，"
    "请更新 import 路径",
    DeprecationWarning,
    stacklevel=2,
)

from skill_cluster.core.registry import (
    DependencyNotFoundError,
    SkillAlreadyExistsError,
    SkillDependencyOccupiedError,
    SkillRegistry,
    SkillRegistryError,
)

__all__ = [
    "SkillRegistry",
    "SkillRegistryError",
    "SkillAlreadyExistsError",
    "DependencyNotFoundError",
    "SkillDependencyOccupiedError",
]
