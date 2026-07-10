"""工作流引擎单元测试"""
import sys
sys.path.insert(0, "/workspace")

import asyncio
import sys
sys.path.insert(0, "/workspace/agent_cluster")
sys.path.insert(0, "/workspace")

from typing import Any

import pytest

from agent_cluster.workflow_engine import (
    WorkflowEngine,
    WorkflowDefinition,
    WorkflowNode,
    WorkflowState,
    FunctionNode,
    AgentNode,
    WorkflowPatterns,
    WorkflowStatus,
)
from agent_cluster.interfaces import AgentTask, AgentResult, IAgentPlugin


class MockAgent(IAgentPlugin):
    agent_id = "mock.agent"
    version = "1.0"
    capabilities = ["mock.do"]

    async def handle_task(self, task: AgentTask) -> AgentResult:
        return AgentResult(
            task_id=task.task_id,
            trace_id=task.trace_id,
            agent_id=self.agent_id,
            status="success",
            output={"echo": task.payload.get("user_input", "")},
        )


class AddNode(WorkflowNode):
    def __init__(self, node_id: str, key: str, value: Any) -> None:
        super().__init__(node_id)
        self.key = key
        self.value = value

    async def execute(self, state: WorkflowState) -> dict[str, Any]:
        state.set(self.key, self.value)
        return {self.key: self.value}


class MultiplyNode(WorkflowNode):
    def __init__(self, node_id: str, key: str, multiplier: int) -> None:
        super().__init__(node_id)
        self.key = key
        self.multiplier = multiplier

    async def execute(self, state: WorkflowState) -> dict[str, Any]:
        val = state.get(self.key, 0)
        result = val * self.multiplier
        state.set(self.key, result)
        return {self.key: result}


class ErrorNode(WorkflowNode):
    async def execute(self, state: WorkflowState) -> dict[str, Any]:
        raise RuntimeError("intentional error")


@pytest.fixture
def engine():
    return WorkflowEngine()


@pytest.mark.asyncio
async def test_chain_execution(engine):
    """测试串行链式执行"""
    n1 = AddNode("n1", "x", 5)
    n2 = MultiplyNode("n2", "x", 3)
    n3 = AddNode("n3", "y", 10)

    wf = WorkflowDefinition("test_chain")
    wf.add_node(n1).add_node(n2).add_node(n3)
    wf.set_entry("n1")
    wf.add_edge("n1", "n2")
    wf.add_edge("n2", "n3")

    state = WorkflowState()
    result = await engine.execute(wf, state)

    assert result.status == WorkflowStatus.COMPLETED
    assert result.final_state.get("x") == 15
    assert result.final_state.get("y") == 10
    assert result.is_success


@pytest.mark.asyncio
async def test_parallel_fan_out(engine):
    """测试并行扇出-归并"""
    async def entry_fn(state: WorkflowState) -> dict[str, Any]:
        return {"start": True}

    async def p1_fn(state: WorkflowState) -> dict[str, Any]:
        return {"branch": 1}

    async def p2_fn(state: WorkflowState) -> dict[str, Any]:
        await asyncio.sleep(0.01)
        return {"slow": True}

    async def merge_fn(state: WorkflowState) -> dict[str, Any]:
        return {"merged": True}

    entry = FunctionNode("entry", entry_fn)
    p1 = FunctionNode("p1", p1_fn)
    p2 = FunctionNode("p2", p2_fn)
    merge = FunctionNode("merge", merge_fn)

    wf = WorkflowPatterns.parallel_fan_out("test_parallel", entry, [p1, p2], merge)

    result = await engine.execute(wf, WorkflowState())
    assert result.status == WorkflowStatus.COMPLETED
    outputs = result.final_state.node_outputs
    assert "entry" in outputs
    assert "p1" in outputs
    assert "p2" in outputs
    assert "merge" in outputs


@pytest.mark.asyncio
async def test_conditional_branching(engine):
    """测试条件分支"""
    n1 = AddNode("n1", "score", 85)

    async def pass_node(state: WorkflowState) -> dict[str, Any]:
        return {"result": "pass"}

    async def fail_node(state: WorkflowState) -> dict[str, Any]:
        return {"result": "fail"}

    n_pass = FunctionNode("pass", pass_node)
    n_fail = FunctionNode("fail", fail_node)

    wf = WorkflowDefinition("test_conditional")
    wf.add_node(n1).add_node(n_pass).add_node(n_fail)
    wf.set_entry("n1")
    wf.add_edge("n1", "pass", condition=lambda s: s.get("score", 0) >= 60)
    wf.add_edge("n1", "fail", condition=lambda s: s.get("score", 0) < 60)

    result = await engine.execute(wf, WorkflowState())
    assert result.status == WorkflowStatus.COMPLETED
    assert "pass" in result.final_state.node_outputs
    assert result.final_state.node_outputs["pass"]["result"] == "pass"


