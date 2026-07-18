"""
Agent 管理测试套件（按功能模块重组）

来源版本：
- test_v10_subagents.py (v10.0 全量子Agent集成：共享数据模型、TaskDAG、
  各子Agent handle_task、分身池、并发安全)

说明：
本文件从 v10 版本测试中提取子 Agent 管理核心功能的测试，按子功能分类组织。
原始版本文件已移入 tests/_legacy/ 目录保存。
"""

from __future__ import annotations

import sys
import os
import time

import pytest
from unittest.mock import MagicMock, AsyncMock

def _make_task(intent: str, payload: dict | None = None, **kwargs):
    """辅助函数：创建 AgentTask"""
    from interfaces import AgentTask
    return AgentTask(
        task_id=f"test.{time.time()}",
        intent=intent,
        payload=payload or {},
        **kwargs,
    )


# ============================================================================
# 1. 共享数据模型测试（来源：test_v10_subagents.py）
# ============================================================================

class TestSharedModels:
    """共享数据模型测试"""

    def test_task_dag_creation(self):
        from shared_models import TaskDAG
        dag = TaskDAG(goal="test goal")
        assert dag.goal == "test goal"
        assert dag.nodes == []

    def test_dag_add_node(self):
        from shared_models import TaskDAG, DAGNode
        dag = TaskDAG(goal="test")
        node = DAGNode(node_id="n1", description="node 1", assigned_agent="agent.a")
        dag.add_node(node)
        assert len(dag.nodes) == 1
        assert dag.nodes[0]["node_id"] == "n1"

    def test_dag_add_edge(self):
        from shared_models import TaskDAG, DAGEdge
        dag = TaskDAG(goal="test")
        edge = DAGEdge(source_node="n1", target_node="n2", edge_type="data")
        dag.add_edge(edge)
        assert len(dag.edges) == 1

    def test_dag_topological_sort_linear(self):
        from shared_models import TaskDAG, DAGNode, DAGEdge
        dag = TaskDAG(goal="test")
        for i in range(4):
            dag.add_node(DAGNode(node_id=f"n{i}"))
        for i in range(3):
            dag.add_edge(DAGEdge(source_node=f"n{i}", target_node=f"n{i+1}"))
        result = dag.topological_sort()
        assert result.index("n0") < result.index("n1")
        assert result.index("n1") < result.index("n2")

    def test_dag_topological_sort_parallel(self):
        from shared_models import TaskDAG, DAGNode, DAGEdge
        dag = TaskDAG(goal="test")
        dag.add_node(DAGNode(node_id="root"))
        dag.add_node(DAGNode(node_id="a"))
        dag.add_node(DAGNode(node_id="b"))
        dag.add_edge(DAGEdge(source_node="root", target_node="a"))
        dag.add_edge(DAGEdge(source_node="root", target_node="b"))
        order = dag.topological_sort()
        assert order.index("root") < order.index("a")
        assert order.index("root") < order.index("b")

    def test_dag_get_ready_nodes(self):
        from shared_models import TaskDAG, DAGNode
        dag = TaskDAG(goal="test")
        dag.add_node(DAGNode(node_id="n1", status="completed"))
        dag.add_node(DAGNode(node_id="n2", dependencies=["n1"]))
        dag.add_node(DAGNode(node_id="n3", dependencies=["n1"]))
        ready = dag.get_ready_nodes()
        assert len(ready) == 2
        ids = {r["node_id"] for r in ready}
        assert "n2" in ids and "n3" in ids

    def test_dag_completion_rate(self):
        from shared_models import TaskDAG, DAGNode
        dag = TaskDAG(goal="test")
        dag.add_node(DAGNode(node_id="n1", status="completed"))
        dag.add_node(DAGNode(node_id="n2", status="running"))
        dag.add_node(DAGNode(node_id="n3", status="pending"))
        assert dag.completion_rate() == pytest.approx(1/3, abs=0.01)

    def test_dag_to_dict(self):
        from shared_models import TaskDAG, DAGNode
        dag = TaskDAG(goal="test", root_task_id="t1")
        dag.add_node(DAGNode(node_id="n1"))
        d = dag.to_dict()
        assert "completion_rate" in d
        assert d["goal"] == "test"

    def test_security_classification_ordering(self):
        from shared_models import SecurityClassification
        assert SecurityClassification.PUBLIC < SecurityClassification.INTERNAL
        assert SecurityClassification.INTERNAL < SecurityClassification.CONFIDENTIAL
        assert SecurityClassification.CONFIDENTIAL < SecurityClassification.TOP_SECRET

    def test_agent_life_state_values(self):
        from shared_models import AgentLifeState
        states = list(AgentLifeState)
        assert len(states) == 8
        assert AgentLifeState.CREATED.value == "created"
        assert AgentLifeState.ARCHIVED.value == "archived"

    def test_clone_identity_defaults(self):
        from shared_models import CloneIdentity, CloneType, SecurityClassification
        clone = CloneIdentity(parent_agent_id="agent.1", clone_type=CloneType.SCOUT)
        assert clone.security_clearance == SecurityClassification.PUBLIC
        assert clone.ttl == 300
        assert clone.clone_id != ""

    def test_load_score_creation(self):
        from shared_models import LoadScore
        score = LoadScore(agent_id="agent.1", vram_score=0.8, cpu_score=0.6, composite=0.7)
        assert score.agent_id == "agent.1"
        assert score.composite == 0.7


