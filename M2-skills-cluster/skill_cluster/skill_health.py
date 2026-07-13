"""Skill Cluster Health - 全局健康检查聚合（已迁移至 infrastructure.health.skill_health）.

.. deprecated::
    请使用 ``skill_cluster.infrastructure.health.skill_health`` 替代。
"""

from skill_cluster.infrastructure.health.skill_health import *  # noqa: F401,F403
import warnings

warnings.warn(
    "skill_cluster.skill_health is deprecated, use skill_cluster.infrastructure.health.skill_health",
    DeprecationWarning,
    stacklevel=2,
)
