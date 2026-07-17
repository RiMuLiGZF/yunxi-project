"""
云汐内核 V10.0 — Agent 实例池

管理 Agent 实例的完整生命周期：
  CREATED → ACTIVATING → ACTIVE → SUSPENDED → DRAINING → TERMINATED → ARCHIVED

支持引用计数机制，多个任务可引用同一个 Agent 实例，
实例仅在引用归零时才允许进入 TERMINATED 状态。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

from shared_models import AgentLifeState, AgentRole

logger = structlog.get_logger(__name__)


# ── 合法状态转移表 ──────────────────────────────────────────
_VALID_TRANSITIONS: dict[AgentLifeState, set[AgentLifeState]] = {
    AgentLifeState.CREATED:    {AgentLifeState.ACTIVATING},
    AgentLifeState.ACTIVATING: {AgentLifeState.ACTIVE, AgentLifeState.FAILED},
    AgentLifeState.ACTIVE:     {AgentLifeState.SUSPENDED, AgentLifeState.DRAINING},
    AgentLifeState.SUSPENDED:  {AgentLifeState.ACTIVE, AgentLifeState.DRAINING},
    AgentLifeState.DRAINING:   {AgentLifeState.TERMINATED},
    AgentLifeState.TERMINATED: {AgentLifeState.ARCHIVED},
    # ARCHIVED 和 FAILED 为终态，不可再转移
}


@dataclass
class AgentInstance:
    """单个 Agent 实例的数据快照

    Attributes:
        agent_id:          全局唯一标识
        role:              Agent 角色枚举
        capabilities:      能力标签列表
        state:             当前生命周期状态
        created_at:        创建时间戳
        activated_at:      首次激活时间戳
        terminated_at:     终止时间戳
        ref_count:         当前引用计数
        config:            实例配置字典
        health:            健康信息字典
        last_heartbeat:    最后心跳时间戳
    """
    agent_id: str = ""
    role: AgentRole = AgentRole.EXECUTOR
    capabilities: list[str] = field(default_factory=list)
    state: AgentLifeState = AgentLifeState.CREATED
    created_at: float = field(default_factory=time.time)
    activated_at: float = 0.0
    terminated_at: float = 0.0
    ref_count: int = 0
    config: dict[str, Any] = field(default_factory=dict)
    health: dict[str, Any] = field(default_factory=dict)
    last_heartbeat: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典，用于事件发布与持久化"""
        return {
            "agent_id": self.agent_id,
            "role": self.role.value,
            "capabilities": list(self.capabilities),
            "state": self.state.value,
            "created_at": self.created_at,
            "activated_at": self.activated_at,
            "terminated_at": self.terminated_at,
            "ref_count": self.ref_count,
            "config": self.config,
            "health": self.health,
            "last_heartbeat": self.last_heartbeat,
        }


