"""API 弹性中间件（向后兼容入口）.

本文件已重构为从 src.middleware 包再导出，保持向后兼容。
新代码请直接从 src.middleware 导入：
    from src.middleware import (
        RateLimitMiddleware,
        CircuitBreakerMiddleware,
        IdempotencyMiddleware,
    )

主要功能：
- 全局限流：基于 IP 的令牌桶限流
- 接口级熔断：按路由路径独立熔断器统计
- 幂等性保护：基于请求头的幂等键缓存响应结果
- 降级响应：触发限流/熔断时返回标准错误响应
"""

from __future__ import annotations

from src.middleware import (  # noqa: F401
    # 限流
    RateLimitMiddleware,
    TokenBucketRateLimiter,
    # 熔断
    CircuitBreakerMiddleware,
    CircuitBreaker,
    CircuitState,
    # 幂等
    IdempotencyMiddleware,
)
