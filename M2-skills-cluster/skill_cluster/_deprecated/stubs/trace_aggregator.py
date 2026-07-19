"""Trace Aggregator - 调用链路追踪聚合器（已迁移至 infrastructure.tracing.aggregator）.

.. deprecated::
    请使用 ``skill_cluster.infrastructure.tracing.aggregator`` 替代。
"""

from skill_cluster.infrastructure.tracing.aggregator import *  # noqa: F401,F403
import warnings

warnings.warn(
    "skill_cluster.trace_aggregator is deprecated, use skill_cluster.infrastructure.tracing.aggregator",
    DeprecationWarning,
    stacklevel=2,
)
