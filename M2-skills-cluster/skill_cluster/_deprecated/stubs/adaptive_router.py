from __future__ import annotations
"""[DEPRECATED] 已迁移至 skill_cluster.discovery.routers.adaptive.

本文件为向后兼容存根，将从新路径导入并发出废弃警告。
请更新为: from skill_cluster.discovery.routers.adaptive import ...
"""

import warnings

warnings.warn(
    "skill_cluster.adaptive_router 已废弃，请使用 skill_cluster.discovery.routers.adaptive",
    DeprecationWarning,
    stacklevel=2,
)

from skill_cluster.discovery.routers.adaptive import (  # noqa: F401
    AdaptiveRouter,
    SkillMetrics,
)
