"""
测试：舱壁模式（Bulkhead Pattern）
"""

import pytest
import sys
import os
import asyncio

# 将项目根目录加入路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bulkhead import (
    SemaphoreBulkhead,
    BulkheadRegistry,
    BulkheadFullError,
    bulkhead as bulkhead_decorator,
)


# ── SemaphoreBulkhead 基本功能测试 ────────────────────────


@pytest.mark.asyncio
async def test_bulkhead_execute_success():
    """测试舱壁正常执行异步函数"""
    bh = SemaphoreBulkhead("test_success", max_concurrent=5)

    async def work():
        return "done"

    result = await bh.execute(work)
    assert result == "done"


@pytest.mark.asyncio
async def test_bulkhead_execute_with_args():
    """测试舱壁执行带参数的函数"""
    bh = SemaphoreBulkhead("test_args", max_concurrent=5)

    async def add(a, b):
        return a + b

    result = await bh.execute(add, 3, 4)
    assert result == 7


@pytest.mark.asyncio
async def test_bulkhead_execute_with_kwargs():
    """测试舱壁执行带关键字参数的函数"""
    bh = SemaphoreBulkhead("test_kwargs", max_concurrent=5)

    async def greet(name, greeting="Hello"):
        return f"{greeting}, {name}!"

    result = await bh.execute(greet, "Alice", greeting="Hi")
    assert result == "Hi, Alice!"


@pytest.mark.asyncio
async def test_bulkhead_concurrent_limit():
    """测试舱壁并发限制功能：最大并发数生效"""
    bh = SemaphoreBulkhead("test_concurrent", max_concurrent=2, max_waiting=10)
    running = 0
    max_running = 0
    lock = asyncio.Lock()

    async def work():
        nonlocal running, max_running
        async with lock:
            running += 1
            if running > max_running:
                max_running = running
        await asyncio.sleep(0.05)
        async with lock:
            running -= 1

    # 启动 5 个并发任务
    tasks = [asyncio.create_task(bh.execute(work)) for _ in range(5)]
    await asyncio.gather(*tasks)

    assert max_running <= 2, f"最大并发应不超过 2，实际为 {max_running}"


# ── 满队列拒绝测试 ────────────────────────────────────────


@pytest.mark.asyncio
async def test_bulkhead_full_rejection():
    """测试满队列拒绝：并发槽位和等待队列都满时拒绝请求"""
    bh = SemaphoreBulkhead(
        "test_reject",
        max_concurrent=1,
        max_waiting=0,  # 不等待，直接拒绝
    )

    async def slow_work():
        await asyncio.sleep(0.1)
        return "done"

    # 第一个占满槽位
    task1 = asyncio.create_task(bh.execute(slow_work))
    # 等待第一个任务开始执行
    await asyncio.sleep(0.01)

    # 第二个应该被立即拒绝
    with pytest.raises(BulkheadFullError) as exc_info:
        await bh.execute(slow_work)

    assert exc_info.value.reason == "rejected"
    assert exc_info.value.bulkhead_name == "test_reject"
    assert exc_info.value.max_concurrent == 1
    assert exc_info.value.max_waiting == 0

    await task1


@pytest.mark.asyncio
async def test_bulkhead_full_error_message_rejected():
    """测试拒绝时的错误消息格式"""
    bh = SemaphoreBulkhead("test_msg_reject", max_concurrent=1, max_waiting=0)

    async def slow_work():
        await asyncio.sleep(0.1)
        return "done"

    task1 = asyncio.create_task(bh.execute(slow_work))
    await asyncio.sleep(0.01)

    with pytest.raises(BulkheadFullError) as exc_info:
        await bh.execute(slow_work)

    assert "is full" in str(exc_info.value)
    assert "test_msg_reject" in str(exc_info.value)

    await task1


# ── 等待超时测试 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_bulkhead_wait_timeout():
    """测试等待超时：wait_timeout 触发后拒绝"""
    bh = SemaphoreBulkhead(
        "test_timeout",
        max_concurrent=1,
        max_waiting=5,
        wait_timeout=0.05,
    )

    async def slow_work():
        await asyncio.sleep(0.2)
        return "done"

    # 第一个占满槽位
    task1 = asyncio.create_task(bh.execute(slow_work))
    await asyncio.sleep(0.01)

    # 第二个进入等待队列，但会超时
    with pytest.raises(BulkheadFullError) as exc_info:
        await bh.execute(slow_work)

    assert exc_info.value.reason == "timeout"
    assert "wait timeout" in str(exc_info.value)

    await task1


# ── 统计信息测试 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_bulkhead_stats_basic():
    """测试基本统计信息正确性"""
    bh = SemaphoreBulkhead("test_stats", max_concurrent=3)

    async def work():
        return "ok"

    await bh.execute(work)
    await bh.execute(work)

    stats = bh.get_stats()
    assert stats["name"] == "test_stats"
    assert stats["max_concurrent"] == 3
    assert stats["total_executed"] == 2
    assert stats["total_rejected"] == 0
    assert stats["total_timeouts"] == 0
    assert stats["current_concurrent"] == 0
    assert stats["waiting_count"] == 0
    assert stats["closed"] is False


