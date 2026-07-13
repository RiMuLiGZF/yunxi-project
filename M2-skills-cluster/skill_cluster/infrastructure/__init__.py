"""基础设施层 - Infrastructure Layer.

提供技能集群的底层基础设施能力：
- metrics: 结构化指标收集
- event_bus: 事件驱动总线
- config_center: 热更新配置中心
- hooks: 统一钩子系统
- tracing: 调用链路追踪
- health: 健康检查
- streaming: 流式调用支持
"""

from skill_cluster.infrastructure.metrics import (
    Counter,
    Histogram,
    MetricSample,
    MetricsCollector,
)
from skill_cluster.infrastructure.event_bus import EventBus, SkillEvent
from skill_cluster.infrastructure.config_center import ConfigCenter
from skill_cluster.infrastructure.hooks import HookManager, HookRegistration
from skill_cluster.infrastructure.tracing.aggregator import (
    TraceAggregator,
    TraceChain,
    TraceSpan,
)
from skill_cluster.infrastructure.health.skill_health import (
    CacheHealthChecker,
    CircuitBreakerHealthChecker,
    ClusterHealthReport,
    ComponentHealth,
    HealthStatus,
    RegistryHealthChecker,
    SkillClusterHealthChecker,
)
from skill_cluster.infrastructure.health.checker import HealthChecker

# streaming 模块延迟导入（避免循环依赖，因 streaming 依赖上层 skill_router）
_STREAMING_ATTRS = {
    "StreamChunk",
    "StreamInvokeResult",
    "StreamableSkillMixin",
    "StreamingInvoker",
}


def __getattr__(name: str):
    """延迟导入 streaming 模块，避免循环依赖."""
    if name in _STREAMING_ATTRS:
        from skill_cluster.infrastructure import streaming as _streaming_mod
        return getattr(_streaming_mod, name)
    raise AttributeError(f"module 'skill_cluster.infrastructure' has no attribute {name!r}")


__all__ = [
    # metrics
    "Counter",
    "Histogram",
    "MetricSample",
    "MetricsCollector",
    # event_bus
    "EventBus",
    "SkillEvent",
    # config_center
    "ConfigCenter",
    # hooks
    "HookManager",
    "HookRegistration",
    # tracing
    "TraceAggregator",
    "TraceChain",
    "TraceSpan",
    # health
    "CacheHealthChecker",
    "CircuitBreakerHealthChecker",
    "ClusterHealthReport",
    "ComponentHealth",
    "HealthChecker",
    "HealthStatus",
    "RegistryHealthChecker",
    "SkillClusterHealthChecker",
    # streaming (延迟导入)
    "StreamChunk",
    "StreamInvokeResult",
    "StreamableSkillMixin",
    "StreamingInvoker",
]
