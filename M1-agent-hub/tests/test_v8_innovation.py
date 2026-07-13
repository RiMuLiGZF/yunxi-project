"""
测试：Swarm + Trace-to-Memory + 失败复盘 + 模型轮换 + V8 编排器
"""

import pytest
import sys
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, "/workspace/agent_cluster")

from swarm_and_innovation import (
    SwarmManager, TraceToMemory, RetrospectiveEngine,
    ModelRotationManager, ModelInfo, FailureType,
)
from orchestrator_v8 import OrchestratorV8
from ensemble_engine import EnsembleStrategy


# ═════════════ SwarmManager ═════════════


def test_swarm_recommend_no_history():
    sm = SwarmManager()
    team = sm.recommend_team("writing", ["a1", "a2", "a3"], team_size=2)
    assert len(team) == 2
    assert team == ["a1", "a2"]  # 无历史时取前N个


def test_swarm_recommend_with_history():
    sm = SwarmManager()
    # 记录 (a1, a2) 成功3次
    for _ in range(3):
        sm.record_result(
            swarm_id=f"s_{_}", success=True, avg_latency_ms=100.0
        )
    # 覆盖 swarm agents
    sm._active_swarms = {}
    sm._history["default"] = []
    # 直接写入历史
    from swarm_and_innovation import SwarmRecord
    sm._history["test_task"] = [
        SwarmRecord(task_type="test_task", agent_ids=["a1", "a2"], success=True, avg_latency_ms=100),
        SwarmRecord(task_type="test_task", agent_ids=["a2", "a3"], success=True, avg_latency_ms=200),
        SwarmRecord(task_type="test_task", agent_ids=["a1", "a3"], success=False, avg_latency_ms=300),
    ]
    team = sm.recommend_team("test_task", ["a1", "a2", "a3"])
    # (a1,a2) 成功率 1.0，应优先
    assert set(team) == {"a1", "a2"}


def test_swarm_create_and_record():
    sm = SwarmManager()
    swarm = sm.create_swarm("coding", ["a1", "a2", "a3"])
    assert swarm.swarm_id.startswith("swarm_")
    assert swarm.coordinator == "a1"
    assert swarm.status == "active"

    sm.record_result(swarm.swarm_id, success=True, avg_latency_ms=150.0)
    assert swarm.status == "completed"

    stats = sm.stats()
    # completed swarm 仍在 active_swarms 中但 status 为 completed
    assert stats["active_swarms"] == 1


def test_swarm_dissolve():
    sm = SwarmManager()
    swarm = sm.create_swarm("test", ["a1"])
    sm.dissolve_swarm(swarm.swarm_id)
    assert swarm.status == "dissolved"
    assert sm.stats()["active_swarms"] == 0


# ═════════════ TraceToMemory ═════════════


def test_extract_from_empty_trace():
    t2m = TraceToMemory()
    memories = t2m.extract_from_trace({"spans": []})
    assert len(memories) == 0


def test_extract_guardrail_events():
    t2m = TraceToMemory()
    trace = {
        "trace_id": "t1",
        "spans": [
            {
                "name": "guardrail_check",
                "kind": "guardrail",
                "events": [
                    {"name": "guardrail_blocked", "attributes": {"rule": "keyword"}}
                ],
                "attributes": {},
            }
        ],
    }
    memories = t2m.extract_from_trace(trace)
    assert len(memories) == 1
    assert memories[0].memory_type == "guardrail_event"
    assert memories[0].importance == 0.8


def test_extract_agent_execution_summary():
    t2m = TraceToMemory()
    trace = {
        "trace_id": "t1",
        "spans": [
            {"name": "agent_a", "kind": "agent", "attributes": {"agent_id": "agent_a"}, "duration_ms": 100},
            {"name": "agent_b", "kind": "agent", "attributes": {"agent_id": "agent_b"}, "duration_ms": 200},
        ],
    }
    memories = t2m.extract_from_trace(trace)
    assert len(memories) == 1
    assert "agent_a" in memories[0].content
    assert memories[0].memory_type == "execution_summary"


