from __future__ import annotations

"""云汐内核 - Skill 技能集群系统.

统一管理系统内所有技能能力，提供技能的注册、发现、挂载、调用、权限管控。
"""

__version__ = "1.2.0"


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
# 向后兼容：旧模块名 -> 新模块路径 映射表
# 原 stubs/ 目录已归档至 _deprecated/stubs/
# 通过动态创建代理模块保持 skill_cluster.xxx 旧路径的兼容性
# ============================================================

_DEPRECATED_MODULE_MAP = {
    'a2a_bus': 'skill_cluster.extensions.a2a.bus',
    'a2a_protocol': 'skill_cluster.models.a2a',
    'adaptive_router': 'skill_cluster.discovery.routers.adaptive',
    'agent_memory': 'skill_cluster.agent.memory',
    'agent_runtime': 'skill_cluster.agent.runtime',
    'api_v2': 'skill_cluster.api.v2',
    'ast_scanner': 'skill_cluster.security.ast_scanner',
    'circuit_breaker': 'skill_cluster.resilience.circuit_breaker',
    'code_execution_bridge': 'skill_cluster.security.code_exec.bridge',
    'config_center': 'skill_cluster.infrastructure.config_center',
    'edge_cloud_orchestrator': 'skill_cluster.discovery.routers.edge_cloud',
    'event_bus': 'skill_cluster.infrastructure.event_bus',
    'function_schema': 'skill_cluster.core.function_schema',
    'health_checker': 'skill_cluster.infrastructure.health.checker',
    'hooks': 'skill_cluster.infrastructure.hooks',
    'http_api': 'skill_cluster.api.http',
    'idempotency': 'skill_cluster.resilience.idempotency',
    'm8_auth_middleware': 'skill_cluster.api.middleware.m8_auth',
    'mcp_bridge': 'skill_cluster.extensions.mcp.bridge',
    'memory_skill_bridge': 'skill_cluster.agent.experience.memory_bridge',
    'metrics': 'skill_cluster.infrastructure.metrics',
    'middleware': 'skill_cluster.core.middleware',
    'permissions': 'skill_cluster.security.permissions',
    'pipeline_store': 'skill_cluster.core.pipeline.store',
    'plugin_loader': 'skill_cluster.extensions.plugins.loader',
    'rate_limiter': 'skill_cluster.resilience.rate_limiter',
    'result_renderer': 'skill_cluster.security.code_exec.renderer',
    'sandbox': 'skill_cluster.security.sandbox',
    'skill_bandit_router': 'skill_cluster.discovery.routers.bandit',
    'skill_cache': 'skill_cluster.core.cache',
    'skill_discovery': 'skill_cluster.discovery.engine',
    'skill_experience': 'skill_cluster.agent.experience.bank',
    'skill_graph': 'skill_cluster.agent.experience.graph',
    'skill_handbook': 'skill_cluster.agent.experience.handbook',
    'skill_health': 'skill_cluster.infrastructure.health.skill_health',
    'skill_pipeline': 'skill_cluster.core.pipeline',
    'skill_recommender': 'skill_cluster.discovery.recommender',
    'skill_registry': 'skill_cluster.core.registry',
    'skill_router': 'skill_cluster.core.router',
    'skill_selection': 'skill_cluster.discovery.selection',
    'streaming': 'skill_cluster.infrastructure.streaming',
    'test_endpoints': 'skill_cluster.api.test_endpoints',
    'token_budget': 'skill_cluster.agent.token_budget',
    'tool_lazy_discoverer': 'skill_cluster.discovery.lazy_discoverer',
    'trace_aggregator': 'skill_cluster.infrastructure.tracing.aggregator',
    'upgrade_endpoints': 'skill_cluster.api.upgrade',
    'voice_polish': 'skill_cluster.extensions.voice_polish',
}

# 特殊符号别名：某些旧模块中有额外的符号别名（非直接重导出）
# 格式: {模块名: {旧符号名: 新符号名}}
_DEPRECATED_SYMBOL_ALIASES = {
    'http_api': {
        'create_app': 'create_http_app',
    },
}


