"""离线数据管理测试.

覆盖：
- 离线数据缓存（cache_set/cache_get/cache_delete）
- 离线操作队列（enqueue_operation/get_queue_items/flush_queue）
- 在线检测与自动同步
- 离线模式切换
- 数据过期清理
- 指标统计
"""

from __future__ import annotations

import asyncio
import time

import pytest

from edge_cloud_kernel.services.offline_manager import (
    CachePriority,
    OfflineCacheEntry,
    OfflineManager,
    OfflineMetrics,
    OfflineQueueEntry,
    OfflineStatus,
)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def offline_manager(tmp_path):
    """创建 OfflineManager 测试实例（未初始化）."""
    data_dir = str(tmp_path / "offline_data")
    manager = OfflineManager(data_dir=data_dir)
    yield manager


# ============================================================
# 辅助函数
# ============================================================

def run_async(coro):
    """运行异步函数并返回结果."""
    return asyncio.run(coro)


async def init_manager(manager):
    """初始化管理器."""
    await manager.initialize()
    return manager


async def cleanup_manager(manager):
    """清理管理器."""
    await manager.shutdown()


# ============================================================
# 离线状态枚举测试
# ============================================================

class TestOfflineStatus:
    """离线状态枚举测试."""

    def test_status_enum_values(self):
        """测试离线状态枚举值."""
        assert OfflineStatus.ONLINE == "online"
        assert OfflineStatus.OFFLINE == "offline"
        assert OfflineStatus.RECONNECTING == "reconnecting"
        assert OfflineStatus.FLUSHING == "flushing"

    def test_status_is_str_enum(self):
        """测试是 str 类型枚举."""
        assert isinstance(OfflineStatus.ONLINE, str)
        assert OfflineStatus.ONLINE.value == "online"


class TestCachePriority:
    """缓存优先级枚举测试."""

    def test_priority_values(self):
        """测试缓存优先级枚举值."""
        assert CachePriority.CRITICAL == "critical"
        assert CachePriority.HIGH == "high"
        assert CachePriority.NORMAL == "normal"
        assert CachePriority.LOW == "low"


# ============================================================
# OfflineManager 初始化测试
# ============================================================

class TestOfflineManagerInit:
    """OfflineManager 初始化测试."""

    def test_init_defaults(self, offline_manager):
        """测试默认初始化."""
        assert offline_manager is not None

    def test_initial_status_online(self, offline_manager):
        """测试初始状态应为在线."""
        async def test():
            await offline_manager.initialize()
            try:
                assert offline_manager.status == OfflineStatus.ONLINE
                assert offline_manager.is_online is True
                assert offline_manager.is_offline is False
            finally:
                await offline_manager.shutdown()
        run_async(test())


# ============================================================
# 离线模式切换测试
# ============================================================

class TestOfflineModeSwitching:
    """离线模式切换测试."""

    def test_go_offline(self, offline_manager):
        """测试切换到离线模式."""
        async def test():
            await offline_manager.initialize()
            try:
                await offline_manager.set_offline_mode()
                assert offline_manager.status == OfflineStatus.OFFLINE
                assert offline_manager.is_offline is True
                assert offline_manager.is_online is False
            finally:
                await offline_manager.shutdown()
        run_async(test())

    def test_go_online(self, offline_manager):
        """测试切换到在线模式."""
        async def test():
            await offline_manager.initialize()
            try:
                await offline_manager.set_offline_mode()
                assert offline_manager.is_offline is True
                await offline_manager.set_online_mode()
                assert offline_manager.is_online is True
            finally:
                await offline_manager.shutdown()
        run_async(test())

    def test_status_transition(self, offline_manager):
        """测试状态转换."""
        async def test():
            await offline_manager.initialize()
            try:
                assert offline_manager.status == OfflineStatus.ONLINE
                await offline_manager.set_offline_mode()
                assert offline_manager.status == OfflineStatus.OFFLINE
                await offline_manager.set_online_mode()
                assert offline_manager.status == OfflineStatus.ONLINE
            finally:
                await offline_manager.shutdown()
        run_async(test())

    def test_double_transition_noop(self, offline_manager):
        """测试重复切换同一状态."""
        async def test():
            await offline_manager.initialize()
            try:
                assert offline_manager.status == OfflineStatus.ONLINE
                await offline_manager.set_online_mode()
                assert offline_manager.status == OfflineStatus.ONLINE
            finally:
                await offline_manager.shutdown()
        run_async(test())


