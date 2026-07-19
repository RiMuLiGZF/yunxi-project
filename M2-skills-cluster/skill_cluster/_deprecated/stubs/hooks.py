"""统一钩子系统 - Hook Manager（已迁移至 infrastructure.hooks）.

.. deprecated::
    请使用 ``skill_cluster.infrastructure.hooks`` 替代。
"""

from skill_cluster.infrastructure.hooks import *  # noqa: F401,F403
import warnings

warnings.warn(
    "skill_cluster.hooks is deprecated, use skill_cluster.infrastructure.hooks",
    DeprecationWarning,
    stacklevel=2,
)