class AgentInstancePool:
    """Agent 实例池

    集中管理所有 Agent 实例的创建、状态转移、引用计数与归档。
    内部维护 _instances（实例映射）和 _ref_counts（引用计数映射），
    保证状态转移的合法性。
    """

    def __init__(self) -> None:
        self._instances: dict[str, AgentInstance] = {}
        self._ref_counts: dict[str, int] = {}
        self._logger = logger.bind(component="instance_pool")

    # ── 状态转移验证 ──────────────────────────────────

    @staticmethod
    def _can_transition(current: AgentLifeState, target: AgentLifeState) -> bool:
        """检查 current → target 是否为合法转移"""
        return target in _VALID_TRANSITIONS.get(current, set())

    # ── 生命周期操作 ──────────────────────────────────

    def create(
        self,
        agent_id: str,
        role: AgentRole,
        capabilities: list[str] | None = None,
        config: dict[str, Any] | None = None,
    ) -> AgentInstance:
        """创建一个新实例，初始状态为 CREATED

        Args:
            agent_id:      全局唯一标识
            role:          Agent 角色
            capabilities:  能力标签列表
            config:        实例配置字典

        Returns:
            新创建的 AgentInstance

        Raises:
            ValueError: agent_id 已存在时抛出
        """
        if agent_id in self._instances:
            raise ValueError(f"实例已存在: {agent_id}")

        instance = AgentInstance(
            agent_id=agent_id,
            role=role,
            capabilities=capabilities or [],
            state=AgentLifeState.CREATED,
            config=config or {},
        )
        self._instances[agent_id] = instance
        self._ref_counts[agent_id] = 0

        self._logger.info(
            "instance_created",
            agent_id=agent_id,
            role=role.value,
            capabilities=capabilities,
        )
        return instance

    def activate(self, agent_id: str) -> bool:
        """激活实例：CREATED → ACTIVE（经过 ACTIVATING 中间态）

        Args:
            agent_id: 目标实例 ID

        Returns:
            转移成功返回 True
        """
        instance = self._instances.get(agent_id)
        if instance is None:
            self._logger.warning("activate_not_found", agent_id=agent_id)
            return False

        # 仅 CREATED 状态允许激活
        if instance.state != AgentLifeState.CREATED:
            self._logger.warning(
                "activate_invalid_state",
                agent_id=agent_id,
                current=instance.state.value,
            )
            return False

        # CREATED → ACTIVATING → ACTIVE
        instance.state = AgentLifeState.ACTIVATING

        # 模拟激活过程后直接进入 ACTIVE
        instance.state = AgentLifeState.ACTIVE
        instance.activated_at = time.time()
        instance.last_heartbeat = time.time()

        self._logger.info("instance_activated", agent_id=agent_id)
        return True

    def suspend(self, agent_id: str) -> bool:
        """挂起实例：ACTIVE → SUSPENDED

        Args:
            agent_id: 目标实例 ID

        Returns:
            转移成功返回 True
        """
        instance = self._instances.get(agent_id)
        if instance is None:
            self._logger.warning("suspend_not_found", agent_id=agent_id)
            return False

        if not self._can_transition(instance.state, AgentLifeState.SUSPENDED):
            self._logger.warning(
                "suspend_invalid_transition",
                agent_id=agent_id,
                current=instance.state.value,
            )
            return False

        instance.state = AgentLifeState.SUSPENDED
        self._logger.info("instance_suspended", agent_id=agent_id)
        return True

    def resume(self, agent_id: str) -> bool:
        """恢复实例：SUSPENDED → ACTIVE

        Args:
            agent_id: 目标实例 ID

        Returns:
            转移成功返回 True
        """
        instance = self._instances.get(agent_id)
        if instance is None:
            self._logger.warning("resume_not_found", agent_id=agent_id)
            return False

        if not self._can_transition(instance.state, AgentLifeState.ACTIVE):
            self._logger.warning(
                "resume_invalid_transition",
                agent_id=agent_id,
                current=instance.state.value,
            )
            return False

        instance.state = AgentLifeState.ACTIVE
        instance.last_heartbeat = time.time()
        self._logger.info("instance_resumed", agent_id=agent_id)
        return True

    def drain(self, agent_id: str) -> bool:
        """优雅终止：进入 DRAINING 状态，等待引用归零后自动转为 TERMINATED

        仅 ACTIVE 或 SUSPENDED 状态的实例可以进入 DRAINING。
        如果当前引用计数已为零，则直接进入 TERMINATED。

        Args:
            agent_id: 目标实例 ID

        Returns:
            转移成功返回 True
        """
        instance = self._instances.get(agent_id)
        if instance is None:
            self._logger.warning("drain_not_found", agent_id=agent_id)
            return False

        if not self._can_transition(instance.state, AgentLifeState.DRAINING):
            self._logger.warning(
                "drain_invalid_transition",
                agent_id=agent_id,
                current=instance.state.value,
            )
            return False

        # 若引用已归零，直接终止
        if self._ref_counts.get(agent_id, 0) <= 0:
            instance.state = AgentLifeState.TERMINATED
            instance.terminated_at = time.time()
            self._logger.info(
                "instance_drained_immediately",
                agent_id=agent_id,
                reason="ref_count_zero",
            )
        else:
            instance.state = AgentLifeState.DRAINING
            self._logger.info(
                "instance_draining",
                agent_id=agent_id,
                ref_count=self._ref_counts[agent_id],
            )
        return True

    def terminate(self, agent_id: str) -> bool:
        """强制终止：无论当前状态，直接置为 TERMINATED

        注意：此操作会跳过 DRAINING 的优雅等待，
        仅在紧急情况下使用。

        Args:
            agent_id: 目标实例 ID

        Returns:
            操作成功返回 True
        """
        instance = self._instances.get(agent_id)
        if instance is None:
            self._logger.warning("terminate_not_found", agent_id=agent_id)
            return False

        # ARCHIVED 和已 TERMINATED 的实例无需再终止
        if instance.state in (AgentLifeState.TERMINATED, AgentLifeState.ARCHIVED):
            self._logger.warning(
                "terminate_already_terminated",
                agent_id=agent_id,
                state=instance.state.value,
            )
            return False

        instance.state = AgentLifeState.TERMINATED
        instance.terminated_at = time.time()

        # 强制终止时清除引用计数
        self._ref_counts[agent_id] = 0

        self._logger.info("instance_terminated_forcefully", agent_id=agent_id)
        return True

    def archive(self, agent_id: str) -> bool:
        """归档实例：TERMINATED → ARCHIVED

        Args:
            agent_id: 目标实例 ID

        Returns:
            转移成功返回 True
        """
        instance = self._instances.get(agent_id)
        if instance is None:
            self._logger.warning("archive_not_found", agent_id=agent_id)
            return False

        if not self._can_transition(instance.state, AgentLifeState.ARCHIVED):
            self._logger.warning(
                "archive_invalid_transition",
                agent_id=agent_id,
                current=instance.state.value,
            )
            return False

        instance.state = AgentLifeState.ARCHIVED
        self._logger.info("instance_archived", agent_id=agent_id)
        return True

    # ── 引用计数 ──────────────────────────────────────

    def add_ref(self, agent_id: str) -> int:
        """增加对实例的引用计数

        Args:
            agent_id: 目标实例 ID

        Returns:
            更新后的引用计数

        Raises:
            KeyError: agent_id 不存在时抛出
        """
        if agent_id not in self._ref_counts:
            raise KeyError(f"实例不存在: {agent_id}")

        self._ref_counts[agent_id] += 1
        instance = self._instances[agent_id]
        instance.ref_count = self._ref_counts[agent_id]

        self._logger.debug(
            "ref_added",
            agent_id=agent_id,
            ref_count=self._ref_counts[agent_id],
        )

        # DRAINING 状态的实例在引用恢复时不做自动恢复
        return self._ref_counts[agent_id]

    def release_ref(self, agent_id: str) -> int:
        """释放对实例的引用计数

        当 DRAINING 状态的实例引用归零时，自动转为 TERMINATED。

        Args:
            agent_id: 目标实例 ID

        Returns:
            更新后的引用计数

        Raises:
            KeyError: agent_id 不存在时抛出
        """
        if agent_id not in self._ref_counts:
            raise KeyError(f"实例不存在: {agent_id}")

        if self._ref_counts[agent_id] <= 0:
            self._logger.warning(
                "ref_underflow",
                agent_id=agent_id,
                ref_count=self._ref_counts[agent_id],
            )
            return 0

        self._ref_counts[agent_id] -= 1
        instance = self._instances[agent_id]
        instance.ref_count = self._ref_counts[agent_id]

        self._logger.debug(
            "ref_released",
            agent_id=agent_id,
            ref_count=self._ref_counts[agent_id],
        )

        # DRAINING 状态引用归零 → 自动终止
        if (
            self._ref_counts[agent_id] == 0
            and instance.state == AgentLifeState.DRAINING
        ):
            instance.state = AgentLifeState.TERMINATED
            instance.terminated_at = time.time()
            self._logger.info(
                "instance_auto_terminated",
                agent_id=agent_id,
                reason="draining_ref_released",
            )

        return self._ref_counts[agent_id]

    # ── 查询操作 ──────────────────────────────────────

    def get_instance(self, agent_id: str) -> AgentInstance | None:
        """获取指定 ID 的实例

        Args:
            agent_id: 目标实例 ID

        Returns:
            AgentInstance 或 None
        """
        return self._instances.get(agent_id)

    def list_by_state(self, state: AgentLifeState) -> list[AgentInstance]:
        """列出指定状态下的所有实例

        Args:
            state: 目标生命周期状态

        Returns:
            符合条件的实例列表
        """
        return [inst for inst in self._instances.values() if inst.state == state]

    def stats(self) -> dict[str, Any]:
        """返回实例池的整体统计快照

        Returns:
            包含各状态计数、总实例数等信息的字典
        """
        state_counts: dict[str, int] = {}
        for s in AgentLifeState:
            state_counts[s.value] = 0

        total = 0
        for inst in self._instances.values():
            state_counts[inst.state.value] += 1
            total += 1

        draining_with_refs = [
            inst.agent_id
            for inst in self._instances.values()
            if inst.state == AgentLifeState.DRAINING and inst.ref_count > 0
        ]

        return {
            "total_instances": total,
            "state_counts": state_counts,
            "active_count": state_counts.get("active", 0),
            "draining_pending": len(draining_with_refs),
            "draining_agent_ids": draining_with_refs,
        }
