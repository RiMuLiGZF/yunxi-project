"""
测试：V10.0-R06 硬件健康探测与断连重连

验证TaskDispatcher的硬件感知调度、断连缓存和降级策略。
"""

import pytest
import sys
import asyncio
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, "/workspace/agent_cluster")

from task_dispatcher import TaskDispatcher
from agent_registry import AgentRegistry
from interfaces import AgentTask, HardwareStatus


@pytest.fixture
def dispatcher():
    reg = AgentRegistry()
    bus = MagicMock()
    bus.publish = AsyncMock()
    td = TaskDispatcher(registry=reg, message_bus=bus)
    return td, reg, bus


@pytest.mark.asyncio
async def test_hardware_online_by_default(dispatcher):
    td, _, _ = dispatcher
    assert td.is_hardware_online("watch.1") is True


@pytest.mark.asyncio
async def test_hardware_offline_caches_task(dispatcher):
    td, reg, bus = dispatcher

    # 注册一个mock agent
    agent = MagicMock()
    agent.agent_id = "agent.a"
    agent.handle_task = AsyncMock(return_value=MagicMock(status="success"))
    agent.health = AsyncMock(return_value={"status": "healthy"})
    reg.register_sync(agent)

    # 设置手表离线
    hw = HardwareStatus(device_id="watch.1", device_type="watch", online=False, battery_pct=10.0)
    td.update_hardware_status(hw)
    assert td.is_hardware_online("watch.1") is False

    # 派发任务（绑定到手表）
    task = AgentTask(task_id="t1", target="agent.a", metadata={"device_id": "watch.1"})
    result = await td.dispatch(task)

    # 手表离线 -> 任务应被缓存，返回partial
    assert result.status == "partial"
    assert "cached" in result.error.lower()
    assert len(td._offline_cache.get("watch.1", [])) == 1


@pytest.mark.asyncio
async def test_drone_offline_fails_immediately(dispatcher):
    td, _, _ = dispatcher

    hw = HardwareStatus(device_id="drone.1", device_type="drone", online=False)
    td.update_hardware_status(hw)

    task = AgentTask(task_id="t2", target="agent.a", metadata={"device_id": "drone.1"})
    result = await td.dispatch(task)

    assert result.status == "failure"
    assert "offline" in result.error.lower()


@pytest.mark.asyncio
async def test_hardware_reconnect_flushes_cache(dispatcher):
    td, reg, bus = dispatcher

    agent = MagicMock()
    agent.agent_id = "agent.a"
    agent.handle_task = AsyncMock(return_value=MagicMock(status="success"))
    agent.health = AsyncMock(return_value={"status": "healthy"})
    reg.register_sync(agent)

    # 先离线
    hw_off = HardwareStatus(device_id="ring.1", device_type="ring", online=False)
    td.update_hardware_status(hw_off)

    task = AgentTask(task_id="t3", target="agent.a", metadata={"device_id": "ring.1"})
    await td.dispatch(task)
    assert len(td._offline_cache.get("ring.1", [])) == 1

    # 重连
    hw_on = HardwareStatus(device_id="ring.1", device_type="ring", online=True)
    td.update_hardware_status(hw_on)

    # 给flush任务一点时间
    await asyncio.sleep(0.1)

    # 缓存应被清空
    assert len(td._offline_cache.get("ring.1", [])) == 0


@pytest.mark.asyncio
async def test_should_degrade_for_watch_offline(dispatcher):
    td, _, _ = dispatcher

    hw = HardwareStatus(device_id="watch.2", device_type="watch", online=False)
    td.update_hardware_status(hw)

    task = AgentTask(task_id="t4", target="agent.a", metadata={"device_id": "watch.2"})
    assert td.should_degrade_for_hardware(task) is True
