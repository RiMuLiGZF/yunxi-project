"""幂等性管理器单元测试.

验证 IdempotencyManager 的核心功能：
- 基本的 check/store 操作
- execute 幂等执行（同步函数、异步函数、异常缓存与重抛）
- TTL 过期机制
- LRU 淘汰机制
- per-key 并发锁
- acquire_lock / release_lock
- 幂等键生成工具
- IdempotencyGuard FastAPI 依赖注入
- 统计信息准确性

设计依据：M3 v2.1.0 评审报告 REV-20250628-M3-001。
"""

from __future__ import annotations

import asyncio
import time

import pytest

from edge_cloud_kernel.common.idempotency import (
    IdempotencyError,
    IdempotencyGuard,
    IdempotencyManager,
    generate_config_key,
    generate_request_key,
    generate_sync_key,
)


# ---------------------------------------------------------------------------
# 幂等键生成工具测试
# ---------------------------------------------------------------------------

class TestKeyGeneration:
    """幂等键生成工具测试集."""

    def test_generate_sync_key_valid(self):
        """正常生成同步操作幂等键."""
        k1 = generate_sync_key("device-001", "session-abc")
        assert k1.startswith("sync:")
        assert len(k1) > 8
        # 相同输入生成相同 key
        k2 = generate_sync_key("device-001", "session-abc")
        assert k1 == k2
        # 不同输入生成不同 key
        k3 = generate_sync_key("device-002", "session-abc")
        assert k1 != k3

    def test_generate_sync_key_empty_device(self):
        """device_id 为空时应抛出 ValueError."""
        with pytest.raises(ValueError, match="device_id"):
            generate_sync_key("", "session-abc")

    def test_generate_sync_key_empty_session(self):
        """session_id 为空时应抛出 ValueError."""
        with pytest.raises(ValueError, match="session_id"):
            generate_sync_key("device-001", "")

    def test_generate_config_key_valid(self):
        """正常生成配置操作幂等键."""
        k1 = generate_config_key("sync", "interval")
        assert k1.startswith("config:")
        assert len(k1) > 8
        # 相同输入生成相同 key
        k2 = generate_config_key("sync", "interval")
        assert k1 == k2

    def test_generate_config_key_empty_scope(self):
        """scope 为空时应抛出 ValueError."""
        with pytest.raises(ValueError, match="scope"):
            generate_config_key("", "key")

    def test_generate_config_key_empty_key(self):
        """key 为空时应抛出 ValueError."""
        with pytest.raises(ValueError, match="key"):
            generate_config_key("sync", "")

    def test_generate_request_key_valid(self):
        """正常生成请求幂等键."""
        key = generate_request_key("req-abc123xyz")
        assert key.startswith("req:")
        assert "req-abc123xyz" in key
        # 相同输入生成相同 key
        key2 = generate_request_key("req-abc123xyz")
        assert key == key2

    def test_generate_request_key_empty(self):
        """request_id 为空时应抛出 ValueError."""
        with pytest.raises(ValueError, match="request_id"):
            generate_request_key("")


# ---------------------------------------------------------------------------
# IdempotencyManager 基本操作测试
# ---------------------------------------------------------------------------

