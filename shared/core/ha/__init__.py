"""
云汐高可用架构模块 (High Availability)

提供生产级高可用能力：
- 服务发现与健康检查增强（HTTP/TCP/依赖/资源）
- 负载均衡（轮询/加权轮询/最少连接/最快响应/一致性哈希）
- 故障转移（主备模式、自动切换、状态同步）
- 不健康实例自动摘除与恢复

使用方式：
    from shared.core.ha import (
        HealthCheckerPro,
        LoadBalancer,
        FailoverManager,
        ServiceRegistry,
    )
"""

from .health_checker_pro import (
    HealthCheckerPro,
    HealthCheckType,
    HealthCheckResult,
    TcpHealthCheck,
    DependencyHealthCheck,
    ResourceHealthCheck,
)
from .load_balancer import (
    LoadBalancer,
    LoadBalanceStrategy,
    ServiceInstance,
    RoundRobinBalancer,
    WeightedRoundRobinBalancer,
    LeastConnectionsBalancer,
    FastestResponseBalancer,
    ConsistentHashBalancer,
    create_load_balancer,
)
from .failover_manager import (
    FailoverManager,
    FailoverMode,
    FailoverState,
    FailoverEvent,
)
from .service_registry import (
    ServiceRegistry,
    ServiceInstanceInfo,
    ServiceStatus,
)

__all__ = [
    # 健康检查增强
    "HealthCheckerPro",
    "HealthCheckType",
    "HealthCheckResult",
    "TcpHealthCheck",
    "DependencyHealthCheck",
    "ResourceHealthCheck",
    # 负载均衡
    "LoadBalancer",
    "LoadBalanceStrategy",
    "ServiceInstance",
    "RoundRobinBalancer",
    "WeightedRoundRobinBalancer",
    "LeastConnectionsBalancer",
    "FastestResponseBalancer",
    "ConsistentHashBalancer",
    "create_load_balancer",
    # 故障转移
    "FailoverManager",
    "FailoverMode",
    "FailoverState",
    "FailoverEvent",
    # 服务发现
    "ServiceRegistry",
    "ServiceInstanceInfo",
    "ServiceStatus",
]
