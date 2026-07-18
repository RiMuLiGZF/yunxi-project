"""
有界集合工具类单元测试
=======================

测试 BoundedList、LRUDict、BoundedSet 的核心功能。
"""

import sys
import os
import time
import threading
import pytest

# 确保 shared 包可被导入
from shared.core.bounded_collections import (
    BoundedList,
    LRUDict,
    BoundedSet,
    EvictionReason,
)


# ──────────────────────────────────────────────────────────
# BoundedList 测试
# ──────────────────────────────────────────────────────────

class TestBoundedList:
    """BoundedList 单元测试"""

    def test_basic_append(self):
        """基本追加功能"""
        bl = BoundedList(max_size=5)
        for i in range(3):
            bl.append(i)
        assert len(bl) == 3
        assert bl[0] == 0
        assert bl[1] == 1
        assert bl[2] == 2

    def test_capacity_limit(self):
        """容量限制：超出时淘汰最旧的"""
        bl = BoundedList(max_size=3)
        bl.append(1)
        bl.append(2)
        bl.append(3)
        assert len(bl) == 3
        assert bl.is_full

        # 第 4 个元素应淘汰第 1 个
        evicted = bl.append(4)
        assert len(bl) == 3
        assert evicted == 1
        assert bl[0] == 2
        assert bl[2] == 4

    def test_fifo_order(self):
        """FIFO 淘汰顺序验证"""
        bl = BoundedList(max_size=3)
        bl.extend([1, 2, 3, 4, 5])
        assert len(bl) == 3
        assert bl.to_list() == [3, 4, 5]

    def test_extend(self):
        """批量追加"""
        bl = BoundedList(max_size=5)
        evicted = bl.extend([1, 2, 3])
        assert len(bl) == 3
        assert evicted == []

        evicted = bl.extend([4, 5, 6, 7])
        assert len(bl) == 5
        assert len(evicted) == 2
        assert evicted == [1, 2]
        assert bl.to_list() == [3, 4, 5, 6, 7]

    def test_extend_empty(self):
        """空迭代 extend"""
        bl = BoundedList(max_size=5)
        evicted = bl.extend([])
        assert len(bl) == 0
        assert evicted == []

    def test_clear(self):
        """清空列表"""
        bl = BoundedList(max_size=5)
        bl.extend([1, 2, 3])
        bl.clear()
        assert len(bl) == 0
        assert bl.evicted_count == 0  # clear 重置计数

    def test_evicted_count(self):
        """淘汰计数"""
        bl = BoundedList(max_size=3)
        bl.extend([1, 2, 3, 4, 5, 6])
        assert bl.evicted_count == 3

    def test_first_last(self):
        """首尾元素获取"""
        bl = BoundedList(max_size=5)
        assert bl.first() is None
        assert bl.last() is None

        bl.extend([1, 2, 3])
        assert bl.first() == 1
        assert bl.last() == 3

    def test_iteration(self):
        """迭代功能"""
        bl = BoundedList(max_size=5)
        bl.extend([1, 2, 3])
        result = [x for x in bl]
        assert result == [1, 2, 3]

    def test_contains(self):
        """包含判断"""
        bl = BoundedList(max_size=5)
        bl.extend([1, 2, 3])
        assert 2 in bl
        assert 5 not in bl

    def test_on_evict_callback(self):
        """溢出回调"""
        evicted_items = []

        def on_evict(item, reason):
            evicted_items.append((item, reason))

        bl = BoundedList(max_size=3, on_evict=on_evict)
        bl.extend([1, 2, 3, 4, 5])

        assert len(evicted_items) == 2
        assert evicted_items[0] == (1, EvictionReason.CAPACITY)
        assert evicted_items[1] == (2, EvictionReason.CAPACITY)

    def test_callback_exception_safe(self):
        """回调异常不影响主流程"""
        def bad_callback(item, reason):
            raise RuntimeError("callback error")

        bl = BoundedList(max_size=2, on_evict=bad_callback)
        bl.append(1)
        bl.append(2)
        # 下面这行如果回调异常未被正确捕获会抛错
        bl.append(3)
        assert len(bl) == 2
        assert bl.to_list() == [2, 3]

    def test_invalid_max_size(self):
        """非法容量值"""
        with pytest.raises(ValueError):
            BoundedList(max_size=0)
        with pytest.raises(ValueError):
            BoundedList(max_size=-1)

    def test_resize_expand(self):
        """扩容"""
        bl = BoundedList(max_size=3)
        bl.extend([1, 2, 3])
        evicted = bl.resize(5)
        assert evicted == []
        assert bl.max_size == 5
        assert len(bl) == 3

    def test_resize_shrink(self):
        """缩容"""
        bl = BoundedList(max_size=5)
        bl.extend([1, 2, 3, 4, 5])
        evicted = bl.resize(3)
        assert len(evicted) == 2
        assert evicted == [1, 2]
        assert bl.to_list() == [3, 4, 5]

    def test_stats(self):
        """统计信息"""
        bl = BoundedList(max_size=10)
        bl.extend([1, 2, 3, 4, 5])
        stats = bl.stats()
        assert stats["max_size"] == 10
        assert stats["current_size"] == 5
        assert stats["evicted_count"] == 0
        assert stats["is_full"] is False
        assert stats["utilization"] == 0.5
        assert stats["thread_safe"] is False

    def test_repr(self):
        """字符串表示"""
        bl = BoundedList(max_size=5)
        bl.append(1)
        assert "BoundedList" in repr(bl)
        assert "max_size=5" in repr(bl)

    def test_thread_safety(self):
        """线程安全测试（多线程并发 append）"""
        bl = BoundedList(max_size=1000, thread_safe=True)
        num_threads = 10
        items_per_thread = 200

        def worker(tid):
            for i in range(items_per_thread):
                bl.append(f"t{tid}-{i}")

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 最终元素数不超过 max_size
        assert len(bl) <= 1000
        # 应该正好是 1000（填满了）
        assert len(bl) == 1000
        assert bl.is_full

    def test_index_access(self):
        """索引访问"""
        bl = BoundedList(max_size=5)
        bl.extend([10, 20, 30])
        assert bl[0] == 10
        assert bl[-1] == 30
        assert bl[1] == 20


