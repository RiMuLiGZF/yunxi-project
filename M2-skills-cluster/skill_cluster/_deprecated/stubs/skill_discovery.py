from __future__ import annotations
"""[DEPRECATED] 已迁移至 skill_cluster.discovery.engine.

本文件为向后兼容存根，将从新路径导入并发出废弃警告。
请更新为: from skill_cluster.discovery.engine import ...
"""

import warnings

warnings.warn(
    "skill_cluster.skill_discovery 已废弃，请使用 skill_cluster.discovery.engine",
    DeprecationWarning,
    stacklevel=2,
)

from skill_cluster.discovery.engine import (  # noqa: F401
    CATEGORY_META,
    SCENE_CATEGORY_WEIGHTS,
    SceneType,
    SkillCategory,
    SkillCategoryInfo,
    SkillDiscoveryEngine,
    SkillDiscoveryItem,
    SkillDiscoveryResult,
    TimeContext,
    UserProfile,
)