# ============================================================
# 离线数据缓存测试
# ============================================================

class TestOfflineDataCache:
    """离线数据缓存测试."""

    def test_cache_set(self, offline_manager):
        """测试设置缓存."""
        async def test():
            await offline_manager.initialize()
            try:
                await offline_manager.cache_set("test_key", {"data": "value"})
                result = await offline_manager.cache_get("test_key")
                assert result == {"data": "value"}
            finally:
                await offline_manager.shutdown()
        run_async(test())

    def test_cache_get(self, offline_manager):
        """测试获取缓存."""
        async def test():
            await offline_manager.initialize()
            try:
                await offline_manager.cache_set("key1", "value1")
                value = await offline_manager.cache_get("key1")
                assert value == "value1"
            finally:
                await offline_manager.shutdown()
        run_async(test())

    def test_cache_get_nonexistent(self, offline_manager):
        """测试获取不存在的缓存."""
        async def test():
            await offline_manager.initialize()
            try:
                value = await offline_manager.cache_get("nonexistent_key")
                assert value is None
            finally:
                await offline_manager.shutdown()
        run_async(test())

    def test_cache_delete(self, offline_manager):
        """测试删除缓存."""
        async def test():
            await offline_manager.initialize()
            try:
                await offline_manager.cache_set("del_key", "to_delete")
                result = await offline_manager.cache_delete("del_key")
                assert result is True
                value = await offline_manager.cache_get("del_key")
                assert value is None
            finally:
                await offline_manager.shutdown()
        run_async(test())

    def test_cache_delete_nonexistent(self, offline_manager):
        """测试删除不存在的缓存."""
        async def test():
            await offline_manager.initialize()
            try:
                result = await offline_manager.cache_delete("no_such_key")
                assert result is False
            finally:
                await offline_manager.shutdown()
        run_async(test())

    def test_cache_expiry(self, offline_manager):
        """测试缓存过期."""
        async def test():
            await offline_manager.initialize()
            try:
                await offline_manager.cache_set(
                    "expiring_key", "temp_value", ttl_seconds=1
                )
                value = await offline_manager.cache_get("expiring_key")
                assert value == "temp_value"
                await asyncio.sleep(1.1)
                value = await offline_manager.cache_get("expiring_key")
                assert value is None
            finally:
                await offline_manager.shutdown()
        run_async(test())

    def test_cache_with_category(self, offline_manager):
        """测试带分类的缓存."""
        async def test():
            await offline_manager.initialize()
            try:
                await offline_manager.cache_set(
                    "cat_key", "cat_value", category="user_data"
                )
                value = await offline_manager.cache_get("cat_key")
                assert value == "cat_value"
            finally:
                await offline_manager.shutdown()
        run_async(test())

    def test_cache_with_priority(self, offline_manager):
        """测试带优先级的缓存."""
        async def test():
            await offline_manager.initialize()
            try:
                await offline_manager.cache_set(
                    "prio_key", "important", priority=CachePriority.HIGH
                )
                value = await offline_manager.cache_get("prio_key")
                assert value == "important"
            finally:
                await offline_manager.shutdown()
        run_async(test())

    def test_cache_clear(self, offline_manager):
        """测试清空缓存."""
        async def test():
            await offline_manager.initialize()
            try:
                await offline_manager.cache_set("a", 1)
                await offline_manager.cache_set("b", 2)
                count = await offline_manager.cache_clear()
                assert count >= 2
                assert await offline_manager.cache_get("a") is None
            finally:
                await offline_manager.shutdown()
        run_async(test())

    def test_cache_clear_by_category(self, offline_manager):
        """测试按分类清空缓存."""
        async def test():
            await offline_manager.initialize()
            try:
                await offline_manager.cache_set("x1", 1, category="cat1")
                await offline_manager.cache_set("x2", 2, category="cat2")
                count = await offline_manager.cache_clear(category="cat1")
                assert count >= 1
                assert await offline_manager.cache_get("x1") is None
                assert await offline_manager.cache_get("x2") == 2
            finally:
                await offline_manager.shutdown()
        run_async(test())

    def test_cache_list(self, offline_manager):
        """测试列出缓存条目."""
        async def test():
            await offline_manager.initialize()
            try:
                await offline_manager.cache_set("list1", 1)
                await offline_manager.cache_set("list2", 2)
                entries = await offline_manager.cache_list(limit=10)
                assert len(entries) >= 2
                assert all(isinstance(e, OfflineCacheEntry) for e in entries)
            finally:
                await offline_manager.shutdown()
        run_async(test())


