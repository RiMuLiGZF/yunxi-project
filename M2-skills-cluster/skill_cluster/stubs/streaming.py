"""Streaming 流式调用支持（已迁移至 infrastructure.streaming）.

.. deprecated::
    请使用 ``skill_cluster.infrastructure.streaming`` 替代。
"""

from skill_cluster.infrastructure.streaming import *  # noqa: F401,F403
import warnings

warnings.warn(
    "skill_cluster.streaming is deprecated, use skill_cluster.infrastructure.streaming",
    DeprecationWarning,
    stacklevel=2,
)
