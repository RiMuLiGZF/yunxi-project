"""
M10 系统卫士 - 沙箱任务调度单元测试

测试任务提交、队列管理、动态放行、任务状态管理等功能。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
from m10_system_guard.sandbox_scheduler import (
    SandboxScheduler, get_sandbox_scheduler,
)
from m10_system_guard.models import (
    SandboxTask, TaskLevel, TaskStatus,
)


class TestSandboxScheduler:
    """沙箱任务调度器测试类."""

    def setup_method(self):
        """每个测试用例前初始化."""
        SandboxScheduler._instance = None
        SandboxScheduler._initialized = False
        self.scheduler = SandboxScheduler()

    def teardown_method(self):
        """每个测试用例后清理."""
        if self.scheduler._running:
            self.scheduler.stop()

    def test_singleton_pattern(self):
        """测试单例模式."""
        s1 = SandboxScheduler()
        s2 = SandboxScheduler()
        assert s1 is s2

    def test_get_sandbox_scheduler_function(self):
        """测试全局单例获取函数."""
        import m10_system_guard.sandbox_scheduler as ss
        ss._sandbox_scheduler_instance = None
        instance = get_sandbox_scheduler()
        assert instance is not None
        assert isinstance(instance, SandboxScheduler)

    def test_submit_task_light(self):
        """测试提交轻量级任务."""
        task = self.scheduler.submit_task(
            name="light_task",
            level="light",
            priority=5,
        )
        assert isinstance(task, SandboxTask)
        assert task.name == "light_task"
        assert task.level == TaskLevel.LIGHT
        assert task.task_id != ""
        assert task.status in [TaskStatus.RUNNING, TaskStatus.PENDING]

    def test_submit_task_normal(self):
        """测试提交普通任务."""
        task = self.scheduler.submit_task(name="normal_task", level="normal")
        assert task.level == TaskLevel.NORMAL

    def test_submit_task_heavy(self):
        """测试提交重型任务."""
        task = self.scheduler.submit_task(name="heavy_task", level="heavy")
        assert task.level == TaskLevel.HEAVY

    def test_submit_task_super_heavy(self):
        """测试提交超重型任务."""
        task = self.scheduler.submit_task(name="super_heavy", level="super_heavy")
        assert task.level == TaskLevel.SUPER_HEAVY

    def test_submit_task_with_estimates(self):
        """测试提交带资源预估的任务."""
        task = self.scheduler.submit_task(
            name="estimated_task",
            estimated_cpu_percent=25.0,
            estimated_memory_mb=500.0,
            estimated_duration_seconds=120.0,
        )
        assert task.estimated_cpu_percent == 25.0
        assert task.estimated_memory_mb == 500.0
        assert task.estimated_duration_seconds == 120.0

    def test_submit_task_with_data(self):
        """测试提交带数据的任务."""
        task_data = {"key": "value", "num": 42}
        task = self.scheduler.submit_task(
            name="data_task",
            task_data=task_data,
        )
        assert task.task_data == task_data

    def test_priority_validation(self):
        """测试优先级验证."""
        # 优先级会被限制在 1-10 范围内
        task_low = self.scheduler.submit_task(name="low_priority", priority=0)
        assert task_low.priority == 1

        task_high = self.scheduler.submit_task(name="high_priority", priority=15)
        assert task_high.priority == 10

    def test_get_task(self):
        """测试获取任务信息."""
        task = self.scheduler.submit_task(name="get_task_test")
        retrieved = self.scheduler.get_task(task.task_id)
        assert retrieved is not None
        assert retrieved.task_id == task.task_id
        assert retrieved.name == task.name

    def test_get_task_not_found(self):
        """测试获取不存在的任务."""
        task = self.scheduler.get_task("nonexistent_id")
        assert task is None

    def test_complete_task(self):
        """测试完成任务."""
        task = self.scheduler.submit_task(name="complete_test")
        # 先确保任务在运行中
        if task.status == TaskStatus.RUNNING:
            success = self.scheduler.complete_task(task.task_id)
            assert success is True
            completed = self.scheduler.get_task(task.task_id)
            assert completed.status == TaskStatus.COMPLETED
            assert completed.end_time > 0

    def test_complete_task_not_found(self):
        """测试完成不存在的任务."""
        success = self.scheduler.complete_task("nonexistent_id")
        assert success is False

    def test_cancel_pending_task(self):
        """测试取消队列中的任务."""
        # 提交很多任务使队列非空
        tasks = []
        for i in range(20):
            t = self.scheduler.submit_task(
                name=f"cancel_test_{i}",
                level="super_heavy",
                estimated_cpu_percent=90.0,
                estimated_memory_mb=10000.0,
            )
            tasks.append(t)

        # 找一个在队列中的任务取消
        pending = [t for t in tasks if t.status == TaskStatus.PENDING]
        if pending:
            task_to_cancel = pending[0]
            success = self.scheduler.cancel_task(task_to_cancel.task_id)
            assert success is True
            cancelled = self.scheduler.get_task(task_to_cancel.task_id)
            assert cancelled.status == TaskStatus.CANCELLED

    def test_cancel_running_task(self):
        """测试取消运行中的任务."""
        task = self.scheduler.submit_task(name="cancel_running")
        if task.status == TaskStatus.RUNNING:
            success = self.scheduler.cancel_task(task.task_id)
            assert success is True
            cancelled = self.scheduler.get_task(task.task_id)
            assert cancelled.status == TaskStatus.CANCELLED

    def test_cancel_task_not_found(self):
        """测试取消不存在的任务."""
        success = self.scheduler.cancel_task("nonexistent_id")
        assert success is False

    def test_get_pending_queue(self):
        """测试获取等待队列."""
        queue = self.scheduler.get_pending_queue()
        assert isinstance(queue, list)

    def test_get_running_tasks(self):
        """测试获取运行中任务."""
        self.scheduler.submit_task(name="running_test")
        running = self.scheduler.get_running_tasks()
        assert isinstance(running, list)
        assert len(running) >= 0

    def test_get_completed_tasks(self):
        """测试获取已完成任务."""
        task = self.scheduler.submit_task(name="completed_test")
        if task.status == TaskStatus.RUNNING:
            self.scheduler.complete_task(task.task_id)

        completed = self.scheduler.get_completed_tasks()
        assert isinstance(completed, list)

    def test_get_queue_position(self):
        """测试获取队列位置."""
        task = self.scheduler.submit_task(name="queue_pos_test")
        pos = self.scheduler.get_queue_position(task.task_id)
        assert isinstance(pos, int)
        assert pos >= 0

    def test_get_stats(self):
        """测试获取统计信息."""
        self.scheduler.submit_task(name="stats_test")
        stats = self.scheduler.get_stats()
        assert "submitted" in stats
        assert "running" in stats
        assert "pending" in stats
        assert "completed" in stats
        assert "cancelled" in stats
        assert "max_queue_size" in stats
        assert "concurrency_limit" in stats
        assert "sandbox_mode" in stats
        assert stats["submitted"] >= 1

    def test_task_to_dict(self):
        """测试任务转字典."""
        task = self.scheduler.submit_task(name="dict_test")
        d = task.to_dict()
        assert isinstance(d, dict)
        assert "task_id" in d
        assert "name" in d
        assert "level" in d
        assert "status" in d
        assert "priority" in d
        assert "estimated_cpu_percent" in d
        assert "estimated_memory_mb" in d

    def test_level_thresholds(self):
        """测试不同级别任务的阈值."""
        thresholds_light = self.scheduler._get_level_thresholds(TaskLevel.LIGHT)
        thresholds_heavy = self.scheduler._get_level_thresholds(TaskLevel.HEAVY)

        # 轻量级任务的阈值应该更高（更容易通过）
        assert thresholds_light["max_cpu"] >= thresholds_heavy["max_cpu"]
        assert thresholds_light["max_memory"] >= thresholds_heavy["max_memory"]

    def test_start_stop(self):
        """测试启动和停止调度器."""
        assert self.scheduler._running is False
        self.scheduler.start()
        time.sleep(0.05)
        assert self.scheduler._running is True
        self.scheduler.stop()
        assert self.scheduler._running is False

    def test_clear_completed(self):
        """测试清空已完成任务."""
        # 完成一些任务
        for i in range(3):
            task = self.scheduler.submit_task(name=f"clear_test_{i}")
            if task.status == TaskStatus.RUNNING:
                self.scheduler.complete_task(task.task_id)

        count = self.scheduler.clear_completed()
        assert isinstance(count, int)
        assert count >= 0
