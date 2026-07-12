from __future__ import annotations

"""Circuit Breaker 单元测试."""

import asyncio

import pytest

from skill_cluster.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerOpenError,
    RetryConfig,
    RetryExecutor,
    ResilientSkillInvoker,
)


@pytest.mark.asyncio
async def test_circuit_breaker_closed_allows_calls() -> None:
    cb = CircuitBreaker("test", config=CircuitBreakerConfig(failure_threshold=3))
    result = await cb.call(lambda: asyncio.sleep(0))
    assert cb.state.value == "closed"


@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_failures() -> None:
    cb = CircuitBreaker("test", config=CircuitBreakerConfig(failure_threshold=3))

    for _ in range(3):
        try:
            await cb.call(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
        except RuntimeError:
            pass

    assert cb.state.value == "open"
    with pytest.raises(CircuitBreakerOpenError):
        await cb.call(lambda: asyncio.sleep(0))


@pytest.mark.asyncio
async def test_circuit_breaker_half_open_recovery() -> None:
    config = CircuitBreakerConfig(
        failure_threshold=2,
        recovery_timeout=0.1,
        success_threshold=1,
    )
    cb = CircuitBreaker("test", config=config)

    for _ in range(2):
        try:
            await cb.call(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
        except RuntimeError:
            pass

    assert cb.state.value == "open"
    await asyncio.sleep(0.15)

    await cb.call(lambda: asyncio.sleep(0))
    assert cb.state.value == "closed"


@pytest.mark.asyncio
async def test_retry_executor_success_on_first() -> None:
    retry = RetryExecutor(RetryConfig(max_retries=2, base_delay=0.01))
    result = await retry.execute(lambda: asyncio.sleep(0))
    assert result is None


@pytest.mark.asyncio
async def test_retry_executor_success_after_retries() -> None:
    retry = RetryExecutor(RetryConfig(max_retries=3, base_delay=0.01))
    counter = 0

    async def flaky() -> str:
        nonlocal counter
        counter += 1
        if counter < 3:
            raise RuntimeError("fail")
        return "ok"

    result = await retry.execute(flaky)
    assert result == "ok"
    assert counter == 3


@pytest.mark.asyncio
async def test_retry_executor_exhausted() -> None:
    retry = RetryExecutor(RetryConfig(max_retries=2, base_delay=0.01))

    async def always_fail() -> str:
        raise RuntimeError("fail")

    with pytest.raises(RuntimeError, match="fail"):
        await retry.execute(always_fail)


@pytest.mark.asyncio
async def test_resilient_invoker() -> None:
    invoker = ResilientSkillInvoker(
        circuit_config=CircuitBreakerConfig(failure_threshold=3),
        retry_config=RetryConfig(max_retries=2, base_delay=0.01),
    )
    counter = 0

    async def flaky() -> str:
        nonlocal counter
        counter += 1
        if counter < 2:
            raise RuntimeError("fail")
        return "ok"

    result = await invoker.invoke("skill.test", flaky)
    assert result == "ok"


def test_circuit_breaker_metrics() -> None:
    cb = CircuitBreaker("metrics_test")
    m = cb.get_metrics()
    assert m["name"] == "metrics_test"
    assert m["state"] == "closed"
    assert m["failure_count"] == 0