@pytest.mark.asyncio
async def test_bulkhead_stats_rejected():
    """测试拒绝统计计数正确"""
    bh = SemaphoreBulkhead("test_stats_reject", max_concurrent=1, max_waiting=0)

    async def slow_work():
        await asyncio.sleep(0.1)
        return "done"

    task1 = asyncio.create_task(bh.execute(slow_work))
    await asyncio.sleep(0.01)

    # 发起 3 个被拒绝的请求
    for _ in range(3):
        with pytest.raises(BulkheadFullError):
            await bh.execute(slow_work)

    stats = bh.get_stats()
    assert stats["total_rejected"] == 3
    assert stats["total_executed"] == 0  # task1 还在执行

    await task1

    stats = bh.get_stats()
    assert stats["total_executed"] == 1


@pytest.mark.asyncio
async def test_bulkhead_stats_timeout():
    """测试超时统计计数正确"""
    bh = SemaphoreBulkhead(
        "test_stats_timeout",
        max_concurrent=1,
        max_waiting=3,
        wait_timeout=0.05,
    )

    async def slow_work():
        await asyncio.sleep(0.2)
        return "done"

    task1 = asyncio.create_task(bh.execute(slow_work))
    await asyncio.sleep(0.01)

    with pytest.raises(BulkheadFullError):
        await bh.execute(slow_work)

    stats = bh.get_stats()
    assert stats["total_timeouts"] == 1

    await task1


@pytest.mark.asyncio
async def test_bulkhead_reset_stats():
    """测试重置统计功能"""
    bh = SemaphoreBulkhead("test_reset_stats", max_concurrent=2)

    async def work():
        return "ok"

    await bh.execute(work)
    await bh.execute(work)

    stats = bh.get_stats()
    assert stats["total_executed"] == 2

    bh.reset_stats()
    stats = bh.get_stats()
    assert stats["total_executed"] == 0
    assert stats["total_rejected"] == 0
    assert stats["total_timeouts"] == 0


# ── 装饰器模式测试 ────────────────────────────────────────


@pytest.mark.asyncio
async def test_bulkhead_decorator_basic():
    """测试舱壁装饰器基本功能"""

    @bulkhead_decorator("decorator_test", max_concurrent=3)
    async def my_func(x):
        return x * 2

    result = await my_func(5)
    assert result == 10


@pytest.mark.asyncio
async def test_bulkhead_decorator_concurrency_limit():
    """测试装饰器的并发限制生效"""
    running = 0
    max_running = 0
    lock = asyncio.Lock()

    @bulkhead_decorator("decorator_concurrent", max_concurrent=2, max_waiting=10)
    async def limited_func():
        nonlocal running, max_running
        async with lock:
            running += 1
            if running > max_running:
                max_running = running
        await asyncio.sleep(0.05)
        async with lock:
            running -= 1
        return "done"

    tasks = [asyncio.create_task(limited_func()) for _ in range(5)]
    await asyncio.gather(*tasks)

    assert max_running <= 2


@pytest.mark.asyncio
async def test_bulkhead_decorator_name_attribute():
    """测试装饰器暴露 __bulkhead_name__ 属性"""

    @bulkhead_decorator("my_bh_name", max_concurrent=3)
    async def func():
        return "ok"

    assert func.__bulkhead_name__ == "my_bh_name"


# ── BulkheadRegistry 测试 ─────────────────────────────────


@pytest.mark.asyncio
async def test_registry_get_creates_bulkhead():
    """测试注册中心 get 方法创建舱壁"""
    registry = BulkheadRegistry()
    bh = await registry.get("registry_test", max_concurrent=5)
    assert isinstance(bh, SemaphoreBulkhead)
    assert bh.name == "registry_test"
    assert bh.max_concurrent == 5


@pytest.mark.asyncio
async def test_registry_get_returns_same_instance():
    """测试同名舱壁只创建一个实例"""
    registry = BulkheadRegistry()
    bh1 = await registry.get("same_bh", max_concurrent=3)
    bh2 = await registry.get("same_bh", max_concurrent=5)  # 不同参数
    assert bh1 is bh2
    assert bh1.max_concurrent == 3  # 使用第一次创建的参数


@pytest.mark.asyncio
async def test_registry_remove():
    """测试注册中心移除舱壁"""
    registry = BulkheadRegistry()
    await registry.get("to_remove", max_concurrent=2)

    names = await registry.list_names()
    assert "to_remove" in names

    await registry.remove("to_remove")
    names = await registry.list_names()
    assert "to_remove" not in names


@pytest.mark.asyncio
async def test_registry_remove_nonexistent():
    """测试移除不存在的舱壁不报错"""
    registry = BulkheadRegistry()
    # 不应抛出异常
    await registry.remove("nonexistent")


