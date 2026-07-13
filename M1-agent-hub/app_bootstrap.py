"""
云汐内核 V6 - 应用启动器

灵感来源：Spring Boot Application / FastAPI App Factory

统一的应用工厂，负责：
1. 按依赖顺序创建所有组件
2. 注入 ConfigManager 到各子系统
3. 注册生命周期钩子
4. 注册健康检查
5. 启动 HTTP API 服务
6. 阻塞直到收到关闭信号

使用方式：
    python -m app_bootstrap --config config.yaml
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Any

import structlog

from config_manager import ConfigManager
from message_bus import MessageBus
from agent_registry import AgentRegistry
from task_dispatcher import TaskDispatcher
from a2a_protocol import MemoryTransport
from message_adapter import MessageAdapter
from intent_classifier_v2 import SemanticIntentClassifier
from orchestrator_v2 import OrchestratorV2
from orchestrator_v3 import OrchestratorV3
from orchestrator_v4 import OrchestratorV4
from orchestrator_v5 import OrchestratorV5
from orchestrator_v7 import OrchestratorV7
from orchestrator_v8 import OrchestratorV8
from orchestrator_v9 import OrchestratorV9
from event_store import EventStore
from streaming_engine import StreamingEngine
from llm_provider import LLMProviderFactory
from circuit_breaker import CircuitBreakerRegistry
from persistence import SQLitePersistence
from vector_memory import VectorMemory
from plugin_loader import PluginLoader
from mcp_server import MCPServer
from lifecycle_manager import LifecycleManager
from health_monitor import HealthMonitor
from api.server import YunxiAPI
from ensemble_engine import EnsembleEngine
from budget_manager import BudgetManager
from task_durability import TaskDurabilityManager
from enhanced_registry import EnhancedRegistry, LoopGuard
from checkpointer import Checkpointer
from rbac_memory import RBACMemoryGuard
from swarm_and_innovation import SwarmManager, TraceToMemory, RetrospectiveEngine, ModelRotationManager
from semantic_intent_v3 import SemanticIntentClassifierV3
from otlp_exporter import OTLPExporter
from guardrails_v2 import GuardrailsV2
from ledger_engine import LedgerEngine

logger = structlog.get_logger(__name__)


class YunxiApplication:
    """云汐内核应用实例"""

    def __init__(self, config_path: str | None = None) -> None:
        self.config = ConfigManager(config_path)
        self.lifecycle = LifecycleManager()
        self.health = HealthMonitor()
        self.orchestrator: OrchestratorV9 | None = None
        self.api_server: YunxiAPI | None = None
        self._registry = None
        self._bus = None
        self._ledger = None
        self._clone_pool = None
        self._logger = logger.bind(service="yunxi_app")

    async def build(self) -> OrchestratorV9:
        """构建完整的 V9 应用组件链

        从 V2 逐层构建至 V9，最终暴露 OrchestratorV9 作为统一入口。
        支持条件懒加载：未启用的组件不实例化，降低 7B 本地部署开销。
        """
        self._logger.info("app_build_start")

        # 1. 配置
        db_path = self.config.get_str("persistence.db_path", ":memory:")

        # 2. 基础设施
        bus = await MessageBus.get_instance()
        registry = AgentRegistry()

        # 2.5 A2A Transport & MessageAdapter（双向桥接）
        transport = MemoryTransport()
        adapter = MessageAdapter()
        await adapter.register_with_transport(transport)
        await adapter.register_with_bus(bus)

        # 3. 调度层
        dispatcher = TaskDispatcher(registry, bus)
        classifier = SemanticIntentClassifier()

        # 4. V2 编排器
        v2 = OrchestratorV2(registry, dispatcher, classifier=classifier)

        # 5. V3 编排器
        v3 = OrchestratorV3(v2)

        # 6. V4 组件
        llm_type = self.config.get_str("llm.provider_type", "mock")
        llm_model = self.config.get_str("llm.model", "mock-model")
        llm = LLMProviderFactory.create(llm_type, model=llm_model)

        persistence = SQLitePersistence(db_path)

        v4 = OrchestratorV4(
            orchestrator_v3=v3,
            event_store=EventStore(),
            streaming_engine=StreamingEngine(),
            llm_provider=llm,
            circuit_breakers=CircuitBreakerRegistry(),
            persistence=persistence,
        )

        # 7. V5 组件（条件懒加载）
        v5_kwargs: dict[str, Any] = {
            "orchestrator_v4": v4,
            "config": self.config,
        }
        if self.config.get_bool("vector_memory.enabled", True):
            v5_kwargs["vector_memory"] = VectorMemory(
                dimension=self.config.get_int("vector_memory.dimension", 128),
            )
        if self.config.get_bool("plugin_loader.enabled", True):
            v5_kwargs["plugin_loader"] = PluginLoader(
                plugin_dir=self.config.get_str("plugin_loader.plugin_dir", "./plugins"),
                watch_interval=self.config.get_float("plugin_loader.watch_interval", 10.0),
                auto_reload=self.config.get_bool("plugin_loader.auto_reload", True),
            )
        if self.config.get_bool("mcp_server.enabled", True):
            v5_kwargs["mcp_server"] = MCPServer(registry)

        v5 = OrchestratorV5(**v5_kwargs)

        # 8. V7 组件
        v7 = OrchestratorV7(
            orchestrator_v5=v5,
            ensemble_engine=EnsembleEngine(),
            budget_manager=BudgetManager(),
            durability_manager=TaskDurabilityManager(persistence),
        )

        # 9. V8 组件
        v8 = OrchestratorV8(
            orchestrator_v7=v7,
            registry=EnhancedRegistry(),
            loop_guard=LoopGuard(),
            checkpointer=Checkpointer(),
            rbac_guard=RBACMemoryGuard(),
            swarm_manager=SwarmManager(),
            trace_to_memory=TraceToMemory(),
            retrospective=RetrospectiveEngine(),
            budget_manager=v7._budget,  # [P0-4-2] 将 V7 的 BudgetManager 透传至 V8
        )

        # 10. V9 组件（最终入口）
        otlp_endpoint = self.config.get_str("observability.otlp_endpoint", "")
        otlp = OTLPExporter(endpoint=otlp_endpoint) if otlp_endpoint else None

        guardrails = GuardrailsV2(
            injection_threshold=self.config.get_float("guardrails.injection_threshold", 0.7),
            enable_pii_sanitize=self.config.get_bool("guardrails.enable_pii", True),
        )

        v9 = OrchestratorV9(
            orchestrator_v8=v8,
            intent_classifier=SemanticIntentClassifierV3(),
            otlp_exporter=otlp,
            guardrails=guardrails,
            ledger=LedgerEngine(),
        )

        self.orchestrator = v9

        # 保存 API 需要的组件引用
        self._registry = registry
        self._bus = bus
        self._ledger = v9._ledger if hasattr(v9, '_ledger') else LedgerEngine()

        # 11. 注册生命周期
        self._register_lifecycle(bus, registry, persistence, v9)

        # 12. 注册健康检查
        self._register_health_checks(bus, registry, persistence, v9)

        self._logger.info("app_build_complete", version="v9")
        return v9

    def _register_lifecycle(
        self,
        bus: MessageBus,
        registry: AgentRegistry,
        persistence: SQLitePersistence,
        v9: OrchestratorV9,
    ) -> None:
        """注册生命周期钩子"""

        async def start_plugins() -> None:
            await v9.load_plugins()

        async def shutdown_bus() -> None:
            await bus.shutdown()

        async def shutdown_persistence() -> None:
            persistence.close()

        self.lifecycle.register(
            "plugins",
            startup=start_plugins,
            timeout=self.config.get_float("plugin_loader.timeout", 30.0),
        )
        self.lifecycle.register(
            "message_bus",
            shutdown=shutdown_bus,
            timeout=10.0,
        )
        self.lifecycle.register(
            "persistence",
            shutdown=shutdown_persistence,
            timeout=10.0,
        )

    def _register_health_checks(
        self,
        bus: MessageBus,
        registry: AgentRegistry,
        persistence: SQLitePersistence,
        v9: OrchestratorV9,
    ) -> None:
        """注册健康检查"""

        async def bus_health() -> bool:
            return bus._running

        async def registry_health() -> bool:
            return len(registry.list_ids()) > 0

        async def persistence_health() -> bool:
            try:
                stats = persistence.get_stats()
                return isinstance(stats, dict)
            except Exception:
                return False

        self.health.register("message_bus", bus_health)
        self.health.register("agent_registry", registry_health)
        self.health.register("persistence", persistence_health)

    async def start_api(self, host: str = "0.0.0.0", port: int = 8080) -> None:
        """启动 HTTP API（使用 V11 版本 YunxiAPI）"""
        if self.orchestrator is None:
            raise RuntimeError("Application not built yet. Call build() first.")

        self.api_server = YunxiAPI(
            orchestrator=self.orchestrator,
            registry=self._registry,
            ledger=self._ledger,
            message_bus=self._bus,
            health_monitor=self.health,
            clone_pool=self._clone_pool,
            config_manager=self.config,
            host=host,
            port=port,
        )
        await self.api_server.start()

        self.lifecycle.register(
            "api_server",
            shutdown=self.api_server.stop,
            timeout=10.0,
        )

    async def run(self) -> None:
        """运行应用（构建 + 启动 + 阻塞）"""
        await self.build()
        await self.lifecycle.startup()
        self.lifecycle.setup_signal_handlers()
        self._logger.info("app_running")
        await self.lifecycle.wait_for_shutdown()

    async def shutdown(self) -> None:
        """手动关闭应用"""
        await self.lifecycle.shutdown()


# ── CLI 入口 ──────────────────────────────────────────

def main() -> None:
    """命令行入口"""
    parser = argparse.ArgumentParser(description="云汐内核")
    parser.add_argument("--config", "-c", default=None, help="配置文件路径")
    parser.add_argument("--host", default="0.0.0.0", help="API 服务地址")
    parser.add_argument("--port", "-p", type=int, default=8080, help="API 服务端口")
    parser.add_argument("--no-api", action="store_true", help="不启动 HTTP API")
    args = parser.parse_args()

    async def _run() -> None:
        app = YunxiApplication(config_path=args.config)
        await app.build()
        await app.lifecycle.startup()
        app.lifecycle.setup_signal_handlers()

        if not args.no_api:
            await app.start_api(host=args.host, port=args.port)

        logger.info("yunxi_core_started", config=args.config, api=not args.no_api)
        await app.lifecycle.wait_for_shutdown()

    asyncio.run(_run())


if __name__ == "__main__":
    main()
