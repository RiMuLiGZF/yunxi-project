"""OrchestratorV2 整合编排器单元测试"""
import sys
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from agent_cluster.orchestration.orchestrator_v2 import OrchestratorV2
from agent_cluster.agents.agent_registry import AgentRegistry
from agent_cluster.core.task_dispatcher import TaskDispatcher
from agent_cluster.core.intent_classifier_v2 import SemanticIntentClassifier
from agent_cluster.security.guardrail_pipeline import GuardrailPipeline, KeywordBlockGuardrail
from agent_cluster.observability.tracing import Tracer
from agent_cluster.agents.agent_card import AgentCardRegistry
from agent_cluster.tools.interfaces import AgentTask, AgentResult, IAgentPlugin
from agent_cluster.orchestration.workflow_engine import WorkflowDefinition, WorkflowState, AgentNode


class DummyAgent(IAgentPlugin):
    agent_id = "agent.dummy"
    version = "1.0"
    capabilities = ["dummy.do"]

    async def handle_task(self, task: AgentTask) -> AgentResult:
        return AgentResult(
            task_id=task.task_id,
            trace_id=task.trace_id,
            agent_id=self.agent_id,
            status="success",
            output={"reply": f"dummy processed: {task.payload.get('user_input', '')}"},
        )


class NoteMockAgent(IAgentPlugin):
    agent_id = "agent.note"
    version = "1.0"
    capabilities = ["note.create", "note.search"]

    async def handle_task(self, task: AgentTask) -> AgentResult:
        return AgentResult(
            task_id=task.task_id,
            trace_id=task.trace_id,
            agent_id=self.agent_id,
            status="success",
            output={"reply": "笔记已记录"},
        )


class MasterAgent(IAgentPlugin):
    agent_id = "master_scheduler"
    version = "1.0"
    capabilities = ["general.fallback", "general.system"]

    async def handle_task(self, task: AgentTask) -> AgentResult:
        return AgentResult(
            task_id=task.task_id,
            trace_id=task.trace_id,
            agent_id=self.agent_id,
            status="success",
            output={"reply": "fallback reply"},
        )


@pytest.fixture
def registry():
    return AgentRegistry()


@pytest.fixture
def dispatcher(registry):
    bus = MagicMock()
    bus.publish = AsyncMock()
    return TaskDispatcher(registry, bus)


@pytest.fixture
def orchestrator(registry, dispatcher):
    orch = OrchestratorV2(registry, dispatcher)
    return orch


@pytest.mark.asyncio
async def test_process_direct_route(orchestrator, registry, dispatcher):
    """测试高置信度直接路由"""
    agent = NoteMockAgent()
    await registry.register(agent)
    orchestrator.register_agent_card(agent)

    result = await orchestrator.process("记笔记", enable_guardrails=False)
    assert result["status"] == "success"
    assert result["trace_id"]
    assert "trace_summary" in result
    assert result["trace_summary"]["span_count"] > 0


@pytest.mark.asyncio
async def test_process_confirm_route(orchestrator):
    """测试中置信度确认路由"""
    result = await orchestrator.process("做个笔记吧", enable_guardrails=False)
    assert result["status"] == "confirm"
    assert "需要我帮你处理吗" in result["reply"]


@pytest.mark.asyncio
async def test_process_fallback_route(orchestrator):
    """测试低置信度 fallback 路由"""
    result = await orchestrator.process("完全不相关的 xyz", enable_guardrails=False)
    assert result["status"] == "fallback"
    assert "不太理解" in result["reply"]


@pytest.mark.asyncio
async def test_process_with_guardrails_input_block(orchestrator):
    """测试输入护栏拦截"""
    pipeline = GuardrailPipeline("strict")
    pipeline.add_input_guardrail(KeywordBlockGuardrail(blocklist=["赌博"]))
    orchestrator._guardrails = pipeline

    result = await orchestrator.process("我们来赌博吧")
    assert result["status"] == "blocked"
    assert "安全策略拦截" in result["reply"]


