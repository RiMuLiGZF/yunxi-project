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

from src.config.config_manager import ConfigManager
from src.core.message_bus import MessageBus
from src.agents.agent_registry import AgentRegistry
from src.core.task_dispatcher import TaskDispatcher
from src.core.a2a_protocol import MemoryTransport
from src.core.message_adapter import MessageAdapter
from src.core.intent_classifier_v2 import SemanticIntentClassifier
from src.orchestration.orchestrator_v2 import OrchestratorV2
from src.orchestration.orchestrator_v3 import OrchestratorV3
from src.orchestration.orchestrator_v4 import OrchestratorV4
from src.orchestration.orchestrator_v5 import OrchestratorV5
from src.orchestration.orchestrator_v7 import OrchestratorV7
from src.orchestration.orchestrator_v8 import OrchestratorV8
from src.orchestration.orchestrator_v9 import OrchestratorV9
from src.core.event_store import EventStore
from src.core.streaming_engine import StreamingEngine
from src.tools.llm_provider import LLMProviderFactory
from src.resilience.circuit_breaker import CircuitBreakerRegistry
from src.core.persistence import SQLitePersistence
from src.memory.vector_memory import VectorMemory
from src.core.plugin_loader import PluginLoader
from src.tools.mcp_server import MCPServer
from src.core.lifecycle_manager import LifecycleManager
from src.observability.health_monitor import HealthMonitor
from src.api.server import YunxiAPI
from src.orchestration.ensemble_engine import EnsembleEngine
from src.resilience.budget_manager import BudgetManager
from src.core.task_durability import TaskDurabilityManager
from src.agents.enhanced_registry import EnhancedRegistry, LoopGuard
from src.core.checkpointer import Checkpointer
from src.memory.rbac_memory import RBACMemoryGuard
from src.orchestration.swarm_and_innovation import SwarmManager, TraceToMemory, RetrospectiveEngine, ModelRotationManager
from src.core.semantic_intent_v3 import SemanticIntentClassifierV3
from src.observability.otlp_exporter import OTLPExporter
from guardrails_v2 import GuardrailsV2
from src.core.ledger_engine import LedgerEngine
from src.federation.registry import ExternalAgentRegistry
from src.federation.scheduler import FederatedScheduler
from src.federation.cost_controller import CostController
from src.federation.privacy_guard import FederationPrivacyGuard

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
        self._federation_registry = None
        self._federation_scheduler = None
        self._cost_controller = None
        self._privacy_guard = None
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
        llm_api_key = self.config.get_str("llm.api_key", "")
        llm_base_url = self.config.get_str("llm.base_url", "")
        llm = LLMProviderFactory.create(
            llm_type,
            model=llm_model,
            api_key=llm_api_key or None,
            base_url=llm_base_url or None,
        )

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
                plugin_dir=self.config.get_str("plugin_loader.plugin_dir", "./agents"),
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

        v3_classifier = SemanticIntentClassifierV3()

        v9 = OrchestratorV9(
            orchestrator_v8=v8,
            intent_classifier=v3_classifier,
            otlp_exporter=otlp,
            guardrails=guardrails,
            ledger=LedgerEngine(),
        )

        # 训练 V3 语义意图分类器（从 V2 规则中提取训练样本）
        # V2 分类器的关键词规则作为 V3 TF-IDF 分类器的初始训练数据
        v2_classifier = classifier
        training_samples: dict[str, list[str]] = {}
        for rule in v2_classifier._rules:
            intent = rule.intent
            if intent not in training_samples:
                training_samples[intent] = []
            training_samples[intent].extend(rule.keywords)
            # 每个关键词生成一些变体样本（简单组合）
            for kw in rule.keywords:
                training_samples[intent].append(f"帮我{kw}")
                training_samples[intent].append(f"我想{kw}")
                training_samples[intent].append(f"需要{kw}")

        if training_samples:
            v3_classifier.train(training_samples)
            self._logger.info(
                "v3_classifier_trained",
                intents=list(training_samples.keys()),
                total_samples=sum(len(v) for v in training_samples.values()),
            )

        self.orchestrator = v9

        # 保存 API 需要的组件引用
        self._registry = registry
        self._bus = bus
        self._ledger = v9._ledger if hasattr(v9, '_ledger') else LedgerEngine()

        # 10.5 手动注册内置 Agent（从 ./agents 目录加载）
        # 插件系统因目录配置问题可能加载失败，这里直接 import 并注册，确保核心 Agent 可用
        from src.agents.agent_emotion import EmotionAgent
        from src.agents.agent_dev import DevAgent
        from src.agents.agent_note import NoteAgent
        from src.agents.agent_review import ReviewAgent

        builtin_agents = [EmotionAgent(), DevAgent(), NoteAgent(), ReviewAgent()]
        for agent in builtin_agents:
            try:
                if hasattr(registry, "register_sync"):
                    registry.register_sync(agent)
                    self._logger.info("builtin_agent_registered", agent_id=agent.agent_id)
            except Exception as e:
                self._logger.warning("builtin_agent_register_failed", agent_id=getattr(agent, "agent_id", "unknown"), error=str(e))

        # 10.6 初始化联邦调度系统并注册所有联邦 Agent
        # 联邦层提供外部 Agent 管理、成本控制、隐私防护等能力
        if self.config.get_bool("federation.enabled", True):
            self._init_federation(v9)

        # 11. 注册生命周期
        self._register_lifecycle(bus, registry, persistence, v9)

        # 12. 注册健康检查
        self._register_health_checks(bus, registry, persistence, v9)

        self._logger.info("app_build_complete", version="v9")
        return v9

    def _init_federation(self, v9: OrchestratorV9) -> None:
        """[V11.0] 初始化联邦调度系统并注册所有内置联邦 Agent

        包括：
        - 6 个独立业务 Agent（Hermes/Codex/Explore/Tide/Voice/ModuleManager）
        - 5 个模块管家 Agent（M2/M3/M4/M6/M7）
        - 4 个基础 LLM 适配器（OpenAI/Anthropic/Gemini/Local）
        """
        from shared_models import ExternalAgentType, AgentPrivacyLevel, ConnectionType, LicenseType

        fed_registry = ExternalAgentRegistry()
        fed_scheduler = FederatedScheduler(fed_registry)
        cost_controller = CostController()
        privacy_guard = FederationPrivacyGuard()

        self._federation_registry = fed_registry
        self._federation_scheduler = fed_scheduler
        self._cost_controller = cost_controller
        self._privacy_guard = privacy_guard

        registered_count = 0

        # ── 独立业务 Agent ──────────────────────────────────

        # 1. Hermes 智能代理（qwen2.5:7b，全功能Agent）
        try:
            fed_registry.register_agent(
                display_name="Hermes 智能代理",
                provider="Hermes",
                agent_type=ExternalAgentType.CUSTOM,
                capabilities=["代码生成", "代码审查", "问题解答", "信息检索", "任务规划",
                              "多步推理", "工具调用", "数据分析", "文档处理", "自学习"],
                cost_model={"input_per_1k": 0.0, "output_per_1k": 0.0, "per_request": 0.0, "currency": "USD"},
                privacy_level=AgentPrivacyLevel.LOCAL_ONLY,
                connection_type=ConnectionType.LOCAL,
                config={
                    "adapter_type": "hermes_agent",
                    "ollama_base_url": "http://localhost:11434",
                    "model_name": "qwen2.5:7b",
                    "mcp_server_url": "http://localhost:8002/mcp/v1",
                    "max_iterations": 8,
                    "temperature": 0.7,
                    "description": "Hermes Agent — 基于本地 Ollama 大模型的自进化智能代理。",
                },
                api_key="",
                license=LicenseType.MIT,
                confirm_license_risk=False,
            )
            registered_count += 1
            self._logger.info("federation_agent_registered", agent="hermes", model="qwen2.5:7b")
        except Exception as e:
            self._logger.warning("federation_agent_register_failed", agent="hermes", error=str(e))

        # 2. Codex 代码助手（本地 qwen2.5:7b）
        try:
            fed_registry.register_agent(
                display_name="Codex 代码助手",
                provider="Codex",
                agent_type=ExternalAgentType.CODE,
                capabilities=["代码生成", "代码审查", "Bug修复", "代码解释", "重构建议",
                              "测试生成", "架构设计", "性能优化", "多语言支持", "MCP工具调用"],
                cost_model={"input_per_1k": 0.0, "output_per_1k": 0.0, "currency": "USD"},
                privacy_level=AgentPrivacyLevel.LOCAL_ONLY,
                connection_type=ConnectionType.LOCAL,
                config={
                    "mode": "local",
                    "adapter_type": "codex_agent",
                    "ollama_base_url": "http://localhost:11434",
                    "model_name": "qwen2.5:7b",
                    "description": "Codex 代码助手 — 基于本地 qwen2.5:7b 模型驱动的代码专家。",
                },
                api_key="",
                license=LicenseType.MIT,
                confirm_license_risk=False,
            )
            registered_count += 1
            self._logger.info("federation_agent_registered", agent="codex", model="qwen2.5:7b")
        except Exception as e:
            self._logger.warning("federation_agent_register_failed", agent="codex", error=str(e))

        # 3. 小探 研究助理（qwen2.5:1.5b，轻量快速）
        try:
            fed_registry.register_agent(
                display_name="小探 研究助理",
                provider="Explore",
                agent_type=ExternalAgentType.CUSTOM,
                capabilities=["网页检索", "文档搜索", "信息摘要", "多源整合", "翻译辅助",
                              "资料分类", "要点提取", "文献整理", "MCP工具调用", "快速响应"],
                cost_model={"input_per_1k": 0.0, "output_per_1k": 0.0, "currency": "USD"},
                privacy_level=AgentPrivacyLevel.LOCAL_ONLY,
                connection_type=ConnectionType.LOCAL,
                config={
                    "adapter_type": "explore_agent",
                    "ollama_base_url": "http://localhost:11434",
                    "model_name": "qwen2.5:1.5b",
                    "personality": "小探",
                    "enable_tools": True,
                    "max_iterations": 5,
                    "temperature": 0.5,
                    "description": "小探研究助理 — 基于本地轻量大模型的信息检索专家。",
                },
                api_key="",
                license=LicenseType.MIT,
                confirm_license_risk=False,
            )
            registered_count += 1
            self._logger.info("federation_agent_registered", agent="explore", model="qwen2.5:1.5b")
        except Exception as e:
            self._logger.warning("federation_agent_register_failed", agent="explore", error=str(e))

        # 4. 潮汐管家（M5 记忆系统，qwen2.5:3b）
        try:
            fed_registry.register_agent(
                display_name="潮汐管家",
                provider="Tide",
                agent_type=ExternalAgentType.CUSTOM,
                capabilities=["记忆检索", "记忆归档", "记忆巩固", "人格偏好管理", "记忆统计分析",
                              "四层潮汐存储", "RBAC权限控制", "加密存储", "情绪记忆", "睡眠巩固"],
                cost_model={"input_per_1k": 0.0, "output_per_1k": 0.0, "currency": "USD"},
                privacy_level=AgentPrivacyLevel.LOCAL_ONLY,
                connection_type=ConnectionType.LOCAL,
                config={
                    "adapter_type": "tide_agent",
                    "m5_base_url": "http://localhost:8005",
                    "ollama_base_url": "http://localhost:11434",
                    "model_name": "qwen2.5:3b",
                    "default_domain": "private",
                    "default_layers": ["l1_shallow", "l2_deep"],
                    "enable_llm_enhance": True,
                    "temperature": 0.3,
                    "description": "潮汐管家 — M5 潮汐记忆系统的智能代理。",
                },
                api_key="",
                license=LicenseType.MIT,
                confirm_license_risk=False,
            )
            registered_count += 1
            self._logger.info("federation_agent_registered", agent="tide", model="qwen2.5:3b")
        except Exception as e:
            self._logger.warning("federation_agent_register_failed", agent="tide", error=str(e))

        # 5. 云汐 人格润色（qwen2.5:1.5b）
        try:
            fed_registry.register_agent(
                display_name="云汐 人格润色",
                provider="Voice",
                agent_type=ExternalAgentType.CUSTOM,
                capabilities=["人格润色", "语气调节", "场景适配", "情感表达", "质量自检",
                              "红线检测", "用户偏好管理", "多场景切换", "本地推理", "零API成本"],
                cost_model={"input_per_1k": 0.0, "output_per_1k": 0.0, "currency": "USD"},
                privacy_level=AgentPrivacyLevel.LOCAL_ONLY,
                connection_type=ConnectionType.LOCAL,
                config={
                    "adapter_type": "voice_agent",
                    "ollama_base_url": "http://localhost:11434",
                    "model_name": "qwen2.5:1.5b",
                    "personality_config_path": "config/yunxi_personality.yaml",
                    "default_scene": "work_dev",
                    "default_tone": "default",
                    "enable_m5_persistence": False,
                    "temperature": 0.7,
                    "description": "云汐人格润色 Agent — 负责输出层的语气化妆。",
                },
                api_key="",
                license=LicenseType.MIT,
                confirm_license_risk=False,
            )
            registered_count += 1
            self._logger.info("federation_agent_registered", agent="voice", model="qwen2.5:1.5b")
        except Exception as e:
            self._logger.warning("federation_agent_register_failed", agent="voice", error=str(e))

        # 6. 云汐总管（M8 运维平台）
        try:
            module_addresses = {
                "m1": "http://localhost:8001",
                "m2": "http://localhost:8002",
                "m3": "http://localhost:8003",
                "m4": "http://localhost:8004",
                "m5": "http://localhost:8005",
                "m6": "http://localhost:8006",
                "m7": "http://localhost:8007",
                "m8": "http://localhost:8008",
            }
            fed_registry.register_agent(
                display_name="云汐总管",
                provider="ModuleManager",
                agent_type=ExternalAgentType.CUSTOM,
                capabilities=["健康监控", "性能指标", "配置管理", "版本升级", "升级回滚",
                              "自动化测试", "多模块统一管控", "M8标准接口", "全局运维视图", "异常告警"],
                cost_model={"input_per_1k": 0.0, "output_per_1k": 0.0, "currency": "CNY"},
                privacy_level=AgentPrivacyLevel.LOCAL_ONLY,
                connection_type=ConnectionType.LOCAL,
                config={
                    "adapter_type": "module_manager_agent",
                    "module_addresses": module_addresses,
                    "m8_token": "",
                    "default_base_url": "http://localhost",
                    "request_timeout": 10.0,
                    "parallel_limit": 4,
                    "description": "云汐总管 — M8 模块管理平台的智能代理。",
                },
                api_key="",
                license=LicenseType.MIT,
                confirm_license_risk=False,
            )
            registered_count += 1
            self._logger.info("federation_agent_registered", agent="module_manager", modules=8)
        except Exception as e:
            self._logger.warning("federation_agent_register_failed", agent="module_manager", error=str(e))

        # ── 模块管家 Agent ──────────────────────────────────

        module_agents = [
            {
                "key": "m2", "name": "技能管家", "provider": "SkillManager",
                "port": 8002, "model": "qwen2.5:1.5b",
                "capabilities": ["技能检索", "技能推荐", "技能注册", "版本管理", "沙箱管理",
                                 "技能发现", "技能评测", "流水线管理"],
                "description": "技能管家 — M2 技能集群的管理专家。",
                "url_key": "m2_base_url",
            },
            {
                "key": "m3", "name": "推理管家", "provider": "InferenceManager",
                "port": 8003, "model": "qwen2.5:1.5b",
                "capabilities": ["模型管理", "VRAM监控", "端云调度", "推理路由", "负载均衡",
                                 "缓存管理", "性能优化", "离线缓存"],
                "description": "推理管家 — M3 端云协同推理的调度专家。",
                "url_key": "m3_base_url",
            },
            {
                "key": "m4", "name": "场景管家", "provider": "SceneManager",
                "port": 8004, "model": "qwen2.5:1.5b",
                "capabilities": ["场景识别", "场景切换", "上下文管理", "场景配置", "模式切换",
                                 "状态管理", "工作模式", "生活模式"],
                "description": "场景管家 — M4 场景引擎的调度师。",
                "url_key": "m4_base_url",
            },
            {
                "key": "m6", "name": "创意管家", "provider": "ContentManager",
                "port": 8006, "model": "qwen2.5:1.5b",
                "capabilities": ["文案生成", "创意构思", "内容排版", "图片描述", "多媒体处理",
                                 "硬件感知", "灵感推荐", "风格调整"],
                "description": "创意管家 — M6 创意内容的设计师。",
                "url_key": "m6_base_url",
            },
            {
                "key": "m7", "name": "安全管家", "provider": "SecurityManager",
                "port": 8007, "model": "qwen2.5:1.5b",
                "capabilities": ["安全审计", "隐私保护", "权限管理", "威胁检测", "数据脱敏",
                                 "积木沙箱", "访问控制", "安全扫描"],
                "description": "安全管家 — M7 安全防护的守护官。",
                "url_key": "m7_base_url",
            },
        ]

        for ma in module_agents:
            try:
                config = {
                    "adapter_type": f"{ma['provider'].lower()}_agent",
                    ma["url_key"]: f"http://localhost:{ma['port']}",
                    "ollama_base_url": "http://localhost:11434",
                    "model_name": ma["model"],
                    "enable_llm": True,
                    "temperature": 0.7,
                    "description": ma["description"],
                }
                fed_registry.register_agent(
                    display_name=ma["name"],
                    provider=ma["provider"],
                    agent_type=ExternalAgentType.CUSTOM,
                    capabilities=ma["capabilities"],
                    cost_model={"input_per_1k": 0.0, "output_per_1k": 0.0, "currency": "USD"},
                    privacy_level=AgentPrivacyLevel.LOCAL_ONLY,
                    connection_type=ConnectionType.LOCAL,
                    config=config,
                    api_key="",
                    license=LicenseType.MIT,
                    confirm_license_risk=False,
                )
                registered_count += 1
                self._logger.info("federation_agent_registered", agent=ma["key"], name=ma["name"])
            except Exception as e:
                self._logger.warning(
                    "federation_agent_register_failed",
                    agent=ma.get("key", "unknown"),
                    error=str(e),
                )

        self._logger.info(
            "federation_system_initialized",
            total_agents=registered_count,
            scheduler="federated",
        )

    def _register_lifecycle(
        self,
        bus: MessageBus,
        registry: AgentRegistry,
        persistence: SQLitePersistence,
        v9: OrchestratorV9,
    ) -> None:
        """注册生命周期钩子"""

        async def start_plugins() -> None:
            # 优先使用 V5 的 plugin_loader 加载（如果存在）
            plugin_loader = getattr(v9, "_plugin_loader", None)
            if plugin_loader is None:
                # 从 V9 逐层向下找 plugin_loader
                v8 = getattr(v9, "_v8", None)
                v7 = getattr(v8, "_v7", None) if v8 else None
                v5 = getattr(v7, "_v5", None) if v7 else None
                plugin_loader = getattr(v5, "_plugin_loader", None) if v5 else None

            if plugin_loader is not None:
                try:
                    # 调试：打印 plugin_dir 和扫描到的文件
                    plugin_dir = getattr(plugin_loader, "plugin_dir", None)
                    scanned = plugin_loader.scan() if hasattr(plugin_loader, "scan") else []
                    logger.info(
                        "plugin_loader_debug",
                        plugin_dir=str(plugin_dir),
                        scanned_files=[f.name for f in scanned],
                    )
                    loaded = await plugin_loader.load_all(registry)
                    logger.info("plugins_loaded", count=len(loaded))
                except Exception as e:
                    logger.error("plugin_load_failed", error=str(e))
                    import traceback
                    logger.error("plugin_load_traceback", traceback=traceback.format_exc())
            else:
                logger.warning("plugin_loader_not_found")

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
            federation_registry=self._federation_registry,
            federation_scheduler=self._federation_scheduler,
            cost_controller=self._cost_controller,
            privacy_guard=self._privacy_guard,
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
