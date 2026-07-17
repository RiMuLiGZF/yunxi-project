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
        from shared.core.version import SYSTEM_VERSION
        return SYSTEM_VERSION
    except Exception:
        return "v1.0.0"


SYSTEM_VERSION = _load_system_version()


# ============================================================
# 预注册向后兼容存根模块到 sys.modules
# 必须在主导入之前执行，确保内部模块引用 skill_cluster.xxx 时能找到存根
# ============================================================

_STUB_MODULES = [
    'a2a_bus', 'a2a_protocol', 'adaptive_router', 'agent_memory', 'agent_runtime',
    'api_v2', 'ast_scanner', 'circuit_breaker', 'code_execution_bridge',
    'config_center', 'edge_cloud_orchestrator', 'event_bus', 'function_schema',
    'health_checker', 'hooks', 'http_api', 'idempotency', 'm8_auth_middleware',
    'mcp_bridge', 'memory_skill_bridge', 'metrics', 'middleware', 'permissions',
    'pipeline_store', 'plugin_loader', 'rate_limiter', 'result_renderer', 'sandbox',
    'skill_bandit_router', 'skill_cache', 'skill_discovery', 'skill_experience',
    'skill_graph', 'skill_handbook', 'skill_health', 'skill_pipeline',
    'skill_recommender', 'skill_registry', 'skill_router', 'skill_selection',
    'streaming', 'test_endpoints', 'token_budget', 'tool_lazy_discoverer',
    'trace_aggregator', 'upgrade_endpoints', 'voice_polish',
]


def _register_stub_modules():
    """将存根模块预注册到 sys.modules，使 from skill_cluster.xxx import 能正常工作。
    
    由于部分内部模块仍引用旧的根级模块名（如 skill_router），
    必须在主导入之前将这些存根注册到 sys.modules，避免 ImportError。
    """
    import sys
    import importlib
    import warnings
    
    for name in _STUB_MODULES:
        full_name = f'skill_cluster.{name}'
        if full_name not in sys.modules:
            try:
                # 从 stubs 子包导入存根模块
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", DeprecationWarning)
                    mod = importlib.import_module(f'skill_cluster.stubs.{name}')
                sys.modules[full_name] = mod
            except Exception:
                pass  # 导入失败不影响主包启动


_register_stub_modules()


from skill_cluster.interfaces import (
    ISkill,
    SkillConfig,
    SkillInvokeRequest,
    SkillInvokeResult,
    SkillManifest,
    SkillQuery,
)
from skill_cluster.security.permissions import PermissionMatrix, SkillPermissionManager
from skill_cluster.core.registry import SkillRegistry
from skill_cluster.core.router import SkillRouter
from skill_cluster.core.pipeline import (
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
from skill_cluster.core.cache import SkillCache
from skill_cluster.infrastructure.config_center import ConfigCenter
from skill_cluster.core.function_schema import (
    ActionSignature,
    FunctionParameter,
    FunctionSchema,
    SkillSchemaRegistry,
)
from skill_cluster.core.middleware import (
    MiddlewarePipeline,
    cache_middleware,
    event_middleware,
    logging_middleware,
    metrics_middleware,
    resilient_middleware,
)
from skill_cluster.agent.runtime import (
    AgentRegistry,
    AgentRuntime,
    AgentState,
)
from skill_cluster.core.pipeline.store import (
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
from skill_cluster.models.a2a import (
    A2AAgentCard,
    A2AArtifact,
    A2AMessage,
    A2APart,
    A2ATask,
)
from skill_cluster.extensions.a2a.bus import A2ABus
from skill_cluster.extensions.plugins.loader import PluginInfo, PluginLoader
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
from skill_cluster.api.http import (
    InvokeRequest,
    manifest_to_skill_info,
    result_to_dict,
)
from skill_cluster.extensions.mcp.transport import (
    MCPTransport,
)
from skill_cluster.security.ast_scanner import (
    ASTSecurityScanner,
    ScanResult,
    SecurityFinding,
)
from skill_cluster.market import MarketRegistry, market_router

# create_app 是 http_api 中的工厂函数别名
from skill_cluster.api.http import create_http_app as create_app

# MCP 兼容函数（从 mcp_transport 迁移）
def handle_mcp_tool_list(registry: Any = None) -> dict:
    """MCP 工具列表处理函数（向后兼容）."""
    tools = []
    if registry:
        sids = registry.list_skills() if hasattr(registry, "list_skills") else []
        for sid in sids:
            skill = registry.get_skill(sid) if hasattr(registry, "get_skill") else None
            if skill is None:
                continue
            manifest = getattr(skill, "manifest", skill)
            actions = getattr(manifest, "actions", [])
            for action in actions:
                action_name = getattr(action, "name", "default")
                tools.append({
                    "name": f"{sid}.{action_name}",
                    "description": getattr(action, "description", "") or getattr(manifest, "description", ""),
                    "inputSchema": getattr(action, "input_schema", {"type": "object", "properties": {}}),
                })
    return {"tools": tools}


async def handle_mcp_tool_call(params: dict, registry: Any = None, router: Any = None) -> dict:
    """MCP 工具调用处理函数（向后兼容）."""
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {})

    if "." in tool_name and router:
        skill_id, action = tool_name.rsplit(".", 1)
        from skill_cluster.interfaces import SkillInvokeRequest as RouterInvokeRequest
        import uuid
        invoke_req = RouterInvokeRequest(
            skill_id=skill_id,
            action=action,
            params=arguments,
            trace_id=f"mcp-{uuid.uuid4().hex[:8]}",
        )
        result = await router.invoke(invoke_req, "mcp-client")
        if result.status == "success":
            content = []
            if result.data is not None:
                if isinstance(result.data, str):
                    content.append({"type": "text", "text": result.data})
                else:
                    content.append({"type": "text", "text": str(result.data)})
            return {"content": content}
        else:
            return {
                "content": [{"type": "text", "text": result.error or "Unknown error"}],
                "isError": True,
            }
    return {"content": [], "isError": True}


def wrap_jsonrpc_response(request: dict, result: dict) -> dict:
    """包装 JSON-RPC 响应（向后兼容）."""
    req_id = request.get("id") if isinstance(request, dict) else None
    if req_id is not None:
        return {
            "jsonrpc": "2.0",
            "result": result,
            "id": req_id,
        }
    return result


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
    "MarketRegistry",
    "market_router",
]


def __getattr__(name):
    """属性访问兜底，保持向后兼容。
    
    存根模块已在包加载时预注册到 sys.modules，
    此函数用于属性访问形式的兜底（如 skill_cluster.skill_router）。
    """
    if name in _STUB_MODULES:
        import sys
        full_name = f'skill_cluster.{name}'
        if full_name in sys.modules:
            return sys.modules[full_name]
        import importlib
        mod = importlib.import_module(f'skill_cluster.stubs.{name}')
        return mod
    raise AttributeError(f"module 'skill_cluster' has no attribute '{name}'")
