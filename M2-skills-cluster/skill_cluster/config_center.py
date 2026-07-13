"""Dynamic Config 热更新配置中心（已迁移至 infrastructure.config_center）.

.. deprecated::
    请使用 ``skill_cluster.infrastructure.config_center`` 替代。
"""

from skill_cluster.infrastructure.config_center import *  # noqa: F401,F403
import warnings

warnings.warn(
    "skill_cluster.config_center is deprecated, use skill_cluster.infrastructure.config_center",
    DeprecationWarning,
    stacklevel=2,
)