@pytest.mark.asyncio
async def test_conditional_branch_fail(engine):
    """测试条件分支走 fail 路径"""
    n1 = AddNode("n1", "score", 30)

    async def pass_node(state: WorkflowState) -> dict[str, Any]:
        return {"result": "pass"}

    async def fail_node(state: WorkflowState) -> dict[str, Any]:
        return {"result": "fail"}

    n_pass = FunctionNode("pass", pass_node)
    n_fail = FunctionNode("fail", fail_node)

    wf = WorkflowDefinition("test_conditional_fail")
    wf.add_node(n1).add_node(n_pass).add_node(n_fail)
    wf.set_entry("n1")
    wf.add_edge("n1", "pass", condition=lambda s: s.get("score", 0) >= 60)
    wf.add_edge("n1", "fail", condition=lambda s: s.get("score", 0) < 60)

    result = await engine.execute(wf, WorkflowState())
    assert result.status == WorkflowStatus.COMPLETED
    assert "fail" in result.final_state.node_outputs
    assert result.final_state.node_outputs["fail"]["result"] == "fail"


@pytest.mark.asyncio
async def test_agent_node(engine):
    """测试 Agent 节点"""
    agent = MockAgent()
    node = AgentNode("agent_1", agent, "mock.do")

    wf = WorkflowDefinition("test_agent")
    wf.add_node(node)
    wf.set_entry("agent_1")

    state = WorkflowState(user_input="hello")
    result = await engine.execute(wf, state)

    assert result.status == WorkflowStatus.COMPLETED
    assert result.final_state.node_outputs["agent_1"]["status"] == "success"


@pytest.mark.asyncio
async def test_error_handling(engine):
    """测试节点错误处理"""
    n1 = AddNode("n1", "x", 1)
    n_err = ErrorNode("err")

    wf = WorkflowDefinition("test_error")
    wf.add_node(n1).add_node(n_err)
    wf.set_entry("n1")
    wf.add_edge("n1", "err")

    result = await engine.execute(wf, WorkflowState())
    assert result.status == WorkflowStatus.FAILED
    assert len(result.errors) > 0
    assert "RuntimeError" in result.errors[0] or "intentional error" in result.errors[0]


@pytest.mark.asyncio
async def test_dag_validation_cycle(engine):
    """测试 DAG 环路检测"""
    n1 = AddNode("n1", "x", 1)
    n2 = AddNode("n2", "x", 2)

    wf = WorkflowDefinition("test_cycle")
    wf.add_node(n1).add_node(n2)
    wf.set_entry("n1")
    wf.add_edge("n1", "n2")
    wf.add_edge("n2", "n1")  # 形成环路

    result = await engine.execute(wf, WorkflowState())
    assert result.status == WorkflowStatus.FAILED
    assert any("环路" in e for e in result.errors)


@pytest.mark.asyncio
async def test_dag_validation_no_entry(engine):
    """测试入口节点缺失"""
    n1 = AddNode("n1", "x", 1)

    wf = WorkflowDefinition("test_no_entry")
    wf.add_node(n1)
    # 不设置入口

    result = await engine.execute(wf, WorkflowState())
    assert result.status == WorkflowStatus.FAILED
    assert any("入口" in e for e in result.errors)


@pytest.mark.asyncio
async def test_workflow_result_dict(engine):
    """测试结果序列化"""
    n1 = AddNode("n1", "x", 42)
    wf = WorkflowDefinition("test_result")
    wf.add_node(n1)
    wf.set_entry("n1")

    result = await engine.execute(wf, WorkflowState())
    d = result.output
    assert "n1" in d
    assert result.is_success


@pytest.mark.asyncio
async def test_nested_node_on_hooks(engine):
    """测试节点生命周期钩子"""
    events = []

    class HookNode(WorkflowNode):
        async def on_enter(self, state: WorkflowState) -> None:
            events.append("enter")

        async def execute(self, state: WorkflowState) -> dict[str, Any]:
            events.append("execute")
            return {"ok": True}

        async def on_exit(self, state: WorkflowState, output: dict[str, Any]) -> None:
            events.append("exit")

    node = HookNode("hook")
    wf = WorkflowDefinition("test_hooks")
    wf.add_node(node)
    wf.set_entry("hook")

    await engine.execute(wf, WorkflowState())
    assert events == ["enter", "execute", "exit"]
