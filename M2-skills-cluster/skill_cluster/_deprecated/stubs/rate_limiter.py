"""令牌桶限流中间件（已迁移至 resilience.rate_limiter）.

.. deprecated::
    请使用 ``skill_cluster.resilience.rate_limiter`` 替代。
"""

from skill_cluster.resilience.rate_limiter import *  # noqa: F401,F403
import warnings

warnings.warn(
    "skill_cluster.rate_limiter is deprecated, use skill_cluster.resilience.rate_limiter",
    DeprecationWarning,
    stacklevel=2,
)
