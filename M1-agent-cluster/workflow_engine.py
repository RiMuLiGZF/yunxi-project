"""
云汐内核 V2 - DAG 工作流编排引擎

灵感来源：LangGraph State + Nodes + Edges 图模型
https://langchain.com/blog/benchmarking-multi-agent-architectures

将多 Agent 协作建模为有向无环图（DAG）：
- State: 共享状态，在节点间传递
- Node: Agent 执行单元
- Edge: 条件路由，决定下一个执行哪个节点

支持编排模式：
- Chain（串行链）
- Map-Reduce（并行映射 + 结果归约）
- Conditional Branching（条件分支）
- Parallel Fan-out（并行扇出）
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable

import structlog
from interfaces import AgentTask, AgentResult, IAgentPlugin

logger = structlog.get_logger(__name__)


# ── 工作流状态 ──────────────────────────────────────────────


class WorkflowStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class WorkflowState:
    """工作流共享状态

    在整个 DAG 执行过程中持续传递和累积，
    每个节点可以读取和写入共享数据。
    """

    workflow_id: str = ""
    trace_id: str = ""
    user_input: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    node_outputs: dict[str, Any] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        """获取上下文数据"""
        return self.context.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """设置上下文数据"""
        self.context[key] = value

    def merge_node_output(self, node_id: str, output: dict[str, Any]) -> None:
        """合并节点输出到共享状态"""
        self.node_outputs[node_id] = output


# ── 节点与边 ────────────────────────────────────────────────


class WorkflowNode(ABC):
    """工作流节点抽象基类

    每个节点封装一个可执行的逻辑单元，
    可以是 Agent 调用、函数执行、或子工作流。
    """

    def __init__(self, node_id: str, name: str = "") -> None:
        self.node_id = node_id
        self.name = name or node_id

    @abstractmethod
    async def execute(self, state: WorkflowState) -> dict[str, Any]:
        """执行节点逻辑，返回输出字典"""
        ...

    async def on_enter(self, state: WorkflowState) -> None:
        """节点执行前的钩子"""
        pass

    async def on_exit(self, state: WorkflowState, output: dict[str, Any]) -> None:
        """节点执行后的钩子"""
        pass


class AgentNode(WorkflowNode):
    """Agent 执行节点

    将 Agent 调用封装为工作流节点。
    """

    def __init__(
        self,
        node_id: str,
        agent: IAgentPlugin,
        intent: str = "",
        name: str = "",
    ) -> None:
        super().__init__(node_id, name)
        self.agent = agent
        self.intent = intent

    async def execute(self, state: WorkflowState) -> dict[str, Any]:
        """调用 Agent 处理任务"""
        task = AgentTask(
            trace_id=state.trace_id,
            source="workflow",
            target=self.agent.agent_id,
            intent=self.intent,
            payload={
                "user_input": state.user_input,
                **state.context,
            },
        )
        result = await self.agent.handle_task(task)
        return {
            "agent_id": self.agent.agent_id,
            "status": result.status,
            "output": result.output,
            "error": result.error,
            "latency_ms": result.latency_ms,
        }


class FunctionNode(WorkflowNode):
    """函数执行节点

    将任意 async 函数封装为工作流节点。
    """

    def __init__(
        self,
        node_id: str,
        func: Callable[[WorkflowState], Awaitable[dict[str, Any]]],
        name: str = "",
    ) -> None:
        super().__init__(node_id, name)
        self.func = func

    async def execute(self, state: WorkflowState) -> dict[str, Any]:
        return await self.func(state)


EdgeCondition = Callable[[WorkflowState], bool]
"""边条件函数：返回是否通过此边"""


@dataclass
class WorkflowEdge:
    """工作流边

    定义从一个节点到另一个（或多个）节点的连接关系。
    """

    from_node: str
    to_node: str
    condition: EdgeCondition | None = None


# ── DAG 工作流定义 ──────────────────────────────────────────


class WorkflowDefinition:
    """DAG 工作流定义

    通过 add_node 和 add_edge 构建有向无环图。
    """

    def __init__(self, workflow_id: str, name: str = "") -> None:
        self.workflow_id = workflow_id
        self.name = name or workflow_id
        self.nodes: dict[str, WorkflowNode] = {}
        self.edges: list[WorkflowEdge] = []
        self.entry_node: str = ""
        self._node_incoming: dict[str, list[str]] = {}
        self._node_outgoing: dict[str, list[str]] = {}

    def add_node(self, node: WorkflowNode) -> WorkflowDefinition:
        """添加节点"""
        self.nodes[node.node_id] = node
        if node.node_id not in self._node_incoming:
            self._node_incoming[node.node_id] = []
        if node.node_id not in self._node_outgoing:
            self._node_outgoing[node.node_id] = []
        return self

    def set_entry(self, node_id: str) -> WorkflowDefinition:
        """设置入口节点"""
        if node_id not in self.nodes:
            raise ValueError(f"节点 '{node_id}' 不存在")
        self.entry_node = node_id
        return self

    def add_edge(
        self,
        from_node: str,
        to_node: str,
        condition: EdgeCondition | None = None,
    ) -> WorkflowDefinition:
        """添加有向边"""
        if from_node not in self.nodes:
            raise ValueError(f"源节点 '{from_node}' 不存在")
        if to_node not in self.nodes:
            raise ValueError(f"目标节点 '{to_node}' 不存在")

        self.edges.append(WorkflowEdge(from_node, to_node, condition))
        self._node_outgoing.setdefault(from_node, []).append(to_node)
        self._node_incoming.setdefault(to_node, []).append(from_node)
        return self

    def add_parallel(
        self,
        from_node: str,
        to_nodes: list[str],
    ) -> WorkflowDefinition:
        """添加并行边（扇出）"""
        for to_node in to_nodes:
            self.add_edge(from_node, to_node)
        return self

    def add_conditional(
        self,
        from_node: str,
        branches: dict[str, EdgeCondition],
    ) -> WorkflowDefinition:
        """添加条件分支边

        branches: {target_node_id: condition_func}
        """
        for to_node, condition in branches.items():
            self.add_edge(from_node, to_node, condition)
        return self

    def validate(self) -> list[str]:
        """验证 DAG 合法性

        Returns:
            错误信息列表（空列表表示合法）
        """
        errors: list[str] = []

        # 检查入口节点
        if not self.entry_node:
            errors.append("未设置入口节点")
        elif self.entry_node not in self.nodes:
            errors.append(f"入口节点 '{self.entry_node}' 不存在")

        # 检查是否有节点不可达
        visited = self._dfs_reachable(self.entry_node)
        for node_id in self.nodes:
            if node_id not in visited:
                errors.append(f"节点 '{node_id}' 从入口不可达")

        # 检查环路
        if self._has_cycle():
            errors.append("工作流包含环路，DAG 不合法")

        return errors

    def _dfs_reachable(self, start: str) -> set[str]:
        """DFS 遍历可达节点"""
        visited: set[str] = set()
        stack = [start]
        while stack:
            node = stack.pop()
            if node in visited:
                continue
            visited.add(node)
            for neighbor in self._node_outgoing.get(node, []):
                stack.append(neighbor)
        return visited

    def _has_cycle(self) -> bool:
        """检测环路（基于 DFS）"""
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {node_id: WHITE for node_id in self.nodes}

        def dfs(node_id: str) -> bool:
            color[node_id] = GRAY
            for neighbor in self._node_outgoing.get(node_id, []):
                if color[neighbor] == GRAY:
                    return True
                if color[neighbor] == WHITE and dfs(neighbor):
                    return True
            color[node_id] = BLACK
            return False

        for node_id in self.nodes:
            if color[node_id] == WHITE:
                if dfs(node_id):
                    return True
        return False


# ── 工作流执行引擎 ──────────────────────────────────────────


class WorkflowEngine:
    """DAG 工作流执行引擎

    支持串行、并行、条件分支、Map-Reduce 等编排模式。
    """

    def __init__(self) -> None:
        self._logger = logger.bind(service="workflow_engine")

    async def execute(
        self,
        workflow: WorkflowDefinition,
        initial_state: WorkflowState,
        max_concurrent: int = 10,
    ) -> WorkflowResult:
        """执行工作流

        Args:
            workflow: DAG 工作流定义
            initial_state: 初始状态
            max_concurrent: 最大并行度

        Returns:
            WorkflowResult: 执行结果
        """
        start_time = time.time()

        # 验证工作流
        validation_errors = workflow.validate()
        if validation_errors:
            return WorkflowResult(
                workflow_id=workflow.workflow_id,
                status=WorkflowStatus.FAILED,
                final_state=initial_state,
                execution_time_ms=0.0,
                errors=validation_errors,
            )

        state = initial_state
        state.workflow_id = workflow.workflow_id

        # 执行 DAG：拓扑排序 + 并行执行
        completed_nodes: set[str] = set()
        pending_nodes: set[str] = {workflow.entry_node}
        semaphore = asyncio.Semaphore(max_concurrent)
        node_results: dict[str, dict[str, Any]] = {}
        execution_errors: list[str] = []

        try:
            while pending_nodes:
                # 选择所有入边已完成的节点（可并行执行）
                ready_nodes = [
                    nid
                    for nid in pending_nodes
                    if all(
                        parent in completed_nodes
                        for parent in workflow._node_incoming.get(nid, [])
                    )
                ]

                if not ready_nodes:
                    # 死锁：有 pending 但没有 ready
                    execution_errors.append("工作流死锁：存在循环依赖或缺失入边")
                    break

                # 从 pending 移除 ready 节点
                for nid in ready_nodes:
                    pending_nodes.discard(nid)

                # 并行执行 ready 节点
                tasks = [
                    asyncio.create_task(
                        self._execute_node_with_semaphore(
                            workflow.nodes[nid], state, semaphore
                        )
                    )
                    for nid in ready_nodes
                ]

                results = await asyncio.gather(*tasks, return_exceptions=True)

                for nid, result in zip(ready_nodes, results):
                    node_failed = False
                    if isinstance(result, Exception):
                        execution_errors.append(
                            f"节点 '{nid}' 执行失败: {result}"
                        )
                        state.errors.append({
                            "node_id": nid,
                            "error": str(result),
                            "timestamp": time.time(),
                        })
                        node_failed = True
                    else:
                        node_results[nid] = result
                        state.merge_node_output(nid, result)

                    completed_nodes.add(nid)

                    # 失败节点：将其失败状态注入 state，下游节点可选择处理
                    if node_failed:
                        state.set(f"_node_{nid}_failed", True)
                        # 不再继续传播后继节点
                        continue

                    # 计算下一批节点
                    for next_node in workflow._node_outgoing.get(nid, []):
                        edge = self._find_edge(workflow, nid, next_node)
                        if edge and edge.condition:
                            # 条件边：检查条件是否满足
                            condition_result = edge.condition(state)
                            if not condition_result:
                                continue
                        pending_nodes.add(next_node)

        except Exception as exc:
            execution_errors.append(f"工作流执行异常: {exc}")
            self._logger.error(
                "workflow_execution_error",
                workflow_id=workflow.workflow_id,
                error=str(exc),
            )

        execution_time_ms = (time.time() - start_time) * 1000

        status = (
            WorkflowStatus.FAILED
            if execution_errors
            else WorkflowStatus.COMPLETED
        )

        return WorkflowResult(
            workflow_id=workflow.workflow_id,
            status=status,
            final_state=state,
            execution_time_ms=execution_time_ms,
            errors=execution_errors,
            node_results=node_results,
        )

    async def _execute_node_with_semaphore(
        self,
        node: WorkflowNode,
        state: WorkflowState,
        semaphore: asyncio.Semaphore,
    ) -> dict[str, Any]:
        """在信号量限制下执行节点"""
        async with semaphore:
            await node.on_enter(state)
            start = time.time()
            output: dict[str, Any] = {}
            try:
                output = await node.execute(state)
                output["_execution_time_ms"] = (time.time() - start) * 1000
            finally:
                await node.on_exit(state, output)
            return output

    def _find_edge(
        self, workflow: WorkflowDefinition, from_node: str, to_node: str
    ) -> WorkflowEdge | None:
        """查找指定边"""
        for edge in workflow.edges:
            if edge.from_node == from_node and edge.to_node == to_node:
                return edge
        return None


@dataclass
class WorkflowResult:
    """工作流执行结果"""

    workflow_id: str
    status: WorkflowStatus
    final_state: WorkflowState
    execution_time_ms: float
    errors: list[str] = field(default_factory=list)
    node_results: dict[str, Any] = field(default_factory=dict)

    @property
    def is_success(self) -> bool:
        return self.status == WorkflowStatus.COMPLETED and not self.errors

    @property
    def output(self) -> dict[str, Any]:
        """获取最终输出（通常来自最后一个节点的输出）"""
        return self.final_state.node_outputs


# ── 预置编排模式 ────────────────────────────────────────────


class WorkflowPatterns:
    """预置工作流编排模式工厂

    提供常见的多 Agent 协作模式快速创建。
    """

    @staticmethod
    def chain(
        name: str,
        nodes: list[WorkflowNode],
    ) -> WorkflowDefinition:
        """创建串行链式工作流

        Node1 -> Node2 -> Node3 -> ...
        """
        if not nodes:
            raise ValueError("节点列表不能为空")

        wf = WorkflowDefinition(name, name)
        for node in nodes:
            wf.add_node(node)

        wf.set_entry(nodes[0].node_id)
        for i in range(len(nodes) - 1):
            wf.add_edge(nodes[i].node_id, nodes[i + 1].node_id)

        return wf

    @staticmethod
    def parallel_fan_out(
        name: str,
        entry: WorkflowNode,
        parallel_nodes: list[WorkflowNode],
        merge: WorkflowNode,
    ) -> WorkflowDefinition:
        """创建并行扇出-归并工作流

              -> Node2 ->
        Node1 -> -> Node3 -> Node4
              -> Node5 ->
        """
        wf = WorkflowDefinition(name, name)
        wf.add_node(entry)
        for node in parallel_nodes:
            wf.add_node(node)
        wf.add_node(merge)

        wf.set_entry(entry.node_id)
        wf.add_parallel(entry.node_id, [n.node_id for n in parallel_nodes])
        for node in parallel_nodes:
            wf.add_edge(node.node_id, merge.node_id)

        return wf

    @staticmethod
    def conditional_branch(
        name: str,
        entry: WorkflowNode,
        branches: dict[str, tuple[EdgeCondition, WorkflowNode]],
        default: WorkflowNode | None = None,
    ) -> WorkflowDefinition:
        """创建条件分支工作流

                    -> Branch A (condition_a)
        Entry Node -> -> Branch B (condition_b)
                    -> Default
        """
        wf = WorkflowDefinition(name, name)
        wf.add_node(entry)
        for branch_name, (condition, node) in branches.items():
            wf.add_node(node)
            wf.add_edge(entry.node_id, node.node_id, condition)

        if default:
            wf.add_node(default)
            wf.add_edge(entry.node_id, default.node_id)

        wf.set_entry(entry.node_id)
        return wf
