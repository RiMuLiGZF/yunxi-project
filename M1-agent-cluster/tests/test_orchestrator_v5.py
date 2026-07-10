"""
测试：OrchestratorV5 整合编排器
"""

import pytest
import sys
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, "/workspace/agent_cluster")

from interfaces import AgentTask, AgentResult, IAgentPlugin
from agent_registry import AgentRegistry
from task_dispatcher import TaskDispatcher
from intent_classifier_v2 import SemanticIntentClassifier
from orchestrator_v2 import OrchestratorV2
from orchestrator_v3 import OrchestratorV3
from orchestrator_v4 import OrchestratorV4
from orchestrator_v5 import OrchestratorV5
from config_manager import ConfigManager
from vector_memory import VectorMemory
from plugin_loader import PluginLoader
from mcp_server import MCPServer
from event_store import EventStore
from streaming_engine import StreamingEngine
from llm_provider import MockLLMProvider
from circuit_breaker import CircuitBreakerRegistry
from persistence import SQLitePersistence
from streaming_engine import StreamChunkType


class DummyV5Agent(IAgentPlugin):
    agent_id: str = "agent.dummy"
    version: str = "1.0.0"
    capabilities: list[str] = ["dummy.capability"]

    async def handle_task(self, task: AgentTask) -> AgentResult:
        return AgentResult(
            task_id=task.task_id,
            trace_id=task.trace_id,
            agent_id=self.agent_id,
            status="success",
            output={"reply": f"V5 reply: {task.payload.get('user_input', '')}"},
            latency_ms=10.0,
        )


class MasterFallbackV5(IAgentPlugin):
    agent_id: str = "master_scheduler"
    version: str = "1.0.0"
    capabilities: list[str] = ["general.fallback"]

    async def handle_task(self, task: AgentTask) -> AgentResult:
        return AgentResult(
            task_id=task.task_id,
            trace_id=task.trace_id,
            agent_id=self.agent_id,
            status="success",
            output={"reply": "fallback reply"},
            latency_ms=5.0,
        )


@pytest.fixture
def v5_orchestrator():
    registry = AgentRegistry()
    bus = MagicMock()
    bus.publish = AsyncMock()
    dispatcher = TaskDispatcher(registry, bus)
    classifier = SemanticIntentClassifier()
    v2 = OrchestratorV2(registry, dispatcher, classifier=classifier)
    v3 = OrchestratorV3(v2)

    dummy = DummyV5Agent()
    master = MasterFallbackV5()
    registry.register_sync(dummy)
    registry.register_sync(master)
    v2.register_agent_card(dummy, description="Dummy agent", tags=["test"])
    v2.register_agent_card(master, description="Master scheduler", tags=["system"])

    persistence = SQLitePersistence(":memory:")

    v4 = OrchestratorV4(
        orchestrator_v3=v3,
        event_store=EventStore(),
        streaming_engine=StreamingEngine(),
        llm_provider=MockLLMProvider(),
        circuit_breakers=CircuitBreakerRegistry(),
        persistence=persistence,
    )

    config = ConfigManager()
    vector_memory = VectorMemory(dimension=64)
    plugin_loader = PluginLoader(plugin_dir="./test_plugins", auto_reload=False)
    mcp_server = MCPServer(registry)

    v5 = OrchestratorV5(
        orchestrator_v4=v4,
        config=config,
        vector_memory=vector_memory,
        plugin_loader=plugin_loader,
        mcp_server=mcp_server,
    )

    yield v5

    persistence.close()


@pytest.mark.asyncio
async def test_v5_process(v5_orchestrator):
    result = await v5_orchestrator.process("测试消息", trace_id="trace_v5")
    assert "reply" in result
    assert result["status"] in ("success", "error", "fallback")


@pytest.mark.asyncio
async def test_v5_process_with_vector_memory(v5_orchestrator):
    # 先添加一些记忆
    await v5_orchestrator.add_to_vector_memory("用户喜欢咖啡", memory_type="preference", importance=0.9)

    # 查询应该能召回相关记忆
    result = await v5_orchestrator.process("他喜欢喝什么", trace_id="trace_v5_vm", use_vector_memory=True)
    assert "reply" in result


@pytest.mark.asyncio
async def test_v5_process_stream(v5_orchestrator):
    chunks = []
    async for chunk in v5_orchestrator.process_stream("测试流式", trace_id="trace_v5_stream"):
        chunks.append(chunk)

    assert len(chunks) > 0
    assert any(c.chunk_type == StreamChunkType.DONE for c in chunks)


@pytest.mark.asyncio
async def test_v5_vector_memory_search(v5_orchestrator):
    await v5_orchestrator.add_to_vector_memory("这是一个测试记忆", memory_type="test")
    results = await v5_orchestrator.search_vector_memory("这是一个测试记忆", top_k=3)
    assert len(results) > 0
    assert "similarity" in results[0]


@pytest.mark.asyncio
async def test_v5_config_management(v5_orchestrator):
    assert v5_orchestrator.get_config("llm.model") == "gpt-4o-mini"

    v5_orchestrator.set_config("custom.test_key", "test_value")
    assert v5_orchestrator.get_config("custom.test_key") == "test_value"


@pytest.mark.asyncio
async def test_v5_load_plugins(v5_orchestrator):
    agents = await v5_orchestrator.load_plugins()
    # 测试插件目录为空，应返回空列表
    assert isinstance(agents, list)


@pytest.mark.asyncio
async def test_v5_list_plugins(v5_orchestrator):
    plugins = v5_orchestrator.list_plugins()
    assert isinstance(plugins, list)


def test_v5_diagnose(v5_orchestrator):
    diag = v5_orchestrator.diagnose()
    assert "v5" in diag
    assert "vector_memory_stats" in diag["v5"]
    assert "plugin_loader_stats" in diag["v5"]
    assert "mcp_server" in diag["v5"]


def test_v5_mcp_server(v5_orchestrator):
    mcp = v5_orchestrator.get_mcp_server()
    assert mcp is not None

    # 测试 MCP 初始化
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"clientInfo": {"name": "test", "version": "1.0"}},
    }
    resp = mcp.handle_message(req)
    assert resp is not None
    assert resp["result"]["serverInfo"]["name"] == "yunxi-core-mcp"


def test_v5_config_export(v5_orchestrator, tmp_path):
    path = tmp_path / "config.json"
    v5_orchestrator.export_config(str(path), "json")
    assert path.exists()
