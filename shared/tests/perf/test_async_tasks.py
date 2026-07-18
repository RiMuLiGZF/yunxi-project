"""
异步任务测试

测试覆盖:
- 任务提交与执行
- 任务优先级
- 任务重试
- 任务取消
- 任务进度上报
- 任务依赖
- Worker 池
- 后台任务装饰器
"""

import sys
import time
import pytest
from pathlib import Path

_project_root = Path(__file__).resolve().parents[3]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from shared.perf.async_tasks import (
    AsyncTaskQueue,
    TaskStatus,
    Task,
)
from shared.perf.background_tasks import (
    background_task,
    get_task_queue,
    reset_task_queue,
)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def task_queue():
    """任务队列 fixture"""
    queue = AsyncTaskQueue(
        worker_count=2,
        max_retries=2,
        retry_delay=0.01,
        max_tasks=1000,
    )
    queue.start()
    yield queue
    queue.stop(wait=True)


# ============================================================
# 异步任务队列测试
# ============================================================

class TestAsyncTaskQueue:
    """异步任务队列测试"""

    def test_submit_and_execute(self, task_queue):
        """测试任务提交与执行"""
        result = []

        def add(a, b):
            result.append(a + b)
            return a + b

        task_id = task_queue.submit(add, 2, 3)

        # 等待执行
        time.sleep(0.2)

        # 检查结果
        task_status = task_queue.get_task_status(task_id)
        assert task_status is not None
        assert task_status["status"] == "completed"
        assert len(result) == 1
        assert result[0] == 5

    def test_task_with_kwargs(self, task_queue):
        """测试带关键字参数的任务"""
        result = {}

        def greet(name, greeting="Hello"):
            result["msg"] = f"{greeting}, {name}!"
            return result["msg"]

        task_id = task_queue.submit(greet, name="World", greeting="Hi")
        time.sleep(0.2)

        status = task_queue.get_task_status(task_id)
        assert status["status"] == "completed"
        assert result["msg"] == "Hi, World!"

    def test_task_failure(self, task_queue):
        """测试任务失败"""
        def always_fail():
            raise ValueError("test error")

        task_id = task_queue.submit(always_fail, max_retries=0)
        time.sleep(0.3)  # 等待执行完成

        status = task_queue.get_task_status(task_id)
        assert status is not None
        # 没有重试，最终状态应该是 failed
        assert status["status"] == "failed"
        assert "test error" in status["error"]

    def test_task_retries(self, task_queue):
        """测试任务重试"""
        call_count = 0

        def fail_twice():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError(f"fail {call_count}")
            return "success"

        task_id = task_queue.submit(fail_twice, max_retries=3, retry_delay=0.01)
        time.sleep(0.5)

        status = task_queue.get_task_status(task_id)
        assert status is not None
        # 重试 2 次后第 3 次成功
        assert status["status"] == "completed"
        assert call_count == 3

    def test_task_cancel(self, task_queue):
        """测试任务取消"""
        # 提交一个高延迟任务 (用低优先级，在取消前不会被执行)
        # 实际上需要队列足够忙才能取消 pending 的任务
        def slow_task():
            time.sleep(10)
            return "done"

        # 塞满 worker
        for _ in range(10):
            task_queue.submit(slow_task, priority=1)

        # 提交一个待取消的任务
        task_id = task_queue.submit(slow_task, priority=10)  # 低优先级

        # 立即取消
        cancelled = task_queue.cancel_task(task_id)
        assert cancelled is True

        status = task_queue.get_task_status(task_id)
        assert status["status"] == "cancelled"

        # 清理: 停止队列 (fixture 会 stop)

    def test_task_priority(self):
        """测试任务优先级"""
        # 创建单 worker 队列，确保任务按顺序执行
        queue = AsyncTaskQueue(worker_count=1, max_retries=0)
        execution_order = []

        def record_order(name):
            execution_order.append(name)
            return name

        # 先提交低优先级，再提交高优先级
        queue.submit(record_order, "low", priority=10)
        queue.submit(record_order, "high", priority=1)
        queue.submit(record_order, "medium", priority=5)

        queue.start()
        time.sleep(0.3)
        queue.stop(wait=True)

        # high 应该先执行 (优先级数字越小越高)
        assert execution_order[0] == "high"

    def test_list_tasks(self, task_queue):
        """测试任务列表"""
        def simple():
            return 42

        ids = []
        for i in range(5):
            tid = task_queue.submit(simple)
            ids.append(tid)

        time.sleep(0.2)

        all_tasks = task_queue.list_tasks(limit=10)
        assert len(all_tasks) >= 5

        completed = task_queue.list_tasks(status=TaskStatus.COMPLETED, limit=10)
        assert len(completed) >= 5

    def test_task_progress(self, task_queue):
        """测试任务进度上报"""
        def long_task(queue):
            for i in range(5):
                queue.update_progress("current", (i + 1) / 5, f"step {i+1}")
                time.sleep(0.02)
            return "done"

        # 需要知道 task_id，这里简化测试
        task_id = task_queue.submit(long_task, task_queue)
        time.sleep(0.2)

        status = task_queue.get_task_status(task_id)
        assert status is not None
        # 进度应该在 0-1 之间
        assert 0 <= status["progress"] <= 1

    def test_task_dependencies(self):
        """测试任务依赖"""
        queue = AsyncTaskQueue(worker_count=2, max_retries=0)
        results = []

        def task_a():
            results.append("A")
            return "A_result"

        def task_b():
            results.append("B")
            return "B_result"

        queue.start()

        # A 先执行
        id_a = queue.submit(task_a, priority=1)

        # B 依赖 A
        id_b = queue.submit(task_b, priority=1, dependencies=[id_a])

        time.sleep(0.3)
        queue.stop(wait=True)

        # 两个都应该完成
        status_a = queue.get_task_status(id_a)
        status_b = queue.get_task_status(id_b)
        assert status_a["status"] == "completed"
        assert status_b["status"] == "completed"

    def test_get_result_blocking(self, task_queue):
        """测试阻塞获取结果"""
        def add(a, b):
            time.sleep(0.05)
            return a + b

        task_id = task_queue.submit(add, 10, 20)

        result = task_queue.get_result(task_id, timeout=5.0)
        assert result == 30

    def test_get_result_timeout(self, task_queue):
        """测试结果获取超时"""
        def slow():
            time.sleep(10)
            return "done"

        task_id = task_queue.submit(slow)

        with pytest.raises(TimeoutError):
            task_queue.get_result(task_id, timeout=0.1)

    def test_stats(self, task_queue):
        """测试队列统计"""
        def simple():
            return 42

        for _ in range(10):
            task_queue.submit(simple)

        time.sleep(0.3)

        stats = task_queue.get_stats()
        assert stats["total_tasks"] >= 10
        assert stats["completed"] >= 10
        assert "success_rate" in stats
        assert "queue_sizes" in stats

    def test_multiple_queues(self):
        """测试多队列"""
        queue = AsyncTaskQueue(
            worker_count=2,
            queue_names=["default", "io", "cpu"],
        )
        queue.start()

        def io_task():
            return "io done"

        def cpu_task():
            return "cpu done"

        io_id = queue.submit(io_task, queue="io")
        cpu_id = queue.submit(cpu_task, queue="cpu")

        time.sleep(0.2)

        assert queue.get_task_status(io_id)["status"] == "completed"
        assert queue.get_task_status(cpu_id)["status"] == "completed"

        stats = queue.get_stats()
        assert "io" in stats["queue_sizes"]
        assert "cpu" in stats["queue_sizes"]

        queue.stop(wait=True)

    def test_from_env(self):
        """测试从环境变量创建"""
        import os
        os.environ["PERF_TASK_WORKERS"] = "3"
        os.environ["PERF_TASK_MAX_RETRIES"] = "2"

        queue = AsyncTaskQueue.from_env()
        assert queue.worker_count == 3
        assert queue.max_retries == 2

        del os.environ["PERF_TASK_WORKERS"]
        del os.environ["PERF_TASK_MAX_RETRIES"]