# ============================================================
# 离线操作队列测试
# ============================================================

class TestOfflineOperationQueue:
    """离线操作队列测试."""

    def test_enqueue_operation(self, offline_manager):
        """测试入队操作."""
        async def test():
            await offline_manager.initialize()
            try:
                entry_id = await offline_manager.enqueue_operation(
                    operation="create",
                    entity_type="conversation",
                    entity_id="conv-001",
                    payload={"content": "test"},
                    priority=5,
                )
                assert entry_id is not None
                assert entry_id > 0
            finally:
                await offline_manager.shutdown()
        run_async(test())

    def test_queue_size(self, offline_manager):
        """测试队列大小."""
        async def test():
            await offline_manager.initialize()
            try:
                initial = await offline_manager.get_queue_size()
                await offline_manager.enqueue_operation(
                    operation="update",
                    entity_type="item",
                    entity_id="item-1",
                    payload={"data": "test"},
                )
                size = await offline_manager.get_queue_size()
                assert size == initial + 1
            finally:
                await offline_manager.shutdown()
        run_async(test())

    def test_get_queue_items(self, offline_manager):
        """测试获取队列条目."""
        async def test():
            await offline_manager.initialize()
            try:
                await offline_manager.enqueue_operation(
                    operation="create",
                    entity_type="msg",
                    entity_id="msg-1",
                    payload={"text": "hello"},
                )
                items = await offline_manager.get_queue_items(limit=10)
                assert len(items) >= 1
                assert all(isinstance(item, OfflineQueueEntry) for item in items)
            finally:
                await offline_manager.shutdown()
        run_async(test())

    def test_priority_ordering(self, offline_manager):
        """测试优先级排序."""
        async def test():
            await offline_manager.initialize()
            try:
                await offline_manager.enqueue_operation(
                    operation="op1", entity_type="t", entity_id="e1",
                    payload={}, priority=1,
                )
                await offline_manager.enqueue_operation(
                    operation="op2", entity_type="t", entity_id="e2",
                    payload={}, priority=10,
                )
                items = await offline_manager.get_queue_items(limit=10)
                priorities = [item.priority for item in items]
                assert priorities[0] >= priorities[-1]
            finally:
                await offline_manager.shutdown()
        run_async(test())

    def test_multiple_entities(self, offline_manager):
        """测试多实体类型队列."""
        async def test():
            await offline_manager.initialize()
            try:
                await offline_manager.enqueue_operation(
                    operation="create", entity_type="user", entity_id="u1", payload={}
                )
                await offline_manager.enqueue_operation(
                    operation="update", entity_type="message", entity_id="m1", payload={}
                )
                size = await offline_manager.get_queue_size()
                assert size >= 2
            finally:
                await offline_manager.shutdown()
        run_async(test())


