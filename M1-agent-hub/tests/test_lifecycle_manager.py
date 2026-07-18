"""
测试：LifecycleManager 生命周期管理器
"""

import pytest
import sys
import asyncio
import signal
from lifecycle_manager import LifecycleManager


@pytest.fixture
def lm():
    return LifecycleManager()


@pytest.mark.asyncio
async def test_register_and_startup(lm):
    events = []

    async def start_a():
        events.append("start_a")

    async def start_b():
        events.append("start_b")

    lm.register("a", startup=start_a)
    lm.register("b", startup=start_b)
    await lm.startup()

    assert events == ["start_a", "start_b"]
    assert lm.is_running() is True


@pytest.mark.asyncio
async def test_shutdown_reverse_order(lm):
    events = []

    async def start():
        pass

    async def stop_a():
        events.append("stop_a")

    async def stop_b():
        events.append("stop_b")

    lm.register("a", startup=start, shutdown=stop_a)
    lm.register("b", startup=start, shutdown=stop_b)
    await lm.startup()
    await lm.shutdown()

    assert events == ["stop_b", "stop_a"]
    assert lm.is_running() is False


@pytest.mark.asyncio
async def test_startup_timeout(lm):
    async def slow_start():
        await asyncio.sleep(10)

    lm.register("slow", startup=slow_start, timeout=0.1)
    with pytest.raises(RuntimeError, match="启动超时"):
        await lm.startup()


@pytest.mark.asyncio
async def test_shutdown_timeout(lm):
    async def start():
        pass

    async def slow_stop():
        await asyncio.sleep(10)

    lm.register("slow", startup=start, shutdown=slow_stop, timeout=0.1)
    await lm.startup()
    # 关闭超时不会抛异常，只是记录日志
    await lm.shutdown()


@pytest.mark.asyncio
async def test_health_check_all(lm):
    async def good():
        return True

    async def bad():
        return False

    lm.register("good", health_check=good)
    lm.register("bad", health_check=bad)
    results = await lm.health_check_all()

    assert results["good"] is True
    assert results["bad"] is False


@pytest.mark.asyncio
async def test_wait_for_shutdown(lm):
    lm.register("x")
    await lm.startup()

    async def trigger_shutdown():
        await asyncio.sleep(0.1)
        await lm.shutdown()

    asyncio.create_task(trigger_shutdown())
    await lm.wait_for_shutdown()
    assert lm.is_running() is False
