"""
云汐故障转移管理器 (Failover Manager)

提供主备模式的故障转移能力：
- 主备模式 (active-passive)
- 故障自动检测和切换
- 切换后状态同步
- 自动恢复检查
- 切换历史记录
- 切换事件通知

使用方式：
    from shared.core.ha.failover_manager import FailoverManager, FailoverMode

    fm = FailoverManager(
        service_name="database",
        mode=FailoverMode.ACTIVE_PASSIVE,
        auto_failover=True,
    )
    fm.set_primary("node-1", "http://127.0.0.1:5432")
    fm.set_standby("node-2", "http://127.0.0.1:5433")
    fm.start_monitor()
"""

from __future__ import annotations

import time
import threading
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Callable
from collections import deque
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# ============================================================
# 枚举与常量
# ============================================================

class FailoverMode(str, Enum):
    """故障转移模式"""
    ACTIVE_PASSIVE = "active_passive"   # 主备模式
    ACTIVE_ACTIVE = "active_active"     # 双活模式（预留）


class FailoverState(str, Enum):
    """故障转移状态"""
    INITIALIZING = "initializing"     # 初始化中
    NORMAL = "normal"                 # 正常运行（主节点正常）
    FAILING_OVER = "failing_over"     # 正在切换
    DEGRADED = "degraded"             # 降级运行（备节点接管）
    RECOVERING = "recovering"         # 正在恢复
    UNKNOWN = "unknown"               # 未知状态


class NodeRole(str, Enum):
    """节点角色"""
    PRIMARY = "primary"      # 主节点
    STANDBY = "standby"      # 备节点
    NONE = "none"            # 无角色


class NodeStatus(str, Enum):
    """节点状态"""
    ONLINE = "online"        # 在线
    OFFLINE = "offline"      # 离线
    DEGRADED = "degraded"    # 降级
    SYNCING = "syncing"      # 同步中
    UNKNOWN = "unknown"      # 未知


# ============================================================
# 数据类
# ============================================================

@dataclass
class FailoverNode:
    """故障转移节点"""
    node_id: str
    address: str
    role: NodeRole = NodeRole.NONE
    status: NodeStatus = NodeStatus.UNKNOWN
    weight: int = 1
    last_health_check: float = 0.0
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "address": self.address,
            "role": self.role.value,
            "status": self.status.value,
            "weight": self.weight,
            "last_health_check": self.last_health_check,
            "consecutive_failures": self.consecutive_failures,
            "consecutive_successes": self.consecutive_successes,
            "metadata": self.metadata,
        }


@dataclass
class FailoverEvent:
    """故障转移事件"""
    event_id: str
    event_type: str           # failover / recovery / status_change / manual_switch
    from_node: str = ""
    to_node: str = ""
    reason: str = ""
    timestamp: float = field(default_factory=time.time)
    state_before: str = ""
    state_after: str = ""
    duration_seconds: float = 0.0
    success: bool = False
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "from_node": self.from_node,
            "to_node": self.to_node,
            "reason": self.reason,
            "timestamp": datetime.fromtimestamp(self.timestamp, tz=timezone.utc).isoformat(),
            "state_before": self.state_before,
            "state_after": self.state_after,
            "duration_seconds": round(self.duration_seconds, 3),
            "success": self.success,
            "details": self.details,
        }


# ============================================================
# 故障转移管理器
# ============================================================