# ============================================================
# 在线检测测试
# ============================================================

class TestOnlineDetection:
    """在线检测测试."""

    def test_check_connectivity_default(self, offline_manager):
        """测试默认连通性检测（无回调时返回 True）."""
        async def test():
            await offline_manager.initialize()
            try:
                result = await offline_manager.check_connectivity()
                assert isinstance(result, bool)
                assert result is True
            finally:
                await offline_manager.shutdown()
        run_async(test())

    def test_register_connectivity_check(self, offline_manager):
        """测试注册连通性检测回调."""
        async def test():
            await offline_manager.initialize()
            try:
                call_count = 0

                def check_fn():
                    nonlocal call_count
                    call_count += 1
                    return True

                offline_manager.register_connectivity_check(check_fn)
                result = await offline_manager.check_connectivity()
                assert result is True
                assert call_count == 1
            finally:
                await offline_manager.shutdown()
        run_async(test())

    def test_register_async_connectivity_check(self, offline_manager):
        """测试注册异步连通性检测回调."""
        async def test():
            await offline_manager.initialize()
            try:
                async def async_check():
                    await asyncio.sleep(0.01)
                    return False

                offline_manager.register_connectivity_check(async_check)
                result = await offline_manager.check_connectivity()
                assert result is False
            finally:
                await offline_manager.shutdown()
        run_async(test())

    def test_status_callback(self, offline_manager):
        """测试状态变更回调."""
        async def test():
            await offline_manager.initialize()
            try:
                callback_called = []

                def on_status_change(status):
                    callback_called.append(status)

                offline_manager.register_status_callback(on_status_change)
                await offline_manager.set_offline_mode()
                assert len(callback_called) > 0
                assert callback_called[-1] == OfflineStatus.OFFLINE
            finally:
                await offline_manager.shutdown()
        run_async(test())


# ============================================================
# 队列刷新测试
# ============================================================

class TestQueueFlush:
    """队列刷新测试."""

    def test_flush_queue_empty(self, offline_manager):
        """测试空队列刷新."""
        async def test():
            await offline_manager.initialize()
            try:
                result = await offline_manager.flush_queue()
                assert isinstance(result, dict)
                assert "success" in result
                assert "failed" in result
                assert "remaining" in result
            finally:
                await offline_manager.shutdown()
        run_async(test())

    def test_flush_queue_with_callback(self, offline_manager):
        """测试带回调的队列刷新."""
        async def test():
            await offline_manager.initialize()
            try:
                processed_ops = []

                async def flush_callback(ops):
                    processed_ops.extend(ops)
                    return [op["id"] for op in ops] if ops else []

                offline_manager.register_flush_callback(flush_callback)

                await offline_manager.enqueue_operation(
                    operation="create", entity_type="t", entity_id="e1", payload={"a": 1}
                )
                await offline_manager.enqueue_operation(
                    operation="update", entity_type="t", entity_id="e2", payload={"b": 2}
                )

                result = await offline_manager.flush_queue()
                assert result["success"] >= 2
            finally:
                await offline_manager.shutdown()
        run_async(test())

    def test_flush_queue_failed_callback(self, offline_manager):
        """测试刷新回调失败时的处理."""
        async def test():
            await offline_manager.initialize()
            try:
                async def failing_callback(ops):
                    raise RuntimeError("flush failed")

                offline_manager.register_flush_callback(failing_callback)

                await offline_manager.enqueue_operation(
                    operation="create", entity_type="t", entity_id="e1", payload={}
                )

                result = await offline_manager.flush_queue()
                assert result["failed"] >= 1
            finally:
                await offline_manager.shutdown()
        run_async(test())

    def test_purge_failed(self, offline_manager):
        """测试清理失败操作."""
        async def test():
            await offline_manager.initialize()
            try:
                async def failing_callback(ops):
                    raise RuntimeError("fail")

                offline_manager.register_flush_callback(failing_callback)
                await offline_manager.enqueue_operation(
                    operation="op", entity_type="t", entity_id="e", payload={}
                )
                for _ in range(6):
                    await offline_manager.flush_queue()

                purged = await offline_manager.purge_failed(max_retries=5)
                assert purged >= 0
            finally:
                await offline_manager.shutdown()
        run_async(test())


