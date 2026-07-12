"""
GPU 任务编排器

负责 GPU 计算任务的潮汐式调度：
- 根据潮汐阶段动态调整 GPU 任务并发
- 显存预算管理（含超售）
- 任务优先级队列
- 低优先级任务抢占机制（退潮/枯潮时回收低优先级任务显存）
"""

from __future__ import annotations

import time
import threading
from typing import Dict, List, Optional

import structlog

from .models import (
    GPUMission,
    MissionPriority,
    TidePhase,
    TideStrategy,
)

logger = structlog.get_logger(__name__)


class GPUOrchestrator:
    """GPU 任务编排器

    管理 GPU 任务的生命周期，根据潮汐阶段动态调整。
    """

    def __init__(self, strategy: Optional[TideStrategy] = None):
        self._strategy = strategy or TideStrategy()
        self._current_phase: TidePhase = TidePhase.SLACK

        # 任务存储
        self._missions: Dict[str, GPUMission] = {}
        self._pending_queue: List[GPUMission] = []
        self._running_missions: List[GPUMission] = []
        self._completed_missions: List[GPUMission] = []

        # GPU 资源池
        self._gpu_devices: Dict[int, Dict] = {}  # gpu_id -> {total_mb, used_mb, oversell_mb}

        self._lock = threading.RLock()
        self._baseline_concurrency: int = 10
        self._max_queue_size: int = 100

        # 统计
        self._stats = {
            "total_submitted": 0,
            "total_completed": 0,
            "total_failed": 0,
            "total_preempted": 0,
        }

    def update_strategy(self, strategy: TideStrategy):
        self._strategy = strategy

    def set_gpu_devices(self, devices: List[Dict]):
        """设置 GPU 设备列表

        Args:
            devices: [{gpu_id, memory_total_mb, memory_free_mb}, ...]
        """
        with self._lock:
            self._gpu_devices = {}
            for dev in devices:
                gpu_id = dev.get("gpu_id", 0)
                total_mb = dev.get("memory_total_mb", 0)
                self._gpu_devices[gpu_id] = {
                    "total_mb": total_mb,
                    "used_mb": 0.0,  # 已分配的任务显存
                    "free_mb": dev.get("memory_free_mb", total_mb),
                    "oversell_mb": 0.0,
                }

    def update_phase(self, phase: TidePhase):
        """更新潮汐阶段，触发重调度

        Args:
            phase: 新的潮汐阶段
        """
        old_phase = self._current_phase
        self._current_phase = phase

        if old_phase != phase:
            logger.info(f"GPU 编排器阶段切换: {old_phase.value} -> {phase.value}")
            # 阶段变化时重调度
            self._rebalance()

    def submit_mission(self, mission: GPUMission) -> str:
        """提交 GPU 任务

        Args:
            mission: GPU 任务

        Returns:
            任务 ID
        """
        with self._lock:
            # 检查队列容量
            if len(self._pending_queue) >= self._max_queue_size:
                mission.status = "rejected"
                return mission.mission_id

            # 记录提交时的潮汐阶段
            mission.tide_phase_at_submit = self._current_phase
            mission.status = "pending"
            mission.submit_time = time.time()

            self._missions[mission.mission_id] = mission
            self._pending_queue.append(mission)
            self._stats["total_submitted"] += 1

            # 重新排序（优先级 + 时间）
            self._sort_pending_queue()

            # 尝试立即调度
            self._try_schedule()

            return mission.mission_id

    def complete_mission(self, mission_id: str, success: bool = True, result: Dict = None, error: str = ""):
        """标记任务完成

        Args:
            mission_id: 任务 ID
            success: 是否成功
            result: 结果数据
            error: 错误信息
        """
        with self._lock:
            mission = self._missions.get(mission_id)
            if not mission or mission.status not in ("running", "pending"):
                return

            # 释放 GPU 资源
            if mission.assigned_gpu_id >= 0:
                self._release_gpu_memory(mission.assigned_gpu_id, mission.estimated_gpu_memory_mb)

            mission.status = "completed" if success else "failed"
            mission.end_time = time.time()
            mission.result = result or {}
            mission.error_message = error

            if mission in self._running_missions:
                self._running_missions.remove(mission)

            self._completed_missions.append(mission)
            if len(self._completed_missions) > 200:
                self._completed_missions = self._completed_missions[-200:]

            if success:
                self._stats["total_completed"] += 1
            else:
                self._stats["total_failed"] += 1

            # 调度下一个任务
            self._try_schedule()

    def cancel_mission(self, mission_id: str) -> bool:
        """取消任务"""
        with self._lock:
            mission = self._missions.get(mission_id)
            if not mission:
                return False

            if mission.status == "pending":
                if mission in self._pending_queue:
                    self._pending_queue.remove(mission)
                mission.status = "cancelled"
                return True
            elif mission.status == "running":
                # 运行中任务标记取消（实际执行由调用方处理）
                mission.status = "cancelled"
                self._release_gpu_memory(mission.assigned_gpu_id, mission.estimated_gpu_memory_mb)
                if mission in self._running_missions:
                    self._running_missions.remove(mission)
                return True

            return False

    def _try_schedule(self):
        """尝试调度待执行任务（内部调用，需持有锁）"""
        if not self._pending_queue:
            return

        # 计算当前阶段允许的最大并发数
        max_concurrent = int(self._baseline_concurrency * self._strategy.get_concurrency_multiplier(self._current_phase))
        min_priority = self._strategy.get_min_priority(self._current_phase)

        # 当前运行数
        current_running = len(self._running_missions)

        # 优先级排序
        remaining = []
        for mission in self._pending_queue:
            if current_running >= max_concurrent:
                remaining.append(mission)
                continue

            # 检查优先级
            if not self._priority_allowed(mission.priority, min_priority):
                remaining.append(mission)
                continue

            # 尝试分配 GPU
            gpu_id = self._allocate_gpu(mission)
            if gpu_id is not None:
                mission.assigned_gpu_id = gpu_id
                mission.status = "running"
                mission.start_time = time.time()
                mission.tide_phase_at_start = self._current_phase
                self._running_missions.append(mission)
                current_running += 1
                logger.debug(f"任务调度: {mission.mission_id} -> GPU {gpu_id}")
            else:
                remaining.append(mission)

        self._pending_queue = remaining

        # 更新队列位置
        for i, mission in enumerate(self._pending_queue):
            mission.queue_position = i + 1

    def _allocate_gpu(self, mission: GPUMission) -> Optional[int]:
        """为任务分配 GPU

        Returns:
            GPU ID，None 表示分配失败
        """
        if not self._gpu_devices:
            # 没有 GPU 设备信息，假设可以运行（交给外部管理）
            return 0

        oversell_ratio = self._strategy.get_oversell_ratio(self._current_phase)
        required_mb = mission.estimated_gpu_memory_mb

        best_gpu = None
        best_free = -1

        for gpu_id, info in self._gpu_devices.items():
            # 检查 GPU 亲和性
            if mission.preferred_gpu_id is not None and gpu_id != mission.preferred_gpu_id:
                if not mission.gpu_affinity or gpu_id not in mission.gpu_affinity:
                    # 优先选指定的，没有再考虑其他
                    pass

            # 可分配显存 = (总显存 - 已用) * 超售比例
            effective_free = info["free_mb"] * oversell_ratio - info["oversell_mb"]

            if effective_free >= required_mb:
                # 选择剩余显存最多的（负载均衡）
                if effective_free > best_free:
                    best_free = effective_free
                    best_gpu = gpu_id

        if best_gpu is not None:
            info = self._gpu_devices[best_gpu]
            # 优先从真实空闲分配，不够再从超售额度分配
            if info["free_mb"] >= required_mb:
                info["free_mb"] -= required_mb
                info["used_mb"] += required_mb
            else:
                oversell_needed = required_mb - info["free_mb"]
                info["oversell_mb"] += oversell_needed
                info["used_mb"] += required_mb
                info["free_mb"] = 0

        return best_gpu

    def _release_gpu_memory(self, gpu_id: int, memory_mb: float):
        """释放 GPU 显存"""
        if gpu_id not in self._gpu_devices:
            return

        info = self._gpu_devices[gpu_id]

        # 先归还超售部分
        if info["oversell_mb"] > 0:
            from_oversell = min(info["oversell_mb"], memory_mb)
            info["oversell_mb"] -= from_oversell
            memory_mb -= from_oversell

        # 再归还真实空闲
        info["free_mb"] += memory_mb
        info["used_mb"] = max(0, info["used_mb"] - memory_mb)

    def _rebalance(self):
        """阶段变化时重新平衡

        退潮/枯潮时：
        - 检查是否需要抢占低优先级任务
        - 降低并发上限
        """
        if self._current_phase in (TidePhase.EBB, TidePhase.LOW):
            # 检查是否有需要抢占的低优先级任务
            self._preempt_low_priority_if_needed()

        # 重新调度
        self._try_schedule()

    def _preempt_low_priority_if_needed(self):
        """必要时抢占低优先级任务"""
        if self._current_phase == TidePhase.LOW:
            # 枯潮：抢占 BATCH 和 LOW 优先级的可抢占任务
            preempt_level = MissionPriority.HIGH
        elif self._current_phase == TidePhase.EBB:
            # 退潮：抢占 BATCH 优先级
            preempt_level = MissionPriority.NORMAL
        else:
            return

        to_preempt = []
        for mission in self._running_missions:
            if not mission.tide_preemptible:
                continue
            if not self._priority_allowed(mission.priority, preempt_level):
                to_preempt.append(mission)

        for mission in to_preempt:
            logger.info(f"潮汐抢占任务: {mission.mission_id} (优先级={mission.priority.value})")
            mission.status = "preempted"
            mission.end_time = time.time()
            self._release_gpu_memory(mission.assigned_gpu_id, mission.estimated_gpu_memory_mb)
            self._running_missions.remove(mission)
            self._stats["total_preempted"] += 1

            # 放回队列头部（等待涨潮）
            mission.status = "pending"
            mission.assigned_gpu_id = -1
            self._pending_queue.insert(0, mission)

    def _sort_pending_queue(self):
        """对待执行队列排序"""
        # 优先级从高到低，同优先级按提交时间从早到晚
        priority_order = {
            MissionPriority.CRITICAL: 0,
            MissionPriority.HIGH: 1,
            MissionPriority.NORMAL: 2,
            MissionPriority.LOW: 3,
            MissionPriority.BATCH: 4,
        }
        self._pending_queue.sort(
            key=lambda m: (priority_order.get(m.priority, 5), m.submit_time)
        )

    @staticmethod
    def _priority_allowed(task_priority: MissionPriority, min_priority: MissionPriority) -> bool:
        """检查任务优先级是否满足最低要求"""
        priority_order = {
            MissionPriority.CRITICAL: 0,
            MissionPriority.HIGH: 1,
            MissionPriority.NORMAL: 2,
            MissionPriority.LOW: 3,
            MissionPriority.BATCH: 4,
        }
        return priority_order.get(task_priority, 5) <= priority_order.get(min_priority, 5)

    # ============================================================
    # 查询接口
    # ============================================================

    def get_mission(self, mission_id: str) -> Optional[GPUMission]:
        return self._missions.get(mission_id)

    def list_pending(self, limit: int = 20) -> List[GPUMission]:
        with self._lock:
            return self._pending_queue[:limit]

    def list_running(self, limit: int = 20) -> List[GPUMission]:
        with self._lock:
            return self._running_missions[:limit]

    def list_completed(self, limit: int = 20) -> List[GPUMission]:
        with self._lock:
            return list(reversed(self._completed_missions[-limit:]))

    def get_stats(self) -> Dict:
        with self._lock:
            return {
                **self._stats,
                "current_pending": len(self._pending_queue),
                "current_running": len(self._running_missions),
                "current_phase": self._current_phase.value,
                "gpu_count": len(self._gpu_devices),
                "max_concurrent": int(self._baseline_concurrency * self._strategy.get_concurrency_multiplier(self._current_phase)),
                "gpu_devices": {
                    gpu_id: {
                        "total_mb": info["total_mb"],
                        "used_mb": round(info["used_mb"], 1),
                        "free_mb": round(info["free_mb"], 1),
                        "oversell_mb": round(info["oversell_mb"], 1),
                    }
                    for gpu_id, info in self._gpu_devices.items()
                },
            }
