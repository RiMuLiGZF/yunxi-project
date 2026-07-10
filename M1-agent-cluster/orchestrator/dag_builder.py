"""
云汐内核 - TaskDAG 构建器

将用户请求（目标 + 上下文）解析、分解为有向无环任务图（TaskDAG）。
支持顺序执行、fan_out扇出并行、条件分支（control边）等编排模式。

核心职责：
- 解析用户意图，评估任务复杂度
- 规划DAG节点与边
- 基于能力匹配为节点分配Agent
"""

from __future__ import annotations

import re
import uuid
from typing import Any

import structlog
from shared_models import DAGEdge, DAGNode, SecurityClassification, TaskDAG

logger = structlog.get_logger(__name__)


# ══════════════════════════════════════════════════════════
# 复杂度评估关键词词典
# ══════════════════════════════════════════════════════════

# 高复杂度关键词：暗示需要多阶段、多Agent协作
_COMPLEXITY_KEYWORDS_COMPLEX: list[str] = [
    "分析", "调研", "对比", "评估", "报告", "评审",
    "多步", "多阶段", "全流程", "端到端", "完整方案",
    "架构", "设计", "系统", "平台", "框架",
    "数据采集", "训练", "部署", "测试",
    "报告生成", "竞品分析", "市场调研",
]

# 中等复杂度关键词：暗示需要2-4个步骤
_COMPLEXITY_KEYWORDS_MEDIUM: list[str] = [
    "整理", "汇总", "翻译", "改写", "总结",
    "优化", "修复", "调试", "重构",
    "方案", "计划", "计划书",
    "批量", "多个", "一组",
]

# 简单任务关键词：单步操作
_COMPLEXITY_KEYWORDS_SIMPLE: list[str] = [
    "查", "搜索", "查询", "翻译一句", "解释",
    "回答", "说明", "是什么", "怎么做",
]