# ============================================================
# 数据过期清理测试
# ============================================================

class TestDataExpiration:
    """数据过期清理测试."""

    def test_cleanup_expired_cache(self, offline_manager):
        """测试清理过期缓存."""
        async def test():
            await offline_manager.initialize()
            try:
                await offline_manager.cache_set(
                    "expired1", "old_data", ttl_seconds=1
                )
                await asyncio.sleep(1.1)

                result = await offline_manager.cleanup_expired()
                assert isinstance(result, dict)
                assert "cache_expired" in result
            finally:
                await offline_manager.shutdown()
        run_async(test())

    def test_cleanup_preserves_valid(self, offline_manager):
        """测试清理不影响有效数据."""
        async def test():
            await offline_manager.initialize()
            try:
                await offline_manager.cache_set(
                    "valid_key", "valid_data", ttl_seconds=3600
                )
                await offline_manager.cleanup_expired()
                value = await offline_manager.cache_get("valid_key")
                assert value == "valid_data"
            finally:
                await offline_manager.shutdown()
        run_async(test())


# ============================================================
# 指标统计测试
# ============================================================

class TestOfflineMetrics:
    """离线管理指标测试."""

    def test_get_metrics(self, offline_manager):
        """测试获取指标."""
        async def test():
            await offline_manager.initialize()
            try:
                metrics = await offline_manager.get_metrics()
                assert isinstance(metrics, OfflineMetrics)
                assert hasattr(metrics, "total_queued")
                assert hasattr(metrics, "total_flushed")
                assert hasattr(metrics, "cache_hits")
                assert hasattr(metrics, "cache_misses")
            finally:
                await offline_manager.shutdown()
        run_async(test())

    def test_cache_hit_rate(self, offline_manager):
        """测试缓存命中率."""
        async def test():
            await offline_manager.initialize()
            try:
                await offline_manager.cache_set("hit_key", "value")
                await offline_manager.cache_get("hit_key")
                await offline_manager.cache_get("miss_key")

                hit_rate = await offline_manager.get_cache_hit_rate()
                assert 0.0 <= hit_rate <= 1.0
            finally:
                await offline_manager.shutdown()
        run_async(test())

    def test_metrics_queue_size(self, offline_manager):
        """测试队列大小指标."""
        async def test():
            await offline_manager.initialize()
            try:
                await offline_manager.enqueue_operation(
                    operation="op", entity_type="t", entity_id="e", payload={}
                )
                metrics = await offline_manager.get_metrics()
                assert metrics.current_queue_size >= 1
            finally:
                await offline_manager.shutdown()
        run_async(test())


# ============================================================
# 数据结构测试
# ============================================================

class TestDataStructures:
    """数据结构测试."""

    def test_offline_queue_entry_defaults(self):
        """测试 OfflineQueueEntry 默认值."""
        entry = OfflineQueueEntry()
        assert entry.id == 0
        assert entry.operation == ""
        assert entry.priority == 5
        assert entry.status == "pending"
        assert entry.retry_count == 0

    def test_offline_cache_entry_defaults(self):
        """测试 OfflineCacheEntry 默认值."""
        entry = OfflineCacheEntry()
        assert entry.cache_key == ""
        assert entry.category == "default"
        assert entry.priority == CachePriority.NORMAL
        assert entry.access_count == 0

    def test_offline_metrics_defaults(self):
        """测试 OfflineMetrics 默认值."""
        metrics = OfflineMetrics()
        assert metrics.total_queued == 0
        assert metrics.cache_hits == 0
        assert metrics.offline_duration == 0.0