class TestIdempotencyManagerBasic:
    """IdempotencyManager 基本操作测试集."""

    @pytest.mark.asyncio
    async def test_init_defaults(self):
        """默认参数初始化."""
        manager = IdempotencyManager()
        assert manager.ttl == 3600.0
        assert manager.max_entries == 10000

    @pytest.mark.asyncio
    async def test_init_custom(self):
        """自定义参数初始化."""
        manager = IdempotencyManager(ttl=60.0, max_entries=100)
        assert manager.ttl == 60.0
        assert manager.max_entries == 100

    @pytest.mark.asyncio
    async def test_init_invalid_ttl(self):
        """无效 ttl 应抛出 ValueError."""
        with pytest.raises(ValueError, match="ttl"):
            IdempotencyManager(ttl=0)
        with pytest.raises(ValueError, match="ttl"):
            IdempotencyManager(ttl=-1)

    @pytest.mark.asyncio
    async def test_init_invalid_max_entries(self):
        """无效 max_entries 应抛出 ValueError."""
        with pytest.raises(ValueError, match="max_entries"):
            IdempotencyManager(max_entries=0)
        with pytest.raises(ValueError, match="max_entries"):
            IdempotencyManager(max_entries=-1)

    @pytest.mark.asyncio
    async def test_check_miss(self):
        """未命中时 check 返回 (False, None)."""
        manager = IdempotencyManager()
        hit, result = await manager.check("test-key-basic-001")
        assert hit is False
        assert result is None

    @pytest.mark.asyncio
    async def test_store_and_check_hit(self):
        """存储后 check 应命中并返回缓存结果."""
        manager = IdempotencyManager()
        test_key = "test-key-store-002"
        test_result = {"status": "ok", "data": [1, 2, 3]}

        await manager.store(test_key, test_result)
        hit, result = await manager.check(test_key)

        assert hit is True
        assert result == test_result

    @pytest.mark.asyncio
    async def test_store_error_result(self):
        """存储错误结果，is_error 标记正确."""
        manager = IdempotencyManager(ttl=3600)
        test_key = "test-key-error-store-001"
        error_result = RuntimeError("test error")

        await manager.store(test_key, error_result, is_error=True)
        hit, result = await manager.check(test_key)

        assert hit is True
        assert isinstance(result, RuntimeError)
        assert str(result) == "test error"

    @pytest.mark.asyncio
    async def test_store_overwrite(self):
        """重复存储同一 key 应覆盖旧值."""
        manager = IdempotencyManager()
        test_key = "test-key-overwrite-001"

        await manager.store(test_key, "value1")
        await manager.store(test_key, "value2")
        hit, result = await manager.check(test_key)

        assert hit is True
        assert result == "value2"

    @pytest.mark.asyncio
    async def test_invalid_key_empty(self):
        """空 key 应抛出 ValueError."""
        manager = IdempotencyManager()
        with pytest.raises(ValueError):
            await manager.check("")
        with pytest.raises(ValueError):
            await manager.store("", "value")

    @pytest.mark.asyncio
    async def test_invalid_key_too_short(self):
        """过短的 key 应抛出 ValueError."""
        manager = IdempotencyManager()
        with pytest.raises(ValueError, match="too short"):
            await manager.check("short")

    @pytest.mark.asyncio
    async def test_clear(self):
        """clear 应清空所有缓存和统计."""
        manager = IdempotencyManager()
        await manager.store("key-clear-001", "val1")
        await manager.store("key-clear-002", "val2")

        stats = manager.get_stats()
        assert stats["cache_size"] == 2

        await manager.clear()

        stats = manager.get_stats()
        assert stats["cache_size"] == 0
        assert stats["total_hits"] == 0
        assert stats["total_misses"] == 0
        assert stats["total_evictions"] == 0


# ---------------------------------------------------------------------------
# TTL 过期机制测试
# ---------------------------------------------------------------------------

class TestIdempotencyManagerTTL:
    """TTL 过期机制测试集."""

    @pytest.mark.asyncio
    async def test_expired_key_not_hit(self):
        """过期的 key 不应被命中."""
        manager = IdempotencyManager(ttl=0.1)
        test_key = "test-key-ttl-expire-001"

        await manager.store(test_key, "expired-value")

        # 立即检查应命中
        hit, result = await manager.check(test_key)
        assert hit is True
        assert result == "expired-value"

        # 等待过期
        await asyncio.sleep(0.15)

        # 过期后检查不应命中
        hit, result = await manager.check(test_key)
        assert hit is False
        assert result is None

    @pytest.mark.asyncio
    async def test_error_result_shorter_ttl(self):
        """错误结果的 TTL 应为正常值的 ERROR_TTL_MULTIPLIER 倍."""
        manager = IdempotencyManager(ttl=1.0)
        error_key = "test-key-error-ttl-001"
        normal_key = "test-key-normal-ttl-001"

        # 存储错误结果（通过 execute 触发）
        def raise_err() -> None:
            raise RuntimeError("short ttl error")

        try:
            await manager.execute(error_key, raise_err)
        except RuntimeError:
            pass  # expected

        await manager.store(normal_key, "normal result", is_error=False)

        # 0.3s 后错误结果应已过期（0.2 * 1.0 = 0.2s < 0.3s）
        await asyncio.sleep(0.3)

        hit_error, _ = await manager.check(error_key)
        hit_normal, _ = await manager.check(normal_key)

        assert hit_error is False
        assert hit_normal is True

    @pytest.mark.asyncio
    async def test_cleanup_removes_expired(self):
        """cleanup 应移除所有过期条目."""
        manager = IdempotencyManager(ttl=0.1)

        await manager.store("expired-clean-001", "v1")
        await manager.store("expired-clean-002", "v2")
        await manager.store("expired-clean-003", "v3")

        # 等待全部过期
        await asyncio.sleep(0.15)

        # 清理
        removed = manager.cleanup()
        assert removed == 3

        stats = manager.get_stats()
        assert stats["cache_size"] == 0