# ============================================================================
# 2. Orchestrator Agent 测试（来源：test_v10_subagents.py）
# ============================================================================

class TestOrchestratorAgent:
    """任务编排子Agent测试"""

    @pytest.fixture
    def agent(self):
        from orchestrator.agent import OrchestratorAgent
        return OrchestratorAgent()

    def test_agent_identity(self, agent):
        assert agent.agent_id == "agent.orchestrator"
        assert "orchestrate.build" in agent.capabilities

    @pytest.mark.asyncio
    async def test_build_dag_simple(self, agent):
        task = _make_task("orchestrate.build", payload={
            "goal": "查询天气",
            "context": {"type": "query"},
            "available_agents": [{"agent_id": "agent.weather", "capabilities": ["weather"]}],
        })
        result = await agent.handle_task(task)
        assert result.status == "success"
        assert result.output is not None
        dag_id = result.output.get("dag_id")
        assert dag_id is not None

    @pytest.mark.asyncio
    async def test_build_dag_medium(self, agent):
        task = _make_task("orchestrate.build", payload={
            "goal": "分析并总结报告，然后审查质量",
            "context": {"type": "analysis", "depth": "medium"},
            "available_agents": [
                {"agent_id": "agent.analyzer", "capabilities": ["analysis"]},
                {"agent_id": "agent.summarizer", "capabilities": ["summarization"]},
                {"agent_id": "agent.reviewer", "capabilities": ["review"]},
            ],
        })
        result = await agent.handle_task(task)
        assert result.status == "success"
        nodes = result.output.get("node_count", 0)
        assert nodes >= 3

    @pytest.mark.asyncio
    async def test_query_dag(self, agent):
        task_build = _make_task("orchestrate.build", payload={
            "goal": "简单任务", "context": {},
            "available_agents": [{"agent_id": "agent.a", "capabilities": ["code"]}],
        })
        build_result = await agent.handle_task(task_build)
        dag_id = build_result.output["dag_id"]
        dag = agent.get_dag(dag_id)
        assert dag is not None
        assert dag.dag_id == dag_id

    @pytest.mark.asyncio
    async def test_update_node_status(self, agent):
        task_build = _make_task("orchestrate.build", payload={
            "goal": "测试更新", "context": {},
            "available_agents": [{"agent_id": "agent.a", "capabilities": ["code"]}],
        })
        build_result = await agent.handle_task(task_build)
        dag_id = build_result.output["dag_id"]
        dag = agent.get_dag(dag_id)
        node_id = dag.nodes[0]["node_id"] if dag.nodes else None
        if node_id:
            ok = agent.update_node_status(dag_id, node_id, "completed", result_summary="done")
            assert ok is True
            updated_dag = agent.get_dag(dag_id)
            assert updated_dag.nodes[0]["status"] == "completed"


# ============================================================================
# 3. Lifecycle Agent 测试（来源：test_v10_subagents.py）
# ============================================================================

