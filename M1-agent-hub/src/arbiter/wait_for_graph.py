"""
云汐内核 V10.0 — 等待图与仲裁引擎 (WaitForGraph / ArbitrationEngine)

职责：
- WaitForGraph：维护 Agent 间的等待关系图，检测死锁环
- ArbitrationEngine：三级仲裁引擎（自动解决 → 协商解决 → 人工介入）

依赖：
- shared_models：ArbitrationRequest / ArbitrationResult / ArbitrationLevel
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from typing import Any

import structlog

from shared_models import (
    ArbitrationLevel,
    ArbitrationRequest,
    ArbitrationResult,
)

logger = structlog.get_logger(__name__)


# ══════════════════════════════════════════════════════════
# WaitForGraph — 等待图
# ══════════════════════════════════════════════════════════


class WaitForGraph:
    """Agent等待关系图

    维护 Agent 间的资源等待关系，支持：
    - 添加/移除等待边
    - 使用DFS + 三色标记检测环
    - 获取死锁Agent集合
    - 查询等待某Agent的所有Agent
    - 并发安全（asyncio.Lock）
    """

    def __init__(self) -> None:
        # agent_id -> set(等待该agent的其他agent_id)
        self._edges: dict[str, set[str]] = defaultdict(set)
        # 反向索引：agent_id -> set(该agent正在等待的目标agent_id)
        self._reverse_edges: dict[str, set[str]] = defaultdict(set)
        self._lock: asyncio.Lock = asyncio.Lock()
        self._logger = logger.bind(component="wait_for_graph")

    async def add_edge(self, waiter: str, holder: str) -> None:
        """添加一条等待关系：waiter 等待 holder

        Args:
            waiter: 等待方Agent ID
            holder: 被等待方Agent ID（持有资源的Agent）
        """
        async with self._lock:
            if holder not in self._edges[waiter]:
                self._edges[waiter].add(holder)
                self._reverse_edges[holder].add(waiter)
                self._logger.debug(
                    "wait_edge_added",
                    waiter=waiter,
                    holder=holder,
                )

    async def remove_edge(self, waiter: str, holder: str) -> None:
        """移除一条等待关系

        Args:
            waiter: 等待方Agent ID
            holder: 被等待方Agent ID
        """
        async with self._lock:
            self._edges[waiter].discard(holder)
            self._reverse_edges[holder].discard(waiter)
            # 清理空集合
            if not self._edges[waiter]:
                del self._edges[waiter]
            if holder in self._reverse_edges and not self._reverse_edges[holder]:
                del self._reverse_edges[holder]
            self._logger.debug(
                "wait_edge_removed",
                waiter=waiter,
                holder=holder,
            )

    async def detect_cycle(self) -> list[list[str]]:
        """检测等待图中的所有环（DFS + 三色标记算法）

        使用三种颜色标记节点状态：
        - WHITE (0)：未访问
        - GRAY  (1)：正在访问（在当前DFS路径上）
        - BLACK (2)：访问完成

        Returns:
            所有环的列表，每个环是一个 agent_id 列表
        """
        async with self._lock:
            # 收集所有节点
            all_nodes: set[str] = set(self._edges.keys())
            for holders in self._edges.values():
                all_nodes.update(holders)

            WHITE, GRAY, BLACK = 0, 1, 2
            color: dict[str, int] = {node: WHITE for node in all_nodes}
            cycles: list[list[str]] = []
            path: list[str] = []

            def _dfs(node: str) -> None:
                """DFS回溯寻找环"""
                color[node] = GRAY
                path.append(node)

                for neighbor in self._edges.get(node, set()):
                    if color.get(neighbor, WHITE) == GRAY:
                        # 找到环：从 neighbor 在 path 中的位置到当前 node
                        cycle_start = path.index(neighbor)
                        cycle = path[cycle_start:]
                        if len(cycle) > 1:
                            cycles.append(cycle)
                    elif color.get(neighbor, WHITE) == WHITE:
                        _dfs(neighbor)

                path.pop()
                color[node] = BLACK

            for node in sorted(all_nodes):
                if color.get(node, WHITE) == WHITE:
                    _dfs(node)

            if cycles:
                self._logger.warning(
                    "cycles_detected",
                    count=len(cycles),
                    cycles=cycles,
                )
            else:
                self._logger.debug("no_cycles_detected")

            return cycles

    async def get_deadlocked_agents(self) -> set[str]:
        """获取所有处于死锁状态的Agent集合

        死锁Agent是指处于至少一个环中的Agent。

        Returns:
            死锁Agent ID集合
        """
        cycles = await self.detect_cycle()
        deadlocked: set[str] = set()
        for cycle in cycles:
            deadlocked.update(cycle)
        return deadlocked

    def get_waiters(self, agent_id: str) -> set[str]:
        """获取正在等待指定Agent的所有Agent

        注意：此方法不加锁，适用于读多写少场景。
        如需严格一致性，请在外层使用 _lock。

        Args:
            agent_id: 目标Agent ID

        Returns:
            等待方Agent ID集合
        """
        return set(self._reverse_edges.get(agent_id, set()))

    def get_holders(self, agent_id: str) -> set[str]:
        """获取指定Agent正在等待的所有Agent

        Args:
            agent_id: 等待方Agent ID

        Returns:
            被等待方Agent ID集合
        """
        return set(self._edges.get(agent_id, set()))

    async def clear(self) -> None:
        """清空整个等待图"""
        async with self._lock:
            self._edges.clear()
            self._reverse_edges.clear()
            self._logger.info("wait_for_graph_cleared")

    def stats(self) -> dict[str, Any]:
        """等待图统计信息

        Returns:
            包含节点数、边数、各Agent等待数等统计
        """
        total_edges = sum(len(holders) for holders in self._edges.values())
        return {
            "total_nodes": len(set(self._edges.keys()) | set(self._reverse_edges.keys())),
            "total_edges": total_edges,
            "waiters_count": len(self._edges),
            "holders_count": len(self._reverse_edges),
            "edges_detail": {
                waiter: list(holders)
                for waiter, holders in self._edges.items()
            },
        }


# ══════════════════════════════════════════════════════════
# ArbitrationEngine — 三级仲裁引擎
# ══════════════════════════════════════════════════════════


class ArbitrationEngine:
    """三级仲裁引擎

    当Agent间发生资源冲突或死锁时，按以下三级策略依次尝试解决：
    1. 自动解决（AUTO_RESOLVE）：优先级高的Agent获得资源、超时取消低优先级等待
    2. 协商解决（NEGOTIATE）：降低等待方优先级或重路由任务
    3. 人工介入（HUMAN_ESCALATE）：生成详细报告供人工决策

    所有仲裁结果记录到历史中，支持查询与统计。
    """

    def __init__(self, max_history: int = 10000) -> None:
        self._pending_requests: dict[str, ArbitrationRequest] = {}
        self._history: list[ArbitrationResult] = []
        self._max_history: int = max_history
        self._logger = logger.bind(component="arbitration_engine")

    def submit(self, request: ArbitrationRequest) -> ArbitrationResult:
        """提交仲裁请求，执行三级仲裁

        Args:
            request: 仲裁请求

        Returns:
            仲裁结果
        """
        request_id = request.request_id
        self._pending_requests[request_id] = request

        self._logger.info(
            "arbitration_submitted",
            request_id=request_id,
            conflict_type=request.conflict_type,
            involved_agents=request.involved_agents,
        )

        # 第一级：自动解决
        result = self._level1_auto_resolve(request)
        if result is not None:
            result.level = ArbitrationLevel.AUTO_RESOLVE
            self._record_result(result)
            self._pending_requests.pop(request_id, None)
            return result

        # 第二级：协商解决
        result = self._level2_negotiate(request)
        if result is not None:
            result.level = ArbitrationLevel.NEGOTIATE
            self._record_result(result)
            self._pending_requests.pop(request_id, None)
            return result

        # 第三级：人工介入
        result = self._level3_human_escalate(request)
        self._record_result(result)
        self._pending_requests.pop(request_id, None)
        return result

    def _level1_auto_resolve(
        self, request: ArbitrationRequest
    ) -> ArbitrationResult | None:
        """第一级：自动解决

        策略：
        - 优先级高的Agent获得资源
        - 超时的请求直接取消低优先级Agent的等待
        - 简单的资源死锁通过取消一方解决

        Args:
            request: 仲裁请求

        Returns:
            仲裁结果，若无法自动解决则返回None
        """
        conflict_type = request.conflict_type
        involved = request.involved_agents
        context = request.context

        self._logger.info(
            "level1_auto_resolve_attempt",
            request_id=request.request_id,
            conflict_type=conflict_type,
        )

        # 超时取消策略
        if conflict_type == "timeout":
            # 找到超时的Agent
            timeout_agent: str | None = None
            for agent_id in involved:
                agent_info = context.get("agent_info", {}).get(agent_id, {})
                wait_time = agent_info.get("wait_time_seconds", 0.0)
                if wait_time > agent_info.get("timeout_threshold", 60.0):
                    timeout_agent = agent_id
                    break

            if timeout_agent:
                return ArbitrationResult(
                    request_id=request.request_id,
                    decision="abort",
                    assigned_agent="",
                    reason=f"Agent {timeout_agent} 等待超时，自动取消其等待请求",
                    actions=[
                        {
                            "type": "cancel_wait",
                            "agent_id": timeout_agent,
                            "reason": "wait_timeout",
                        }
                    ],
                )

        # 资源死锁：取消优先级最低的Agent
        if conflict_type == "resource_deadlock":
            min_priority = 999
            victim: str | None = None
            for agent_id in involved:
                agent_info = context.get("agent_info", {}).get(agent_id, {})
                priority = agent_info.get("priority", 5)
                if priority < min_priority:
                    min_priority = priority
                    victim = agent_id

            if victim:
                # 优先级高的Agent获得资源
                winner = [a for a in involved if a != victim]
                return ArbitrationResult(
                    request_id=request.request_id,
                    decision="reroute",
                    assigned_agent=winner[0] if winner else "",
                    reason=(
                        f"资源死锁自动解决：取消低优先级Agent '{victim}' 的等待，"
                        f"资源分配给 Agent '{winner[0] if winner else 'unknown'}'"
                    ),
                    actions=[
                        {
                            "type": "cancel_wait",
                            "agent_id": victim,
                            "reason": "low_priority_victim",
                        },
                        {
                            "type": "grant_resource",
                            "agent_id": winner[0] if winner else "",
                            "resource": context.get("resource_id", ""),
                        },
                    ],
                )

        # 优先级冲突：高优先级Agent胜出
        if conflict_type == "priority_conflict":
            agents_with_priority = []
            for agent_id in involved:
                agent_info = context.get("agent_info", {}).get(agent_id, {})
                priority = agent_info.get("priority", 5)
                agents_with_priority.append((agent_id, priority))

            agents_with_priority.sort(key=lambda x: -x[1])
            if len(agents_with_priority) >= 2:
                winner_id, winner_priority = agents_with_priority[0]
                loser_id, loser_priority = agents_with_priority[1]
                return ArbitrationResult(
                    request_id=request.request_id,
                    decision="retry",
                    assigned_agent=winner_id,
                    reason=(
                        f"优先级冲突自动解决："
                        f"Agent '{winner_id}'(优先级{winner_priority}) > "
                        f"Agent '{loser_id}'(优先级{loser_priority})，"
                        f"高优先级Agent先执行"
                    ),
                    actions=[
                        {
                            "type": "grant_resource",
                            "agent_id": winner_id,
                            "resource": context.get("resource_id", ""),
                        },
                        {
                            "type": "delay_retry",
                            "agent_id": loser_id,
                            "retry_after": 5.0,
                        },
                    ],
                )

        # 依赖环：尝试断开最弱的依赖
        if conflict_type == "dependency_cycle":
            return ArbitrationResult(
                request_id=request.request_id,
                decision="abort",
                assigned_agent="",
                reason="依赖环自动解决：取消环中最后一个加入的Agent的等待，打断环",
                actions=[
                    {
                        "type": "break_cycle",
                        "agent_id": involved[-1] if involved else "",
                        "action": "cancel_wait",
                    }
                ],
            )

        self._logger.info(
            "level1_auto_resolve_unable",
            request_id=request.request_id,
            conflict_type=conflict_type,
        )
        return None

    def _level2_negotiate(
        self, request: ArbitrationRequest
    ) -> ArbitrationResult | None:
        """第二级：协商解决

        策略：
        - 降低等待方优先级以让更高价值的任务通过
        - 重路由等待方到替代资源
        - 分配等待队列位置

        Args:
            request: 仲裁请求

        Returns:
            仲裁结果，若协商失败则返回None
        """
        conflict_type = request.conflict_type
        involved = request.involved_agents
        context = request.context

        self._logger.info(
            "level2_negotiate_attempt",
            request_id=request.request_id,
            conflict_type=conflict_type,
        )

        # 重路由策略：检查是否有替代资源
        if conflict_type == "resource_deadlock":
            for agent_id in involved:
                agent_info = context.get("agent_info", {}).get(agent_id, {})
                alternatives = agent_info.get("alternative_resources", [])
                if alternatives:
                    return ArbitrationResult(
                        request_id=request.request_id,
                        decision="reroute",
                        assigned_agent=agent_id,
                        reason=(
                            f"协商解决：Agent '{agent_id}' 被重路由到替代资源 "
                            f"{alternatives[0]}，释放对原资源的竞争"
                        ),
                        actions=[
                            {
                                "type": "reroute",
                                "agent_id": agent_id,
                                "original_resource": context.get("resource_id", ""),
                                "new_resource": alternatives[0],
                            }
                        ],
                    )

        # 优先级调整策略
        if conflict_type == "priority_conflict":
            adjusted_agents: list[dict[str, Any]] = []
            for agent_id in involved:
                agent_info = context.get("agent_info", {}).get(agent_id, {})
                current_priority = agent_info.get("priority", 5)
                # 等待时间越长，优先级越高（老化策略）
                wait_time = agent_info.get("wait_time_seconds", 0.0)
                boosted_priority = min(10, current_priority + int(wait_time / 30))
                adjusted_agents.append({
                    "agent_id": agent_id,
                    "original_priority": current_priority,
                    "boosted_priority": boosted_priority,
                })

            # 选择优先级最高的
            adjusted_agents.sort(key=lambda x: -x["boosted_priority"])
            winner = adjusted_agents[0]

            return ArbitrationResult(
                request_id=request.request_id,
                decision="retry",
                assigned_agent=winner["agent_id"],
                reason=(
                    f"协商解决：Agent '{winner['agent_id']}' 经优先级老化调整后"
                    f"(优先级 {winner['original_priority']} -> {winner['boosted_priority']}) "
                    f"获得执行权"
                ),
                actions=[
                    {
                        "type": "boost_priority",
                        "agent_id": winner["agent_id"],
                        "new_priority": winner["boosted_priority"],
                    },
                    {
                        "type": "delay_retry",
                        "agent_id": (
                            adjusted_agents[1]["agent_id"]
                            if len(adjusted_agents) > 1
                            else ""
                        ),
                        "retry_after": 10.0,
                    },
                ],
            )

        self._logger.info(
            "level2_negotiate_unable",
            request_id=request.request_id,
            conflict_type=conflict_type,
        )
        return None

    def _level3_human_escalate(self, request: ArbitrationRequest) -> ArbitrationResult:
        """第三级：人工介入

        当自动解决和协商均无法处理时，生成详细报告供人工决策。

        Args:
            request: 仲裁请求

        Returns:
            包含详细报告的仲裁结果
        """
        self._logger.warning(
            "level3_human_escalate",
            request_id=request.request_id,
            conflict_type=request.conflict_type,
            involved_agents=request.involved_agents,
        )

        # 构建详细报告
        involved_details: list[dict[str, Any]] = []
        for agent_id in request.involved_agents:
            agent_info = request.context.get("agent_info", {}).get(agent_id, {})
            involved_details.append({
                "agent_id": agent_id,
                "priority": agent_info.get("priority", "unknown"),
                "wait_time_seconds": agent_info.get("wait_time_seconds", 0.0),
                "status": agent_info.get("status", "unknown"),
                "task_ids": agent_info.get("task_ids", []),
            })

        report = {
            "request_id": request.request_id,
            "conflict_type": request.conflict_type,
            "involved_agents_details": involved_details,
            "task_ids": request.task_ids,
            "context_summary": {
                "resource_id": request.context.get("resource_id", ""),
                "total_wait_time": sum(
                    d.get("wait_time_seconds", 0.0) for d in involved_details
                ),
            },
            "recommendation": (
                "建议人工审查Agent间资源分配策略，"
                "考虑增加资源容量或调整任务调度优先级"
            ),
            "escalation_reason": (
                f"冲突类型 '{request.conflict_type}' 无法通过自动解决和协商处理，"
                f"涉及 {len(request.involved_agents)} 个Agent"
            ),
        }

        return ArbitrationResult(
            request_id=request.request_id,
            level=ArbitrationLevel.HUMAN_ESCALATE,
            decision="escalate",
            assigned_agent="",
            reason="自动解决与协商均失败，已升级为人工介入处理",
            actions=[
                {
                    "type": "human_escalate",
                    "report": report,
                    "priority": "high",
                }
            ],
        )

    def _record_result(self, result: ArbitrationResult) -> None:
        """记录仲裁结果到历史"""
        self._history.append(result)
        # 超过上限时裁剪最旧的记录
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        self._logger.info(
            "arbitration_result_recorded",
            request_id=result.request_id,
            level=result.level.value,
            decision=result.decision,
        )

    def get_history(self, limit: int = 100) -> list[ArbitrationResult]:
        """获取仲裁历史记录

        Args:
            limit: 返回最近N条记录

        Returns:
            ArbitrationResult 列表（按时间倒序）
        """
        return list(reversed(self._history[-limit:]))

    def stats(self) -> dict[str, Any]:
        """仲裁引擎统计信息

        Returns:
            包含各级别仲裁次数、待处理请求数等统计
        """
        level_counts: dict[str, int] = {
            "auto_resolve": 0,
            "negotiate": 0,
            "human_escalate": 0,
        }
        decision_counts: dict[str, int] = {}

        for result in self._history:
            level_name = {
                ArbitrationLevel.AUTO_RESOLVE: "auto_resolve",
                ArbitrationLevel.NEGOTIATE: "negotiate",
                ArbitrationLevel.HUMAN_ESCALATE: "human_escalate",
            }.get(result.level, "unknown")
            level_counts[level_name] = level_counts.get(level_name, 0) + 1
            decision_counts[result.decision] = (
                decision_counts.get(result.decision, 0) + 1
            )

        return {
            "total_arbitrations": len(self._history),
            "pending_requests": len(self._pending_requests),
            "max_history": self._max_history,
            "level_distribution": level_counts,
            "decision_distribution": decision_counts,
        }
