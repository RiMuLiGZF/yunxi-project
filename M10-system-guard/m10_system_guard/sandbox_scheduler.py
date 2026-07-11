"""
M10 系统卫士 - 沙箱任务调度模块 (A6)

任务分级：轻量/普通/重型/超重型
不同级别任务有不同的资源阈值要求
队列管理：超阈值时任务排队
动态放行：资源释放后自动放行队列中的任务
"""

from __future__ import annotations

import time
import uuid
import threading
from collections import deque
from typing import Any, Callable

from .config import get_config
from .models import (
    SandboxTask, TaskLevel, TaskStatus,
)
from .system_monitor import get_system_monitor
from .guard_engine import get_guard_engine


class SandboxScheduler:
    """沙箱任务调度器.

    根据系统资源状况和任务级别，动态管理任务的执行。
    当资源不足时，任务进入队列等待；资源释放后自动放行。

    任务分级：
    - light (轻量): 低资源需求，高优先级放行
    - normal (普通): 标准资源需求
    - heavy (重型): 高资源需求，严格检查
    - super_heavy (超重型): 极高资源需求，最严格检查
    """

    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._init_scheduler()

    def _init_scheduler(self):
        """初始化调度器."""
        config = get_config()
        self.config = config
        self.sched_cfg = config.sandbox_scheduler

        # 依赖组件
        self.system_monitor = get_system_monitor()
        self.guard_engine = get_guard_engine()

        # 任务存储
        self._pending_queue: deque[SandboxTask] = deque()
        self._running_tasks: dict[str, SandboxTask] = {}
        self._completed_tasks: deque[SandboxTask] = deque(maxlen=200)

        # 任务 ID 索引
        self._all_tasks: dict[str, SandboxTask] = {}

        # 锁
        self._lock = threading.Lock()

        # 运行状态
        self._running = False
        self._thread = None

        # 统计
        self._stats = {
            "submitted": 0,
            "rejected": 0,
            "running": 0,
            "completed": 0,
            "cancelled": 0,
        }

    def submit_task(
        self,
        name: str,
        level: str = "normal",
        priority: int = 5,
        estimated_cpu_percent: float = 10.0,
        estimated_memory_mb: float = 100.0,
        estimated_duration_seconds: float = 60.0,
        callback_url: str = "",
        task_data: dict[str, Any] | None = None,
    ) -> SandboxTask:
        """提交一个沙箱任务.

        Args:
            name: 任务名称
            level: 任务级别 (light/normal/heavy/super_heavy)
            priority: 优先级 (1-10)
            estimated_cpu_percent: 预估 CPU 占用 (%)
            estimated_memory_mb: 预估内存占用 (MB)
            estimated_duration_seconds: 预估时长 (秒)
            callback_url: 回调 URL
            task_data: 任务数据

        Returns:
            任务对象
        """
        task_level = TaskLevel(level) if level in [e.value for e in TaskLevel] else TaskLevel.NORMAL

        task = SandboxTask(
            task_id=uuid.uuid4().hex[:16],
            name=name,
            level=task_level,
            status=TaskStatus.PENDING,
            priority=max(1, min(10, priority)),
            estimated_cpu_percent=estimated_cpu_percent,
            estimated_memory_mb=estimated_memory_mb,
            estimated_duration_seconds=estimated_duration_seconds,
            submit_time=time.time(),
            callback_url=callback_url,
            task_data=task_data or {},
        )

        with self._lock:
            # 检查队列是否已满
            if len(self._pending_queue) >= self.sched_cfg.max_queue_size:
                task.status = TaskStatus.REJECTED
                self._stats["rejected"] += 1
                self._all_tasks[task.task_id] = task
                return task

            # 检查是否可以立即执行
            if self._can_start_task(task):
                self._start_task(task)
            else:
                # 加入队列
                self._pending_queue.append(task)
                self._reorder_queue()
                self._update_queue_positions()

            self._stats["submitted"] += 1
            self._all_tasks[task.task_id] = task

        return task

    def _can_start_task(self, task: SandboxTask) -> bool:
        """检查任务是否可以启动.

        根据任务级别和当前系统资源状态判断。

        Args:
            task: 任务对象

        Returns:
            True 表示可以启动
        """
        cfg = self.sched_cfg
        latest = self.system_monitor.get_latest()

        # 获取当前资源使用率（加上预估的任务资源）
        current_cpu = latest.cpu.usage_percent
        current_memory = latest.memory.usage_percent

        # 根据任务级别获取阈值
        thresholds = self._get_level_thresholds(task.level)

        # 检查 CPU（加上预估占用后不能超过阈值）
        if current_cpu + task.estimated_cpu_percent > thresholds["max_cpu"]:
            return False

        # 检查内存
        if current_memory + (task.estimated_memory_mb / latest.memory.total_mb * 100) > thresholds["max_memory"]:
            return False

        # 检查防护引擎状态（重型任务需要额外检查）
        if task.level in (TaskLevel.HEAVY, TaskLevel.SUPER_HEAVY):
            if not self.guard_engine.can_run_heavy_task():
                return False

        # 检查并发限制
        if len(self._running_tasks) >= self.guard_engine.get_concurrency_limit():
            return False

        return True

    def _get_level_thresholds(self, level: TaskLevel) -> dict[str, float]:
        """获取任务级别的资源阈值.

        Args:
            level: 任务级别

        Returns:
            阈值字典
        """
        cfg = self.sched_cfg
        mapping = {
            TaskLevel.LIGHT: {
                "max_cpu": cfg.light_max_cpu,
                "max_memory": cfg.light_max_memory,
            },
            TaskLevel.NORMAL: {
                "max_cpu": cfg.normal_max_cpu,
                "max_memory": cfg.normal_max_memory,
            },
            TaskLevel.HEAVY: {
                "max_cpu": cfg.heavy_max_cpu,
                "max_memory": cfg.heavy_max_memory,
            },
            TaskLevel.SUPER_HEAVY: {
                "max_cpu": cfg.super_heavy_max_cpu,
                "max_memory": cfg.super_heavy_max_memory,
            },
        }
        return mapping.get(level, mapping[TaskLevel.NORMAL])

    def _start_task(self, task: SandboxTask):
        """启动任务（内部调用，需加锁）.

        Args:
            task: 任务对象
        """
        task.status = TaskStatus.RUNNING
        task.start_time = time.time()
        task.queue_position = 0
        self._running_tasks[task.task_id] = task
        self._stats["running"] = len(self._running_tasks)

    def _reorder_queue(self):
        """重新排序队列（按优先级和提交时间）.

        优先级高的在前，同优先级按提交时间排序。
        """
        tasks = list(self._pending_queue)
        tasks.sort(key=lambda t: (-t.priority, t.submit_time))
        self._pending_queue = deque(tasks)

    def _update_queue_positions(self):
        """更新队列中任务的位置信息."""
        for i, task in enumerate(self._pending_queue):
            task.queue_position = i + 1

    def complete_task(self, task_id: str) -> bool:
        """标记任务完成.

        Args:
            task_id: 任务 ID

        Returns:
            是否成功
        """
        with self._lock:
            task = self._running_tasks.pop(task_id, None)
            if task is None:
                return False

            task.status = TaskStatus.COMPLETED
            task.end_time = time.time()
            self._completed_tasks.append(task)
            self._stats["completed"] += 1
            self._stats["running"] = len(self._running_tasks)

            # 任务完成后，尝试放行队列中的任务
            self._try_release_pending()

            return True

    def cancel_task(self, task_id: str) -> bool:
        """取消任务.

        Args:
            task_id: 任务 ID

        Returns:
            是否成功
        """
        with self._lock:
            # 检查是否在队列中
            for i, task in enumerate(self._pending_queue):
                if task.task_id == task_id:
                    task.status = TaskStatus.CANCELLED
                    del self._pending_queue[i]
                    self._stats["cancelled"] += 1
                    self._update_queue_positions()
                    return True

            # 检查是否在运行中
            task = self._running_tasks.pop(task_id, None)
            if task:
                task.status = TaskStatus.CANCELLED
                task.end_time = time.time()
                self._completed_tasks.append(task)
                self._stats["cancelled"] += 1
                self._stats["running"] = len(self._running_tasks)
                # 尝试放行队列中的任务
                self._try_release_pending()
                return True

            return False

    def _try_release_pending(self):
        """尝试放行队列中等待的任务（内部调用，需加锁）.

        从队首开始检查，能启动的就启动。
        """
        while self._pending_queue:
            task = self._pending_queue[0]
            if self._can_start_task(task):
                self._pending_queue.popleft()
                self._start_task(task)
                self._update_queue_positions()
            else:
                break

    def get_task(self, task_id: str) -> SandboxTask | None:
        """获取任务信息.

        Args:
            task_id: 任务 ID

        Returns:
            任务对象
        """
        return self._all_tasks.get(task_id)

    def get_pending_queue(self, limit: int = 50) -> list[SandboxTask]:
        """获取等待队列.

        Args:
            limit: 返回数量限制

        Returns:
            等待任务列表
        """
        with self._lock:
            return list(self._pending_queue)[:limit]

    def get_running_tasks(self, limit: int = 50) -> list[SandboxTask]:
        """获取运行中的任务.

        Args:
            limit: 返回数量限制

        Returns:
            运行中任务列表
        """
        with self._lock:
            return list(self._running_tasks.values())[:limit]

    def get_completed_tasks(self, limit: int = 50) -> list[SandboxTask]:
        """获取已完成的任务.

        Args:
            limit: 返回数量限制

        Returns:
            已完成任务列表（按完成时间倒序）
        """
        with self._lock:
            return list(reversed(self._completed_tasks))[:limit]

    def get_queue_position(self, task_id: str) -> int:
        """获取任务在队列中的位置.

        Args:
            task_id: 任务 ID

        Returns:
            队列位置（从1开始），0 表示不在队列中
        """
        with self._lock:
            for i, task in enumerate(self._pending_queue):
                if task.task_id == task_id:
                    return i + 1
            return 0

    def get_stats(self) -> dict[str, Any]:
        """获取调度器统计信息.

        Returns:
            统计信息字典
        """
        with self._lock:
            return {
                "submitted": self._stats["submitted"],
                "rejected": self._stats["rejected"],
                "running": len(self._running_tasks),
                "pending": len(self._pending_queue),
                "completed": self._stats["completed"],
                "cancelled": self._stats["cancelled"],
                "max_queue_size": self.sched_cfg.max_queue_size,
                "concurrency_limit": self.guard_engine.get_concurrency_limit(),
                "sandbox_mode": self.config.sandbox.enabled,
            }

    def start(self):
        """启动调度器后台检查."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """停止调度器."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _scheduler_loop(self):
        """调度器主循环（后台线程）.

        定期检查队列，尝试放行等待的任务。
        """
        while self._running:
            try:
                with self._lock:
                    self._try_release_pending()
            except Exception:
                pass
            time.sleep(self.sched_cfg.queue_check_interval)

    def clear_completed(self) -> int:
        """清空已完成任务记录.

        Returns:
            清除的数量
        """
        with self._lock:
            count = len(self._completed_tasks)
            self._completed_tasks.clear()
            return count


# 全局单例获取函数
_sandbox_scheduler_instance = None


def get_sandbox_scheduler() -> SandboxScheduler:
    """获取沙箱调度器单例."""
    global _sandbox_scheduler_instance
    if _sandbox_scheduler_instance is None:
        _sandbox_scheduler_instance = SandboxScheduler()
    return _sandbox_scheduler_instance