class FailoverManager:
    """
    故障转移管理器

    支持主备模式下的自动故障检测和切换。

    工作流程：
    1. 配置主节点和备节点
    2. 设置健康检查函数
    3. 启动监控线程
    4. 主节点故障时自动切换到备节点
    5. 主节点恢复后可选择自动回切或保持备节点
    """

    def __init__(
        self,
        service_name: str,
        mode: FailoverMode = FailoverMode.ACTIVE_PASSIVE,
        auto_failover: bool = True,
        auto_recovery: bool = False,     # 是否自动回切到主节点
        failure_threshold: int = 3,      # 连续失败次数阈值
        recovery_threshold: int = 3,     # 连续成功次数阈值
        check_interval: float = 5.0,     # 健康检查间隔（秒）
        switch_cooldown: float = 30.0,   # 切换冷却时间（秒）
    ):
        self.service_name = service_name
        self.mode = mode
        self.auto_failover = auto_failover
        self.auto_recovery = auto_recovery
        self.failure_threshold = failure_threshold
        self.recovery_threshold = recovery_threshold
        self.check_interval = check_interval
        self.switch_cooldown = switch_cooldown

        self._nodes: Dict[str, FailoverNode] = {}
        self._primary_id: Optional[str] = None
        self._standby_id: Optional[str] = None
        self._state: FailoverState = FailoverState.INITIALIZING
        self._last_switch_time: float = 0.0
        self._health_check_fn: Optional[Callable[[str, str], bool]] = None
        self._state_sync_fn: Optional[Callable[[str, str], bool]] = None

        # 事件历史
        self._event_history: deque = deque(maxlen=100)
        self._switch_count: int = 0
        self._total_downtime_seconds: float = 0.0
        self._last_failover_start: float = 0.0

        # 回调
        self._on_failover_callbacks: List[Callable[[FailoverEvent], None]] = []
        self._on_recovery_callbacks: List[Callable[[FailoverEvent], None]] = []
        self._on_state_change_callbacks: List[Callable[[FailoverState, FailoverState], None]] = []

        # 线程
        self._lock = threading.RLock()
        self._monitor_thread: Optional[threading.Thread] = None
        self._monitor_stop = threading.Event()
        self._start_time = time.time()

    # ------------------------------------------------------------------
    #  节点管理
    # ------------------------------------------------------------------

    def add_node(
        self,
        node_id: str,
        address: str,
        role: NodeRole = NodeRole.NONE,
        weight: int = 1,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """添加节点"""
        with self._lock:
            if node_id in self._nodes:
                logger.warning("Node already exists: %s", node_id)
                return False

            node = FailoverNode(
                node_id=node_id,
                address=address,
                role=role,
                weight=weight,
                metadata=metadata or {},
            )
            self._nodes[node_id] = node

            if role == NodeRole.PRIMARY:
                self._primary_id = node_id
            elif role == NodeRole.STANDBY:
                self._standby_id = node_id

            logger.info("Node added: %s (%s), role=%s", node_id, address, role.value)
            return True

    def set_primary(self, node_id: str, address: str, **kwargs) -> bool:
        """设置主节点"""
        return self.add_node(node_id, address, role=NodeRole.PRIMARY, **kwargs)

    def set_standby(self, node_id: str, address: str, **kwargs) -> bool:
        """设置备节点"""
        return self.add_node(node_id, address, role=NodeRole.STANDBY, **kwargs)

    def remove_node(self, node_id: str) -> bool:
        """移除节点"""
        with self._lock:
            if node_id not in self._nodes:
                return False

            if self._primary_id == node_id:
                self._primary_id = None
            if self._standby_id == node_id:
                self._standby_id = None

            del self._nodes[node_id]
            logger.info("Node removed: %s", node_id)
            return True

    def get_node(self, node_id: str) -> Optional[FailoverNode]:
        """获取节点信息"""
        with self._lock:
            return self._nodes.get(node_id)

    def get_primary(self) -> Optional[FailoverNode]:
        """获取当前主节点"""
        with self._lock:
            if self._primary_id:
                return self._nodes.get(self._primary_id)
            return None

    def get_standby(self) -> Optional[FailoverNode]:
        """获取备节点"""
        with self._lock:
            if self._standby_id:
                return self._nodes.get(self._standby_id)
            return None

    def get_all_nodes(self) -> List[FailoverNode]:
        """获取所有节点"""
        with self._lock:
            return list(self._nodes.values())

    # ------------------------------------------------------------------
    #  健康检查与状态同步回调
    # ------------------------------------------------------------------

    def set_health_check(self, fn: Callable[[str, str], bool]) -> None:
        """
        设置健康检查函数

        函数签名：check_fn(node_id: str, address: str) -> bool
        返回 True 表示健康，False 表示不健康。
        """
        self._health_check_fn = fn

    def set_state_sync(self, fn: Callable[[str, str], bool]) -> None:
        """
        设置状态同步函数（切换前调用）

        函数签名：sync_fn(from_address: str, to_address: str) -> bool
        返回 True 表示同步成功。
        """
        self._state_sync_fn = fn

    # ------------------------------------------------------------------
    #  事件回调
    # ------------------------------------------------------------------

    def on_failover(self, callback: Callable[[FailoverEvent], None]) -> None:
        """注册故障转移回调"""
        self._on_failover_callbacks.append(callback)

    def on_recovery(self, callback: Callable[[FailoverEvent], None]) -> None:
        """注册恢复回调"""
        self._on_recovery_callbacks.append(callback)

    def on_state_change(self, callback: Callable[[FailoverState, FailoverState], None]) -> None:
        """注册状态变化回调"""
        self._on_state_change_callbacks.append(callback)

    def _fire_failover_event(self, event: FailoverEvent) -> None:
        for cb in self._on_failover_callbacks:
            try:
                cb(event)
            except Exception as e:
                logger.error("Failover callback error: %s", e)

    def _fire_recovery_event(self, event: FailoverEvent) -> None:
        for cb in self._on_recovery_callbacks:
            try:
                cb(event)
            except Exception as e:
                logger.error("Recovery callback error: %s", e)

    def _fire_state_change(self, old_state: FailoverState, new_state: FailoverState) -> None:
        for cb in self._on_state_change_callbacks:
            try:
                cb(old_state, new_state)
            except Exception as e:
                logger.error("State change callback error: %s", e)

    def _change_state(self, new_state: FailoverState) -> None:
        """变更状态"""
        old_state = self._state
        if old_state != new_state:
            self._state = new_state
            logger.info("Failover state changed: %s -> %s", old_state.value, new_state.value)
            self._fire_state_change(old_state, new_state)

    # ------------------------------------------------------------------
    #  故障切换
    # ------------------------------------------------------------------

    def trigger_failover(self, reason: str = "manual") -> FailoverEvent:
        """
        触发故障转移（手动切换）

        Args:
            reason: 切换原因

        Returns:
            故障转移事件
        """
        return self._do_failover(reason, is_manual=True)

    def trigger_recovery(self, reason: str = "manual") -> FailoverEvent:
        """
        触发恢复（切回主节点）

        Args:
            reason: 恢复原因

        Returns:
            恢复事件
        """
        return self._do_recovery(reason, is_manual=True)

    def _do_failover(self, reason: str, is_manual: bool = False) -> FailoverEvent:
        """执行故障转移"""
        with self._lock:
            start_time = time.time()
            state_before = self._state.value

            event = FailoverEvent(
                event_id=f"fo_{int(start_time * 1000)}",
                event_type="failover",
                reason=reason,
                state_before=state_before,
            )

            # 检查是否有备节点
            if not self._standby_id or self._standby_id not in self._nodes:
                event.success = False
                event.details["error"] = "No standby node available"
                self._record_event(event)
                logger.error("Failover failed: no standby node")
                return event

            # 检查冷却时间
            if start_time - self._last_switch_time < self.switch_cooldown:
                event.success = False
                event.details["error"] = "In cooldown period"
                event.details["cooldown_remaining"] = self.switch_cooldown - (start_time - self._last_switch_time)
                self._record_event(event)
                logger.warning("Failover skipped: in cooldown period")
                return event

            primary_node = self._nodes.get(self._primary_id) if self._primary_id else None
            standby_node = self._nodes[self._standby_id]

            event.from_node = self._primary_id or ""
            event.to_node = self._standby_id

            self._change_state(FailoverState.FAILING_OVER)
            self._last_failover_start = start_time

            try:
                # 执行状态同步（如果配置了）
                if self._state_sync_fn and primary_node:
                    sync_success = self._state_sync_fn(
                        primary_node.address, standby_node.address
                    )
                    event.details["state_sync"] = sync_success
                    if not sync_success:
                        logger.warning("State sync failed during failover")

                # 角色切换
                if primary_node:
                    primary_node.role = NodeRole.STANDBY
                    primary_node.status = NodeStatus.OFFLINE

                standby_node.role = NodeRole.PRIMARY
                standby_node.status = NodeStatus.ONLINE

                # 更新主备ID
                old_primary = self._primary_id
                self._primary_id = self._standby_id
                self._standby_id = old_primary

                event.success = True
                event.state_after = FailoverState.DEGRADED.value
                self._change_state(FailoverState.DEGRADED)

                self._switch_count += 1
                self._last_switch_time = time.time()

                # 计算停机时间
                event.duration_seconds = time.time() - start_time
                self._total_downtime_seconds += event.duration_seconds

                logger.warning(
                    "Failover completed: %s -> %s (reason=%s, duration=%.3fs)",
                    event.from_node, event.to_node, reason, event.duration_seconds
                )

            except Exception as e:
                event.success = False
                event.details["error"] = str(e)
                event.state_after = state_before
                logger.error("Failover failed: %s", e)

            self._record_event(event)

        if event.success:
            self._fire_failover_event(event)

        return event

    def _do_recovery(self, reason: str, is_manual: bool = False) -> FailoverEvent:
        """执行恢复（切回主节点）"""
        with self._lock:
            start_time = time.time()
            state_before = self._state.value

            event = FailoverEvent(
                event_id=f"rc_{int(start_time * 1000)}",
                event_type="recovery",
                reason=reason,
                state_before=state_before,
            )

            # 当前状态必须是 DEGRADED 才恢复
            if self._state != FailoverState.DEGRADED:
                event.success = False
                event.details["error"] = f"Not in degraded state (current: {state_before})"
                self._record_event(event)
                return event

            # 检查冷却时间
            if start_time - self._last_switch_time < self.switch_cooldown:
                event.success = False
                event.details["error"] = "In cooldown period"
                self._record_event(event)
                return event

            # 找到原来的主节点（现在的备节点）
            if not self._standby_id:
                event.success = False
                event.details["error"] = "No standby to recover to"
                self._record_event(event)
                return event

            current_primary = self._nodes.get(self._primary_id) if self._primary_id else None
            recovery_node = self._nodes.get(self._standby_id)

            if not recovery_node:
                event.success = False
                event.details["error"] = "Recovery node not found"
                self._record_event(event)
                return event

            event.from_node = self._primary_id or ""
            event.to_node = self._standby_id

            self._change_state(FailoverState.RECOVERING)

            try:
                # 状态同步（从当前主节点同步到恢复节点）
                if self._state_sync_fn and current_primary:
                    sync_success = self._state_sync_fn(
                        current_primary.address, recovery_node.address
                    )
                    event.details["state_sync"] = sync_success

                # 角色切换
                if current_primary:
                    current_primary.role = NodeRole.STANDBY

                recovery_node.role = NodeRole.PRIMARY
                recovery_node.status = NodeStatus.ONLINE
                recovery_node.consecutive_failures = 0

                # 更新主备ID
                old_primary = self._primary_id
                self._primary_id = self._standby_id
                self._standby_id = old_primary

                event.success = True
                event.state_after = FailoverState.NORMAL.value
                self._change_state(FailoverState.NORMAL)

                self._last_switch_time = time.time()
                event.duration_seconds = time.time() - start_time

                logger.info(
                    "Recovery completed: %s -> %s (reason=%s, duration=%.3fs)",
                    event.from_node, event.to_node, reason, event.duration_seconds
                )

            except Exception as e:
                event.success = False
                event.details["error"] = str(e)
                event.state_after = state_before
                logger.error("Recovery failed: %s", e)

            self._record_event(event)

        if event.success:
            self._fire_recovery_event(event)

        return event

    # ------------------------------------------------------------------
    #  健康检查循环
    # ------------------------------------------------------------------

    def start_monitor(self) -> bool:
        """启动监控线程"""
        if self._monitor_thread and self._monitor_thread.is_alive():
            return True

        # 初始化状态
        if self._primary_id and self._nodes.get(self._primary_id):
            self._change_state(FailoverState.NORMAL)
        else:
            self._change_state(FailoverState.UNKNOWN)

        self._monitor_stop.clear()
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            name=f"FailoverMonitor-{self.service_name}",
            daemon=True,
        )
        self._monitor_thread.start()
        logger.info("Failover monitor started for %s", self.service_name)
        return True

    def stop_monitor(self) -> None:
        """停止监控"""
        self._monitor_stop.set()
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
            self._monitor_thread = None
        logger.info("Failover monitor stopped for %s", self.service_name)

    def _monitor_loop(self) -> None:
        """监控循环"""
        while not self._monitor_stop.is_set():
            try:
                self._check_all_nodes()
                self._evaluate_failover()
            except Exception as e:
                logger.error("Failover monitor error: %s", e)

            self._monitor_stop.wait(self.check_interval)

    def _check_all_nodes(self) -> None:
        """检查所有节点健康状态"""
        if not self._health_check_fn:
            return

        with self._lock:
            nodes = list(self._nodes.values())

        for node in nodes:
            try:
                is_healthy = self._health_check_fn(node.node_id, node.address)
                with self._lock:
                    node.last_health_check = time.time()
                    if is_healthy:
                        node.consecutive_successes += 1
                        node.consecutive_failures = 0
                        if node.status == NodeStatus.OFFLINE:
                            node.status = NodeStatus.ONLINE
                    else:
                        node.consecutive_failures += 1
                        node.consecutive_successes = 0
                        if node.consecutive_failures >= self.failure_threshold:
                            node.status = NodeStatus.OFFLINE
            except Exception as e:
                with self._lock:
                    node.consecutive_failures += 1
                    logger.error("Health check error for %s: %s", node.node_id, e)

    def _evaluate_failover(self) -> None:
        """评估是否需要故障转移或恢复"""
        with self._lock:
            primary = self._nodes.get(self._primary_id) if self._primary_id else None
            standby = self._nodes.get(self._standby_id) if self._standby_id else None

            if not primary:
                return

            # 主节点故障？
            primary_failed = (
                primary.status == NodeStatus.OFFLINE
                and primary.consecutive_failures >= self.failure_threshold
            )

            if primary_failed and self.auto_failover and self._state == FailoverState.NORMAL:
                if standby and standby.status == NodeStatus.ONLINE:
                    # 执行故障转移
                    logger.warning("Primary node failed, triggering failover: %s", primary.node_id)
                    self._do_failover(f"primary_failed: {primary.node_id}")
                    return

            # 原主节点恢复了？
            if self._state == FailoverState.DEGRADED and self.auto_recovery:
                # 当前备节点（原主节点）是否健康
                if standby and standby.status == NodeStatus.ONLINE:
                    if standby.consecutive_successes >= self.recovery_threshold:
                        logger.info("Primary node recovered, triggering recovery: %s", standby.node_id)
                        self._do_recovery(f"primary_recovered: {standby.node_id}")

    # ------------------------------------------------------------------
    #  事件记录
    # ------------------------------------------------------------------

    def _record_event(self, event: FailoverEvent) -> None:
        """记录事件"""
        self._event_history.append(event)

    def get_event_history(self, limit: int = 20) -> List[FailoverEvent]:
        """获取事件历史"""
        with self._lock:
            events = list(self._event_history)[-limit:]
        return list(reversed(events))

    # ------------------------------------------------------------------
    #  查询接口
    # ------------------------------------------------------------------

    @property
    def state(self) -> FailoverState:
        """当前状态"""
        return self._state

    @property
    def is_monitoring(self) -> bool:
        """是否正在监控"""
        return self._monitor_thread is not None and self._monitor_thread.is_alive()

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            uptime = time.time() - self._start_time
            availability = 1.0
            if uptime > 0 and self._total_downtime_seconds > 0:
                availability = max(0, 1 - self._total_downtime_seconds / uptime)

            return {
                "service_name": self.service_name,
                "mode": self.mode.value,
                "state": self._state.value,
                "uptime_seconds": round(uptime, 2),
                "node_count": len(self._nodes),
                "primary_node": self._primary_id,
                "standby_node": self._standby_id,
                "switch_count": self._switch_count,
                "total_downtime_seconds": round(self._total_downtime_seconds, 3),
                "availability_percent": round(availability * 100, 4),
                "last_switch_time": self._last_switch_time,
                "auto_failover": self.auto_failover,
                "auto_recovery": self.auto_recovery,
                "failure_threshold": self.failure_threshold,
                "check_interval": self.check_interval,
            }