# ---------------------------------------------------------------------------
# LRU 淘汰机制测试
# ---------------------------------------------------------------------------

class TestIdempotencyManagerLRU:
    """LRU 淘汰机制测试集."""

    @pytest.mark.asyncio
    async def test_eviction_when_full(self):
        """缓存满时应淘汰最久未使用的条目."""
        manager = IdempotencyManager(ttl=3600, max_entries=3)

        await manager.store("lru-key-001", "v1")
        await manager.store("lru-key-002", "v2")
        await manager.store("lru-key-003", "v3")

        # 访问 key-001，使其变为最近使用
        await manager.check("lru-key-001")

        # 再存一个新 key，应该淘汰 key-002（最久未使用）
        await manager.store("lru-key-004", "v4")

        stats = manager.get_stats()
        assert stats["cache_size"] == 3
        assert stats["total_evictions"] == 1

        # key-002 应被淘汰
        hit, _ = await manager.check("lru-key-002")
        assert hit is False

        # key-001、key-003、key-004 应存在
        hit1, _ = await manager.check("lru-key-001")
        hit3, _ = await manager.check("lru-key-003")
        hit4, _ = await manager.check("lru-key-004")
        assert hit1 is True
        assert hit3 is True
        assert hit4 is True

    @pytest.mark.asyncio
    async def test_multiple_evictions(self):
        """多次超过上限应持续淘汰."""
        manager = IdempotencyManager(ttl=3600, max_entries=2)

        await manager.store("lru-k-001", "v1")
        await manager.store("lru-k-002", "v2")
        await manager.store("lru-k-003", "v3")  # 淘汰 k1
        await manager.store("lru-k-004", "v4")  # 淘汰 k2

        stats = manager.get_stats()
        assert stats["total_evictions"] == 2
        assert stats["cache_size"] == 2

        hit1, _ = await manager.check("lru-k-001")
        hit2, _ = await manager.check("lru-k-002")
        assert hit1 is False
        assert hit2 is False


# ---------------------------------------------------------------------------
# execute 幂等执行测试
# ---------------------------------------------------------------------------

class TestIdempotencyManagerExecute:
    """execute 幂等执行测试集."""

    @pytest.mark.asyncio
    async def test_execute_sync_function(self):
        """执行同步函数并缓存结果."""
        manager = IdempotencyManager()
        call_count = 0

        def add(a: int, b: int) -> int:
            nonlocal call_count
            call_count += 1
            return a + b

        r1 = await manager.execute("exec-sync-test-001", add, 2, 3)
        assert r1 == 5
        assert call_count == 1

        # 第二次执行应命中缓存，函数不被调用
        r2 = await manager.execute("exec-sync-test-001", add, 2, 3)
        assert r2 == 5
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_execute_async_function(self):
        """执行异步函数并缓存结果."""
        manager = IdempotencyManager()
        call_count = 0

        async def async_greet(name: str) -> str:
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.01)
            return f"Hello, {name}!"

        r1 = await manager.execute("exec-async-test-001", async_greet, "World")
        assert r1 == "Hello, World!"
        assert call_count == 1

        r2 = await manager.execute("exec-async-test-001", async_greet, "World")
        assert r2 == "Hello, World!"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_execute_different_keys(self):
        """不同 key 应独立缓存."""
        manager = IdempotencyManager()
        call_count = 0

        def identity(x: int) -> int:
            nonlocal call_count
            call_count += 1
            return x

        r1 = await manager.execute("exec-key-a-001", identity, 10)
        r2 = await manager.execute("exec-key-b-001", identity, 20)

        assert r1 == 10
        assert r2 == 20
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_execute_exception_caching_and_rethrow(self):
        """异常应被缓存，重复调用应重新抛出相同异常."""
        manager = IdempotencyManager(ttl=3600)
        call_count = 0

        def failing_func() -> None:
            nonlocal call_count
            call_count += 1
            raise ValueError("test failure")

        # 第一次执行应抛出异常
        with pytest.raises(ValueError, match="test failure"):
            await manager.execute("exec-error-test-001", failing_func)
        assert call_count == 1

        # 第二次执行也应抛出相同异常（从缓存重抛）
        with pytest.raises(ValueError, match="test failure"):
            await manager.execute("exec-error-test-001", failing_func)
        assert call_count == 1  # 函数未被再次调用

    @pytest.mark.asyncio
    async def test_execute_with_kwargs(self):
        """支持关键字参数."""
        manager = IdempotencyManager()

        def greet(name: str, greeting: str = "Hello") -> str:
            return f"{greeting}, {name}!"

        result = await manager.execute(
            "exec-kwargs-test-001", greet, name="Alice", greeting="Hi"
        )
        assert result == "Hi, Alice!"


