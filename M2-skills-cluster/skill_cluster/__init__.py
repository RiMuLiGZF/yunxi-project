from __future__ import annotations

"""云汐内核 - Skill 技能集群系统.

统一管理系统内所有技能能力，提供技能的注册、发现、挂载、调用、权限管控。
"""

__version__ = "1.0.0"


def _load_system_version() -> str:
    """从 shared.version 导入系统版本号，导入失败则回退到默认值"""
    try:
        # 查找项目根目录并加入 sys.path
        from pathlib import Path
        current = Path(__file__).resolve().parent
        for _ in range(10):
            if (current / "shared" / "version.py").exists():
                import sys
                if str(current) not in sys.path:
                    sys.path.insert(0, str(current))
                break
            current = current.parent
        from shared.version import SYSTEM_VERSION
        return SYSTEM_VERSION
    except Exception:
        return "v1.0.0"


SYSTEM_VERSION = _load_system_version()

from skill_cluster.interfaces import (
    ISkill,
    SkillConfig,
    SkillInvokeRequest,
    SkillInvokeResult,
    SkillManifest,
    SkillQuery,
)
from skill_cluster.security.permissions import PermissionMatrix, SkillPermissionManager
from skill_cluster.skill_registry import SkillRegistry
from skill_cluster.skill_router import SkillRouter
from skill_cluster.skill_pipeline import (
    PipelineDefinition,
    PipelineEngine,
    PipelineStep,
)
from skill_cluster.infrastructure.event_bus import EventBus, SkillEvent
from skill_cluster.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerOpenError,
    ResilientSkillInvoker,
    RetryConfig,
    RetryExecutor,
)
from skill_cluster.skill_cache import SkillCache
from skill_cluster.infrastructure.config_center import ConfigCenter
from skill_cluster.function_schema import (
    ActionSignature,
    FunctionParameter,
    FunctionSchema,
    SkillSchemaRegistry,
)
from skill_cluster.middleware import (
    MiddlewarePipeline,
    cache_middleware,
    event_middleware,
    resilient_middleware,
    metrics_middleware,
    logging_middleware,
)
from skill_cluster.agent.runtime import (
    AgentRegistry,
    AgentRuntime,
    AgentState,
)
from skill_cluster.pipeline_store import (
    PipelineRunRecord,
    PipelineStateStore,
)
from skill_cluster.infrastructure.metrics import (
    Counter,
    Histogram,
    MetricsCollector,
    MetricSample,
)
from skill_cluster.infrastructure.streaming import (
    StreamChunk,
    StreamInvokeResult,
    StreamingInvoker,
    StreamableSkillMixin,
)
from skill_cluster.security.sandbox import (
    SandboxConfig,
    SandboxExecutor,
    SandboxMiddleware,
    SandboxPolicy,
    create_sandbox_middleware,
)
from skill_cluster.a2a_protocol import (
    A2AAgentCard,
    A2AArtifact,
    A2AMessage,
    A2APart,
    A2ATask,
)
from skill_cluster.a2a_bus import A2ABus
from skill_cluster.plugin_loader import PluginInfo, PluginLoader
from skill_cluster.infrastructure.hooks import HookManager, HookRegistration
from skill_cluster.agent.memory import AgentMemory, MemoryEntry
from skill_cluster.discovery.routers.adaptive import AdaptiveRouter, SkillMetrics
from skill_cluster.agent.experience.graph import ComposableChain, GraphEdge, SkillGraph
from skill_cluster.agent.token_budget import BudgetAlert, BudgetEntry, TokenBudget
from skill_cluster.agent.experience.bank import (
    ExperienceRecord,
    SkillExperienceBank,
    SuccessPattern,
)
from skill_cluster.discovery.recommender import SkillRecommender, SkillRecommendation
from skill_cluster.agent.experience.memory_bridge import (
    BridgeStats,
    MemorySkillBridge,
)
from skill_cluster.agent.experience.handbook import SkillHandbook, SkillProfile
from skill_cluster.discovery.routers.edge_cloud import (
    EdgeCloudConfig,
    EdgeCloudOrchestrator,
)
from skill_cluster.discovery.lazy_discoverer import ToolLazyDiscoverer, ToolReference
from skill_cluster.discovery.routers.bandit import SkillBanditRouter, BanditArm
from skill_cluster.discovery.selection import (
    AdaptiveSelection,
    BanditSelection,
    CompositeSelection,
    ISkillSelectionStrategy,
    RoundRobinSelection,
    SelectionContext,
    SelectionResult,
    SelectionStrategyType,
    SkillSelectionOrchestrator,
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
from skill_cluster.infrastructure.tracing.aggregator import (
    TraceAggregator,
    TraceChain,
    TraceSpan,
)
from skill_cluster.http_api import (
    InvokeRequest,
    create_app,
    manifest_to_skill_info,
    result_to_dict,
)
from skill_cluster.mcp_transport import (
    handle_mcp_tool_call,
    handle_mcp_tool_list,
    wrap_jsonrpc_response,
)
from skill_cluster.security.ast_scanner import (
    ASTSecurityScanner,
    ScanResult,
    SecurityFinding,
)

__all__ = [
    "ISkill",
    "SkillConfig",
    "SkillInvokeRequest",
    "SkillInvokeResult",
    "SkillManifest",
    "SkillQuery",
    "PermissionMatrix",
    "SkillPermissionManager",
    "SkillRegistry",
    "SkillRouter",
    "PipelineDefinition",
    "PipelineEngine",
    "PipelineStep",
    "EventBus",
    "SkillEvent",
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitBreakerOpenError",
    "ResilientSkillInvoker",
    "RetryConfig",
    "RetryExecutor",
    "SkillCache",
    "ConfigCenter",
    "ActionSignature",
    "FunctionParameter",
    "FunctionSchema",
    "SkillSchemaRegistry",
    "MiddlewarePipeline",
    "cache_middleware",
    "event_middleware",
    "resilient_middleware",
    "metrics_middleware",
    "logging_middleware",
    "AgentRegistry",
    "AgentRuntime",
    "AgentState",
    "PipelineRunRecord",
    "PipelineStateStore",
    "Counter",
    "Histogram",
    "MetricsCollector",
    "MetricSample",
    "StreamChunk",
    "StreamInvokeResult",
    "StreamingInvoker",
    "StreamableSkillMixin",
    "SandboxConfig",
    "SandboxExecutor",
    "SandboxMiddleware",
    "SandboxPolicy",
    "create_sandbox_middleware",
    "A2AAgentCard",
    "A2AArtifact",
    "A2AMessage",
    "A2APart",
    "A2ATask",
    "A2ABus",
    "PluginInfo",
    "PluginLoader",
    "HookManager",
    "HookRegistration",
    "AgentMemory",
    "MemoryEntry",
    "AdaptiveRouter",
    "SkillMetrics",
    "ComposableChain",
    "GraphEdge",
    "SkillGraph",
    "BudgetAlert",
    "BudgetEntry",
    "TokenBudget",
    "ExperienceRecord",
    "SkillExperienceBank",
    "SuccessPattern",
    "SkillRecommender",
    "SkillRecommendation",
    "BridgeStats",
    "MemorySkillBridge",
    "SkillHandbook",
    "SkillProfile",
    "EdgeCloudConfig",
    "EdgeCloudOrchestrator",
    "ToolLazyDiscoverer",
    "ToolReference",
    "SkillBanditRouter",
    "BanditArm",
    "AdaptiveSelection",
    "BanditSelection",
    "CompositeSelection",
    "ISkillSelectionStrategy",
    "RoundRobinSelection",
    "SelectionContext",
    "SelectionResult",
    "SelectionStrategyType",
    "SkillSelectionOrchestrator",
    "CacheHealthChecker",
    "CircuitBreakerHealthChecker",
    "ClusterHealthReport",
    "ComponentHealth",
    "HealthStatus",
    "RegistryHealthChecker",
    "SkillClusterHealthChecker",
    "TraceAggregator",
    "TraceChain",
    "TraceSpan",
    "InvokeRequest",
    "create_app",
    "manifest_to_skill_info",
    "result_to_dict",
    "handle_mcp_tool_call",
    "handle_mcp_tool_list",
    "wrap_jsonrpc_response",
    "ASTSecurityScanner",
    "ScanResult",
    "SecurityFinding",
]
