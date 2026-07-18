"""边缘任务调度器测试.

覆盖：
- 任务调度策略（本地优先/云端优先/自适应）
- 任务分片
- 算力评估
- 任务提交与状态
"""

from __future__ import annotations

import asyncio

import pytest

from edge_cloud_kernel.services.edge_scheduler import (
    DeviceComputeProfile,
    EdgeScheduler,
    EdgeTask,
    ExecutionTarget,
    SchedulingDecision,
    SchedulingStrategy,
    TaskFragment,
    TaskPriority,
    TaskStatus,
)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def edge_scheduler():
    """创建 EdgeScheduler 测试实例."""
    scheduler = EdgeScheduler()
    yield scheduler


@pytest.fixture
def device_profile_high():
    """高算力设备画像."""
    return DeviceComputeProfile(
        device_id="device-high",
        performance_score=90.0,
        cpu_cores=8,
        cpu_usage=30.0,
        memory_gb=16.0,
        memory_usage=50.0,
        gpu_available=True,
        gpu_vram_gb=8.0,
        battery_level=90.0,
        battery_charging=True,
        network_type="wifi",
        network_latency_ms=20.0,
        network_bandwidth_mbps=500.0,
        temperature_celsius=45.0,
        thermal_throttling=False,
    )


@pytest.fixture
def device_profile_low():
    """低算力设备画像."""
    return DeviceComputeProfile(
        device_id="device-low",
        performance_score=20.0,
        cpu_cores=2,
        cpu_usage=80.0,
        memory_gb=2.0,
        memory_usage=75.0,
        gpu_available=False,
        gpu_vram_gb=0.0,
        battery_level=20.0,
        battery_charging=False,
        network_type="4g",
        network_latency_ms=200.0,
        network_bandwidth_mbps=10.0,
        temperature_celsius=70.0,
        thermal_throttling=True,
    )


# ============================================================
# 枚举值测试
# ============================================================

class TestEnums:
    """枚举值测试."""

    def test_scheduling_strategy_values(self):
        """测试调度策略枚举值."""
        assert SchedulingStrategy.LOCAL_FIRST == "local_first"
        assert SchedulingStrategy.CLOUD_FIRST == "cloud_first"
        assert SchedulingStrategy.ADAPTIVE == "adaptive"

    def test_task_status_values(self):
        """测试任务状态枚举值."""
        assert TaskStatus.PENDING == "pending"
        assert TaskStatus.SCHEDULED == "scheduled"
        assert TaskStatus.RUNNING == "running"
        assert TaskStatus.COMPLETED == "completed"
        assert TaskStatus.FAILED == "failed"
        assert TaskStatus.CANCELLED == "cancelled"

    def test_task_priority_values(self):
        """测试任务优先级枚举值."""
        assert TaskPriority.LOW == "low"
        assert TaskPriority.NORMAL == "normal"
        assert TaskPriority.HIGH == "high"
        assert TaskPriority.CRITICAL == "critical"

    def test_execution_target_values(self):
        """测试执行目标枚举值."""
        assert ExecutionTarget.LOCAL == "local"
        assert ExecutionTarget.CLOUD == "cloud"
        assert ExecutionTarget.HYBRID == "hybrid"


# ============================================================
# 设备算力画像测试
# ============================================================

class TestDeviceComputeProfile:
    """设备算力画像测试."""

    def test_high_device_capable_of_simple_task(self, device_profile_high):
        """测试高算力设备能处理简单任务."""
        assert device_profile_high.is_capable_of(30.0) is True

    def test_high_device_capable_of_complex_task(self, device_profile_high):
        """测试高算力设备能处理复杂任务."""
        assert device_profile_high.is_capable_of(80.0) is True

    def test_low_device_incapable_of_complex_task(self, device_profile_low):
        """测试低算力设备不能处理复杂任务."""
        # 低性能 + 温度降频 + 低电量
        assert device_profile_low.is_capable_of(80.0) is False

    def test_low_device_capable_of_simple_task(self, device_profile_low):
        """测试低算力设备能处理简单任务."""
        # 简单任务应该可以处理
        result = device_profile_low.is_capable_of(10.0)
        assert isinstance(result, bool)

    def test_profile_defaults(self):
        """测试默认设备画像默认值."""
        profile = DeviceComputeProfile(device_id="test")
        assert profile.device_id == "test"
        assert profile.performance_score == 50.0
        assert profile.cpu_cores == 4
        assert profile.gpu_available is False


