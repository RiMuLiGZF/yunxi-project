"""Health Checker - 技能集群健康检查器（门面模块，已迁移至 infrastructure.health.checker）.

.. deprecated::
    请使用 ``skill_cluster.infrastructure.health.checker`` 替代。
"""

from skill_cluster.infrastructure.health.checker import *  # noqa: F401,F403
import warnings

__all__ = [
    "HealthChecker",
    "HealthStatus",
    "ClusterHealthReport",
]

warnings.warn(
    "skill_cluster.health_checker is deprecated, use skill_cluster.infrastructure.health.checker",
    DeprecationWarning,
    stacklevel=2,
)
