from __future__ import annotations

"""Agent Runtime 单元测试."""

import pytest

from skill_cluster.agent_runtime import AgentRegistry, AgentRuntime
from skill_cluster.interfaces import SkillInvokeRequest, SkillInvokeResult


def test_create_agent() -> None:
    runtime = AgentRuntime()
    agent = runtime.create_agent("TestAgent", "测试 Agent")
    assert agent.name == "TestAgent"
    assert agent.description == "测试 Agent"
    assert agent.status == "idle"
    assert agent.agent_id.startswith("agent_")


def test_bind_skills() -> None:
    runtime = AgentRuntime()
    agent = runtime.create_agent("TestAgent")
    runtime.bind_skills(agent.agent_id, ["skill.a", "skill.b"])

    skills = runtime.get_available_skills(agent.agent_id)
    assert sorted(skills) == ["skill.a", "skill.b"]


def test_agent_registry_bind_unbind() -> None:
    registry = AgentRegistry()
    from skill_cluster.agent_runtime import AgentState

    state = AgentState(agent_id="a1", name="Test")
    registry.register(state)

    assert registry.bind_skill("a1", "skill.x") is True
    assert registry.get_bound_skills("a1") == ["skill.x"]

    assert registry.unbind_skill("a1", "skill.x") is True
    assert registry.get_bound_skills("a1") == []


def test_agent_memory() -> None:
    registry = AgentRegistry()
    from skill_cluster.agent_runtime import AgentState

    state = AgentState(agent_id="a1", name="Test")
    registry.register(state)

    registry.update_memory("a1", "key1", {"data": "value"})
    agent = registry.get("a1")
    assert agent.memory_context["key1"] == {"data": "value"}


def test_inject_agent_context() -> None:
    runtime = AgentRuntime()
    agent = runtime.create_agent("TestAgent")
    runtime._registry.update_memory(agent.agent_id, "session_id", "sess_123")

    request = SkillInvokeRequest(
        skill_id="skill.test",
        action="test",
        params={"x": 1},
        trace_id="t1",
    )
    injected = runtime.inject_agent_context(request, agent.agent_id)

    assert injected.params["session_id"] == "sess_123"
    assert injected.params["x"] == 1
    assert injected.params["__agent_id"] == agent.agent_id
    assert injected.params["__agent_name"] == "TestAgent"


@pytest.mark.asyncio
async def test_run_skill() -> None:
    runtime = AgentRuntime()
    agent = runtime.create_agent("TestAgent")

    async def mock_invoke(request: SkillInvokeRequest, agent_id: str) -> SkillInvokeResult:
        return SkillInvokeResult(
            skill_id="skill.test",
            action="test",
            status="success",
            data={"result": "ok"},
            latency_ms=0.0,
            trace_id="t1",
        )

    result = await runtime.run_skill(
        agent.agent_id, "skill.test", "test", {}, mock_invoke
    )

    assert result.status == "success"
    assert result.data == {"result": "ok"}

    # 验证 Agent 状态被重置为 idle
    updated = runtime.get_agent(agent.agent_id)
    assert updated.status == "idle"

    # 验证结果被写入记忆
    assert updated.memory_context.get("last_result:skill.test:test") == {"result": "ok"}


def test_get_all_agents() -> None:
    runtime = AgentRuntime()
    runtime.create_agent("AgentA")
    runtime.create_agent("AgentB")
    agents = runtime.get_all_agents()
    assert len(agents) == 2
