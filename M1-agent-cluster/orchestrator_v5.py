"""
云汐内核 V5 - 整合编排器

在 V4 基础上集成 V5 核心能力：
- 配置中心（ConfigManager）：所有参数外部化、热重载
- 向量记忆（VectorMemory）：语义相似度检索
- 插件热加载（PluginLoader）：运行时动态加载 Agent
- MCP 服务端（MCPServer）：暴露标准 MCP Tools

提供可配置、可扩展、可对接外部生态的 Agent 集群调度中枢。
"""

from __future__ import annotations

import time
from typing import Any, AsyncIterator

import structlog

from orchestrator_v4 import OrchestratorV4
from config_manager import ConfigManager
from vector_memory import VectorMemory
from plugin_loader import PluginLoader, PluginContext
from mcp_server import MCPServer

logger = structlog.get_logger(__name__)


class OrchestratorV5:
    """V5 整合编排器

    在 V4 基础上增加：
    1. 配置驱动：所有组件参数从 ConfigManager 读取
    2. 向量记忆：语义检索增强 LTM
    3. 插件系统：运行时热加载 Agent
    4. MCP 服务：对外暴露标准工具协议
    """

    def __init__(
        self,
        orchestrator_v4: OrchestratorV4,
        config: ConfigManager | None = None,
        vector_memory: VectorMemory | None = None,
        plugin_loader: PluginLoader | None = None,
        mcp_server: MCPServer | None = None,
    ) -> None:
        self._v4 = orchestrator_v4
        self._config = config or ConfigManager()
        self._vector_memory = vector_memory or VectorMemory(
            dimension=self._config.get_int("vector_memory.dimension", 128),
        )
        self._plugin_loader = plugin_loader or PluginLoader(
            plugin_dir=self._config.get_str("plugin_loader.plugin_dir", "./plugins"),
            watch_interval=self._config.get_float("plugin_loader.watch_interval", 10.0),
            auto_reload=self._config.get_bool("plugin_loader.auto_reload", True),
        )
        self._mcp_server = mcp_server
        self._logger = logger.bind(service="orchestrator_v5")

        # 初始化插件上下文
        registry = getattr(self._v4._v3._v2, "_registry", None)
        self._plugin_loader.set_context(
            PluginContext(
                registry=registry,
                config=self._config,
                event_store=self._v4._events,
            )
        )

    # ── 核心入口 ────────────────────────────────────────

    async def process(
        self,
        user_input: str,
        trace_id: str | None = None,
        enable_guardrails: bool = True,
        enable_tracing: bool = True,
        enable_memory: bool = True,
        enable_reflection: bool = True,
        use_llm: bool = False,
        use_vector_memory: bool = True,
        override_intent: dict | None = None,
    ) -> dict[str, Any]:
        """处理用户请求（V5 增强版）

        流程：
        1. 配置热重载检查
        2. 插件热重载检查
        3. 向量记忆语义检索（注入上下文）
        4. V4 处理
        5. 将结果写入向量记忆

        Args:
            override_intent: [P2-003] V9/V8/V7 下发的 V3 意图覆盖，透传至 V2。
        """
        # 1. 配置热重载
        self._config.check_reload()

        # 2. 插件热重载
        registry = getattr(self._v4._v3._v2, "_registry", None)
        await self._plugin_loader.check_reload(registry)

        trace_id = trace_id or f"trace_{int(time.time() * 1000)}"

        # 3. 向量记忆语义检索
        memory_context = ""
        if use_vector_memory and enable_memory:
            similar = await self._vector_memory.search_similar(
                query=user_input,
                top_k=self._config.get_int("vector_memory.top_k", 5),
                threshold=self._config.get_float("vector_memory.similarity_threshold", 0.5),
            )
            if similar:
                memory_context = "\n".join(
                    f"[记忆] {s['content']} (相似度: {s['similarity']})"
                    for s in similar
                )
                self._logger.debug("vector_memory_enhanced", trace_id=trace_id, hits=len(similar))

        # 如果有记忆上下文，注入到用户输入
        enhanced_input = user_input
        if memory_context:
            enhanced_input = f"{user_input}\n\n相关记忆上下文：\n{memory_context}"

        # 4. V4 处理
        result = await self._v4.process(
            user_input=enhanced_input,
            trace_id=trace_id,
            enable_guardrails=enable_guardrails,
            enable_tracing=enable_tracing,
            enable_memory=enable_memory,
            enable_reflection=enable_reflection,
            use_llm=use_llm,
            override_intent=override_intent,
        )

        # 5. 将本次交互写入向量记忆
        if use_vector_memory and enable_memory:
            await self._vector_memory.add(
                content=f"用户: {user_input}\n回复: {result.get('reply', '')}",
                memory_type="conversation",
                source="orchestrator_v5",
                importance=0.6,
                metadata={"trace_id": trace_id, "status": result.get("status", "")},
            )

        return result

    async def process_stream(
        self,
        user_input: str,
        trace_id: str | None = None,
        enable_guardrails: bool = True,
        enable_tracing: bool = True,
        enable_memory: bool = True,
        enable_reflection: bool = True,
        use_llm: bool = False,
        use_vector_memory: bool = True,
    ) -> AsyncIterator[Any]:
        """流式处理用户请求（V5 增强版）"""
        # 配置热重载
        self._config.check_reload()

        # 插件热重载
        registry = getattr(self._v4._v3._v2, "_registry", None)
        await self._plugin_loader.check_reload(registry)

        trace_id = trace_id or f"trace_{int(time.time() * 1000)}"

        # 向量记忆增强
        memory_context = ""
        if use_vector_memory and enable_memory:
            similar = await self._vector_memory.search_similar(
                query=user_input,
                top_k=self._config.get_int("vector_memory.top_k", 5),
                threshold=self._config.get_float("vector_memory.similarity_threshold", 0.5),
            )
            if similar:
                memory_context = "\n".join(
                    f"[记忆] {s['content']} (相似度: {s['similarity']})"
                    for s in similar
                )

        enhanced_input = user_input
        if memory_context:
            enhanced_input = f"{user_input}\n\n相关记忆上下文：\n{memory_context}"

        # 委托给 V4 流式处理
        async for chunk in self._v4.process_stream(
            user_input=enhanced_input,
            trace_id=trace_id,
            enable_guardrails=enable_guardrails,
            enable_tracing=enable_tracing,
            enable_memory=enable_memory,
            enable_reflection=enable_reflection,
            use_llm=use_llm,
        ):
            yield chunk

        # 写入向量记忆
        if use_vector_memory and enable_memory:
            await self._vector_memory.add(
                content=f"用户: {user_input}",
                memory_type="conversation",
                source="orchestrator_v5",
                importance=0.6,
                metadata={"trace_id": trace_id},
            )

    # ── 插件管理 ────────────────────────────────────────

    async def load_plugins(self) -> list[Any]:
        """加载所有插件"""
        registry = getattr(self._v4._v3._v2, "_registry", None)
        return await self._plugin_loader.load_all(registry)

    def list_plugins(self) -> list[str]:
        """列出已加载的插件 Agent"""
        return self._plugin_loader.list_loaded()

    # ── 向量记忆管理 ────────────────────────────────────

    async def add_to_vector_memory(
        self,
        content: str,
        memory_type: str = "generic",
        importance: float = 0.5,
    ) -> Any:
        """手动添加内容到向量记忆"""
        return await self._vector_memory.add(
            content=content,
            memory_type=memory_type,
            importance=importance,
        )

    async def search_vector_memory(
        self,
        query: str,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """搜索向量记忆"""
        return await self._vector_memory.search_similar(query, top_k=top_k)

    # ── MCP 服务 ────────────────────────────────────────

    def get_mcp_server(self) -> MCPServer | None:
        """获取 MCP 服务端实例"""
        return self._mcp_server

    def start_mcp_stdio(self) -> None:
        """启动 MCP stdio 服务（阻塞式）"""
        if self._mcp_server is None:
            registry = getattr(self._v4._v3._v2, "_registry", None)
            self._mcp_server = MCPServer(registry)
        self._mcp_server.run_stdio()

    # ── 配置管理 ────────────────────────────────────────

    def get_config(self, key: str, default: Any = None) -> Any:
        """获取配置值"""
        return self._config.get(key, default)

    def set_config(self, key: str, value: Any) -> None:
        """运行时设置配置"""
        self._config.set(key, value)

    def export_config(self, path: str, format: str = "json") -> None:
        """导出配置到文件"""
        self._config.export_to_file(path, format)

    # ── 诊断 ────────────────────────────────────────────

    def diagnose(self) -> dict[str, Any]:
        """V5 增强诊断"""
        v4_diagnosis = self._v4.diagnose()
        return {
            **v4_diagnosis,
            "v5": {
                "config": self._config.to_dict(),
                "vector_memory_stats": self._vector_memory.stats(),
                "plugin_loader_stats": self._plugin_loader.stats(),
                "mcp_server": {
                    "enabled": self._mcp_server is not None,
                    "name": MCPServer.SERVER_NAME if self._mcp_server else None,
                },
            },
        }

    # ── V4/V3/V2/V1 能力透传（白名单） ────────────────

    def __getattr__(self, name: str) -> Any:
        """透传 V4 的已知方法"""
        allowed = {
            "submit_feedback", "generate_with_llm", "generate_with_llm_stream",
            "register_agent_card", "discover_agents", "get_trace", "list_traces",
            "build_chain_workflow", "build_parallel_workflow", "execute_workflow",
        }
        if name in allowed:
            return getattr(self._v4, name)
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")