def _create_lazy_deprecated_module(name: str, target_module: str):
    """创建一个惰性加载的废弃模块代理。

    预注册到 sys.modules 时不需要立即加载目标模块，
    首次属性访问时才真正导入目标模块，避免循环导入问题。

    替代原 stubs/ 目录下的 47 个存根文件，
    以统一的动态模块机制保持向后兼容。
    """
    import sys
    import os
    import warnings
    from types import ModuleType

    warning_msg = (
        f"skill_cluster.{name} is deprecated, use {target_module} instead. "
        f"原 stubs 目录已归档至 _deprecated/stubs/，请更新 import 路径。"
    )

    _real_mod = [None]  # 使用列表以便在闭包中修改
    # 获取该模块的特殊符号别名映射
    _aliases = _DEPRECATED_SYMBOL_ALIASES.get(name, {})

    def _get_real_mod():
        if _real_mod[0] is None:
            import importlib
            _real_mod[0] = importlib.import_module(target_module)
        return _real_mod[0]

    def _resolve_attr(attr):
        """解析属性名，处理符号别名。"""
        real = _get_real_mod()
        # 先尝试直接获取
        try:
            return getattr(real, attr)
        except AttributeError:
            # 如果有别名，尝试通过别名获取
            if attr in _aliases:
                return getattr(real, _aliases[attr])
            raise

    # 预计算目标模块的文件路径（不导入模块），设置 __file__
    # 避免 inspect.getmodule 等触发 __getattr__ 导致循环导入
    def _derive_module_file(mod_name):
        """根据模块名推导文件路径，不实际导入模块。"""
        parts = mod_name.split('.')
        # 只处理 skill_cluster 内部的模块
        if parts[0] != 'skill_cluster':
            return None
        # 从 skill_cluster 包目录开始查找
        base_dir = os.path.dirname(os.path.abspath(__file__))
        rel_parts = parts[1:]
        # 模块可能是 package/__init__.py 或 module.py
        pkg_path = os.path.join(base_dir, *rel_parts, '__init__.py')
        mod_path = os.path.join(base_dir, *rel_parts[:-1], rel_parts[-1] + '.py')
        if os.path.exists(pkg_path):
            return pkg_path
        if os.path.exists(mod_path):
            return mod_path
        return None

    class _LazyDeprecatedModule(ModuleType):
        """惰性代理模块：首次业务属性访问时才加载真实模块并发出废弃警告。"""

        def __getattr__(self, attr):
            # 注意：Python 特殊属性如 __file__, __name__, __path__ 等
            # 由 ModuleType 基类或实例字典直接处理，
            # 只有业务属性访问才会走到这里
            warnings.warn(warning_msg, DeprecationWarning, stacklevel=2)
            return _resolve_attr(attr)

        def __dir__(self):
            try:
                names = dir(_get_real_mod())
                # 添加别名到 dir 结果中
                names.extend(_aliases.keys())
                return names
            except Exception:
                return list(_aliases.keys())

        def __repr__(self):
            if _real_mod[0] is not None:
                return f"<deprecated module 'skill_cluster.{name}' (alias for {target_module})>"
            return f"<deprecated module 'skill_cluster.{name}' (lazy, alias for {target_module})>"

    proxy = _LazyDeprecatedModule(f'skill_cluster.{name}')
    proxy.__package__ = 'skill_cluster'

    # 预设置 __file__ 属性，避免 inspect 等工具触发 __getattr__
    derived_file = _derive_module_file(target_module)
    if derived_file:
        proxy.__file__ = derived_file

    return proxy


def _register_deprecated_modules():
    """将所有废弃模块名预注册到 sys.modules。

    使用惰性加载代理模块，避免在包初始化阶段因循环导入而失败。
    使 `from skill_cluster.xxx import ...` 形式的旧导入路径仍能正常工作，
    同时发出 DeprecationWarning 提示迁移到新路径。
    """
    import sys

    for name, target in _DEPRECATED_MODULE_MAP.items():
        full_name = f'skill_cluster.{name}'
        if full_name not in sys.modules:
            try:
                mod = _create_lazy_deprecated_module(name, target)
                sys.modules[full_name] = mod
            except Exception:
                pass  # 注册失败不影响主包启动


_register_deprecated_modules()


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

    废弃模块已在包加载时预注册到 sys.modules，
    此函数用于属性访问形式的兜底（如 skill_cluster.skill_router）。
    """
    if name in _DEPRECATED_MODULE_MAP:
        import sys
        full_name = f'skill_cluster.{name}'
        if full_name in sys.modules:
            return sys.modules[full_name]
        target = _DEPRECATED_MODULE_MAP[name]
        mod = _create_lazy_deprecated_module(name, target)
        if mod is not None:
            sys.modules[full_name] = mod
            return mod
    raise AttributeError(f"module 'skill_cluster' has no attribute '{name}'")