# ---------------------------------------------------------------------------
# 并发锁测试
# ---------------------------------------------------------------------------

class TestIdempotencyManagerConcurrency:
    """并发锁测试集."""

    @pytest.mark.asyncio
    async def test_concurrent_execute_same_key(self):
        """同一 key 的并发执行应被串行化，只执行一次."""
        manager = IdempotencyManager()
        call_count = 0

        async def slow_func() -> str:
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.1)
            return "done"

        async def worker() -> str:
            return await manager.execute("concurrent-key-001", slow_func)

        tasks = [asyncio.create_task(worker()) for _ in range(5)]
        results = await asyncio.gather(*tasks)

        assert all(r == "done" for r in results)
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_concurrent_execute_different_keys(self):
        """不同 key 的并发执行应互不干扰."""
        manager = IdempotencyManager()
        results: dict[str, int] = {}

        async def func(key: str) -> str:
            results[key] = results.get(key, 0) + 1
            await asyncio.sleep(0.05)
            return f"result-{key}"

        async def worker(key: str) -> str:
            return await manager.execute(key, func, key)

        keys = [f"concurrent-diff-key-{i:03d}" for i in range(5)]
        tasks = [asyncio.create_task(worker(k)) for k in keys]
        await asyncio.gather(*tasks)

        # 每个 key 都应执行了一次
        assert all(results.get(k, 0) == 1 for k in keys)

    @pytest.mark.asyncio
    async def test_acquire_lock_and_release(self):
        """acquire_lock / release_lock 正常工作."""
        manager = IdempotencyManager()

        # 获取锁
        result = await manager.acquire_lock("lock-test-key-001")
        assert result is True

        # 已锁定的 key 不能重复获取
        result = await manager.acquire_lock("lock-test-key-001")
        assert result is False

        # 释放后可以重新获取
        released = manager.release_lock("lock-test-key-001")
        assert released is True
        result = await manager.acquire_lock("lock-test-key-001")
        assert result is True

        # 清理
        manager.release_lock("lock-test-key-001")

    @pytest.mark.asyncio
    async def test_release_nonexistent_key(self):
        """释放不存在的 key 返回 False."""
        manager = IdempotencyManager()
        released = manager.release_lock("nonexistent-key-001")
        assert released is False


# ---------------------------------------------------------------------------
# 统计信息测试
# ---------------------------------------------------------------------------

