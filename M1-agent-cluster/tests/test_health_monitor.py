"""
测试：HealthMonitor 健康监控中心
"""

import pytest
import sys

sys.path.insert(0, "/workspace/agent_cluster")

from health_monitor import HealthMonitor


@pytest.fixture
def hm():
    return HealthMonitor()


@pytest.mark.asyncio
async def test_register_and_check(hm):
    async def good():
        return True

    hm.register("component_a", good)
    status = await hm.check("component_a")
    assert status.status == "up"


@pytest.mark.asyncio
async def test_check_failure(hm):
    async def bad():
        return False

    hm.register("component_b", bad)
    status = await hm.check("component_b")
    assert status.status == "down"


@pytest.mark.asyncio
async def test_check_exception(hm):
    async def explode():
        raise ValueError("boom")

    hm.register("component_c", explode)
    status = await hm.check("component_c")
    assert status.status == "down"
    assert "boom" in (status.error or "")


@pytest.mark.asyncio
async def test_check_unknown(hm):
    status = await hm.check("nonexistent")
    assert status.status == "unknown"


@pytest.mark.asyncio
async def test_check_all(hm):
    async def good():
        return True

    async def bad():
        return False

    hm.register("good", good)
    hm.register("bad", bad)

    results = await hm.check_all(use_cache=False)
    assert results["good"].status == "up"
    assert results["bad"].status == "down"


@pytest.mark.asyncio
async def test_cache(hm):
    call_count = 0

    async def counter():
        nonlocal call_count
        call_count += 1
        return True

    hm.register("cached", counter)

    await hm.check_all(use_cache=False)
    assert call_count == 1

    await hm.check_all(use_cache=True)
    assert call_count == 1  # 缓存命中，不增加


@pytest.mark.asyncio
async def test_liveness(hm):
    live = await hm.liveness()
    assert live.status == "up"
    assert "pid" in live.details


@pytest.mark.asyncio
async def test_overall_status(hm):
    async def ok():
        return True

    hm.register("a", ok)
    hm.register("b", ok)

    overall = await hm.overall_status()
    assert overall["status"] == "up"
    assert "liveness" in overall
    assert "readiness" in overall


@pytest.mark.asyncio
async def test_overall_degraded(hm):
    async def ok():
        return True

    async def fail():
        return False

    hm.register("a", ok)
    hm.register("b", fail)

    overall = await hm.overall_status()
    assert overall["status"] == "degraded"


@pytest.mark.asyncio
async def test_to_prometheus(hm):
    async def ok():
        return True

    async def fail():
        return False

    hm.register("a", ok)
    hm.register("b", fail)

    prom = await hm.to_prometheus()
    assert "yunxi_health" in prom
    assert 'component="a"} 1' in prom
    assert 'component="b"} 0' in prom
