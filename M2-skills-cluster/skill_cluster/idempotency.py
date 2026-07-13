"""幂等性管理器（已迁移至 resilience.idempotency）.

.. deprecated::
    请使用 ``skill_cluster.resilience.idempotency`` 替代。
"""

from skill_cluster.resilience.idempotency import *  # noqa: F401,F403
import warnings

warnings.warn(
    "skill_cluster.idempotency is deprecated, use skill_cluster.resilience.idempotency",
    DeprecationWarning,
    stacklevel=2,
)
