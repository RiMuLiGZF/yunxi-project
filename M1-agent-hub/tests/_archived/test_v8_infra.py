"""
测试：A2A 协议 + Checkpointer + 增强注册中心 + RBAC
"""

import pytest
import sys
import asyncio
from a2a_protocol import (
    A2AClient, AgentCard, Artifact, MemoryTransport, Task, TaskStatus, TaskUpdate
)
from checkpointer import Checkpointer, CheckpointConfig
from enhanced_registry import (
    EnhancedRegistry, LoopGuard, LoadBalancer, LoadMetrics, LazyAgentRegistry
)
from rbac_memory import (
    RBACMemoryGuard, AgentIdentity, AgentRole, MemoryAccessPolicy, Visibility
)
from interfaces import BusMessage


# ═════════════ A2A Protocol ═════════════


def test_task_state_transition():
    t = Task()
    assert t.status == TaskStatus.SUBMITTED
    t.transition_to(TaskStatus.WORKING)
    assert t.status == TaskStatus.WORKING
    t.transition_to(TaskStatus.COMPLETED)
    assert t.status == TaskStatus.COMPLETED


def test_task_invalid_transition():
    t = Task()
    with pytest.raises(ValueError, match="非法状态转换"):
        t.transition_to(TaskStatus.COMPLETED)  # SUBMITTED → COMPLETED 直接跳转不允许


def test_agent_card_sign_and_verify():
    card = AgentCard(agent_id="test_agent", name="Test", capabilities=["chat", "code"])
    card.sign("my-secret")
    assert card.signature != ""
    assert card.verify("my-secret") is True
    assert card.verify("wrong-secret") is False


def test_agent_card_to_dict():
    card = AgentCard(agent_id="a1", name="Agent1", version="2.0")
    d = card.to_dict()
    assert d["agent_id"] == "a1"
    assert d["version"] == "2.0"


@pytest.mark.asyncio
async def test_memory_transport():
    transport = MemoryTransport()

    async def handler(task):
        return TaskUpdate(task_id=task.task_id, status=TaskStatus.WORKING)

    transport.register_handler("agent_a", handler)
    client = A2AClient(transport=transport)

    task = Task(description="test task")
    result = await client.send_task(AgentCard(agent_id="agent_a", url="memory://agent_a"), task)
    assert result.status == TaskStatus.WORKING


@pytest.mark.asyncio
async def test_memory_transport_agent_not_found():
    transport = MemoryTransport()
    client = A2AClient(transport=transport)
    task = Task(description="test")
    result = await client.send_task(AgentCard(agent_id="ghost", url="memory://ghost"), task)
    assert result.status == TaskStatus.FAILED
    assert "not found" in result.error


# ═════════════ Checkpointer ═════════════


def test_checkpoint_save_and_load():
    cp = Checkpointer()
    saved = cp.save(
        workflow_id="wf1", trace_id="t1", node_id="n1", step_index=0,
        completed_nodes=["n0"], state_snapshot={"key": "val"},
        node_outputs={"n0": {"out": 1}}, errors=[],
    )
    assert saved.checkpoint_id.startswith("cp_wf1_0_")

    loaded = cp.load("wf1", saved.checkpoint_id)
    assert loaded is not None
    assert loaded.node_id == "n1"
    assert loaded.state_snapshot["key"] == "val"


def test_checkpoint_load_latest():
    cp = Checkpointer()
    cp.save("wf1", "t1", "n1", 0, ["n0"], {"a": 1}, {}, [])
    cp.save("wf1", "t1", "n2", 1, ["n0", "n1"], {"a": 2}, {}, [])

    latest = cp.load_latest("wf1")
    assert latest is not None
    assert latest.step_index == 1
    assert latest.node_id == "n2"


def test_checkpoint_max_limit():
    config = CheckpointConfig(max_checkpoints_per_workflow=2)
    cp = Checkpointer(config)
    for i in range(5):
        cp.save("wf1", "t1", f"n{i}", i, [], {}, {}, [])

    cps = cp.list_checkpoints("wf1")
    assert len(cps) == 2
    assert cps[0].step_index == 3  # 旧的被淘汰
    assert cps[1].step_index == 4


def test_checkpoint_remove():
    cp = Checkpointer()
    saved = cp.save("wf1", "t1", "n1", 0, [], {}, {}, [])
    assert cp.remove("wf1", saved.checkpoint_id) is True
    assert cp.load("wf1", saved.checkpoint_id) is None


def test_checkpoint_stats():
    cp = Checkpointer()
    cp.save("wf1", "t1", "n1", 0, [], {}, {}, [])
    cp.save("wf2", "t1", "n1", 0, [], {}, {}, [])
    stats = cp.stats()
    assert stats["total_checkpoints"] == 2
    assert stats["workflow_count"] == 2


# ═════════════ LoopGuard ═════════════


def test_loop_guard_allows_normal():
    guard = LoopGuard(max_hops=10)
    msg = BusMessage(topic="test", sender="agent_a", payload={"_meta": {"hop_count": 0, "breadcrumb": []}})
    can, reason = guard.check(msg)
    assert can is True
    assert reason == "ok"


def test_loop_guard_blocks_hop_limit():
    guard = LoopGuard(max_hops=3)
    msg = BusMessage(topic="test", sender="agent_a", payload={"_meta": {"hop_count": 3, "breadcrumb": []}})
    can, reason = guard.check(msg)
    assert can is False
    assert "hop_limit" in reason


def test_loop_guard_blocks_loop():
    guard = LoopGuard(max_hops=10)
    msg = BusMessage(topic="test", sender="agent_a", payload={"_meta": {"hop_count": 0, "breadcrumb": ["agent_b", "agent_c", "agent_a"]}})
    can, reason = guard.check(msg)
    assert can is False
    assert "loop" in reason