# ──────────────────────────────────────────────────────────
# LRUDict 测试
# ──────────────────────────────────────────────────────────

class TestLRUDict:
    """LRUDict 单元测试"""

    def test_basic_set_get(self):
        """基本 set/get"""
        d = LRUDict(max_size=5)
        d.set("a", 1)
        d.set("b", 2)
        assert d.get("a") == 1
        assert d.get("b") == 2
        assert len(d) == 2

    def test_capacity_limit(self):
        """容量限制：LRU 淘汰"""
        d = LRUDict(max_size=3)
        d.set("a", 1)
        d.set("b", 2)
        d.set("c", 3)
        assert len(d) == 3
        assert d.is_full

        # 访问 a，使 b 成为最久未使用
        d.get("a")
        # 插入 d，应淘汰 b
        evicted = d.set("d", 4)
        assert evicted is not None
        assert evicted[0] == "b"
        assert evicted[1] == 2
        assert len(d) == 3
        assert d.get("b") is None
        assert d.get("a") == 1
        assert d.get("c") == 3
        assert d.get("d") == 4

    def test_update_existing_key(self):
        """更新已存在的键会刷新 LRU 顺序"""
        d = LRUDict(max_size=3)
        d.set("a", 1)
        d.set("b", 2)
        d.set("c", 3)

        # 更新 a 的值
        d.set("a", 10)
        # 此时 LRU 顺序: b, c, a
        # 插入 d 应淘汰 b
        d.set("d", 4)
        assert d.get("a") == 10
        assert d.get("b") is None

    def test_delete(self):
        """删除键"""
        d = LRUDict(max_size=5)
        d.set("a", 1)
        d.set("b", 2)
        result = d.delete("a")
        assert result == 1
        assert len(d) == 1
        assert d.get("a") is None

        # 删除不存在的键
        result = d.delete("nonexistent")
        assert result is None

    def test_clear(self):
        """清空"""
        d = LRUDict(max_size=5)
        d.set("a", 1)
        d.set("b", 2)
        d.clear()
        assert len(d) == 0
        assert d.evicted_count == 0
        assert d.expired_count == 0

    def test_get_default(self):
        """get 默认值"""
        d = LRUDict(max_size=5)
        assert d.get("missing", 42) == 42
        assert d.get("missing") is None

    def test_peek(self):
        """peek 不刷新 LRU 顺序"""
        d = LRUDict(max_size=3)
        d.set("a", 1)
        d.set("b", 2)
        d.set("c", 3)

        # peek a 不刷新顺序
        val = d.peek("a")
        assert val == 1

        # 插入 d，a 仍是最久未使用，应被淘汰
        d.set("d", 4)
        assert d.get("a") is None
        assert d.get("b") == 2

    def test_ttl_expiry(self):
        """TTL 过期"""
        d = LRUDict(max_size=10, ttl=0.1)  # 100ms
        d.set("a", 1)
        d.set("b", 2)

        assert d.get("a") == 1
        time.sleep(0.15)

        # 过期了
        assert d.get("a") is None
        assert "a" not in d
        assert d.expired_count >= 1

    def test_ttl_per_key(self):
        """单键独立 TTL"""
        d = LRUDict(max_size=10, ttl=10)  # 全局 10 秒
        d.set("fast", 1, ttl=0.1)  # 这个 100ms 就过期
        d.set("slow", 2)  # 这个用全局 10 秒

        time.sleep(0.15)
        assert d.get("fast") is None
        assert d.get("slow") == 2

    def test_purge_expired(self):
        """主动清理过期项"""
        d = LRUDict(max_size=10, ttl=0.1)
        d.set("a", 1)
        d.set("b", 2)
        d.set("c", 3)

        time.sleep(0.15)
        expired = d.purge_expired()
        assert len(expired) == 3
        assert len(d) == 0

    def test_purge_expired_no_ttl(self):
        """无 TTL 时 purge_expired 返回空"""
        d = LRUDict(max_size=10)
        d.set("a", 1)
        expired = d.purge_expired()
        assert expired == []
        assert len(d) == 1

    def test_dict_style_access(self):
        """字典风格的下标访问"""
        d = LRUDict(max_size=5)
        d["a"] = 1
        assert d["a"] == 1

        del d["a"]
        assert "a" not in d

    def test_keys_values_items(self):
        """keys/values/items 方法"""
        d = LRUDict(max_size=5)
        d.set("a", 1)
        d.set("b", 2)
        d.set("c", 3)

        assert d.keys() == ["a", "b", "c"]
        assert d.values() == [1, 2, 3]
        assert d.items() == [("a", 1), ("b", 2), ("c", 3)]

        # 访问 a 后顺序变了
        d.get("a")
        assert d.keys() == ["b", "c", "a"]

    def test_on_evict_callback(self):
        """淘汰回调"""
        evictions = []

        def on_evict(key, value, reason):
            evictions.append((key, value, reason))

        d = LRUDict(max_size=3, on_evict=on_evict)
        d.set("a", 1)
        d.set("b", 2)
        d.set("c", 3)
        d.set("d", 4)  # 淘汰 a

        assert len(evictions) == 1
        assert evictions[0] == ("a", 1, EvictionReason.CAPACITY)

    def test_ttl_expiry_callback(self):
        """过期回调"""
        evictions = []

        def on_evict(key, value, reason):
            evictions.append((key, value, reason))

        d = LRUDict(max_size=10, ttl=0.1, on_evict=on_evict)
        d.set("a", 1)
        time.sleep(0.15)
        d.get("a")  # 触发过期检查

        assert len(evictions) == 1
        assert evictions[0][0] == "a"
        assert evictions[0][2] == EvictionReason.EXPIRED

    def test_invalid_max_size(self):
        """非法容量"""
        with pytest.raises(ValueError):
            LRUDict(max_size=0)

    def test_resize(self):
        """调整容量"""
        d = LRUDict(max_size=5)
        d.set("a", 1)
        d.set("b", 2)
        d.set("c", 3)

        # 缩容
        evicted = d.resize(2)
        assert len(evicted) == 1
        assert evicted[0][0] == "a"
        assert d.max_size == 2

    def test_stats(self):
        """统计信息"""
        d = LRUDict(max_size=10, ttl=60)
        d.set("a", 1)
        d.set("b", 2)
        stats = d.stats()
        assert stats["max_size"] == 10
        assert stats["current_size"] == 2
        assert stats["ttl"] == 60
        assert stats["evicted_count"] == 0
        assert stats["expired_count"] == 0
        assert stats["utilization"] == 0.2

    def test_thread_safety(self):
        """线程安全测试"""
        d = LRUDict(max_size=500, thread_safe=True)
        num_threads = 10
        items_per_thread = 100

        def worker(tid):
            for i in range(items_per_thread):
                key = f"t{tid}-{i}"
                d.set(key, i)
                d.get(key)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(d) <= 500

    def test_iteration(self):
        """迭代"""
        d = LRUDict(max_size=5)
        d.set("a", 1)
        d.set("b", 2)
        d.set("c", 3)
        keys = [k for k in d]
        assert keys == ["a", "b", "c"]

    def test_contains_with_expiry(self):
        """contains 操作触发过期检查"""
        d = LRUDict(max_size=5, ttl=0.1)
        d.set("a", 1)
        assert "a" in d
        time.sleep(0.15)
        assert "a" not in d