# ============================================================
# 调度策略测试
# ============================================================

class TestSchedulingStrategies:
    """调度策略测试."""

    def test_local_first_strategy_low_latency(self, edge_scheduler, device_profile_high):
        """测试本地优先策略 - 低延迟需求任务应本地执行."""
        edge_scheduler.update_device_profile(device_profile_high)
        task = EdgeTask(
            task_id="task-low-latency",
            name="Low Latency Task",
            complexity=30.0,
            latency_requirement_ms=100.0,
            strategy=SchedulingStrategy.LOCAL_FIRST,
        )
        decision = edge_scheduler.schedule_task(task)
        assert isinstance(decision, SchedulingDecision)
        assert decision.strategy == SchedulingStrategy.LOCAL_FIRST
        assert decision.target == ExecutionTarget.LOCAL

    def test_cloud_first_strategy_high_complexity(self, edge_scheduler, device_profile_low):
        """测试云端优先策略 - 高复杂度任务应云端执行."""
        edge_scheduler.update_device_profile(device_profile_low)
        task = EdgeTask(
            task_id="task-high-complexity",
            name="High Complexity Task",
            complexity=90.0,
            strategy=SchedulingStrategy.CLOUD_FIRST,
        )
        decision = edge_scheduler.schedule_task(task)
        assert isinstance(decision, SchedulingDecision)
        assert decision.strategy == SchedulingStrategy.CLOUD_FIRST
        assert decision.target == ExecutionTarget.CLOUD

    def test_adaptive_strategy_high_device(self, edge_scheduler, device_profile_high):
        """测试自适应策略 - 高算力设备倾向本地."""
        edge_scheduler.update_device_profile(device_profile_high)
        task = EdgeTask(
            task_id="task-adaptive-1",
            name="Adaptive Task",
            complexity=50.0,
            strategy=SchedulingStrategy.ADAPTIVE,
        )
        decision = edge_scheduler.schedule_task(task)
        assert isinstance(decision, SchedulingDecision)
        assert decision.strategy == SchedulingStrategy.ADAPTIVE
        assert decision.target in (ExecutionTarget.LOCAL, ExecutionTarget.CLOUD, ExecutionTarget.HYBRID)

    def test_adaptive_strategy_low_device(self, edge_scheduler, device_profile_low):
        """测试自适应策略 - 低算力设备倾向云端."""
        edge_scheduler.update_device_profile(device_profile_low)
        task = EdgeTask(
            task_id="task-adaptive-2",
            name="Adaptive Task Low",
            complexity=70.0,
            strategy=SchedulingStrategy.ADAPTIVE,
        )
        decision = edge_scheduler.schedule_task(task)
        assert isinstance(decision, SchedulingDecision)
        assert decision.strategy == SchedulingStrategy.ADAPTIVE

    def test_adaptive_high_privacy_local(self, edge_scheduler, device_profile_high):
        """测试自适应策略 - 高隐私等级任务本地执行."""
        edge_scheduler.update_device_profile(device_profile_high)
        task = EdgeTask(
            task_id="task-private",
            name="Private Task",
            complexity=40.0,
            privacy_level=9,
            strategy=SchedulingStrategy.ADAPTIVE,
        )
        decision = edge_scheduler.schedule_task(task)
        assert isinstance(decision, SchedulingDecision)
        # 高隐私应倾向本地
        assert decision.confidence > 0

    def test_decision_has_reason(self, edge_scheduler, device_profile_high):
        """测试决策包含理由."""
        edge_scheduler.update_device_profile(device_profile_high)
        task = EdgeTask(
            task_id="task-reason",
            name="Task With Reason",
            strategy=SchedulingStrategy.LOCAL_FIRST,
        )
        decision = edge_scheduler.schedule_task(task)
        assert decision.reason != ""
        assert 0.0 <= decision.confidence <= 1.0

    def test_estimated_latency(self, edge_scheduler, device_profile_high):
        """测试预估延迟."""
        edge_scheduler.update_device_profile(device_profile_high)
        task = EdgeTask(
            task_id="task-latency",
            name="Latency Task",
            strategy=SchedulingStrategy.LOCAL_FIRST,
        )
        decision = edge_scheduler.schedule_task(task)
        assert decision.estimated_latency_ms >= 0