class TestLifecycleAgent:
    """生命周期管理子Agent测试"""

    @pytest.fixture
    def agent(self):
        from lifecycle.agent import LifecycleAgent
        return LifecycleAgent()

    def test_agent_identity(self, agent):
        assert agent.agent_id == "agent.lifecycle"

    @pytest.mark.asyncio
    async def test_create_and_activate(self, agent):
        task = _make_task("lifecycle.create", payload={
            "agent_id": "agent.test",
            "role": "executor",
            "capabilities": ["code", "review"],
        })
        result = await agent.handle_task(task)
        assert result.status == "success"
        task_act = _make_task("lifecycle.activate", payload={"agent_id": "agent.test"})
        result_act = await agent.handle_task(task_act)
        assert result_act.status == "success"

    @pytest.mark.asyncio
    async def test_suspend_resume(self, agent):
        await agent.handle_task(_make_task("lifecycle.create", payload={
            "agent_id": "agent.sr", "role": "executor", "capabilities": ["code"],
        }))
        await agent.handle_task(_make_task("lifecycle.activate", payload={"agent_id": "agent.sr"}))
        task_suspend = _make_task("lifecycle.suspend", payload={"agent_id": "agent.sr"})
        result = await agent.handle_task(task_suspend)
        assert result.status == "success"
        task_resume = _make_task("lifecycle.resume", payload={"agent_id": "agent.sr"})
        result = await agent.handle_task(task_resume)
        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_full_lifecycle(self, agent):
        aid = "agent.full"
        await agent.handle_task(_make_task("lifecycle.create", payload={
            "agent_id": aid, "role": "executor", "capabilities": ["code"],
        }))
        await agent.handle_task(_make_task("lifecycle.activate", payload={"agent_id": aid}))
        await agent.handle_task(_make_task("lifecycle.suspend", payload={"agent_id": aid}))
        await agent.handle_task(_make_task("lifecycle.drain", payload={"agent_id": aid}))
        await agent.handle_task(_make_task("lifecycle.terminate", payload={"agent_id": aid}))
        await agent.handle_task(_make_task("lifecycle.archive", payload={"agent_id": aid}))
        stats = agent._pool.stats()
        assert stats["state_counts"].get("archived", 0) >= 1

    def test_instance_pool_ref_count(self):
        from lifecycle.instance_pool import AgentInstancePool
        from shared_models import AgentRole
        pool = AgentInstancePool()
        pool.create("agent.ref", AgentRole.EXECUTOR, ["code"], {})
        pool.activate("agent.ref")
        pool.add_ref("agent.ref")
        pool.add_ref("agent.ref")
        assert pool._ref_counts["agent.ref"] == 2
        pool.release_ref("agent.ref")
        assert pool._ref_counts["agent.ref"] == 1


# ============================================================================
# 4. Discovery Agent 测试（来源：test_v10_subagents.py）
# ============================================================================

class TestDiscoveryAgent:
    """注册发现与负载均衡子Agent测试"""

    @pytest.fixture
    def agent(self):
        from discovery.agent import DiscoveryAgent
        return DiscoveryAgent()

    def test_agent_identity(self, agent):
        assert agent.agent_id == "agent.discovery"

    def test_load_evaluator_scoring(self):
        from discovery.load_evaluator import LoadEvaluator
        evaluator = LoadEvaluator()
        score = evaluator.update_score("agent.1", {
            "vram_usage": 0.3, "cpu_usage": 0.5,
            "battery_pct": 80.0, "network_latency": 20.0,
            "active_tasks": 3,
        })
        assert score.agent_id == "agent.1"
        assert 0 <= score.composite <= 1.0

    def test_scheduling_policy_local_first(self):
        from discovery.scheduling_policy import SchedulingPolicy, SchedulingDecision
        policy = SchedulingPolicy()
        decision = policy.decide(battery_pct=90.0, network_available=True, task_complexity=0.3)
        assert decision == SchedulingDecision.LOCAL_FIRST

    @pytest.mark.asyncio
    async def test_register_and_find(self, agent):
        task_reg = _make_task("discovery.register", payload={
            "agent_info": {
                "agent_id": "agent.code",
                "capabilities": ["code", "review"],
                "role": "executor",
            },
        })
        result = await agent.handle_task(task_reg)
        assert result.status == "success"
        found = agent.find_agent(["code"])
        assert found is not None


