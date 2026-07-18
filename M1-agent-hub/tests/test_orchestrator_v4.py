"""
测试：OrchestratorV4 整合编排器
"""

import pytest
import sys
import asyncio
from unittest.mock import AsyncMock, MagicMock
from interfaces import AgentTask, AgentResult, IAgentPlugin
from agent_registry import AgentRegistry
from task_dispatcher import TaskDispatcher
from intent_classifier_v2 import SemanticIntentClassifier
from orchestrator_v2 import OrchestratorV2
from orchestrator_v3 import OrchestratorV3
from orchestrator_v4 import OrchestratorV4
from event_store import EventStore
from streaming_engine import StreamingEngine
from llm_provider import MockLLMProvider
from circuit_breaker import CircuitBreakerRegistry
from persistence import SQLitePersistence
from streaming_engine import StreamChunkType


class DummyAgent(IAgentPlugin):
    agent_id: str = "agent.dummy"
    version: str = "1.0.0"
    capabilities: list[str] = ["dummy.capability"]

    async def handle_task(self, task: AgentTask) -> AgentResult:
        return AgentResult(
            task_id=task.task_id,
            trace_id=task.trace_id,
            agent_id=self.agent_id,
            status="success",
            output={"reply": f"Dummy reply to: {task.payload.get('user_input', '')}"},
            latency_ms=10.0,
        )


class MasterFallbackAgent(IAgentPlugin):
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
def v4_orchestrator():
    registry = AgentRegistry()
    bus = MagicMock()
    bus.publish = AsyncMock()
    dispatcher = TaskDispatcher(registry, bus)
    classifier = SemanticIntentClassifier()
    v2 = OrchestratorV2(registry, dispatcher, classifier=classifier)
    v3 = OrchestratorV3(v2)

    dummy = DummyAgent()
    master = MasterFallbackAgent()
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

    yield v4

    persistence.close()


@pytest.mark.asyncio
async def test_v4_process(v4_orchestrator):
    result = await v4_orchestrator.process("测试消息", trace_id="trace_test")
    assert "reply" in result
    assert result["status"] in ("success", "error", "fallback")


@pytest.mark.asyncio
async def test_v4_process_stream(v4_orchestrator):
    chunks = []
    async for chunk in v4_orchestrator.process_stream("测试消息", trace_id="trace_stream"):
        chunks.append(chunk)

    assert len(chunks) > 0
    assert any(c.chunk_type == StreamChunkType.DONE for c in chunks)


@pytest.mark.asyncio
async def test_v4_event_store(v4_orchestrator):
    await v4_orchestrator.process("测试事件", trace_id="trace_event")
    events = v4_orchestrator._events.get_by_trace("trace_event")
    assert len(events) >= 1
    assert any(e.event_type.value == "user.input_received" for e in events)


@pytest.mark.asyncio
async def test_v4_circuit_breaker(v4_orchestrator):
    # 多次调用应正常工作
    for i in range(3):
        result = await v4_orchestrator.process(f"消息{i}")
        assert "reply" in result

    stats = v4_orchestrator._breakers.get_all_stats()
    assert len(stats) > 0


@pytest.mark.asyncio
async def test_v4_persistence(v4_orchestrator):
    await v4_orchestrator.process("测试持久化", trace_id="trace_persist")

    # 检查事件是否被持久化
    persisted_events = v4_orchestrator._persistence.load_events(trace_id="trace_persist")
    assert len(persisted_events) >= 1


@pytest.mark.asyncio
async def test_v4_feedback(v4_orchestrator):
    v4_orchestrator.submit_feedback(
        trace_id="trace_fb",
        agent_id="agent.dummy",
        intent="test",
        rating=5,
        comment="不错",
    )

    feedbacks = v4_orchestrator._persistence.load_feedbacks(agent_id="agent.dummy")
    assert len(feedbacks) == 1
    assert feedbacks[0]["rating"] == 5


@pytest.mark.asyncio
async def test_v4_diagnose(v4_orchestrator):
    diag = v4_orchestrator.diagnose()
    assert "v4" in diag
    assert "event_store_stats" in diag["v4"]
    assert "circuit_breaker_stats" in diag["v4"]


@pytest.mark.asyncio
async def test_v4_llm_generate(v4_orchestrator):
    text = await v4_orchestrator.generate_with_llm("hello")
    assert len(text) > 0


@pytest.mark.asyncio
async def test_v4_llm_generate_stream(v4_orchestrator):
    chunks = []
    async for chunk in v4_orchestrator.generate_with_llm_stream("hello"):
        chunks.append(chunk)

    assert len(chunks) > 0
