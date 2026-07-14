"""
M1 Agent 集群 - 任务相关模型

任务提交、任务状态查询、分身池、DAG 编排等任务相关的 Pydantic 模型。
包含从 shared_models 迁移的 DAG 核心模型。
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field

from models.base import M1BaseModel
from models.enums import SecurityClassification


class SubmitTaskRequest(M1BaseModel):
    """提交任务请求。

    字段边界校验：
    - user_input: 1~10000 字符
    - task_id: 最长 64 字符，允许空字符串（服务端自动生成）
    - trace_id: 最长 64 字符
    - model: 最长 128 字符
    - priority: 1~10 整数
    """

    user_input: str = Field(..., min_length=1, max_length=10000)
    task_id: str = Field(default="", max_length=64)
    trace_id: str = Field(default="", max_length=64)
    model: str = Field(default="", max_length=128)
    budget: dict[str, Any] = Field(default_factory=dict)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    priority: int = Field(default=5, ge=1, le=10)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SubmitTaskResponse(M1BaseModel):
    """提交任务响应。"""

    status: str
    task_id: str = ""
    result: dict[str, Any] = Field(default_factory=dict)
    trace_id: str = ""
    agents_deployed: list[str] = Field(default_factory=list)
    budget_consumed: float = 0.0


class TaskStatusResponse(M1BaseModel):
    """任务状态响应。"""

    task_id: str
    goal: str = ""
    status: str
    completion_rate: float = 0.0
    plans: list[dict[str, Any]] = Field(default_factory=list)
    agents: list[dict[str, Any]] = Field(default_factory=list)
    active: bool = False


class TaskInfo(M1BaseModel):
    """任务信息模型。

    用于在各模块间传递任务核心信息的结构化模型，
    替代松散的 dict[str, Any] 以提升类型安全性。
    """

    task_id: str
    trace_id: str = ""
    intent: str = ""
    status: str = "pending"  # pending / running / completed / failed / timeout
    target_agent: str = ""
    priority: int = Field(default=5, ge=1, le=10)
    created_at: float = 0.0
    completed_at: float | None = None
    latency_ms: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class CloneRequest(M1BaseModel):
    """分身申请请求。

    字段边界校验：
    - parent_agent_id: 1~64 字符
    - clone_type: 枚举值（scout/planner/writer/reviewer）
    - ttl: 0~86400 秒（0 表示使用默认 TTL）
    """

    parent_agent_id: str = Field(..., min_length=1, max_length=64)
    clone_type: Literal["scout", "planner", "writer", "reviewer"] = "scout"
    task_id: str = Field(default="", max_length=64)
    capabilities: list[str] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    ttl: int = Field(default=0, ge=0, le=86400)  # 0 表示使用默认 TTL


class CloneReleaseRequest(M1BaseModel):
    """分身释放请求。

    字段边界校验：
    - clone_id: 1~64 字符
    """

    clone_id: str = Field(..., min_length=1, max_length=64)


class ChatRequest(M1BaseModel):
    """同步对话请求。

    用于 /api/v1/chat 端点，替代直接读取 request.json() 的方式。
    字段边界校验：
    - user_input: 1~10000 字符
    - trace_id: 最长 64 字符
    - model: 最长 128 字符
    """

    user_input: str = Field(..., min_length=1, max_length=10000)
    trace_id: str = Field(default="", max_length=64)
    model: str = Field(default="", max_length=128)


class ChatStreamRequest(M1BaseModel):
    """流式对话请求。

    用于 /api/v1/chat/stream 端点，替代直接读取 request.json() 的方式。
    字段边界校验：
    - user_input: 1~10000 字符
    - trace_id: 最长 64 字符
    - voice_polish: 是否启用人格润色（默认 True）
    """

    user_input: str = Field(..., min_length=1, max_length=10000)
    trace_id: str = Field(default="", max_length=64)
    voice_polish: bool = True


# ══════════════════════════════════════════════════════════
# DAG 核心模型（从 shared_models 迁移）
# ══════════════════════════════════════════════════════════


@dataclass
class DAGNode:
    """DAG节点：一个可执行的原子任务单元"""
    node_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    task_id: str = ""
    description: str = ""
    assigned_agent: str = ""
    dependencies: list[str] = field(default_factory=list)  # 前置node_id列表
    status: str = "pending"  # pending → running → completed | failed | skipped
    priority: int = 5
    security_level: SecurityClassification = SecurityClassification.INTERNAL
    result_summary: str = ""
    error: str = ""
    started_at: float = 0.0
    completed_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DAGEdge:
    """DAG边：节点间的数据/控制依赖"""
    source_node: str = ""
    target_node: str = ""
    edge_type: str = "data"  # data | control | fan_out
    condition: str = ""      # 可选的条件表达式


class TaskDAG(BaseModel):
    """
    任务有向无环图（吸收Dify可视化编排 + LangGraph状态机）

    标准格式输出，供工作台渲染。
    支持拓扑排序、并行检测、关键路径分析。
    """
    dag_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    root_task_id: str = ""
    goal: str = ""
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    security_level: SecurityClassification = SecurityClassification.INTERNAL
    created_at: float = Field(default_factory=time.time)
    version: int = 1

    def add_node(self, node: DAGNode) -> None:
        self.nodes.append({
            "node_id": node.node_id,
            "task_id": node.task_id,
            "description": node.description,
            "assigned_agent": node.assigned_agent,
            "dependencies": node.dependencies,
            "status": node.status,
            "priority": node.priority,
            "security_level": node.security_level.value,
            "result_summary": node.result_summary,
            "error": node.error,
            "started_at": node.started_at,
            "completed_at": node.completed_at,
            "metadata": node.metadata,
        })

    def add_edge(self, edge: DAGEdge) -> None:
        self.edges.append({
            "source_node": edge.source_node,
            "target_node": edge.target_node,
            "edge_type": edge.edge_type,
            "condition": edge.condition,
        })

    def topological_sort(self) -> list[str]:
        """拓扑排序，返回可执行的节点ID序列

        Returns:
            按依赖关系排序的node_id列表。存在环时返回部分排序。
        """
        in_degree: dict[str, int] = defaultdict(int)
        adj: dict[str, list[str]] = defaultdict(list)

        for node in self.nodes:
            nid = node.get("node_id", "")
            in_degree[nid] = 0

        for edge in self.edges:
            src = edge.get("source_node", "")
            tgt = edge.get("target_node", "")
            adj[src].append(tgt)
            in_degree[tgt] = in_degree.get(tgt, 0) + 1

        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        result = []

        while queue:
            queue.sort()  # 确定性排序
            current = queue.pop(0)
            result.append(current)
            for neighbor in adj[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        return result

    def get_ready_nodes(self) -> list[dict]:
        """获取当前可执行的节点（所有前置依赖已完成）"""
        completed = {n["node_id"] for n in self.nodes if n["status"] in ("completed", "skipped")}
        ready = []
        for node in self.nodes:
            if node["status"] != "pending":
                continue
            deps = node.get("dependencies", [])
            if all(d in completed for d in deps):
                ready.append(node)
        return sorted(ready, key=lambda n: -n.get("priority", 5))

    def get_critical_path(self) -> list[str]:
        """获取关键路径（最长执行路径）"""
        node_map = {n["node_id"]: n for n in self.nodes}
        durations: dict[str, float] = {}
        for n in self.nodes:
            if n["status"] in ("completed", "failed", "skipped"):
                s = n.get("started_at", 0)
                c = n.get("completed_at", 0)
                durations[n["node_id"]] = max(c - s, 0)
            else:
                durations[n["node_id"]] = 0  # 未完成的节点用0估算

        adj: dict[str, list[str]] = defaultdict(list)
        for edge in self.edges:
            adj[edge["source_node"]].append(edge["target_node"])

        memo: dict[str, float] = {}

        def _longest(nid: str) -> float:
            if nid in memo:
                return memo[nid]
            children = adj.get(nid, [])
            if not children:
                memo[nid] = durations.get(nid, 0)
                return memo[nid]
            best = max(_longest(c) for c in children)
            memo[nid] = durations.get(nid, 0) + best
            return memo[nid]

        sources = [n["node_id"] for n in self.nodes if not n.get("dependencies")]
        for s in sources:
            _longest(s)

        return list(memo.keys())

    def completion_rate(self) -> float:
        """DAG整体完成率"""
        if not self.nodes:
            return 0.0
        done = sum(1 for n in self.nodes if n["status"] in ("completed", "skipped"))
        return done / len(self.nodes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dag_id": self.dag_id,
            "root_task_id": self.root_task_id,
            "goal": self.goal,
            "nodes": self.nodes,
            "edges": self.edges,
            "security_level": self.security_level.value,
            "created_at": self.created_at,
            "version": self.version,
            "completion_rate": round(self.completion_rate(), 4),
        }


# ══════════════════════════════════════════════════════════
# TypedDict 核心数据结构定义
# ══════════════════════════════════════════════════════════


class TaskInfoDict(TypedDict):
    """任务信息 TypedDict

    用于在各模块间传递任务核心信息的结构化字典，
    替代松散的 dict[str, Any] 以提升类型安全性。
    """
    task_id: str
    trace_id: str
    intent: str
    status: str                    # pending / running / completed / failed / timeout
    target_agent: str
    priority: int
    created_at: float
    completed_at: float | None
    latency_ms: float
    metadata: dict[str, Any]


class TraceSpanDict(TypedDict):
    """追踪 Span TypedDict

    用于链路追踪系统的 Span 结构化数据。
    """
    span_id: str
    parent_span_id: str
    name: str
    start_time: float              # 秒级时间戳
    end_time: float | None         # 秒级时间戳
    duration_ms: float
    status: str                    # ok / error
    error_message: str | None
    attributes: dict[str, Any]
    events: list[dict[str, Any]]
