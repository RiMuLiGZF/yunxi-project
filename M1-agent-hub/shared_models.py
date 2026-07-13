"""
云汐内核 V10.0 — 子Agent核心数据模型与共享类型

所有8个子Agent共享的数据模型定义，包括：
- TaskDAG：任务有向无环图
- SubAgentIdentity：子Agent身份模型
- AgentRole：Agent角色枚举
- SecurityClassification：涉密分级
- LoadScore：负载评分
- TeamComposition：组队方案
- ArbitrationResult：仲裁结果
"""

from __future__ import annotations

import hashlib
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


# ══════════════════════════════════════════════════════════
# 枚举与常量
# ══════════════════════════════════════════════════════════


class AgentRole(str, Enum):
    """Agent角色模型（吸收CrewAI角色隔离）"""
    SUPERVISOR = "supervisor"    # 总管：编排全局任务
    EXECUTOR = "executor"        # 执行：承接子任务
    REVIEWER = "reviewer"        # 审查：审查执行结果
    EXTERNAL = "external"        # 外部：对接外部系统


class SecurityClassification(IntEnum):
    """涉密四级分级（吸收安全审计要求）"""
    PUBLIC = 0       # 公开
    INTERNAL = 1     # 内部
    CONFIDENTIAL = 2 # 机密
    TOP_SECRET = 3  # 绝密


class AgentLifeState(str, Enum):
    """Agent全生命周期状态（吸收LangGraph显式状态机）"""
    CREATED = "created"
    ACTIVATING = "activating"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DRAINING = "draining"       # 优雅终止中
    TERMINATED = "terminated"
    ARCHIVED = "archived"
    FAILED = "failed"


class SchedulingDecision(str, Enum):
    """端云调度决策"""
    LOCAL_FIRST = "local_first"
    AUTO = "auto"
    CLOUD_FIRST = "cloud_first"


class ArbitrationLevel(IntEnum):
    """三级仲裁（吸收AutoGen多Agent仲裁）"""
    AUTO_RESOLVE = 1   # 自动解决
    NEGOTIATE = 2       # 协商解决
    HUMAN_ESCALATE = 3  # 人工介入


class CloneType(str, Enum):
    """分身类型（吸收Claude Code委派分身）"""
    SCOUT = "scout"           # 勘探分身
    PLANNER = "planner"       # 规划分身
    WRITER = "writer"         # 撰写分身
    REVIEWER = "reviewer"     # 审查分身


# ══════════════════════════════════════════════════════════
# TaskDAG — 任务有向无环图
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
# SubAgent 基础模型
# ══════════════════════════════════════════════════════════


class SubAgentIdentity(BaseModel):
    """子Agent身份模型"""
    agent_id: str = ""
    name: str = ""
    role: AgentRole = AgentRole.EXECUTOR
    version: str = "1.0.0"
    capabilities: list[str] = Field(default_factory=list)
    security_clearance: SecurityClassification = SecurityClassification.INTERNAL


@dataclass
class LoadScore:
    """
    负载评分（综合VRAM/CPU/电量/网络）

    评分算法为技术秘密，具体权重参数不在代码注释中暴露。
    """
    agent_id: str = ""
    vram_score: float = 0.0
    cpu_score: float = 0.0
    battery_score: float = 0.0
    network_score: float = 0.0
    composite: float = 0.0  # 综合评分（内部聚合）
    timestamp: float = field(default_factory=time.time)


class TeamComposition(BaseModel):
    """动态组队方案"""
    team_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    task_id: str = ""
    members: list[str] = Field(default_factory=list)  # agent_id列表
    roles: dict[str, str] = Field(default_factory=dict)  # agent_id -> role
    formation_reason: str = ""
    security_level: SecurityClassification = SecurityClassification.INTERNAL
    created_at: float = Field(default_factory=time.time)


class ArbitrationRequest(BaseModel):
    """仲裁请求"""
    request_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    conflict_type: str = ""  # resource_deadlock | priority_conflict | dependency_cycle | timeout
    involved_agents: list[str] = Field(default_factory=list)
    task_ids: list[str] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)