class DAGBuilder:
    """TaskDAG 构建器

    接收用户请求（goal + context），解析意图，评估复杂度，
    规划DAG节点与边，基于能力匹配分配Agent，最终生成完整的 TaskDAG。

    使用方式::

        builder = DAGBuilder()
        dag = builder.build_dag(
            goal="完成竞品分析报告",
            context={"industry": "AI"},
            available_agents=[
                {"agent_id": "agent.research", "capabilities": ["research", "analysis"]},
                {"agent_id": "agent.writer", "capabilities": ["writing", "summary"]},
            ],
        )

    Attributes:
        _logger: structlog 绑定日志器
    """

    def __init__(self) -> None:
        self._logger = logger.bind(component="DAGBuilder")

    # ──────────────────────────────────────────────────────
    # 公开接口
    # ──────────────────────────────────────────────────────

    def build_dag(
        self,
        goal: str,
        context: dict[str, Any],
        available_agents: list[dict[str, Any]],
    ) -> TaskDAG:
        """构建完整的 TaskDAG

        分析目标复杂度，规划节点与边，分配Agent，生成可执行的DAG。

        Args:
            goal: 用户描述的任务目标（自然语言）
            context: 附加上下文信息（行业、约束、偏好等）
            available_agents: 可用Agent列表，每个Agent包含
                agent_id, capabilities 等字段

        Returns:
            构建完成的 TaskDAG 实例
        """
        self._logger.info(
            "build_dag_start",
            goal=goal[:80],
            agent_count=len(available_agents),
        )

        # 第一步：评估复杂度
        complexity: str = self._analyze_complexity(goal, context)
        self._logger.debug("complexity_assessed", complexity=complexity)

        # 第二步：规划节点
        nodes: list[DAGNode] = self._plan_nodes(goal, complexity, available_agents)
        self._logger.debug("nodes_planned", node_count=len(nodes))

        # 第三步：规划边（节点间的依赖关系）
        edges: list[DAGEdge] = self._plan_edges(nodes)
        self._logger.debug("edges_planned", edge_count=len(edges))

        # 第四步：基于能力匹配为节点分配Agent
        self._assign_agents(nodes, available_agents)
        self._logger.debug("agents_assigned")

        # 第五步：组装 TaskDAG
        dag = TaskDAG(
            root_task_id=uuid.uuid4().hex[:16],
            goal=goal,
        )
        for node in nodes:
            dag.add_node(node)
        for edge in edges:
            dag.add_edge(edge)

        self._logger.info(
            "build_dag_complete",
            dag_id=dag.dag_id,
            node_count=len(dag.nodes),
            edge_count=len(dag.edges),
        )
        return dag

    # ──────────────────────────────────────────────────────
    # 复杂度分析
    # ──────────────────────────────────────────────────────

    def _analyze_complexity(
        self,
        goal: str,
        context: dict[str, Any],
    ) -> str:
        """分析任务复杂度

        基于关键词匹配、上下文深度、显式提示三个维度综合判断。

        Args:
            goal: 用户描述的任务目标
            context: 附加上下文

        Returns:
            复杂度等级，取值为 "simple" | "medium" | "complex"
        """
        # 显式复杂度提示优先
        explicit: str = context.get("complexity", "")
        if explicit in ("simple", "medium", "complex"):
            return explicit

        goal_lower = goal.lower()

        # 统计关键词命中
        complex_hits = sum(
            1 for kw in _COMPLEXITY_KEYWORDS_COMPLEX if kw in goal_lower
        )
        medium_hits = sum(
            1 for kw in _COMPLEXITY_KEYWORDS_MEDIUM if kw in goal_lower
        )
        simple_hits = sum(
            1 for kw in _COMPLEXITY_KEYWORDS_SIMPLE if kw in goal_lower
        )

        # 上下文丰富度加分
        context_depth = len(context)
        if context_depth > 5:
            complex_hits += 1
        elif context_depth > 2:
            medium_hits += 1

        # 综合判定
        if complex_hits >= 2:
            return "complex"
        elif complex_hits >= 1 or medium_hits >= 2:
            return "medium"
        elif medium_hits >= 1:
            return "medium"
        elif simple_hits >= 1:
            return "simple"
        else:
            # 默认中等复杂度
            return "medium"

    # ──────────────────────────────────────────────────────
    # 节点规划
    # ──────────────────────────────────────────────────────

    def _plan_nodes(
        self,
        goal: str,
        complexity: str,
        agents: list[dict[str, Any]],
    ) -> list[DAGNode]:
        """根据目标和复杂度规划DAG节点

        根据复杂度等级生成不同规模的节点集合：
        - simple: 1-2个节点，顺序执行
        - medium: 3-5个节点，支持fan_out扇出
        - complex: 6+个节点，支持fan_out扇出和条件分支

        Args:
            goal: 用户描述的任务目标
            complexity: 复杂度等级
            agents: 可用Agent列表（用于判断是否需要fan_out）

        Returns:
            规划好的DAGNode列表
        """
        nodes: list[DAGNode] = []

        if complexity == "simple":
            nodes = self._plan_simple_nodes(goal)
        elif complexity == "medium":
            nodes = self._plan_medium_nodes(goal, agents)
        else:
            nodes = self._plan_complex_nodes(goal, agents)

        # 为每个节点设置统一的task_id前缀
        for i, node in enumerate(nodes):
            node.task_id = f"task_{i:03d}"

        return nodes

    def _plan_simple_nodes(self, goal: str) -> list[DAGNode]:
        """规划简单任务的节点（1-2个节点，顺序执行）

        Args:
            goal: 任务目标描述

        Returns:
            1-2个顺序执行的DAGNode
        """
        # 节点1：直接执行目标任务
        exec_node = DAGNode(
            description=f"执行任务：{goal}",
            priority=5,
            status="pending",
            metadata={"complexity": "simple", "phase": "execution"},
        )
        return [exec_node]

    def _plan_medium_nodes(
        self,
        goal: str,
        agents: list[dict[str, Any]],
    ) -> list[DAGNode]:
        """规划中等复杂度任务的节点（3-5个节点，可能包含fan_out）

        典型编排模式：准备 -> 并行执行（fan_out） -> 汇总

        Args:
            goal: 任务目标描述
            agents: 可用Agent列表

        Returns:
            3-5个DAGNode
        """
        nodes: list[DAGNode] = []

        # 节点1：准备与上下文收集
        prep_node = DAGNode(
            description=f"准备上下文与资源：{goal}",
            priority=8,
            status="pending",
            metadata={"complexity": "medium", "phase": "preparation"},
        )
        nodes.append(prep_node)

        # 判断是否需要fan_out扇出
        needs_fan_out = len(agents) >= 2
        fan_out_targets: list[str] = []

        if needs_fan_out:
            # fan_out：按Agent能力拆分为并行子任务
            for idx, agent in enumerate(agents[:3]):  # 最多扇出到3个并行节点
                fan_node = DAGNode(
                    description=f"并行子任务{idx + 1}（{goal}）",
                    priority=6,
                    status="pending",
                    dependencies=[prep_node.node_id],
                    metadata={
                        "complexity": "medium",
                        "phase": "parallel_execution",
                        "fan_out_index": idx,
                        "preferred_agent": agent.get("agent_id", ""),
                    },
                )
                nodes.append(fan_node)
                fan_out_targets.append(fan_node.node_id)
        else:
            # 无fan_out，顺序执行
            exec_node = DAGNode(
                description=f"执行核心任务：{goal}",
                priority=6,
                status="pending",
                dependencies=[prep_node.node_id],
                metadata={"complexity": "medium", "phase": "execution"},
            )
            nodes.append(exec_node)
            fan_out_targets.append(exec_node.node_id)

        # 最后一个节点：汇总与输出
        deps = fan_out_targets
        summary_node = DAGNode(
            description=f"汇总结果并输出：{goal}",
            priority=5,
            status="pending",
            dependencies=deps,
            metadata={"complexity": "medium", "phase": "summary"},
        )
        nodes.append(summary_node)

        return nodes

    def _plan_complex_nodes(
        self,
        goal: str,
        agents: list[dict[str, Any]],
    ) -> list[DAGNode]:
        """规划高复杂度任务的节点（6+个节点，支持fan_out + 条件分支）

        典型编排模式：
        规划 -> [扇出: 调研/分析/采集] -> 条件判断 -> [扇出: 撰写/评审] -> 汇总 -> 输出

        Args:
            goal: 任务目标描述
            agents: 可用Agent列表

        Returns:
            6+个DAGNode
        """
        nodes: list[DAGNode] = []

        # ── 阶段1：规划 ──
        plan_node = DAGNode(
            description=f"分解任务与制定计划：{goal}",
            priority=9,
            status="pending",
            metadata={"complexity": "complex", "phase": "planning"},
        )
        nodes.append(plan_node)

        # ── 阶段2：并行信息收集（fan_out） ──
        collect_label = ["调研", "分析", "采集"]
        collect_deps: list[str] = []
        for idx, label in enumerate(collect_label[:min(len(collect_label), len(agents))]):
            collect_node = DAGNode(
                description=f"{label}：{goal} 的相关信息",
                priority=7,
                status="pending",
                dependencies=[plan_node.node_id],
                metadata={
                    "complexity": "complex",
                    "phase": "information_gathering",
                    "fan_out_index": idx,
                    "sub_type": label,
                },
            )
            nodes.append(collect_node)
            collect_deps.append(collect_node.node_id)

        # ── 阶段3：条件判断节点 ──
        # 基于前序节点结果决定后续路径
        gate_node = DAGNode(
            description=f"评估信息充分性，决定后续路径",
            priority=8,
            status="pending",
            dependencies=collect_deps,
            metadata={
                "complexity": "complex",
                "phase": "conditional_gate",
                "gate_type": "sufficiency_check",
            },
        )
        nodes.append(gate_node)

        # ── 阶段4：并行执行（fan_out） ──
        exec_label = ["撰写", "评审", "优化"]
        exec_deps: list[str] = []
        for idx, label in enumerate(exec_label[:min(len(exec_label), len(agents))]):
            exec_node = DAGNode(
                description=f"{label}任务内容：{goal}",
                priority=6,
                status="pending",
                dependencies=[gate_node.node_id],
                metadata={
                    "complexity": "complex",
                    "phase": "execution",
                    "fan_out_index": idx,
                    "sub_type": label,
                },
            )
            nodes.append(exec_node)
            exec_deps.append(exec_node.node_id)

        # ── 阶段5：汇总 ──
        merge_node = DAGNode(
            description=f"合并并行执行结果：{goal}",
            priority=5,
            status="pending",
            dependencies=exec_deps,
            metadata={"complexity": "complex", "phase": "merge"},
        )
        nodes.append(merge_node)

        # ── 阶段6：最终输出 ──
        output_node = DAGNode(
            description=f"生成最终输出：{goal}",
            priority=5,
            status="pending",
            dependencies=[merge_node.node_id],
            metadata={"complexity": "complex", "phase": "output"},
        )
        nodes.append(output_node)

        return nodes

    # ──────────────────────────────────────────────────────
    # 边规划
    # ──────────────────────────────────────────────────────

    def _plan_edges(self, nodes: list[DAGNode]) -> list[DAGEdge]:
        """根据节点依赖关系规划DAG边

        分析每个节点的 dependencies 字段，自动生成对应的边。
        当一个节点被多个后续节点依赖时，自动标记为 fan_out 类型。
        对 metadata 中标记为 conditional_gate 的节点，生成 control 类型边。

        Args:
            nodes: 已规划的DAGNode列表

        Returns:
            规划好的DAGEdge列表
        """
        edges: list[DAGEdge] = []
        node_map: dict[str, DAGNode] = {n.node_id: n for n in nodes}

        # 统计每个源节点被引用的次数（用于识别fan_out）
        source_ref_count: dict[str, int] = {}
        for node in nodes:
            for dep_id in node.dependencies:
                source_ref_count[dep_id] = source_ref_count.get(dep_id, 0) + 1

        for node in nodes:
            for dep_id in node.dependencies:
                # 判断边类型
                source_node = node_map.get(dep_id)
                if source_node and source_node.metadata.get("gate_type") == "sufficiency_check":
                    # 从条件判断节点出发的边为control类型
                    edge_type = "control"
                    # 设置条件表达式：基于源节点的判断结果
                    condition = f"result.{dep_id}.sufficient == true"
                elif source_ref_count.get(dep_id, 0) > 1:
                    # 被多个节点依赖 -> fan_out
                    edge_type = "fan_out"
                    condition = ""
                else:
                    # 普通数据依赖
                    edge_type = "data"
                    condition = ""

                edge = DAGEdge(
                    source_node=dep_id,
                    target_node=node.node_id,
                    edge_type=edge_type,
                    condition=condition,
                )
                edges.append(edge)

        self._logger.debug(
            "edges_detail",
            total=len(edges),
            fan_out=sum(1 for e in edges if e.edge_type == "fan_out"),
            control=sum(1 for e in edges if e.edge_type == "control"),
            data=sum(1 for e in edges if e.edge_type == "data"),
        )

        return edges

    # ──────────────────────────────────────────────────────
    # Agent 分配
    # ──────────────────────────────────────────────────────

    def _assign_agents(
        self,
        nodes: list[DAGNode],
        agents: list[dict[str, Any]],
    ) -> None:
        """基于能力匹配为DAG节点分配Agent

        匹配策略：
        1. 优先使用节点 metadata 中指定的 preferred_agent
        2. 根据节点描述关键词与Agent capabilities 进行模糊匹配
        3. 未匹配到Agent的节点保持 assigned_agent 为空，等待后续人工或动态分配

        Args:
            nodes: DAGNode列表（原地修改 assigned_agent 字段）
            agents: 可用Agent列表
        """
        if not agents:
            self._logger.warn("no_available_agents_for_assignment")
            return

        # 构建 capability -> agent_id 的反向索引
        cap_to_agents: dict[str, list[str]] = {}
        for agent in agents:
            agent_id = agent.get("agent_id", "")
            for cap in agent.get("capabilities", []):
                cap_to_agents.setdefault(cap, []).append(agent_id)

        for node in nodes:
            # 策略1：preferred_agent 优先
            preferred = node.metadata.get("preferred_agent", "")
            if preferred and any(a.get("agent_id") == preferred for a in agents):
                node.assigned_agent = preferred
                continue

            # 策略2：关键词与能力模糊匹配
            description = node.description
            phase = node.metadata.get("phase", "")
            sub_type = node.metadata.get("sub_type", "")

            # 构建匹配用的关键词列表
            match_keywords = self._extract_match_keywords(description, phase, sub_type)

            best_agent: str = ""
            best_score: int = 0

            for agent in agents:
                agent_id = agent.get("agent_id", "")
                capabilities = agent.get("capabilities", [])
                score = self._compute_match_score(match_keywords, capabilities)
                if score > best_score:
                    best_score = score
                    best_agent = agent_id

            if best_agent:
                node.assigned_agent = best_agent
                self._logger.debug(
                    "agent_assigned",
                    node_id=node.node_id,
                    agent_id=best_agent,
                    score=best_score,
                )
            else:
                self._logger.debug(
                    "agent_not_assigned",
                    node_id=node.node_id,
                    reason="no_capability_match",
                )

    def _extract_match_keywords(
        self,
        description: str,
        phase: str,
        sub_type: str,
    ) -> list[str]:
        """从节点描述和元数据中提取匹配关键词

        Args:
            description: 节点描述文本
            phase: 执行阶段
            sub_type: 子类型（如"调研"/"撰写"）

        Returns:
            关键词列表
        """
        keywords: list[str] = []

        # 从描述中提取中文关键词（简单分词）
        # 提取2-4字的中文词组
        chinese_pattern = re.compile(r"[\u4e00-\u9fff]{2,4}")
        words = chinese_pattern.findall(description)
        keywords.extend(words)

        # phase映射关键词
        phase_keywords_map: dict[str, list[str]] = {
            "planning": ["planning", "plan", "规划", "计划"],
            "preparation": ["prep", "准备", "收集"],
            "information_gathering": ["research", "调研", "分析", "采集", "search"],
            "parallel_execution": ["exec", "执行", "处理"],
            "execution": ["exec", "执行", "处理", "implement"],
            "conditional_gate": ["gate", "评估", "判断", "check"],
            "merge": ["merge", "合并", "汇总", "aggregate"],
            "summary": ["summary", "总结", "汇总", "summarize"],
            "output": ["output", "输出", "生成", "generate"],
            "review": ["review", "评审", "review"],
            "writing": ["writing", "撰写", "write"],
        }
        phase_kws = phase_keywords_map.get(phase, [])
        keywords.extend(phase_kws)

        # sub_type 直接作为关键词
        if sub_type:
            keywords.append(sub_type)

        return keywords

    def _compute_match_score(
        self,
        keywords: list[str],
        capabilities: list[str],
    ) -> int:
        """计算关键词与Agent能力的匹配得分

        匹配规则：
        - 关键词与capability完全匹配：+3分
        - 关键词是capability的子串：+1分
        - capability是关键词的子串：+1分

        Args:
            keywords: 待匹配关键词列表
            capabilities: Agent能力列表

        Returns:
            匹配得分（0表示无匹配）
        """
        score: int = 0
        for kw in keywords:
            kw_lower = kw.lower()
            for cap in capabilities:
                cap_lower = cap.lower()
                if kw_lower == cap_lower:
                    score += 3  # 完全匹配
                elif kw_lower in cap_lower or cap_lower in kw_lower:
                    score += 1  # 包含匹配
        return score
