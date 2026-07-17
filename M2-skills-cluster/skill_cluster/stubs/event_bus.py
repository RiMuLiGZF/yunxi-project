"""Event Bus 事件驱动总线（已迁移至 infrastructure.event_bus）.

.. deprecated::
    请使用 ``skill_cluster.infrastructure.event_bus`` 替代。
"""

from skill_cluster.infrastructure.event_bus import *  # noqa: F401,F403
import warnings

warnings.warn(
    "skill_cluster.event_bus is deprecated, use skill_cluster.infrastructure.event_bus",
    DeprecationWarning,
    stacklevel=2,
)
