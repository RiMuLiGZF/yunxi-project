"""重试协调器功能验证脚本（直接运行，无需 pytest）.

直接运行: python run_retry_tests.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import traceback
from dataclasses import replace
from typing import Any

# 确保项目根目录在 sys.path 中
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
from edge_cloud_kernel.common.retry import (
    RetryCoordinator,
    RetryPolicy,
    get_default_coordinator,
    with_retry,
)


passed = 0
failed = 0


def assert_equal(actual: Any, expected: Any, msg: str = "") -> None:
    global passed, failed
    if actual == expected:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {msg} - expected {expected!r}, got {actual!r}")


def assert_true(condition: bool, msg: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {msg}")


def _pass() -> None:
    """记录一个通过的断言."""
    global passed
    passed += 1


def _fail(msg: str) -> None:
    """记录一个失败的断言."""
    global failed
    failed += 1
    print(f"  FAIL: {msg}")


# ---------------------------------------------------------------------------
# Test 1: RetryPolicy 默认值
# ---------------------------------------------------------------------------
def test_retry_policy_defaults() -> None:
    print("\n[Test] RetryPolicy 默认值")
    policy = RetryPolicy()
    assert_equal(policy.max_retries, 3, "max_retries default")
    assert_equal(policy.base_delay, 0.5, "base_delay default")
    assert_equal(policy.max_delay, 10.0, "max_delay default")
    assert_equal(policy.backoff_factor, 2.0, "backoff_factor default")
    assert_true(policy.jitter is True, "jitter default True")
    assert_true(429 in policy.retryable_status_codes, "429 in retryable status codes")
    assert_true(500 in policy.retryable_status_codes, "500 in retryable status codes")


# ---------------------------------------------------------------------------
# Test 2: 延迟计算（无抖动）
# ---------------------------------------------------------------------------
def test_delay_calculation() -> None:
    print("\n[Test] 延迟计算（指数退避 + 最大值限制）")
    policy = RetryPolicy(base_delay=1.0, backoff_factor=2.0, max_delay=10.0, jitter=False)
    assert_equal(policy.calculate_delay(0), 1.0, "delay attempt 0")
    assert_equal(policy.calculate_delay(1), 2.0, "delay attempt 1")
    assert_equal(policy.calculate_delay(2), 4.0, "delay attempt 2")
    assert_equal(policy.calculate_delay(3), 8.0, "delay attempt 3")
    assert_equal(policy.calculate_delay(10), 10.0, "delay capped at max_delay")


# ---------------------------------------------------------------------------
# Test 3: 延迟计算（带抖动）
# ---------------------------------------------------------------------------
def test_delay_with_jitter() -> None:
    print("\n[Test] 延迟计算（带抖动）")
    policy = RetryPolicy(base_delay=1.0, backoff_factor=2.0, max_delay=10.0, jitter=True)
    delay = policy.calculate_delay(2)  # base = 4.0, jitter +/-25% = [3.0, 5.0]
    assert_true(3.0 <= delay <= 5.0, f"jitter delay {delay} in [3.0, 5.0]")


# ---------------------------------------------------------------------------
# Test 4: execute 首次成功
# ---------------------------------------------------------------------------
async def test_execute_success_first_try() -> None:
    print("\n[Test] execute 首次执行成功")
    coordinator = RetryCoordinator()
    call_count = 0

    async def success_func(x: int) -> int:
        nonlocal call_count
        call_count += 1
        return x * 2

    result = await coordinator.execute(success_func, 21)
    assert_equal(result, 42, "result correct")
    assert_equal(call_count, 1, "called once")


# ---------------------------------------------------------------------------
# Test 5: execute 重试后成功
# ---------------------------------------------------------------------------
async def test_execute_retry_then_success() -> None:
    print("\n[Test] execute 重试后成功")
    coordinator = RetryCoordinator(
        default_policy=RetryPolicy(max_retries=3, base_delay=0.001, jitter=False)
    )
    call_count = 0

    async def flaky_func() -> str:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ConnectionError("temporary error")
        return "ok"

    result = await coordinator.execute(flaky_func)
    assert_equal(result, "ok", "result ok")
    assert_equal(call_count, 3, "called 3 times (2 failures + 1 success)")

    stats = coordinator.get_stats()
    assert_equal(stats["total_calls"], 1, "stats total_calls")
    assert_equal(stats["total_retries"], 2, "stats total_retries")
    assert_equal(stats["retry_successes"], 1, "stats retry_successes")
    assert_equal(stats["total_failures"], 0, "stats total_failures")


# ---------------------------------------------------------------------------
# Test 6: execute 重试耗尽
# ---------------------------------------------------------------------------
async def test_execute_retry_exhausted() -> None:
    print("\n[Test] execute 重试耗尽")
    coordinator = RetryCoordinator(
        default_policy=RetryPolicy(max_retries=2, base_delay=0.001, jitter=False)
    )
    call_count = 0

    async def always_fail() -> None:
        nonlocal call_count
        call_count += 1
        raise ConnectionError("always fails")

    try:
        await coordinator.execute(always_fail)
        _fail("expected ConnectionError (retry exhausted)")
    except ConnectionError:
        _pass()

    assert_equal(call_count, 3, "called 3 times (1 first + 2 retries)")

    stats = coordinator.get_stats()
    assert_equal(stats["total_failures"], 1, "stats total_failures")
    assert_equal(stats["total_retries"], 2, "stats total_retries")


# ---------------------------------------------------------------------------
# Test 7: 不可重试异常立即抛出
# ---------------------------------------------------------------------------
async def test_non_retryable_exception() -> None:
    print("\n[Test] 不可重试异常立即抛出")
    coordinator = RetryCoordinator(
        default_policy=RetryPolicy(
            max_retries=3,
            base_delay=0.001,
            retryable_exceptions=(ConnectionError,),
        )
    )
    call_count = 0

    async def bad_value() -> None:
        nonlocal call_count
        call_count += 1
        raise ValueError("bad value")

    try:
        await coordinator.execute(bad_value)
        _fail("expected ValueError (non-retryable)")
    except ValueError:
        _pass()

    assert_equal(call_count, 1, "called once (no retry)")


# ---------------------------------------------------------------------------
# Test 8: 基于 status_code 的可重试判断
# ---------------------------------------------------------------------------
async def test_status_code_retryable() -> None:
    print("\n[Test] 基于 status_code 的可重试判断")

    class HTTPError(Exception):
        def __init__(self, status_code: int) -> None:
            self.status_code = status_code
            super().__init__(f"HTTP {status_code}")

    coordinator = RetryCoordinator(
        default_policy=RetryPolicy(max_retries=2, base_delay=0.001, jitter=False)
    )
    call_count = 0

    async def func_with_503() -> str:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise HTTPError(503)
        return "ok"

    result = await coordinator.execute(func_with_503)
    assert_equal(result, "ok", "retry succeeded for 503")
    assert_equal(call_count, 3, "called 3 times for 503")

    # 401 不可重试
    call_count_401 = 0

    async def func_with_401() -> None:
        nonlocal call_count_401
        call_count_401 += 1
        raise HTTPError(401)

    try:
        await coordinator.execute(func_with_401)
        _fail("expected HTTPError for 401 (non-retryable)")
    except HTTPError:
        _pass()

    assert_equal(call_count_401, 1, "401 not retried")


# ---------------------------------------------------------------------------
# Test 9: 命名策略注册和获取
# ---------------------------------------------------------------------------
def test_policy_registration() -> None:
    print("\n[Test] 命名策略注册和获取")
    coordinator = RetryCoordinator()
    policy = RetryPolicy(max_retries=5, base_delay=0.3)

    coordinator.register_policy("fast", policy)
    retrieved = coordinator.get_policy("fast")
    assert_true(retrieved is policy, "retrieved policy is same object")
    assert_equal(retrieved.max_retries, 5, "policy max_retries")

    # get_policy_or_default fallback
    default = coordinator.get_policy_or_default("nonexistent")
    assert_equal(default.max_retries, 3, "fallback to default policy")

    # 空名称
    try:
        coordinator.register_policy("", RetryPolicy())
        _fail("expected ValueError for empty name")
    except ValueError:
        _pass()


# ---------------------------------------------------------------------------
# Test 10: execute 使用命名策略
# ---------------------------------------------------------------------------
async def test_execute_with_policy_name() -> None:
    print("\n[Test] execute 使用命名策略")
    coordinator = RetryCoordinator()
    fast_policy = RetryPolicy(max_retries=1, base_delay=0.001, jitter=False)
    coordinator.register_policy("fast", fast_policy)

    call_count = 0

    async def fail_func() -> None:
        nonlocal call_count
        call_count += 1
        raise ConnectionError("fail")

    try:
        await coordinator.execute(fail_func, policy_name="fast")
        _fail("expected ConnectionError (fast policy)")
    except ConnectionError:
        _pass()

    assert_equal(call_count, 2, "fast policy: 1 first + 1 retry = 2 calls")


# ---------------------------------------------------------------------------
# Test 11: 统计信息
# ---------------------------------------------------------------------------
async def test_stats() -> None:
    print("\n[Test] 统计信息")
    coordinator = RetryCoordinator(
        default_policy=RetryPolicy(max_retries=2, base_delay=0.001, jitter=False)
    )

    # 成功（重试1次）
    count1 = 0

    async def func1() -> str:
        nonlocal count1
        count1 += 1
        if count1 < 2:
            raise ConnectionError("err1")
        return "ok1"

    await coordinator.execute(func1)

    # 失败（重试耗尽）
    async def func2() -> None:
        raise ConnectionError("err2")

    try:
        await coordinator.execute(func2)
    except ConnectionError:
        pass

    stats = coordinator.get_stats()
    assert_equal(stats["total_calls"], 2, "total_calls")
    assert_equal(stats["total_retries"], 3, "total_retries (1+2)")
    assert_equal(stats["total_failures"], 1, "total_failures")
    assert_equal(stats["retry_successes"], 1, "retry_successes")
    assert_true(stats["retry_success_rate"] > 0, "retry_success_rate > 0")
    assert_true(len(stats["most_common_retryable_errors"]) > 0, "most_common_errors populated")

    # 重置统计
    coordinator.reset_stats()
    stats2 = coordinator.get_stats()
    assert_equal(stats2["total_calls"], 0, "after reset: total_calls=0")
    assert_equal(stats2["total_retries"], 0, "after reset: total_retries=0")


# ---------------------------------------------------------------------------
# Test 12: per-policy 统计
# ---------------------------------------------------------------------------
async def test_per_policy_stats() -> None:
    print("\n[Test] per-policy 统计")
    coordinator = RetryCoordinator()
    coordinator.register_policy(
        "p1",
        RetryPolicy(max_retries=1, base_delay=0.001, jitter=False),
    )

    async def fa() -> None:
        raise ConnectionError("a")

    try:
        await coordinator.execute(fa, policy_name="p1")
    except ConnectionError:
        pass

    stats = coordinator.get_stats()
    assert_true("p1" in stats["per_policy"], "p1 in per_policy stats")
    assert_equal(stats["per_policy"]["p1"]["total_failures"], 1, "p1 total_failures=1")


# ---------------------------------------------------------------------------
# Test 13: 熔断器 OPEN 状态直接拒绝
# ---------------------------------------------------------------------------
async def test_circuit_breaker_open() -> None:
    print("\n[Test] 熔断器 OPEN 状态直接拒绝")
    coordinator = RetryCoordinator(
        default_policy=RetryPolicy(max_retries=3, base_delay=0.001)
    )

    # 模拟 OPEN 状态熔断器
    class MockState:
        value = "open"

    class MockCircuitBreaker:
        name = "test_cb"
        _reset_timeout_s = 10.0

        @property
        def state(self) -> MockState:
            return MockState()

    coordinator.set_circuit_breaker(MockCircuitBreaker())

    call_count = 0

    async def func() -> str:
        nonlocal call_count
        call_count += 1
        return "ok"

    try:
        await coordinator.execute(func)
        _fail("expected circuit breaker rejection")
    except Exception as e:
        error_str = str(e).lower()
        assert_true(
            "circuit" in error_str or "CIRCUIT_OPEN" in str(e),
            f"circuit breaker error raised: {e}",
        )

    assert_equal(call_count, 0, "func not called when circuit open")


# ---------------------------------------------------------------------------
# Test 14: 熔断器 HALF_OPEN 减少重试
# ---------------------------------------------------------------------------
async def test_circuit_breaker_half_open() -> None:
    print("\n[Test] 熔断器 HALF_OPEN 减少重试")
    coordinator = RetryCoordinator(
        default_policy=RetryPolicy(max_retries=5, base_delay=0.001, jitter=False)
    )

    class MockState:
        value = "half_open"

    class MockCircuitBreaker:
        name = "test_cb"
        _reset_timeout_s = 10.0

        @property
        def state(self) -> MockState:
            return MockState()

    coordinator.set_circuit_breaker(MockCircuitBreaker())

    call_count = 0

    async def fail_func() -> None:
        nonlocal call_count
        call_count += 1
        raise ConnectionError("fail")

    try:
        await coordinator.execute(fail_func)
    except ConnectionError:
        pass

    # HALF_OPEN: max_retries=1, 所以总调用 = 1 + 1 = 2
    assert_equal(call_count, 2, "half_open: 1 first + 1 retry = 2 calls")


# ---------------------------------------------------------------------------
# Test 15: 熔断器 CLOSED 正常重试
# ---------------------------------------------------------------------------
async def test_circuit_breaker_closed() -> None:
    print("\n[Test] 熔断器 CLOSED 正常重试")
    coordinator = RetryCoordinator(
        default_policy=RetryPolicy(max_retries=2, base_delay=0.001, jitter=False)
    )

    class MockState:
        value = "closed"

    class MockCircuitBreaker:
        name = "test_cb"

        @property
        def state(self) -> MockState:
            return MockState()

    coordinator.set_circuit_breaker(MockCircuitBreaker())

    call_count = 0

    async def fail_func() -> None:
        nonlocal call_count
        call_count += 1
        raise ConnectionError("fail")

    try:
        await coordinator.execute(fail_func)
    except ConnectionError:
        pass

    assert_equal(call_count, 3, "closed: 1 first + 2 retries = 3 calls")


# ---------------------------------------------------------------------------
# Test 16: execute_with_fallback
# ---------------------------------------------------------------------------
async def test_execute_with_fallback() -> None:
    print("\n[Test] execute_with_fallback 降级")
    coordinator = RetryCoordinator(
        default_policy=RetryPolicy(max_retries=1, base_delay=0.001, jitter=False)
    )

    async def main_func() -> None:
        raise ConnectionError("main fail")

    async def async_fallback() -> dict[str, str]:
        return {"fallback": "async_value"}

    def sync_fallback() -> str:
        return "sync_value"

    # 异步降级
    result = await coordinator.execute_with_fallback(main_func, async_fallback)
    assert_equal(result, {"fallback": "async_value"}, "async fallback result")

    # 同步降级
    result2 = await coordinator.execute_with_fallback(main_func, sync_fallback)
    assert_equal(result2, "sync_value", "sync fallback result")

    # 成功时不调用降级
    call_count = 0

    async def success_func() -> str:
        return "success"

    async def fallback_func() -> str:
        nonlocal call_count
        call_count += 1
        return "fallback"

    result3 = await coordinator.execute_with_fallback(success_func, fallback_func)
    assert_equal(result3, "success", "success no fallback")
    assert_equal(call_count, 0, "fallback not called on success")


# ---------------------------------------------------------------------------
# Test 17: is_retryable
# ---------------------------------------------------------------------------
def test_is_retryable() -> None:
    print("\n[Test] is_retryable 可重试判断")
    coordinator = RetryCoordinator()

    assert_true(coordinator.is_retryable(ConnectionError("conn")), "ConnectionError retryable")
    assert_true(coordinator.is_retryable(TimeoutError("timeout")), "TimeoutError retryable")
    assert_true(not coordinator.is_retryable(ValueError("val")), "ValueError not retryable")
    assert_true(not coordinator.is_retryable(TypeError("type")), "TypeError not retryable")

    # 带 status_code 的异常
    class HTTPErr(Exception):
        def __init__(self, code: int) -> None:
            self.status_code = code
            super().__init__(f"HTTP {code}")

    assert_true(coordinator.is_retryable(HTTPErr(503)), "503 retryable")
    assert_true(coordinator.is_retryable(HTTPErr(429)), "429 retryable")
    assert_true(not coordinator.is_retryable(HTTPErr(401)), "401 not retryable")
    assert_true(not coordinator.is_retryable(HTTPErr(403)), "403 not retryable")


# ---------------------------------------------------------------------------
# Test 18: with_retry 装饰器
# ---------------------------------------------------------------------------
async def test_with_retry_decorator() -> None:
    print("\n[Test] with_retry 装饰器")

    # 基本重试
    call_count = 0

    @with_retry(max_retries=2, base_delay=0.001, jitter=False)
    async def flaky_decorated() -> str:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ConnectionError("fail")
        return "success"

    result = await flaky_decorated()
    assert_equal(result, "success", "decorator retry success")
    assert_equal(call_count, 3, "decorator called 3 times")

    # 函数名保留
    assert_equal(flaky_decorated.__name__, "flaky_decorated", "function name preserved")

    # 使用命名策略 + 自定义协调器
    coord = RetryCoordinator()
    coord.register_policy(
        "deco_test",
        RetryPolicy(max_retries=1, base_delay=0.001, jitter=False),
    )

    count2 = 0

    @with_retry(policy="deco_test", coordinator=coord)
    async def policy_decorated() -> str:
        nonlocal count2
        count2 += 1
        if count2 < 2:
            raise ConnectionError("fail")
        return "ok"

    result2 = await policy_decorated()
    assert_equal(result2, "ok", "policy decorator result")
    assert_equal(count2, 2, "policy decorator called 2 times")


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------
async def main() -> None:
    global passed, failed
    print("=" * 60)
    print("全局重试协调器功能验证")
    print("=" * 60)

    # 同步测试
    test_retry_policy_defaults()
    test_delay_calculation()
    test_delay_with_jitter()
    test_policy_registration()
    test_is_retryable()

    # 异步测试
    await test_execute_success_first_try()
    await test_execute_retry_then_success()
    await test_execute_retry_exhausted()
    await test_non_retryable_exception()
    await test_status_code_retryable()
    await test_execute_with_policy_name()
    await test_stats()
    await test_per_policy_stats()
    await test_circuit_breaker_open()
    await test_circuit_breaker_half_open()
    await test_circuit_breaker_closed()
    await test_execute_with_fallback()
    await test_with_retry_decorator()

    print("\n" + "=" * 60)
    total = passed + failed
    print(f"结果: {passed}/{total} 通过, {failed} 失败")
    print("=" * 60)

    if failed > 0:
        sys.exit(1)
    else:
        print("所有测试通过!")


if __name__ == "__main__":
    asyncio.run(main())