@pytest.mark.asyncio
async def test_registry_get_all_stats():
    """测试获取所有舱壁统计"""
    registry = BulkheadRegistry()
    await registry.get("bh_a", max_concurrent=2)
    await registry.get("bh_b", max_concurrent=3)

    all_stats = await registry.get_all_stats()
    assert "bh_a" in all_stats
    assert "bh_b" in all_stats
    assert all_stats["bh_a"]["max_concurrent"] == 2
    assert all_stats["bh_b"]["max_concurrent"] == 3


@pytest.mark.asyncio
async def test_registry_list_names():
    """测试获取所有舱壁名称"""
    registry = BulkheadRegistry()
    await registry.get("name_1", max_concurrent=1)
    await registry.get("name_2", max_concurrent=2)

    names = await registry.list_names()
    assert len(names) == 2
    assert "name_1" in names
    assert "name_2" in names


@pytest.mark.asyncio
async def test_registry_reset_all():
    """测试重置所有舱壁统计"""
    registry = BulkheadRegistry()
    bh = await registry.get("reset_all_test", max_concurrent=2)

    async def work():
        return "ok"

    await bh.execute(work)
    assert bh.get_stats()["total_executed"] == 1

    await registry.reset_all()
    assert bh.get_stats()["total_executed"] == 0


# ── 异步安全性（并发下统计正确） ──────────────────────────


@pytest.mark.asyncio
async def test_bulkhead_concurrent_stats_correct():
    """测试高并发下统计信息正确性"""
    bh = SemaphoreBulkhead("test_concurrent_stats", max_concurrent=5, max_waiting=20)

    async def work():
        await asyncio.sleep(0.01)
        return "ok"

    # 并发执行 20 个任务
    tasks = [asyncio.create_task(bh.execute(work)) for _ in range(20)]
    results = await asyncio.gather(*tasks)

    assert len(results) == 20
    assert all(r == "ok" for r in results)

    stats = bh.get_stats()
    assert stats["total_executed"] == 20
    assert stats["current_concurrent"] == 0
    assert stats["total_rejected"] == 0


# ── 其他边界测试 ──────────────────────────────────────────


def test_bulkhead_invalid_params():
    """测试初始化时参数校验"""
    with pytest.raises(ValueError, match="max_concurrent must be positive"):
        SemaphoreBulkhead("bad", max_concurrent=0)

    with pytest.raises(ValueError, match="max_concurrent must be positive"):
        SemaphoreBulkhead("bad", max_concurrent=-1)

    with pytest.raises(ValueError, match="max_waiting must be non-negative"):
        SemaphoreBulkhead("bad", max_concurrent=1, max_waiting=-1)

    with pytest.raises(ValueError, match="wait_timeout must be non-negative"):
        SemaphoreBulkhead("bad", max_concurrent=1, wait_timeout=-1)


@pytest.mark.asyncio
async def test_bulkhead_close():
    """测试关闭舱壁后拒绝新请求"""
    bh = SemaphoreBulkhead("test_close", max_concurrent=2)

    async def work():
        return "ok"

    # 关闭前正常
    result = await bh.execute(work)
    assert result == "ok"

    bh.close()
    assert bh.get_stats()["closed"] is True

    # 关闭后执行应抛出 RuntimeError
    with pytest.raises(RuntimeError, match="is closed"):
        await bh.execute(work)


@pytest.mark.asyncio
async def test_bulkhead_can_acquire():
    """测试 can_acquire 方法"""
    bh = SemaphoreBulkhead("test_can_acquire", max_concurrent=1)
    assert bh.can_acquire() is True

    async def slow_work():
        await asyncio.sleep(0.1)
        return "done"

    task = asyncio.create_task(bh.execute(slow_work))
    await asyncio.sleep(0.01)
    assert bh.can_acquire() is False

    await task
    assert bh.can_acquire() is True


@pytest.mark.asyncio
async def test_bulkhead_reconfigure():
    """测试动态调整配置"""
    bh = SemaphoreBulkhead("test_reconfig", max_concurrent=2, max_waiting=0, wait_timeout=0)

    bh.reconfigure(max_concurrent=5, max_waiting=10, wait_timeout=1.0)
    assert bh.max_concurrent == 5
    assert bh.max_waiting == 10
    assert bh.wait_timeout == 1.0


# ── BulkheadFullError 转换测试 ────────────────────────────


def test_bulkhead_full_error_to_resource_exhausted():
    """测试 BulkheadFullError 转换为 ResourceExhaustedError"""
    err = BulkheadFullError(
        bulkhead_name="test_bh",
        max_concurrent=3,
        max_waiting=5,
        reason="rejected",
    )
    resource_err = err.to_resource_exhausted(trace_id="trace-123")

    from exceptions import ResourceExhaustedError
    assert isinstance(resource_err, ResourceExhaustedError)
    assert resource_err.trace_id == "trace-123"
    assert resource_err.data["bulkhead_name"] == "test_bh"
    assert resource_err.data["reason"] == "rejected"