# ──────────────────────────────────────────────────────────
# BoundedSet 测试
# ──────────────────────────────────────────────────────────

class TestBoundedSet:
    """BoundedSet 单元测试"""

    def test_basic_add(self):
        """基本添加"""
        bs = BoundedSet(max_size=5)
        bs.add(1)
        bs.add(2)
        bs.add(3)
        assert len(bs) == 3
        assert 1 in bs
        assert 2 in bs
        assert 4 not in bs

    def test_duplicate_add(self):
        """重复添加不增加数量，但刷新顺序"""
        bs = BoundedSet(max_size=3)
        bs.add(1)
        bs.add(2)
        bs.add(1)  # 重复
        assert len(bs) == 2

    def test_capacity_limit(self):
        """容量限制：FIFO 淘汰"""
        bs = BoundedSet(max_size=3)
        bs.add(1)
        bs.add(2)
        bs.add(3)
        assert bs.is_full

        evicted = bs.add(4)
        assert evicted == 1
        assert len(bs) == 3
        assert 1 not in bs
        assert 4 in bs

    def test_add_existing_refreshes_order(self):
        """添加已存在元素刷新淘汰顺序"""
        bs = BoundedSet(max_size=3)
        bs.add(1)
        bs.add(2)
        bs.add(3)

        # 重新添加 1，刷新顺序
        bs.add(1)
        # 现在顺序是 2, 3, 1
        # 添加 4 应淘汰 2
        evicted = bs.add(4)
        assert evicted == 2
        assert 1 in bs
        assert 2 not in bs

    def test_update(self):
        """批量添加"""
        bs = BoundedSet(max_size=5)
        evicted = bs.update([1, 2, 3])
        assert len(bs) == 3
        assert evicted == []

        evicted = bs.update([4, 5, 6, 7])
        assert len(bs) == 5
        assert len(evicted) == 2
        assert evicted == [1, 2]

    def test_discard(self):
        """移除元素"""
        bs = BoundedSet(max_size=5)
        bs.add(1)
        bs.add(2)
        assert bs.discard(1) is True
        assert len(bs) == 1
        assert 1 not in bs

        assert bs.discard(999) is False

    def test_clear(self):
        """清空"""
        bs = BoundedSet(max_size=5)
        bs.add(1)
        bs.add(2)
        bs.clear()
        assert len(bs) == 0
        assert bs.evicted_count == 0

    def test_evicted_count(self):
        """淘汰计数"""
        bs = BoundedSet(max_size=3)
        bs.update([1, 2, 3, 4, 5, 6])
        assert bs.evicted_count == 3

    def test_to_set(self):
        """转换为 set"""
        bs = BoundedSet(max_size=5)
        bs.update([1, 2, 3])
        s = bs.to_set()
        assert isinstance(s, set)
        assert s == {1, 2, 3}

    def test_to_list(self):
        """转换为 list（有序）"""
        bs = BoundedSet(max_size=5)
        bs.add(3)
        bs.add(1)
        bs.add(2)
        lst = bs.to_list()
        assert lst == [3, 1, 2]

    def test_on_evict_callback(self):
        """溢出回调"""
        evicted_items = []

        def on_evict(item, reason):
            evicted_items.append((item, reason))

        bs = BoundedSet(max_size=3, on_evict=on_evict)
        bs.update([1, 2, 3, 4, 5])

        assert len(evicted_items) == 2
        assert evicted_items[0] == (1, EvictionReason.CAPACITY)
        assert evicted_items[1] == (2, EvictionReason.CAPACITY)

    def test_invalid_max_size(self):
        """非法容量"""
        with pytest.raises(ValueError):
            BoundedSet(max_size=0)

    def test_resize(self):
        """调整容量"""
        bs = BoundedSet(max_size=5)
        bs.update([1, 2, 3, 4, 5])

        # 缩容
        evicted = bs.resize(3)
        assert len(evicted) == 2
        assert set(evicted) == {1, 2}
        assert bs.max_size == 3
        assert len(bs) == 3

    def test_stats(self):
        """统计信息"""
        bs = BoundedSet(max_size=10)
        bs.update([1, 2, 3])
        stats = bs.stats()
        assert stats["max_size"] == 10
        assert stats["current_size"] == 3
        assert stats["utilization"] == 0.3
        assert stats["thread_safe"] is False

    def test_iteration(self):
        """迭代"""
        bs = BoundedSet(max_size=5)
        bs.update([3, 1, 2])
        result = [x for x in bs]
        assert result == [3, 1, 2]

    def test_thread_safety(self):
        """线程安全测试"""
        bs = BoundedSet(max_size=500, thread_safe=True)
        num_threads = 10
        items_per_thread = 100

        def worker(tid):
            for i in range(items_per_thread):
                bs.add(f"t{tid}-{i}")

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(bs) <= 500

    def test_repr(self):
        """字符串表示"""
        bs = BoundedSet(max_size=5)
        bs.add(1)
        assert "BoundedSet" in repr(bs)
        assert "max_size=5" in repr(bs)

    def test_contains_does_not_refresh(self):
        """contains 不刷新 LRU 顺序（保持 set 语义）"""
        bs = BoundedSet(max_size=3)
        bs.add(1)
        bs.add(2)
        bs.add(3)

        # 用 contains 访问 1
        _ = 1 in bs
        # 添加 4，应该淘汰 1（因为 contains 没刷新顺序）
        evicted = bs.add(4)
        assert evicted == 1


