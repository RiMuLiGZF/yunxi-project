from __future__ import annotations
"""[DEPRECATED] 已迁移至 skill_cluster.agent.experience.handbook.

本文件为向后兼容存根，将从新路径导入并发出废弃警告。
请更新为: from skill_cluster.agent.experience.handbook import ...
"""

import warnings

warnings.warn(
    "skill_cluster.skill_handbook 已废弃，请使用 skill_cluster.agent.experience.handbook",
    DeprecationWarning,
    stacklevel=2,
)

from skill_cluster.agent.experience.handbook import (  # noqa: F401
    SkillHandbook,
    SkillProfile,
)