class ArbitrationResult(BaseModel):
    """仲裁结果"""
    request_id: str = ""
    level: ArbitrationLevel = ArbitrationLevel.AUTO_RESOLVE
    decision: str = ""  # retry | abort | reroute | escalate | negotiate
    assigned_agent: str = ""
    reason: str = ""
    actions: list[dict[str, Any]] = Field(default_factory=list)
    timestamp: float = Field(default_factory=time.time)


# ══════════════════════════════════════════════════════════
# 分身池模型
# ══════════════════════════════════════════════════════════


class CloneIdentity(BaseModel):
    """临时分身身份"""
    clone_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    parent_agent_id: str = ""
    clone_type: CloneType = CloneType.SCOUT
    task_id: str = ""
    capabilities: list[str] = Field(default_factory=list)
    security_clearance: SecurityClassification = SecurityClassification.PUBLIC  # 分身默认最低权限
    created_at: float = Field(default_factory=time.time)
    ttl: int = 300  # 秒，分身最大存活时间
    minimized_context: dict[str, Any] = Field(default_factory=dict)  # 最小信息下发


# ══════════════════════════════════════════════════════════
# M4 底层执行模式（M4全局标准 v2.6.1）
# ══════════════════════════════════════════════════════════


class M4ExecutionMode(str, Enum):
    """M4 六大底层执行模式（全局标准命名）

    决定「做什么类型的事」，与 M1 调度策略（STRAT-A~F）属于不同层级。
    """
    DOCUMENT = "DOCUMENT"       # 文档写作/处理
    CODING = "CODING"           # 代码开发/评审
    REVIEW = "REVIEW"           # 评审/复盘
    DESIGN = "DESIGN"           # 设计/规划
    MENTAL = "MENTAL"           # 情绪陪伴/心理支持
    PLANNING = "PLANNING"       # 计划/任务管理


class UserScene(str, Enum):
    """上层用户可见场景（六场景）

    用户视角的场景分类，基于 M4 底层模式叠加业务语义。
    """
    WORK_DEV = "work_dev"               # 工作开发
    STUDY_PLAN = "study_plan"           # 学业规划
    REVIEW_SUMMARY = "review_summary"   # 复盘总结
    RELATIONSHIP = "relationship"       # 人际关系
    EMOTION_COMPANION = "emotion_companion"  # 情绪陪伴
    LIFE_MANAGEMENT = "life_management"     # 生活综合管理


class SchedulingStrategy(str, Enum):
    """M1 调度策略（STRAT-A~F）

    决定「用什么方式组队执行」，与 M4 底层模式正交。
    """
    STRAT_A = "STRAT_A"  # 简单任务直调
    STRAT_B = "STRAT_B"  # 复杂任务DAG编排
    STRAT_C = "STRAT_C"  # 端云协同计算
    STRAT_D = "STRAT_D"  # 涉密内容处理
    STRAT_E = "STRAT_E"  # 多Agent冲突仲裁
    STRAT_F = "STRAT_F"  # 断点续跑恢复


# ══════════════════════════════════════════════════════════
# 命名映射表：底层模式 ↔ 上层场景 ↔ 调度策略
# ══════════════════════════════════════════════════════════

# M4 底层模式 → 上层用户场景（一对多，主映射为一对一）
MODE_TO_SCENE_PRIMARY: dict[M4ExecutionMode, UserScene] = {
    M4ExecutionMode.CODING: UserScene.WORK_DEV,
    M4ExecutionMode.DOCUMENT: UserScene.STUDY_PLAN,
    M4ExecutionMode.REVIEW: UserScene.REVIEW_SUMMARY,
    M4ExecutionMode.DESIGN: UserScene.RELATIONSHIP,
    M4ExecutionMode.MENTAL: UserScene.EMOTION_COMPANION,
    M4ExecutionMode.PLANNING: UserScene.LIFE_MANAGEMENT,
}