# ============================================================================
# 5. Security Agent 测试（来源：test_v10_subagents.py）
# ============================================================================

class TestSecurityAgent:
    """安全审计子Agent测试"""

    @pytest.fixture
    def agent(self):
        from security.agent import SecurityAgent
        return SecurityAgent()

    def test_agent_identity(self, agent):
        assert agent.agent_id == "agent.security"

    def test_classify_public(self):
        from security.classifier import SecurityClassifier
        classifier = SecurityClassifier()
        level = classifier.classify_content("今天天气真好")
        from shared_models import SecurityClassification
        assert level == SecurityClassification.PUBLIC

    def test_classify_confidential(self):
        from security.classifier import SecurityClassifier
        classifier = SecurityClassifier()
        level = classifier.classify_content("内部项目代号：云汐系统，预算200万元")
        from shared_models import SecurityClassification
        assert level >= SecurityClassification.INTERNAL

    def test_clearance_check(self):
        from security.classifier import SecurityClassifier
        from shared_models import SecurityClassification
        classifier = SecurityClassifier()
        assert classifier.check_clearance(SecurityClassification.CONFIDENTIAL, SecurityClassification.PUBLIC) is True
        assert classifier.check_clearance(SecurityClassification.PUBLIC, SecurityClassification.TOP_SECRET) is False

    def test_audit_log_record_and_query(self):
        from security.audit_log import AuditLog
        from shared_models import SecurityClassification
        log = AuditLog()
        log.record("agent.1", "read", "doc.1", SecurityClassification.INTERNAL, "allowed")
        log.record("agent.1", "write", "doc.2", SecurityClassification.CONFIDENTIAL, "denied")
        entries = log.query(agent_id="agent.1")
        assert len(entries) == 2
        stats = log.stats()
        assert stats["total_entries"] == 2

    @pytest.mark.asyncio
    async def test_check_input(self, agent):
        result = agent.check_input("正常输入，请查询天气")
        assert result["blocked"] is False

    @pytest.mark.asyncio
    async def test_check_access(self, agent):
        from shared_models import SecurityClassification
        agent.register_agent_clearance("agent.1", SecurityClassification.CONFIDENTIAL)
        assert agent.check_access("agent.1", SecurityClassification.INTERNAL) is True
        assert agent.check_access("agent.1", SecurityClassification.TOP_SECRET) is False


# ============================================================================
# 6. Budget Agent 测试（来源：test_v10_subagents.py）
# ============================================================================

class TestBudgetAgent:
    """预算管控子Agent测试"""

    @pytest.fixture
    def agent(self):
        from budget.agent import BudgetAgent
        return BudgetAgent()

    def test_agent_identity(self, agent):
        assert agent.agent_id == "agent.budget"

    def test_check_budget_available(self):
        agent = self._make_agent()
        available, used, limit = agent.check_budget("session", "mock-model", 0.01)
        assert available is True

    def test_record_usage(self):
        agent = self._make_agent()
        record = agent.record_usage("mock-model", 100, 200, "agent.1")
        assert record["model"] == "mock-model"
        assert record["input_tokens"] == 100

    def test_select_model(self):
        agent = self._make_agent()
        model = agent.select_model("low")
        assert model is not None

    def test_budget_report(self):
        agent = self._make_agent()
        report = agent.get_budget_report()
        assert "daily_budget" in report

    def _make_agent(self):
        from budget.agent import BudgetAgent
        return BudgetAgent()


# ============================================================================
# 7. Snapshot Agent 测试（来源：test_v10_subagents.py）
# ============================================================================

