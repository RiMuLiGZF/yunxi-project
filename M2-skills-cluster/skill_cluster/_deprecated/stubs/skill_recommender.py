from __future__ import annotations
"""[DEPRECATED] 已迁移至 skill_cluster.discovery.recommender.

本文件为向后兼容存根，将从新路径导入并发出废弃警告。
请更新为: from skill_cluster.discovery.recommender import ...
"""

import warnings

warnings.warn(
    "skill_cluster.skill_recommender 已废弃，请使用 skill_cluster.discovery.recommender",
    DeprecationWarning,
    stacklevel=2,
)

from skill_cluster.discovery.recommender import (  # noqa: F401
    SkillRecommendation,
    SkillRecommender,
)
