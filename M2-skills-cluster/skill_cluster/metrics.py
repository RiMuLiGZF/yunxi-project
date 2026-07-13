"""Metrics Collector - 结构化指标收集（已迁移至 infrastructure.metrics）.

.. deprecated::
    请使用 ``skill_cluster.infrastructure.metrics`` 替代。
"""

from skill_cluster.infrastructure.metrics import *  # noqa: F401,F403
import warnings

warnings.warn(
    "skill_cluster.metrics is deprecated, use skill_cluster.infrastructure.metrics",
    DeprecationWarning,
    stacklevel=2,
)