class TestSnapshotAgent:
    """状态快照与断点续跑测试"""

    @pytest.fixture
    def agent(self):
        from snapshot.agent import SnapshotAgent
        return SnapshotAgent()

    def test_agent_identity(self, agent):
        assert agent.agent_id == "agent.snapshot"

    @pytest.mark.asyncio
    async def test_create_snapshot(self, agent):
        entry = agent.create(
            task_id="task.1", dag_id="dag.1",
            context={"nodes": [{"id": "n1", "status": "completed"}]},
        )
        assert entry.task_id == "task.1"
        assert entry.checksum != ""

    @pytest.mark.asyncio
    async def test_snapshot_chain(self, agent):
        agent.create("task.2", "dag.2", {"nodes": [{"id": "n1", "status": "running"}]})
        agent.create("task.2", "dag.2", {"nodes": [{"id": "n1", "status": "completed"}]})
        chain = agent.get_chain("task.2")
        assert len(chain) == 2

    def test_store_integrity(self):
        from snapshot.snapshot_store import SnapshotStore
        store = SnapshotStore()
        entry = store.create_snapshot(
            task_id="t1", dag_id="d1",
            node_states=[{"id": "n1", "status": "running"}],
            agent_states=[{"id": "a1", "state": "active"}],
            budget_snapshot={"used": 0.5},
        )
        assert store.verify_integrity(entry.snapshot_id) is True

    def test_store_prune(self):
        from snapshot.snapshot_store import SnapshotStore
        store = SnapshotStore()
        store.create_snapshot("t1", "d1", [], [], {})
        store.create_snapshot("t1", "d1", [], [], {})
        count = store.prune_older_than("t1", max_age_seconds=0)
        assert count >= 1


# ============================================================================
# 8. Arbiter Agent 测试（来源：test_v10_subagents.py）
# ============================================================================

class TestArbiterAgent:
    """死锁仲裁子Agent测试"""

    @pytest.fixture
    def agent(self):
        from arbiter.agent import ArbiterAgent
        return ArbiterAgent()

    def test_agent_identity(self, agent):
        assert agent.agent_id == "agent.arbiter"

    @pytest.mark.asyncio
    async def test_no_deadlock(self, agent):
        cycles = await agent.check_deadlock()
        assert cycles == []

    @pytest.mark.asyncio
    async def test_deadlock_detection(self):
        from arbiter.wait_for_graph import WaitForGraph
        wfg = WaitForGraph()
        await wfg.add_edge("a", "b")
        await wfg.add_edge("b", "c")
        await wfg.add_edge("c", "a")
        cycles = await wfg.detect_cycle()
        assert len(cycles) >= 1

    def test_arbitration_engine_timeout(self):
        from arbiter.wait_for_graph import ArbitrationEngine
        from shared_models import ArbitrationRequest
        engine = ArbitrationEngine()
        req = ArbitrationRequest(
            conflict_type="timeout",
            involved_agents=["agent.1"],
            task_ids=["task.1"],
            context={
                "agent_info": {"agent.1": {"wait_time_seconds": 120.0, "timeout_threshold": 60.0}},
            },
        )
        result = engine.submit(req)
        assert result.decision == "abort"

    @pytest.mark.asyncio
    async def test_update_wait_for(self, agent):
        await agent.update_wait_for("agent.a", "agent.b")
        await agent.update_wait_for("agent.b", "agent.c")
        status = await agent.get_status()
        assert status["graph_stats"]["total_edges"] == 2

    @pytest.mark.asyncio
    async def test_resolve_wait_for(self, agent):
        await agent.update_wait_for("agent.a", "agent.b")
        await agent.resolve_wait_for("agent.a", "agent.b")
        status = await agent.get_status()
        assert status["graph_stats"]["total_edges"] == 0


# ============================================================================
# 9. Clone Pool（分身池）测试（来源：test_v10_subagents.py）
# ============================================================================