def test_extract_ensemble_dissent():
    t2m = TraceToMemory()
    trace = {
        "trace_id": "t1",
        "spans": [
            {"name": "ensemble_vote", "kind": "custom", "attributes": {"dissent_count": 2}, "duration_ms": 50},
        ],
    }
    memories = t2m.extract_from_trace(trace)
    assert len(memories) == 1
    assert memories[0].memory_type == "ensemble_dissent"


def test_t2m_stats():
    t2m = TraceToMemory()
    stats = t2m.stats()
    assert stats["total_extracted"] == 0


# ═════════════ RetrospectiveEngine ═════════════


def test_analyze_timeout():
    re = RetrospectiveEngine()
    report = re.analyze("task_1", error="Request timeout after 30s", failed_agent="agent_a")
    assert report.failure_type == FailureType.TIMEOUT
    assert "TTL" in report.recommendation or "超时" in report.recommendation


def test_analyze_guardrail():
    re = RetrospectiveEngine()
    report = re.analyze("task_2", error="Guardrail blocked: sensitive keyword detected")
    assert report.failure_type == FailureType.GUARDRAIL_BLOCKED


def test_analyze_budget():
    re = RetrospectiveEngine()
    report = re.analyze("task_3", error="Budget exceeded: daily limit reached")
    assert report.failure_type == FailureType.BUDGET_EXCEEDED


def test_analyze_unknown():
    re = RetrospectiveEngine()
    report = re.analyze("task_4", error="something weird happened")
    assert report.failure_type == FailureType.UNKNOWN


def test_similar_failures():
    re = RetrospectiveEngine()
    re.analyze("t1", "timeout", failed_agent="a1")
    re.analyze("t2", "timeout", failed_agent="a1")
    report = re.analyze("t3", "timeout", failed_agent="a1")
    assert report.similar_failures == 2


def test_failure_patterns():
    re = RetrospectiveEngine()
    re.analyze("t1", "timeout")
    re.analyze("t2", "timeout")
    re.analyze("t3", "exception error")
    patterns = re.get_failure_patterns()
    assert patterns[0]["type"] == "timeout"
    assert patterns[0]["count"] == 2


# ═════════════ ModelRotationManager ═════════════


@pytest.mark.asyncio
async def test_model_rotation_acquire():
    mgr = ModelRotationManager(max_vram_mb=6000)
    mgr.register_model(ModelInfo(name="qwen2-7b", size_mb=5000, capabilities=["chat"]))
    mgr.register_model(ModelInfo(name="qwen2-3b", size_mb=2000, capabilities=["chat"]))

    assert await mgr.acquire("qwen2-7b") == "qwen2-7b"
    assert mgr.get_active() == "qwen2-7b"

    # 切换模型
    assert await mgr.acquire("qwen2-3b") == "qwen2-3b"
    assert mgr.get_active() == "qwen2-3b"


@pytest.mark.asyncio
async def test_model_rotation_same_model():
    mgr = ModelRotationManager()
    mgr.register_model(ModelInfo(name="m1", size_mb=100))
    assert await mgr.acquire("m1") == "m1"
    assert await mgr.acquire("m1") == "m1"  # 同模型，不重新加载


@pytest.mark.asyncio
async def test_model_rotation_too_large():
    mgr = ModelRotationManager(max_vram_mb=3000)
    mgr.register_model(ModelInfo(name="huge", size_mb=10000))
    assert await mgr.acquire("huge") is None


@pytest.mark.asyncio
async def test_model_rotation_select_for_capabilities():
    mgr = ModelRotationManager()
    mgr.register_model(ModelInfo(name="m1", capabilities=["chat"]))
    mgr.register_model(ModelInfo(name="m2", capabilities=["code", "chat"]))
    mgr.register_model(ModelInfo(name="m3", capabilities=["vision"]))

    # 模拟加载以建立 MRU 顺序
    await mgr.acquire("m1")
    await mgr.acquire("m2")
    await mgr.acquire("m3")

    result = mgr.select_model_for_context(["code"])
    assert result == "m2"

    result = mgr.select_model_for_context(["vision"])
    assert result == "m3"