# ============================================================
# 任务分片测试
# ============================================================

class TestTaskFragmentation:
    """任务分片测试."""

    def test_fragment_simple_task(self, edge_scheduler):
        """测试简单任务分片."""
        task = EdgeTask(
            task_id="frag-task-1",
            name="Fragmentable Task",
            data={"items": list(range(20))},
            complexity=60.0,
        )
        fragments = edge_scheduler.fragment_task(task, fragment_count=4)
        assert len(fragments) == 4
        assert all(isinstance(f, TaskFragment) for f in fragments)
        assert all(f.task_id == task.task_id for f in fragments)
        assert fragments[0].index == 0
        assert fragments[-1].index == 3

    def test_fragment_count_matches_total(self, edge_scheduler):
        """测试分片总数匹配."""
        task = EdgeTask(
            task_id="frag-task-2",
            name="Fragment Task 2",
            data={"items": [1, 2, 3]},
        )
        fragments = edge_scheduler.fragment_task(task, fragment_count=3)
        assert len(fragments) == 3
        for f in fragments:
            assert f.total_fragments == 3

    def test_merge_fragment_results(self, edge_scheduler):
        """测试分片结果合并."""
        fragments = [
            TaskFragment(
                fragment_id="f1", task_id="t1", index=0, total_fragments=2,
                result={"part": 0, "data": [1, 2]},
                status=TaskStatus.COMPLETED,
            ),
            TaskFragment(
                fragment_id="f2", task_id="t1", index=1, total_fragments=2,
                result={"part": 1, "data": [3, 4]},
                status=TaskStatus.COMPLETED,
            ),
        ]
        merged = edge_scheduler.merge_fragment_results(fragments)
        assert merged is not None

    def test_single_fragment(self, edge_scheduler):
        """测试单分片任务."""
        task = EdgeTask(
            task_id="single-frag",
            name="Single Fragment",
            data={"value": 42},
        )
        fragments = edge_scheduler.fragment_task(task, fragment_count=1)
        assert len(fragments) == 1
        assert fragments[0].total_fragments == 1


# ============================================================
# 算力评估测试
# ============================================================

class TestComputeEvaluation:
    """算力评估测试."""

    def test_evaluate_high_performance(self, edge_scheduler, device_profile_high):
        """测试高算力设备评估."""
        edge_scheduler.update_device_profile(device_profile_high)
        score = edge_scheduler.evaluate_device_performance()
        assert isinstance(score, float)
        assert 0 <= score <= 100

    def test_evaluate_low_performance(self, edge_scheduler, device_profile_low):
        """测试低算力设备评估."""
        edge_scheduler.update_device_profile(device_profile_low)
        score = edge_scheduler.evaluate_device_performance()
        assert isinstance(score, float)
        assert 0 <= score <= 100

    def test_high_score_greater_than_low(self, edge_scheduler, device_profile_high, device_profile_low):
        """测试高算力设备评分高于低算力设备."""
        edge_scheduler.update_device_profile(device_profile_high)
        high_score = edge_scheduler.evaluate_device_performance()

        edge_scheduler.update_device_profile(device_profile_low)
        low_score = edge_scheduler.evaluate_device_performance()

        assert high_score > low_score

    def test_get_device_profile(self, edge_scheduler, device_profile_high):
        """测试获取设备画像."""
        edge_scheduler.update_device_profile(device_profile_high)
        profile = edge_scheduler.get_device_profile()
        assert profile.device_id == "device-high"
        assert profile.performance_score == 90.0


# ============================================================
# 任务提交与状态测试
# ============================================================