class TestClonePool:
    """临时分身池测试"""

    @pytest.fixture
    def pool(self):
        from pool.clone_pool import ClonePool
        return ClonePool()

    @pytest.fixture
    def factory(self):
        from pool.clone_factory import CloneFactory
        return CloneFactory()

    def test_create_clone(self, factory):
        from shared_models import CloneType
        clone = factory.create_clone(
            parent_agent_id="agent.1",
            clone_type=CloneType.SCOUT,
            task_id="task.1",
            capabilities=["search"],
            ttl=300,
            context={"task_description": "查询API文档", "goal": "找到端点"},
        )
        assert clone.clone_type == CloneType.SCOUT
        assert clone.parent_agent_id == "agent.1"
        assert "goal" in clone.minimized_context
        assert "full_spec" not in clone.minimized_context

    @pytest.mark.asyncio
    async def test_acquire_and_release(self, pool, factory):
        from shared_models import CloneType
        clone = await pool.acquire(
            parent_agent_id="agent.1",
            clone_type=CloneType.WRITER,
            task_id="task.1",
            context={"task_description": "撰写报告"},
        )
        assert clone is not None
        assert pool.get_clone(clone.clone_id) is not None
        pool.release(clone.clone_id)
        assert pool.get_clone(clone.clone_id) is None

    def test_factory_minimize_context_types(self, factory):
        from shared_models import CloneType
        types_info = {
            CloneType.SCOUT: ["goal", "key_constraints"],
            CloneType.PLANNER: ["dependencies", "resource_info"],
            CloneType.WRITER: ["output_format", "reference_materials"],
            CloneType.REVIEWER: ["check_criteria", "content_summary"],
        }
        full_ctx = {
            "task_description": "完成项目",
            "goal": "交付",
            "key_constraints": ["预算100万", "3人团队"],
            "dependencies": ["API完成", "UI完成"],
            "resource_info": {"team_size": 3},
            "output_format": "Markdown报告",
            "reference_materials": ["RFC文档"],
            "check_criteria": ["无语法错误", "逻辑完整"],
            "content_summary": "摘要...",
        }
        for ct, expected_keys in types_info.items():
            clone = factory.create_clone("agent.1", ct, "task.1", [], 300, full_ctx)
            for key in expected_keys:
                assert key in clone.minimized_context, f"CloneType {ct} missing key {key}"


# ============================================================================
# 10. Bus Agent 测试（来源：test_v10_subagents.py）
# ============================================================================

class TestBusAgent:
    """A2A通信总线子Agent测试"""

    @pytest.fixture
    def agent(self):
        from bus.agent import BusAgent
        return BusAgent()

    def test_agent_identity(self, agent):
        assert agent.agent_id == "agent.bus"

    @pytest.mark.asyncio
    async def test_health(self, agent):
        health = await agent.health()
        assert health["status"] in ("healthy", "up")


# ============================================================================
# 11. 并发安全测试（来源：test_v10_subagents.py）
# ============================================================================

class TestConcurrencySafety:
    """并发安全测试"""

    @pytest.mark.asyncio
    async def test_concurrent_dag_build(self):
        import asyncio
        from orchestrator.agent import OrchestratorAgent
        agent = OrchestratorAgent()
        tasks = []
        for i in range(10):
            task = _make_task("orchestrate.build", payload={
                "goal": f"并发任务 {i}",
                "context": {"type": "simple"},
                "available_agents": [{"agent_id": "agent.a", "capabilities": ["code"]}],
            })
            tasks.append(agent.handle_task(task))
        results = await asyncio.gather(*tasks)
        assert all(r.status == "success" for r in results)
        assert len(agent._dag_registry) == 10

    @pytest.mark.asyncio
    async def test_concurrent_lifecycle_ops(self):
        import asyncio
        from lifecycle.agent import LifecycleAgent
        agent = LifecycleAgent()
        for i in range(10):
            await agent.handle_task(_make_task("lifecycle.create", payload={
                "agent_id": f"agent.c{i}", "role": "executor", "capabilities": ["code"],
            }))
        activate_tasks = [
            agent.handle_task(_make_task("lifecycle.activate", payload={"agent_id": f"agent.c{i}"}))
            for i in range(10)
        ]
        results = await asyncio.gather(*activate_tasks)
        assert all(r.status == "success" for r in results)

    @pytest.mark.asyncio
    async def test_concurrent_snapshot(self):
        from snapshot.agent import SnapshotAgent
        agent = SnapshotAgent()
        entries = [agent.create("task.concurrent", "dag.1", {"step": i}) for i in range(20)]
        assert len(entries) == 20
        chain = agent.get_chain("task.concurrent")
        assert len(chain) == 20

    @pytest.mark.asyncio
    async def test_concurrent_deadlock_detection(self):
        import asyncio
        from arbiter.agent import ArbiterAgent
        agent = ArbiterAgent()
        for i in range(5):
            await agent.update_wait_for(f"agent.w{i}", f"agent.h{i}")
        cycles = await agent.check_deadlock()
        assert cycles == []
        await agent.update_wait_for("agent.x", "agent.y")
        await agent.update_wait_for("agent.y", "agent.x")
        cycles = await agent.check_deadlock()
        assert len(cycles) >= 1


# ============================================================================
# 测试入口
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
