"""Circuit Breaker 熔断与重试机制（已迁移至 resilience.circuit_breaker）.

.. deprecated::
    请使用 ``skill_cluster.resilience.circuit_breaker`` 替代。
"""

from skill_cluster.resilience.circuit_breaker import *  # noqa: F401,F403
import warnings

warnings.warn(
    "skill_cluster.circuit_breaker is deprecated, use skill_cluster.resilience.circuit_breaker",
    DeprecationWarning,
    stacklevel=2,
)