# 上层用户场景 → M4 底层模式（反向映射）
SCENE_TO_MODE: dict[UserScene, M4ExecutionMode] = {
    UserScene.WORK_DEV: M4ExecutionMode.CODING,
    UserScene.STUDY_PLAN: M4ExecutionMode.DOCUMENT,
    UserScene.REVIEW_SUMMARY: M4ExecutionMode.REVIEW,
    UserScene.RELATIONSHIP: M4ExecutionMode.DESIGN,
    UserScene.EMOTION_COMPANION: M4ExecutionMode.MENTAL,
    UserScene.LIFE_MANAGEMENT: M4ExecutionMode.PLANNING,
}

# 场景中文名称映射
SCENE_NAMES_ZH: dict[UserScene, str] = {
    UserScene.WORK_DEV: "工作开发",
    UserScene.STUDY_PLAN: "学业规划",
    UserScene.REVIEW_SUMMARY: "复盘总结",
    UserScene.RELATIONSHIP: "人际关系",
    UserScene.EMOTION_COMPANION: "情绪陪伴",
    UserScene.LIFE_MANAGEMENT: "生活综合管理",
}

# M4 模式中文名称映射
MODE_NAMES_ZH: dict[M4ExecutionMode, str] = {
    M4ExecutionMode.CODING: "代码开发",
    M4ExecutionMode.DOCUMENT: "文档写作",
    M4ExecutionMode.REVIEW: "评审复盘",
    M4ExecutionMode.DESIGN: "设计规划",
    M4ExecutionMode.MENTAL: "情绪支持",
    M4ExecutionMode.PLANNING: "计划管理",
}


# ══════════════════════════════════════════════════════════
# 云汐人格偏好模型
# ══════════════════════════════════════════════════════


class PersonalityPreference(BaseModel):
    """云汐人格用户偏好配置

    存储在 M5 潮汐记忆系统（L2 海湾层），标记为 CONFIDENTIAL 级。
    """
    user_id: str = ""
    tone_temperature: str = "default"   # colder / default / warmer
    formality_level: str = "medium"     # casual / medium / formal
    verbosity: str = "balanced"         # concise / balanced / detailed
    humor_level: str = "medium"         # low / medium / high
    nickname: str | None = None         # 用户自定义称呼
    updated_at: float = Field(default_factory=time.time)
    version: int = 1


# ══════════════════════════════════════════════════════════
# Agent 联邦调度系统（V11.0-FEDERATION）
# ══════════════════════════════════════════════════════════


class ExternalAgentType(str, Enum):
    """外部 Agent 类型"""
    LLM = "llm"              # 通用大模型
    CODE = "code"            # 代码专用
    DESIGN = "design"        # 设计/创意
    SEARCH = "search"        # 搜索/研究
    TOOL = "tool"            # 工具调用
    CUSTOM = "custom"        # 自定义


class AgentPrivacyLevel(str, Enum):
    """外部 Agent 隐私等级"""
    STANDARD = "standard"    # 标准（数据可能经过服务商）
    ENHANCED = "enhanced"    # 增强（企业级隐私协议）
    LOCAL_ONLY = "local_only"  # 本地（数据不出境）


class ConnectionType(str, Enum):
    """连接类型"""
    API_KEY = "api_key"
    OAUTH = "oauth"
    LOCAL = "local"


class LicenseType(str, Enum):
    """Agent 许可证类型"""
    MIT = "MIT"                   # MIT 宽松协议
    APACHE = "Apache-2.0"         # Apache 2.0
    BSD = "BSD-3-Clause"          # BSD 3-Clause
    GPL_2 = "GPL-2.0"             # GPL v2（传染性）
    GPL_3 = "GPL-3.0"             # GPL v3（传染性）
    AGPL = "AGPL"                 # AGPL（强传染性）
    LGPL = "LGPL"                 # LGPL（弱传染性）
    PROPRIETARY = "Proprietary"   # 商业/专有
    OTHER = "Other"               # 其他