# ──────────────────────────────────────────────────────────
# 集成场景测试
# ──────────────────────────────────────────────────────────

class TestIntegrationScenarios:
    """模拟实际使用场景的集成测试"""

    def test_event_store_pattern(self):
        """模拟 event_store 场景：主列表 + 索引字典"""
        max_events = 100
        events = BoundedList(max_size=max_events)
        trace_index = LRUDict[str, list[str]](max_size=50)  # 50 个 trace

        # 模拟 200 个事件，分布在 30 个 trace 中
        for i in range(200):
            trace_id = f"trace_{i % 30}"
            event_id = f"evt_{i}"
            events.append({"id": event_id, "trace_id": trace_id})

            # 更新索引
            existing = trace_index.get(trace_id, [])
            existing.append(event_id)
            trace_index.set(trace_id, existing)

        assert len(events) == 100
        assert events.is_full
        # 最后一个事件应该是最新的
        assert events.last()["id"] == "evt_199"

    def test_feedback_pattern(self):
        """模拟 feedback_loop 场景：主列表 + 按 agent 分组"""
        max_feedbacks = 50
        feedbacks = BoundedList(max_size=max_feedbacks)
        agent_feedback_count = LRUDict[str, int](max_size=20)

        # 模拟 100 条反馈，10 个 agent
        for i in range(100):
            agent_id = f"agent_{i % 10}"
            feedbacks.append({"agent_id": agent_id, "rating": i % 5})
            count = agent_feedback_count.get(agent_id, 0)
            agent_feedback_count.set(agent_id, count + 1)

        assert len(feedbacks) == 50
        assert len(agent_feedback_count) == 10  # 所有 agent 都在

    def test_cache_pattern_with_ttl(self):
        """模拟缓存场景：LRU + TTL"""
        cache = LRUDict[str, dict](max_size=100, ttl=0.2)

        # 填充缓存
        for i in range(50):
            cache.set(f"key_{i}", {"data": f"value_{i}"})

        assert len(cache) == 50

        # 访问部分 key
        for i in range(10):
            cache.get(f"key_{i}")

        # 等待过期
        time.sleep(0.25)

        # 清理过期
        expired = cache.purge_expired()
        assert len(expired) == 50
        assert len(cache) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
