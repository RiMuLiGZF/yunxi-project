"""M2 技能集群 - 弹性配置模型.

包含熔断、限流、幂等等弹性机制的配置模型。

注意：
    当前熔断器配置（CircuitBreakerConfig, RetryConfig 等）使用 dataclass
    定义在 ``circuit_breaker.py`` 中，限流配置（RateLimitConfig）使用
    普通类定义在 ``rate_limiter.py`` 中，幂等配置（IdempotencyConfig）
    定义在 ``config.py`` 中。

    本模块预留作为弹性配置模型的统一入口，后续可将 dataclass 配置
    逐步迁移为 Pydantic 模型以获得更好的校验能力。
"""

from __future__ import annotations

# 当前弹性相关的配置模型使用 dataclass / 普通类定义，
# 未使用 Pydantic BaseModel，因此暂无可迁移的 Pydantic 模型。
# 此处预留模块位置，保持目录结构完整性。

__all__: list[str] = []