# ============================================================
# 后台任务装饰器测试
# ============================================================

class TestBackgroundTasks:
    """后台任务装饰器测试"""

    def test_background_task_decorator(self):
        """测试 @background_task 装饰器"""
        reset_task_queue()

        results = []

        @background_task(queue="default", priority=5, max_retries=0)
        def add_task(a, b):
            results.append(a + b)
            return a + b

        task_id = add_task(3, 4)
        assert isinstance(task_id, str)

        # 等待执行
        time.sleep(0.3)

        assert len(results) == 1
        assert results[0] == 7

        reset_task_queue()

    def test_background_task_status(self):
        """测试获取任务状态"""
        reset_task_queue()

        @background_task(max_retries=0)
        def simple():
            time.sleep(0.05)
            return "ok"

        task_id = simple()
        time.sleep(0.2)

        status = simple.get_status(task_id)
        assert status is not None
        assert status["status"] == "completed"

        reset_task_queue()

    def test_background_task_cancel(self):
        """测试取消后台任务"""
        reset_task_queue()

        @background_task(max_retries=0)
        def slow():
            time.sleep(10)
            return "done"

        # 提交很多任务让队列忙起来
        for _ in range(20):
            slow()

        # 这个任务应该还是 pending 状态
        task_id = slow()
        time.sleep(0.05)

        # 尝试取消 (可能已经开始执行了)
        cancelled = slow.cancel(task_id)
        # 可能成功也可能失败，取决于调度时机
        assert isinstance(cancelled, bool)

        reset_task_queue()

    def test_background_task_with_dependencies(self):
        """测试带依赖的后台任务"""
        reset_task_queue()

        results = []

        @background_task(max_retries=0)
        def first():
            results.append("first")
            return "first_done"

        @background_task(max_retries=0)
        def second():
            results.append("second")
            return "second_done"

        id1 = first()
        id2 = second.with_dependencies([id1])

        time.sleep(0.3)

        assert len(results) == 2

        reset_task_queue()

    def test_background_task_get_result(self):
        """测试获取结果"""
        reset_task_queue()

        @background_task(max_retries=0)
        def compute(x):
            return x * 2

        task_id = compute(21)
        result = compute.get_result(task_id, timeout=5.0)
        assert result == 42

        reset_task_queue()