def test_loop_guard_prepare_transit():
    guard = LoopGuard(max_hops=10)
    msg = BusMessage(topic="test", sender="agent_a", payload={"_meta": {"hop_count": 0, "breadcrumb": []}})
    prepared = guard.prepare_transit(msg)
    assert prepared.payload["_meta"]["hop_count"] == 1
    assert "agent_a" in prepared.payload["_meta"]["breadcrumb"]


# ═════════════ EnhancedRegistry ═════════════


@pytest.mark.asyncio
async def test_enhanced_registry_register():
    reg = EnhancedRegistry()

    class FakeAgent:
        agent_id = "test_a"
        version = "1.0"
        capabilities = ["chat"]

    await reg.register(FakeAgent(), agent_type="expert")
    assert reg.get("test_a") is not None
    assert "test_a" in reg.list_ids()


@pytest.mark.asyncio
async def test_enhanced_registry_load_balance():
    reg = EnhancedRegistry(LoadBalancer(strategy="least_conn"))

    class FakeAgent:
        def __init__(self, aid):
            self.agent_id = aid
            self.version = "1.0"
            self.capabilities = ["chat"]

    await reg.register(FakeAgent("a1"), "general")
    await reg.register(FakeAgent("a2"), "general")
    await reg.register(FakeAgent("a3"), "general")

    # 记录 a1 有 5 个 inflight
    for _ in range(5):
        reg.record_task_start("a1")

    # least_conn 应选 inflight 最少的
    agent = reg.select_by_load("general")
    assert agent is not None
    assert agent.agent_id in ("a2", "a3")  # a1 有 5 个 inflight


@pytest.mark.asyncio
async def test_enhanced_registry_metrics():
    reg = EnhancedRegistry()

    class FakeAgent:
        agent_id = "test_a"
        version = "1.0"
        capabilities = []

    await reg.register(FakeAgent())
    reg.record_task_start("test_a")
    reg.record_task_end("test_a", success=True, latency_ms=100.0)
    reg.record_task_end("test_a", success=False, latency_ms=200.0)

    m = reg.get_metrics("test_a")
    assert m.total_tasks == 2
    assert m.success_count == 1
    assert m.failure_count == 1
    assert m.error_rate == 0.5


def test_enhanced_registry_stats():
    reg = EnhancedRegistry()
    stats = reg.stats()
    assert stats["total_agents"] == 0


# ═════════════ LazyAgentRegistry ═════════════


def test_lazy_registry_register_factory():
    lazy = LazyAgentRegistry()
    lazy.register_factory("agent_x", lambda: "fake_instance")
    stats = lazy.stats()
    assert stats["registered_factories"] == 1
    assert stats["active_instances"] == 0


def test_lazy_registry_evict_idle():
    import time
    lazy = LazyAgentRegistry(idle_ttl=0.1, min_instances=0)
    lazy.register_factory("a1", lambda: "inst1")
    lazy._active["a1"] = "inst1"
    lazy._last_access["a1"] = time.time() - 1.0  # 1秒前
    evicted = lazy.evict_idle()
    assert evicted == 1
    assert "a1" not in lazy._active


# ═════════════ RBAC Memory ═════════════


def test_admin_can_read_all():
    rbac = RBACMemoryGuard()
    admin = AgentIdentity(agent_id="admin_1", role=AgentRole.ADMIN)
    for vis in Visibility:
        policy = MemoryAccessPolicy(owner="someone", visibility=vis)
        assert rbac.can_read(admin, policy) is True


def test_guest_read_restrictions():
    rbac = RBACMemoryGuard()
    guest = AgentIdentity(agent_id="guest_1", role=AgentRole.GUEST)

    # 可以读 public
    assert rbac.can_read(guest, MemoryAccessPolicy(owner="other", visibility=Visibility.PUBLIC)) is True
    # 不能读 private
    assert rbac.can_read(guest, MemoryAccessPolicy(owner="other", visibility=Visibility.PRIVATE)) is False
    # 不能读 team
    assert rbac.can_read(guest, MemoryAccessPolicy(owner="other", visibility=Visibility.TEAM)) is False
    # 不能读 sensitive
    assert rbac.can_read(guest, MemoryAccessPolicy(owner="other", visibility=Visibility.SENSITIVE)) is False


def test_expert_read_team():
    rbac = RBACMemoryGuard()
    expert = AgentIdentity(agent_id="exp_1", role=AgentRole.EXPERT, team="alpha")
    # 不能读其他人的 team 记忆
    other_policy = MemoryAccessPolicy(owner="exp_2", visibility=Visibility.TEAM)
    assert rbac.can_read(expert, other_policy) is False
    # 可以读自己创建的 team 记忆
    own_policy = MemoryAccessPolicy(owner="exp_1", visibility=Visibility.TEAM)
    assert rbac.can_read(expert, own_policy) is True


def test_rbac_filter_entries():
    rbac = RBACMemoryGuard()
    guest = AgentIdentity(agent_id="guest_1", role=AgentRole.GUEST)
    entries = [
        {"content": "public data", "owner": "user1", "visibility": "public"},
        {"content": "private data", "owner": "user1", "visibility": "private"},
        {"content": "sensitive data", "owner": "user1", "visibility": "sensitive"},
    ]
    filtered = rbac.filter_entries(guest, entries)
    assert len(filtered) == 1
    assert filtered[0]["content"] == "public data"


def test_rbac_stats():
    rbac = RBACMemoryGuard()
    stats = rbac.stats()
    assert "admin" in stats["roles_defined"]
    assert "public" in stats["visibility_levels"]