def test_model_rotation_stats():
    mgr = ModelRotationManager()
    mgr.register_model(ModelInfo(name="m1"))
    stats = mgr.stats()
    assert "m1" in stats["registered_models"]


# ═════════════ OrchestratorV8 ═════════════


@pytest.mark.asyncio
async def test_v8_diagnose():
    v7_mock = MagicMock()
    v7_mock.diagnose = MagicMock(return_value={"v7": {"test": True}})
    v7_mock.process = AsyncMock(return_value={"reply": "ok", "status": "success"})

    # Mock the internal tracer chain
    class FakeV4:
        _events = MagicMock()
        class _FakeV3:
            class _FakeV2:
                _tracer = MagicMock()
                _registry = MagicMock()
            _v2 = _FakeV2()
        _v3 = _FakeV3()
    v7_mock._v5 = MagicMock()
    v7_mock._v5._v4 = FakeV4()

    v8 = OrchestratorV8(v7_mock)
    diag = v8.diagnose()
    assert "v7" in diag
    assert "v8" in diag
    assert "loop_guard" in diag["v8"]
    assert "checkpointer" in diag["v8"]
    assert "swarm" in diag["v8"]
    assert "retrospective" in diag["v8"]


@pytest.mark.asyncio
async def test_v8_route_by_load():
    v7_mock = MagicMock()
    v8 = OrchestratorV8(v7_mock)
    # 注册一些 agent
    class FakeAgent:
        def __init__(self, aid):
            self.agent_id = aid
            self.version = "1.0"
            self.capabilities = []

    await v8._registry.register(FakeAgent("a1"), "general")

    result = v8.route_by_load("general")
    assert result == "a1"


@pytest.mark.asyncio
async def test_v8_filter_memories():
    v7_mock = MagicMock()
    v8 = OrchestratorV8(v7_mock)
    guest = MagicMock()
    guest.agent_id = "guest_1"
    guest.role = "guest"
    guest.team = ""

    from rbac_memory import AgentIdentity, AgentRole
    identity = AgentIdentity(agent_id="guest_1", role=AgentRole.GUEST)

    entries = [
        {"content": "public", "owner": "u1", "visibility": "public"},
        {"content": "private", "owner": "u1", "visibility": "private"},
    ]
    filtered = v8.filter_memories(entries, identity)
    assert len(filtered) == 1


@pytest.mark.asyncio
async def test_v8_retrospective_on_failure():
    v7_mock = MagicMock()
    v7_mock.process = AsyncMock(return_value={
        "reply": "error occurred", "status": "failure", "error": "timeout after 30s"
    })

    class FakeV4:
        _events = MagicMock()
        class _FakeV3:
            class _FakeV2:
                _tracer = MagicMock()
                _registry = MagicMock()
            _v2 = _FakeV2()
        _v3 = _FakeV3()
    v7_mock._v5 = MagicMock()
    v7_mock._v5._v4 = FakeV4()

    v8 = OrchestratorV8(v7_mock)
    result = await v8.process("test input")
    assert "retrospective" in result
    assert result["retrospective"]["failure_type"] == "timeout"


@pytest.mark.asyncio
async def test_v8_swarm_process():
    v7_mock = MagicMock()

    from ensemble_engine import EnsembleResult, AgentVote
    v7_mock.process_ensemble = AsyncMock(return_value=EnsembleResult(
        final_answer="swarm answer",
        strategy=EnsembleStrategy.VOTING,
        votes=[AgentVote(agent_id="a", response="swarm answer", confidence=0.9)],
        consensus_reached=True,
        rounds=1,
    ))

    v8 = OrchestratorV8(v7_mock)

    # 手动注册 agents
    class FakeAgent:
        def __init__(self, aid):
            self.agent_id = aid
            self.version = "1.0"
            self.capabilities = []

    await v8._registry.register(FakeAgent("a1"), "general")
    await v8._registry.register(FakeAgent("a2"), "general")
    await v8._registry.register(FakeAgent("a3"), "general")

    result = await v8.process_with_swarm("write code", "coding", team_size=2)
    assert result["status"] == "success"
    assert "swarm_id" in result
    assert result["consensus"] is True
