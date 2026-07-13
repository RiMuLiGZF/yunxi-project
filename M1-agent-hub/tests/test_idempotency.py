"""
测试：幂等性管理模块
"""

import pytest
import sys
import os
import asyncio
import time

# 将项目根目录加入路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from idempotency import (
    IdempotencyManager,
    generate_task_key,
    generate_agent_key,
    generate_message_key,
    generate_request_key,
    idempotent,
    get_idempotency_manager,
)


# ── 幂等键生成工具测试 ────────────────────────────────────


def test_generate_task_key_format():
    """测试任务幂等键格式正确"""
    key = generate_task_key("task_123")
    assert key == "task:task_123"


def test_generate_agent_key_format():
    """测试 Agent 操作幂等键格式正确"""
    key = generate_agent_key("agent_001", "register")
    assert key == "agent:agent_001:register"


def test_generate_message_key_format():
    """测试消息幂等键格式正确"""
    key = generate_message_key("msg_abc")
    assert key == "msg:msg_abc"


def test_generate_request_key_format():
    """测试 HTTP 请求幂等键格式正确"""
    key = generate_request_key("req-xyz-789")
    assert key == "req:req-xyz-789"


def test_generate_keys_unique():
    """测试不同参数生成不同的键"""
    k1 = generate_task_key("a")
    k2 = generate_task_key("b")
    assert k1 != k2

    k3 = generate_agent_key("a", "register")
    k4 = generate_agent_key("a", "update")
    assert k3 != k4


# ── IdempotencyManager 基本功能测试 ──────────────────────


@pytest.mark.asyncio
async def test_idempotency_check_miss():
    """测试 check 方法：键不存在时返回 miss"""
    mgr = IdempotencyManager(ttl=3600, max_entries=100)
    exists, result = await mgr.check("nonexistent_key")
    assert exists is False
    assert result is None


@pytest.mark.asyncio
async def test_idempotency_store_and_check():
    """测试 store 后 check 能命中"""
    mgr = IdempotencyManager(ttl=3600, max_entries=100)
    await mgr.store("key1", {"status": "ok"})

    exists, result = await mgr.check("key1")
    assert exists is True
    assert result == {"status": "ok"}


@pytest.mark.asyncio
async def test_idempotency_execute_first_time():
    """测试 execute 第一次执行函数并缓存结果"""
    mgr = IdempotencyManager(ttl=3600, max_entries=100)
    call_count = 0

    async def do_work(x):
        nonlocal call_count
        call_count += 1
        return x * 2

    result = await mgr.execute("key_exec", do_work, 5)
    assert result == 10
    assert call_count == 1


@pytest.mark.asyncio
async def test_idempotency_execute_cached():
    """测试 execute 第二次相同 key 返回缓存，不重复执行"""
    mgr = IdempotencyManager(ttl=3600, max_entries=100)
    call_count = 0

    async def do_work(x):
        nonlocal call_count
        call_count += 1
        return x * 2

    result1 = await mgr.execute("key_cached", do_work, 5)
    result2 = await mgr.execute("key_cached", do_work, 10)  # 参数不同但 key 相同

    assert result1 == 10
    assert result2 == 10  # 返回缓存结果
    assert call_count == 1  # 只执行了一次


# ── TTL 过期测试 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_idempotency_ttl_expiry():
    """测试 TTL 过期后重新执行"""
    mgr = IdempotencyManager(ttl=0.1, max_entries=100)  # 100ms 过期
    call_count = 0

    async def do_work():
        nonlocal call_count
        call_count += 1
        return "result"

    # 第一次执行
    result1 = await mgr.execute("ttl_key", do_work)
    assert result1 == "result"
    assert call_count == 1

    # 未过期时命中缓存
    result2 = await mgr.execute("ttl_key", do_work)
    assert result2 == "result"
    assert call_count == 1

    # 等待过期
    await asyncio.sleep(0.15)

    # 过期后重新执行
    result3 = await mgr.execute("ttl_key", do_work)
    assert result3 == "result"
    assert call_count == 2


@pytest.mark.asyncio
async def test_idempotency_check_expired_returns_miss():
    """测试 check 过期键返回未命中"""
    mgr = IdempotencyManager(ttl=0.05, max_entries=100)
    await mgr.store("expired_key", "value")

    # 刚存入能命中
    exists, _ = await mgr.check("expired_key")
    assert exists is True

    # 等待过期
    await asyncio.sleep(0.1)

    # 过期后未命中
    exists, result = await mgr.check("expired_key")
    assert exists is False
    assert result is None


# ── max_entries 限制（LRU 淘汰）测试 ─────────────────────


