"""弹性容错层 - Resilience Layer.

提供技能集群的容错与弹性能力：
- circuit_breaker: 熔断器与重试机制
- rate_limiter: 令牌桶限流
- idempotency: 幂等性保障
"""

from skill_cluster.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerOpenError,
    CircuitBreakerStats,
    CircuitState,
    ErrorClassifier,
    ResilientSkillInvoker,
    RetryConfig,
    RetryExecutor,
    RetryStats,
)
from skill_cluster.resilience.rate_limiter import (
    RateLimitConfig,
    RateLimitError,
    RateLimiterRegistry,
    TokenBucket,
    check_rate_limit,
    get_global_registry,
    rate_limit_middleware,
)
from skill_cluster.resilience.idempotency import (
    IdempotencyManager,
    generate_pipeline_key,
    generate_request_key,
    generate_skill_key,
    get_default_manager,
    idempotent_middleware,
)

__all__ = [
    # circuit_breaker
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitBreakerOpenError",
    "CircuitBreakerStats",
    "CircuitState",
    "ErrorClassifier",
    "ResilientSkillInvoker",
    "RetryConfig",
    "RetryExecutor",
    "RetryStats",
    # rate_limiter
    "RateLimitConfig",
    "RateLimitError",
    "RateLimiterRegistry",
    "TokenBucket",
    "check_rate_limit",
    "get_global_registry",
    "rate_limit_middleware",
    # idempotency
    "IdempotencyManager",
    "generate_pipeline_key",
    "generate_request_key",
    "generate_skill_key",
    "get_default_manager",
    "idempotent_middleware",
]
