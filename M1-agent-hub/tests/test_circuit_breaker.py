"""
测试：CircuitBreaker 熔断器
"""

import pytest
import sys
import asyncio

sys.path.insert(0, "/workspace/agent_cluster")

from circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerRegistry,
    CircuitBreakerConfig,
    CircuitState,
    CircuitBreakerError,
)


@pytest.mark.asyncio
async def test_circuit_closed_success():
    cb = CircuitBreaker("agent.test", CircuitBreakerConfig(failure_threshold=3))

    async def success():
        return "ok"

    result = await cb.call(success)
    assert result == "ok"
    assert cb.get_state() == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_circuit_opens_after_failures():
    cb = CircuitBreaker("agent.test", CircuitBreakerConfig(failure_threshold=3))

    async def fail():
        raise ValueError("fail")

    # 失败 3 次
    for _ in range(3):
        with pytest.raises(ValueError):
            await cb.call(fail)

    assert cb.get_state() == CircuitState.OPEN

    # 再次调用应被熔断
    with pytest.raises(CircuitBreakerError):
        await cb.call(fail)


@pytest.mark.asyncio
async def test_circuit_half_open_recovery():
    config = CircuitBreakerConfig(failure_threshold=2, recovery_timeout=0.1, success_threshold=1)
    cb = CircuitBreaker("agent.test", config)

    async def fail():
        raise ValueError("fail")

    async def success():
        return "ok"

    # 触发熔断
    for _ in range(2):
        with pytest.raises(ValueError):
            await cb.call(fail)
    assert cb.get_state() == CircuitState.OPEN

    # 等待恢复超时
    await asyncio.sleep(0.15)
    assert cb.get_state() == CircuitState.HALF_OPEN

    # 成功一次后恢复
    result = await cb.call(success)
    assert result == "ok"
    assert cb.get_state() == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_circuit_half_open_reopen():
    config = CircuitBreakerConfig(failure_threshold=2, recovery_timeout=0.1)
    cb = CircuitBreaker("agent.test", config)

    async def fail():
        raise ValueError("fail")

    # 触发熔断
    for _ in range(2):
        with pytest.raises(ValueError):
            await cb.call(fail)

    await asyncio.sleep(0.15)
    assert cb.get_state() == CircuitState.HALF_OPEN

    # 半开状态失败，重新熔断
    with pytest.raises(ValueError):
        await cb.call(fail)
    assert cb.get_state() == CircuitState.OPEN


@pytest.mark.asyncio
async def test_circuit_exclusion():
    config = CircuitBreakerConfig(failure_threshold=2, exclusion_statuses={"not_found"})
    cb = CircuitBreaker("agent.test", config)

    async def not_found():
        raise ValueError("Agent not_found")

    # 被排除的错误不计入
    for _ in range(5):
        with pytest.raises(ValueError):
            await cb.call(not_found)

    assert cb.get_state() == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_registry():
    registry = CircuitBreakerRegistry(CircuitBreakerConfig(failure_threshold=3))

    cb1 = registry.get("agent.a")
    cb2 = registry.get("agent.a")
    assert cb1 is cb2

    stats = registry.get_all_stats()
    assert "agent.a" in stats

    registry.reset_all()
    assert cb1.get_state() == CircuitState.CLOSED