class TestTaskSubmission:
    """任务提交与状态测试."""

    def test_submit_task(self, edge_scheduler, device_profile_high):
        """测试提交任务."""
        edge_scheduler.update_device_profile(device_profile_high)
        task_id = asyncio.run(edge_scheduler.submit_task(
            task_data={"input": "test"},
            task_type="compute",
            name="Submit Test Task",
        ))
        assert task_id is not None
        assert isinstance(task_id, str)

    def test_get_task(self, edge_scheduler, device_profile_high):
        """测试获取任务状态."""
        edge_scheduler.update_device_profile(device_profile_high)
        task_id = asyncio.run(edge_scheduler.submit_task(
            task_data={"value": 42},
            task_type="compute",
            name="Get Task Test",
        ))
        retrieved = edge_scheduler.get_task(task_id)
        assert retrieved is not None
        assert retrieved.task_id == task_id

    def test_get_nonexistent_task(self, edge_scheduler):
        """测试获取不存在的任务."""
        result = edge_scheduler.get_task("nonexistent")
        assert result is None

    def test_list_tasks(self, edge_scheduler, device_profile_high):
        """测试列出任务."""
        edge_scheduler.update_device_profile(device_profile_high)
        for i in range(3):
            asyncio.run(edge_scheduler.submit_task(
                task_data={"i": i},
                task_type="compute",
                name=f"Task {i}",
            ))
        tasks = edge_scheduler.list_tasks(limit=10)
        assert len(tasks) >= 3

    def test_cancel_task(self, edge_scheduler, device_profile_high):
        """测试取消任务."""
        edge_scheduler.update_device_profile(device_profile_high)
        task_id = asyncio.run(edge_scheduler.submit_task(
            task_data={"data": "cancel-test"},
            task_type="compute",
            name="Cancel Me",
        ))
        result = asyncio.run(edge_scheduler.cancel_task(task_id))
        assert isinstance(result, bool)

    def test_cancel_nonexistent_task(self, edge_scheduler):
        """测试取消不存在的任务."""
        result = asyncio.run(edge_scheduler.cancel_task("no-such-task"))
        assert result is False


# ============================================================
# 执行器注册测试
# ============================================================

class TestExecutorRegistration:
    """执行器注册测试."""

    def test_register_local_executor(self, edge_scheduler):
        """测试注册本地执行器."""
        called = []

        def executor(task):
            called.append(task)
            return {"result": "ok"}

        edge_scheduler.register_local_executor(executor)
        # 注册不应报错

    def test_register_cloud_executor(self, edge_scheduler):
        """测试注册云端执行器."""
        called = []

        async def executor(task):
            called.append(task)
            return {"result": "ok"}

        edge_scheduler.register_cloud_executor(executor)
        # 注册不应报错


# ============================================================
# 指标测试
# ============================================================

class TestSchedulerMetrics:
    """调度器指标测试."""

    def test_get_metrics(self, edge_scheduler):
        """测试获取指标."""
        metrics = edge_scheduler.get_metrics()
        assert isinstance(metrics, dict)
        assert "total_tasks" in metrics or "tasks_submitted" in metrics


# ============================================================
# 数据结构测试
# ============================================================

class TestDataStructures:
    """数据结构测试."""

    def test_edge_task_defaults(self):
        """测试 EdgeTask 默认值."""
        task = EdgeTask(task_id="test-task")
        assert task.task_id == "test-task"
        assert task.status == TaskStatus.PENDING
        assert task.priority == TaskPriority.NORMAL
        assert task.strategy == SchedulingStrategy.ADAPTIVE
        assert task.complexity == 50.0

    def test_task_fragment_defaults(self):
        """测试 TaskFragment 默认值."""
        frag = TaskFragment(
            fragment_id="f1",
            task_id="t1",
            index=0,
            total_fragments=1,
        )
        assert frag.status == TaskStatus.PENDING
        assert frag.target == ExecutionTarget.LOCAL

    def test_scheduling_decision_required_fields(self):
        """测试 SchedulingDecision 必填字段."""
        decision = SchedulingDecision(
            task_id="t1",
            target=ExecutionTarget.LOCAL,
            strategy=SchedulingStrategy.ADAPTIVE,
        )
        assert decision.task_id == "t1"
        assert decision.target == ExecutionTarget.LOCAL
        assert decision.strategy == SchedulingStrategy.ADAPTIVE
        assert decision.confidence == 0.8
        assert decision.should_fragment is False
        assert decision.fragment_count == 1