class UserPreferenceMode(str, Enum):
    """用户联邦调度偏好模式"""
    QUALITY_FIRST = "quality_first"    # 质量优先
    BALANCED = "balanced"              # 平衡模式
    COST_FIRST = "cost_first"          # 成本优先
    SPEED_FIRST = "speed_first"        # 速度优先


class ComparisonOutputMode(str, Enum):
    """多 Agent 对比输出模式"""
    BEST_ONLY = "best_only"      # 单优模式
    FUSION = "fusion"            # 融合模式
    SIDE_BY_SIDE = "side_by_side"  # 对比模式


class CostModel(BaseModel):
    """外部 Agent 成本模型"""
    input_per_1k: float = 0.0     # 输入单价（美元/1K tokens）
    output_per_1k: float = 0.0    # 输出单价（美元/1K tokens）
    currency: str = "USD"
    per_request: float = 0.0      # 每次请求固定费用


class ExternalAgentProfile(BaseModel):
    """外部 Agent 能力画像"""
    agent_id: str = ""
    display_name: str = ""
    provider: str = ""              # 服务商名称
    agent_type: ExternalAgentType = ExternalAgentType.LLM
    capabilities: list[str] = Field(default_factory=list)  # 能力标签
    languages: list[str] = Field(default_factory=lambda: ["zh", "en"])
    response_speed: str = "medium"  # fast / medium / slow
    quality_rating: float = 4.0     # 1-5 质量评分
    cost_model: CostModel = Field(default_factory=CostModel)
    privacy_level: AgentPrivacyLevel = AgentPrivacyLevel.STANDARD
    connection_type: ConnectionType = ConnectionType.API_KEY
    license: LicenseType = LicenseType.OTHER
    status: str = "active"          # active / inactive / error
    config: dict[str, Any] = Field(default_factory=dict)  # 连接配置（不含密钥）
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    last_health_check: float | None = None


class FederationDecision(BaseModel):
    """联邦调度决策结果"""
    use_external: bool = False
    selected_agent_id: str = ""
    selected_agent_name: str = ""
    decision_reason: str = ""
    estimated_cost: float = 0.0     # 预估费用（美元）
    estimated_latency: str = "medium"
    privacy_check: str = "passed"   # passed / warning / blocked
    quality_score: float = 0.0      # 综合评分 0-100
    fallback_agent_id: str = ""     # 备选 Agent


class AgentResultItem(BaseModel):
    """单 Agent 结果条目"""
    agent_id: str = ""
    agent_name: str = ""
    output: str = ""
    quality_score: float = 0.0      # 0-100
    cost: float = 0.0
    latency_ms: float = 0.0
    success: bool = True
    error: str = ""


class MultiAgentComparison(BaseModel):
    """多 Agent 对比结果"""
    task_id: str = ""
    results: list[AgentResultItem] = Field(default_factory=list)
    best_result_index: int = 0
    fusion_output: str = ""         # 融合输出（可选）
    output_mode: ComparisonOutputMode = ComparisonOutputMode.BEST_ONLY
    comparison_summary: str = ""
    total_cost: float = 0.0


class CostRecord(BaseModel):
    """成本记录"""
    record_id: str = ""
    task_id: str = ""
    agent_id: str = ""
    agent_name: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    currency: str = "USD"
    timestamp: float = Field(default_factory=time.time)
    task_type: str = ""
    success: bool = True


class FederationBudget(BaseModel):
    """联邦调度预算"""
    monthly_budget: float = 10.0    # 月度预算（美元）
    spent_this_month: float = 0.0   # 本月已花费
    alert_threshold_50: bool = False
    alert_threshold_80: bool = False
    alert_threshold_100: bool = False
    currency: str = "USD"
    last_reset_month: str = ""      # YYYY-MM


class PrivacyScanResult(BaseModel):
    """隐私扫描结果"""
    passed: bool = True
    risk_level: str = "none"        # none / low / medium / high
    detections: list[dict[str, Any]] = Field(default_factory=list)
    sanitized_content: str = ""     # 脱敏后的内容
    blocked: bool = False
    block_reason: str = ""
    summary: str = ""