@pytest.mark.asyncio
async def test_idempotency_max_entries_eviction():
    """测试超出 max_entries 后 LRU 淘汰最旧条目"""
    mgr = IdempotencyManager(ttl=3600, max_entries=3)

    # 存入 3 个条目
    await mgr.store("key1", "val1")
    await mgr.store("key2", "val2")
    await mgr.store("key3", "val3")

    stats = mgr.get_stats()
    assert stats["total_keys"] == 3
    assert stats["total_evictions"] == 0

    # 存入第 4 个，应淘汰最旧的 key1
    await mgr.store("key4", "val4")

    stats = mgr.get_stats()
    assert stats["total_keys"] == 3
    assert stats["total_evictions"] == 1

    # key1 应被淘汰
    exists, _ = await mgr.check("key1")
    assert exists is False

    # key2, key3, key4 应存在
    for key in ["key2", "key3", "key4"]:
        exists, _ = await mgr.check(key)
        assert exists is True, f"{key} 应该存在"


@pytest.mark.asyncio
async def test_idempotency_lru_order_update():
    """测试 LRU 顺序：访问旧条目后将其移到末尾，不被淘汰"""
    mgr = IdempotencyManager(ttl=3600, max_entries=3)

    await mgr.store("key_a", "a")
    await mgr.store("key_b", "b")
    await mgr.store("key_c", "c")

    # 访问 key_a，使其变为最近使用
    await mgr.check("key_a")

    # 存入新键，应淘汰最久未使用的 key_b
    await mgr.store("key_d", "d")

    exists_a, _ = await mgr.check("key_a")
    exists_b, _ = await mgr.check("key_b")

    assert exists_a is True  # 被访问过，保留
    assert exists_b is False  # 最久未使用，被淘汰


# ── 错误结果缓存测试 ──────────────────────────────────────


@pytest.mark.asyncio
async def test_idempotency_store_error_result():
    """测试错误结果也会被缓存"""
    mgr = IdempotencyManager(ttl=3600, max_entries=100)

    await mgr.store("error_key", "错误信息", is_error=True)

    exists, result = await mgr.check("error_key")
    assert exists is True
    assert result == "错误信息"

    stats = mgr.get_stats()
    assert stats["total_errors"] == 1


@pytest.mark.asyncio
async def test_idempotency_execute_exception_not_cached():
    """测试 execute 中函数抛出异常不会被缓存"""
    mgr = IdempotencyManager(ttl=3600, max_entries=100)
    call_count = 0

    async def failing_func():
        nonlocal call_count
        call_count += 1
        raise ValueError("something went wrong")

    # 第一次调用抛出异常
    with pytest.raises(ValueError):
        await mgr.execute("err_key", failing_func)
    assert call_count == 1

    # 第二次调用仍会执行（异常不缓存）
    with pytest.raises(ValueError):
        await mgr.execute("err_key", failing_func)
    assert call_count == 2


# ── 装饰器模式测试 ────────────────────────────────────────


@pytest.mark.asyncio
async def test_idempotent_decorator_basic():
    """测试幂等装饰器基本功能"""
    mgr = IdempotencyManager(ttl=3600, max_entries=100)
    call_count = 0

    @idempotent(
        key_func=lambda task_id, data: generate_task_key(task_id),
        manager=mgr,
    )
    async def submit_task(task_id, data):
        nonlocal call_count
        call_count += 1
        return {"task_id": task_id, "status": "submitted"}

    result1 = await submit_task("task_001", {"x": 1})
    result2 = await submit_task("task_001", {"x": 2})  # 相同 task_id

    assert result1 == {"task_id": "task_001", "status": "submitted"}
    assert result2 == result1
    assert call_count == 1


@pytest.mark.asyncio
async def test_idempotent_decorator_different_keys():
    """测试装饰器不同 key 会分别执行"""
    mgr = IdempotencyManager(ttl=3600, max_entries=100)
    call_count = 0

    @idempotent(
        key_func=lambda task_id: generate_task_key(task_id),
        manager=mgr,
    )
    async def process(task_id):
        nonlocal call_count
        call_count += 1
        return f"processed_{task_id}"

    r1 = await process("task_a")
    r2 = await process("task_b")

    assert r1 == "processed_task_a"
    assert r2 == "processed_task_b"
    assert call_count == 2


