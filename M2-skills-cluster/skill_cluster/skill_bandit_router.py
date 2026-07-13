from __future__ import annotations
"""[DEPRECATED] 已迁移至 skill_cluster.discovery.routers.bandit.

本文件为向后兼容存根，将从新路径导入并发出废弃警告。
请更新为: from skill_cluster.discovery.routers.bandit import ...
"""

import warnings

warnings.warn(
    "skill_cluster.skill_bandit_router 已废弃，请使用 skill_cluster.discovery.routers.bandit",
    DeprecationWarning,
    stacklevel=2,
)

from skill_cluster.discovery.routers.bandit import (  # noqa: F401
    BanditArm,
    SkillBanditRouter,
)