class TestIdempotencyManagerStats:
    """统计信息测试集."""

    @pytest.mark.asyncio
    async def test_stats_initial(self):
        """初始统计状态."""
        manager = IdempotencyManager(ttl=3600, max_entries=100)
        stats = manager.get_stats()

        assert stats["cache_size"] == 0
        assert stats["max_entries"] == 100
        assert stats["ttl"] == 3600
        assert stats["total_hits"] == 0
        assert stats["total_misses"] == 0
        assert stats["total_evictions"] == 0
        assert stats["total_errors_stored"] == 0
        assert stats["hit_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_stats_hit_miss(self):
        """命中/未命中统计."""
        manager = IdempotencyManager()

        # 未命中 3 次
        await manager.check("stats-key-miss-001")
        await manager.check("stats-key-miss-002")
        await manager.check("stats-key-miss-003")

        # 存储 2 个
        await manager.store("stats-key-hit-001", "v1")
        await manager.store("stats-key-hit-002", "v2")

        # 命中 2 次
        await manager.check("stats-key-hit-001")
        await manager.check("stats-key-hit-002")

        stats = manager.get_stats()
        assert stats["total_hits"] == 2
        assert stats["total_misses"] == 3
        assert stats["hit_rate"] == pytest.approx(2 / 5, rel=0.01)
        assert stats["cache_size"] == 2

    @pytest.mark.asyncio
    async def test_stats_error_stored(self):
        """错误结果存储统计."""
        manager = IdempotencyManager()

        await manager.store("stats-err-001", ValueError("e1"), is_error=True)
        await manager.store("stats-err-002", RuntimeError("e2"), is_error=True)
        await manager.store("stats-ok-001", "value", is_error=False)

        stats = manager.get_stats()
        assert stats["total_errors_stored"] == 2


# ---------------------------------------------------------------------------
# IdempotencyGuard 依赖注入测试
# ---------------------------------------------------------------------------

class TestIdempotencyGuard:
    """IdempotencyGuard FastAPI 依赖注入测试集."""

    @pytest.mark.asyncio
    async def test_guard_disabled_no_header(self):
        """无幂等键请求头时，guard 处于禁用状态."""
        guard = IdempotencyGuard()
        mock_request = type("MockRequest", (), {"headers": {}})()

        result = await guard.__call__(mock_request)

        assert result.enabled is False
        assert result.key == ""

    @pytest.mark.asyncio
    async def test_guard_enabled_with_header(self):
        """有有效幂等键时，guard 处于启用状态."""
        guard = IdempotencyGuard()
        mock_request = type(
            "MockRequest",
            (),
            {"headers": {"X-Idempotency-Key": "test-idempotency-key-12345"}},
        )()

        result = await guard.__call__(mock_request)

        assert result.enabled is True
        assert result.key == "test-idempotency-key-12345"

    @pytest.mark.asyncio
    async def test_guard_disabled_short_key(self):
        """过短的幂等键被视为无效，guard 禁用."""
        guard = IdempotencyGuard()
        mock_request = type(
            "MockRequest",
            (),
            {"headers": {"X-Idempotency-Key": "short"}},
        )()

        result = await guard.__call__(mock_request)

        assert result.enabled is False
        assert result.key == ""

    @pytest.mark.asyncio
    async def test_guard_execute_disabled(self):
        """禁用状态下 execute 直接执行函数（不缓存）."""
        manager = IdempotencyManager()
        guard = IdempotencyGuard(manager=manager)
        guard.enabled = False
        guard.key = ""
        call_count = 0

        def func() -> int:
            nonlocal call_count
            call_count += 1
            return 42

        r1 = await guard.execute(func)
        r2 = await guard.execute(func)

        assert r1 == 42
        assert r2 == 42
        assert call_count == 2  # 每次都执行

    @pytest.mark.asyncio
    async def test_guard_execute_enabled(self):
        """启用状态下 execute 应做幂等缓存."""
        manager = IdempotencyManager()
        guard = IdempotencyGuard(manager=manager)
        guard.enabled = True
        guard.key = "guard-exec-test-key-001"
        call_count = 0

        def func() -> str:
            nonlocal call_count
            call_count += 1
            return "cached-result"

        r1 = await guard.execute(func)
        r2 = await guard.execute(func)

        assert r1 == "cached-result"
        assert r2 == "cached-result"
        assert call_count == 1  # 只执行一次

    @pytest.mark.asyncio
    async def test_guard_check_disabled(self):
        """禁用状态下 check 返回 (False, None)."""
        guard = IdempotencyGuard()
        guard.enabled = False

        hit, result = await guard.check()
        assert hit is False
        assert result is None

    @pytest.mark.asyncio
    async def test_guard_store_and_check(self):
        """启用状态下 store 和 check 正常工作."""
        manager = IdempotencyManager()
        guard = IdempotencyGuard(manager=manager)
        guard.enabled = True
        guard.key = "guard-store-test-key-001"

        await guard.store({"data": "test"}, is_error=False)
        hit, result = await guard.check()

        assert hit is True
        assert result == {"data": "test"}

    @pytest.mark.asyncio
    async def test_guard_execute_async_function(self):
        """启用状态下执行异步函数."""
        manager = IdempotencyManager()
        guard = IdempotencyGuard(manager=manager)
        guard.enabled = True
        guard.key = "guard-async-test-key-001"
        call_count = 0

        async def async_func() -> str:
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.01)
            return "async-result"

        r1 = await guard.execute(async_func)
        r2 = await guard.execute(async_func)

        assert r1 == "async-result"
        assert r2 == "async-result"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_guard_custom_header(self):
        """支持自定义请求头名称."""
        guard = IdempotencyGuard(header_name="X-Custom-Idem-Key")
        mock_request = type(
            "MockRequest",
            (),
            {"headers": {"X-Custom-Idem-Key": "custom-key-12345678"}},
        )()

        result = await guard.__call__(mock_request)
        assert result.enabled is True
        assert result.key == "custom-key-12345678"

    @pytest.mark.asyncio
    async def test_guard_manager_property(self):
        """manager 属性返回底层管理器."""
        manager = IdempotencyManager()
        guard = IdempotencyGuard(manager=manager)
        assert guard.manager is manager