# ── 统计信息测试 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_idempotency_stats_hit_rate():
    """测试统计信息中的命中率计算"""
    mgr = IdempotencyManager(ttl=3600, max_entries=100)

    await mgr.store("key_hit", "value")

    # 3 次命中 + 2 次未命中 = 5 次查询
    await mgr.check("key_hit")
    await mgr.check("key_hit")
    await mgr.check("key_hit")
    await mgr.check("key_miss1")
    await mgr.check("key_miss2")

    stats = mgr.get_stats()
    assert stats["total_hits"] == 3
    assert stats["total_misses"] == 2
    assert stats["total_executions"] == 1  # 只有 1 次 store (新条目)
    assert stats["hit_rate"] == pytest.approx(0.6, abs=0.01)
    assert stats["total_keys"] == 1


@pytest.mark.asyncio
async def test_idempotency_stats_zero_requests():
    """测试没有请求时命中率为 0"""
    mgr = IdempotencyManager(ttl=3600, max_entries=100)
    stats = mgr.get_stats()
    assert stats["hit_rate"] == 0.0
    assert stats["total_keys"] == 0


# ── 同步函数支持测试 ──────────────────────────────────────


@pytest.mark.asyncio
async def test_idempotency_execute_sync_function():
    """测试 execute 支持同步函数"""
    mgr = IdempotencyManager(ttl=3600, max_entries=100)
    call_count = 0

    def sync_work(x):
        nonlocal call_count
        call_count += 1
        return x + 10

    result1 = await mgr.execute("sync_key", sync_work, 5)
    result2 = await mgr.execute("sync_key", sync_work, 100)

    assert result1 == 15
    assert result2 == 15  # 缓存结果
    assert call_count == 1


# ── cleanup 测试 ──────────────────────────────────────────


def test_idempotency_cleanup_removes_expired():
    """测试 cleanup 方法清理过期条目"""
    mgr = IdempotencyManager(ttl=0.05, max_entries=100)

    # 手动操作 _cache 模拟过期（同步方式）
    mgr._cache["key1"] = ("val1", False, time.time() - 10)  # 已过期
    mgr._cache["key2"] = ("val2", False, time.time())  # 未过期

    removed = mgr.cleanup()
    assert removed == 1

    stats = mgr.get_stats()
    assert stats["total_keys"] == 1
    assert stats["total_expired"] >= 1


# ── 异步安全性测试 ────────────────────────────────────────


@pytest.mark.asyncio
async def test_idempotency_concurrent_access():
    """测试并发访问下的正确性"""
    mgr = IdempotencyManager(ttl=3600, max_entries=1000)
    call_count = 0
    lock = asyncio.Lock()

    async def do_work(key_suffix):
        nonlocal call_count
        async with lock:
            call_count += 1
        return f"result_{key_suffix}"

    # 并发执行多个不同 key 的任务
    tasks = []
    for i in range(20):
        key = f"concurrent_key_{i}"
        tasks.append(asyncio.create_task(mgr.execute(key, do_work, i)))

    results = await asyncio.gather(*tasks)
    assert len(results) == 20
    assert call_count == 20

    stats = mgr.get_stats()
    assert stats["total_keys"] == 20
    assert stats["total_executions"] == 20


@pytest.mark.asyncio
async def test_idempotency_concurrent_same_key():
    """测试同一 key 并发执行时的行为"""
    mgr = IdempotencyManager(ttl=3600, max_entries=100)
    call_count = 0
    lock = asyncio.Lock()

    async def do_work():
        nonlocal call_count
        async with lock:
            call_count += 1
        await asyncio.sleep(0.01)
        return "shared_result"

    # 同时发起多个相同 key 的请求
    tasks = [asyncio.create_task(mgr.execute("same_key", do_work)) for _ in range(5)]
    results = await asyncio.gather(*tasks)

    # 所有结果应一致
    assert all(r == "shared_result" for r in results)


# ── 模块级单例测试 ────────────────────────────────────────


def test_get_idempotency_manager_singleton():
    """测试 get_idempotency_manager 返回单例"""
    # 重置全局单例以便测试
    import idempotency
    idempotency._default_manager = None

    mgr1 = get_idempotency_manager(ttl=100, max_entries=50)
    mgr2 = get_idempotency_manager(ttl=200, max_entries=200)  # 参数不同

    assert mgr1 is mgr2  # 同一实例
    assert mgr1.ttl == 100  # 以首次创建的参数为准


# ── store 更新已有条目测试 ────────────────────────────────


@pytest.mark.asyncio
async def test_idempotency_store_update_existing():
    """测试 store 更新已有条目"""
    mgr = IdempotencyManager(ttl=3600, max_entries=100)

    await mgr.store("update_key", "old_value")
    exists, result = await mgr.check("update_key")
    assert result == "old_value"

    await mgr.store("update_key", "new_value")
    exists, result = await mgr.check("update_key")
    assert result == "new_value"

    # 执行数不增加（更新不计数）
    stats = mgr.get_stats()
    assert stats["total_executions"] == 1