@pytest.mark.asyncio
async def test_process_with_guardrails_output_sanitize(orchestrator, registry, dispatcher):
    """测试输出护栏脱敏"""
    agent = NoteMockAgent()
    await registry.register(agent)
    orchestrator.register_agent_card(agent)

    result = await orchestrator.process("记笔记", enable_guardrails=True)
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_process_tracing_enabled(orchestrator, registry, dispatcher):
    """测试追踪记录"""
    agent = NoteMockAgent()
    await registry.register(agent)
    orchestrator.register_agent_card(agent)

    result = await orchestrator.process("记笔记")
    trace_id = result["trace_id"]
    trace = orchestrator.get_trace(trace_id)
    assert trace is not None
    assert trace.duration_ms >= 0


@pytest.mark.asyncio
async def test_process_agent_failure_degradation(orchestrator, registry, dispatcher):
    """测试 Agent 失败降级"""
    class FailingAgent(IAgentPlugin):
        agent_id = "agent.failing"
        version = "1.0"
        capabilities = ["failing.do"]

        async def handle_task(self, task: AgentTask) -> AgentResult:
            return AgentResult(
                task_id=task.task_id,
                trace_id=task.trace_id,
                agent_id=self.agent_id,
                status="failure",
                error="always fails",
            )

    failing = FailingAgent()
    master = MasterAgent()
    await registry.register(failing)
    await registry.register(master)
    orchestrator.register_agent_card(failing)
    orchestrator.register_agent_card(master)

    result = await orchestrator.process("复盘总结", enable_guardrails=False)
    # 失败降级逻辑


@pytest.mark.asyncio
async def test_build_chain_workflow(orchestrator, registry):
    agent1 = DummyAgent()
    agent2 = DummyAgent()
    agent2.agent_id = "agent.dummy2"
    await registry.register(agent1)
    await registry.register(agent2)

    wf = orchestrator.build_chain_workflow("test_chain", [
        (agent1, "dummy.do"),
        (agent2, "dummy.do"),
    ])
    assert wf.entry_node == "node_0"
    assert len(wf.nodes) == 2
    assert "node_0" in wf._node_outgoing
    assert "node_1" in wf._node_incoming


@pytest.mark.asyncio
async def test_execute_workflow(orchestrator, registry):
    agent = DummyAgent()
    await registry.register(agent)

    wf = WorkflowDefinition("simple")
    wf.add_node(AgentNode("a1", agent, "dummy.do"))
    wf.set_entry("a1")

    result = await orchestrator.execute_workflow(wf, WorkflowState(user_input="hi"))
    assert result.is_success
    assert result.final_state.node_outputs["a1"]["status"] == "success"


@pytest.mark.asyncio
async def test_discover_agents(orchestrator, registry):
    agent = DummyAgent()
    await registry.register(agent)
    orchestrator.register_agent_card(agent, tags=["test"])

    results = orchestrator.discover_agents("dummy")
    assert len(results) >= 1


@pytest.mark.asyncio
async def test_register_agent_card(orchestrator, registry):
    agent = DummyAgent()
    await registry.register(agent)
    orchestrator.register_agent_card(agent, description="test agent", tags=["test"])

    card = orchestrator._card_registry.get("agent.dummy")
    assert card is not None
    assert card.description == "test agent"
    assert "test" in card.tags


@pytest.mark.asyncio
async def test_process_trace_summary(orchestrator, registry, dispatcher):
    """测试 trace_summary 包含正确信息"""
    agent = NoteMockAgent()
    await registry.register(agent)
    orchestrator.register_agent_card(agent)

    result = await orchestrator.process("记笔记", enable_guardrails=False)
    summary = result.get("trace_summary")
    assert summary is not None
    assert "duration_ms" in summary
    assert "span_count" in summary
    assert isinstance(summary["is_success"], bool)