# ---------------------------------------------------------------------------
# 集成场景测试
# ---------------------------------------------------------------------------

class TestIntegrationScenarios:
    """集成场景测试集."""

    @pytest.mark.asyncio
    async def test_sync_push_idempotency(self):
        """模拟同步推送接口的幂等保护场景."""
        manager = IdempotencyManager(ttl=3600)
        push_count = 0

        async def push_changes(device_id: str, changes: list) -> dict:
            nonlocal push_count
            push_count += 1
            await asyncio.sleep(0.01)
            return {
                "accepted": [c["id"] for c in changes],
                "rejected": [],
                "conflicts": [],
            }

        # 生成幂等键
        key = generate_sync_key("device-001", "session-abc123def456")

        changes = [
            {"id": "item-1", "type": "conversation", "version": 1},
            {"id": "item-2", "type": "memory", "version": 1},
        ]

        # 第一次推送
        result1 = await manager.execute(key, push_changes, "device-001", changes)
        assert result1["accepted"] == ["item-1", "item-2"]
        assert push_count == 1

        # 重复推送（网络重试），应直接返回缓存结果
        result2 = await manager.execute(key, push_changes, "device-001", changes)
        assert result2["accepted"] == ["item-1", "item-2"]
        assert push_count == 1

    @pytest.mark.asyncio
    async def test_config_update_idempotency(self):
        """模拟配置更新接口的幂等保护场景."""
        manager = IdempotencyManager(ttl=3600)
        update_count = 0

        def update_config(updates: dict) -> dict:
            nonlocal update_count
            update_count += 1
            return {
                "updated_keys": list(updates.keys()),
                "rejected_keys": [],
                "restart_required": False,
            }

        key = generate_config_key("sync", "sync.interval")
        updates = {"sync.interval": 120}

        # 第一次更新
        result1 = await manager.execute(key, update_config, updates)
        assert result1["updated_keys"] == ["sync.interval"]
        assert update_count == 1

        # 重复更新
        result2 = await manager.execute(key, update_config, updates)
        assert result2["updated_keys"] == ["sync.interval"]
        assert update_count == 1

    @pytest.mark.asyncio
    async def test_request_id_idempotency(self):
        """基于请求 ID 的通用幂等场景."""
        manager = IdempotencyManager(ttl=3600)
        process_count = 0

        async def process_request(payload: dict) -> dict:
            nonlocal process_count
            process_count += 1
            await asyncio.sleep(0.01)
            return {"status": "success", "processed": len(payload)}

        key = generate_request_key("req-abc123xyz789")
        payload = {"items": [1, 2, 3]}

        result1 = await manager.execute(key, process_request, payload)
        assert result1["status"] == "success"
        assert process_count == 1

        result2 = await manager.execute(key, process_request, payload)
        assert result2["status"] == "success"
        assert process_count == 1

    @pytest.mark.asyncio
    async def test_large_number_of_keys(self):
        """大量 key 下的正确性（简化版压力测试）."""
        manager = IdempotencyManager(ttl=3600, max_entries=1000)

        # 存储 500 个 key
        for i in range(500):
            await manager.store(f"bulk-key-{i:04d}", f"value-{i}")

        stats = manager.get_stats()
        assert stats["cache_size"] == 500

        # 随机访问验证
        for i in [0, 100, 250, 499]:
            hit, result = await manager.check(f"bulk-key-{i:04d}")
            assert hit is True
            assert result == f"value-{i}"

        # 继续存储到超过上限
        for i in range(500, 1200):
            await manager.store(f"bulk-key-{i:04d}", f"value-{i}")

        stats = manager.get_stats()
        assert stats["cache_size"] == 1000
        assert stats["total_evictions"] == 200
