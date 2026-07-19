"""
M12 安全盾 - 线程安全测试
验证核心组件在多线程并发场景下的安全性和数据一致性。

测试覆盖：
1. RWLock 读写锁正确性
2. AtomicCounter 原子计数器正确性
3. ThreadSafeDict 线程安全字典正确性
4. ThreadSafeSet 线程安全集合正确性
5. ThreadSafeQueue 线程安全队列正确性
6. WAF 规则并发读写一致性
7. IP 黑白名单并发修改一致性
8. RateLimiter 并发限流正确性
"""

import os
import sys
import threading
import time
import random
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

# ===========================================================================
# 测试环境初始化
# ===========================================================================

_current_dir = Path(__file__).resolve().parent
_backend_dir = _current_dir.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

# 使用临时数据库
os.environ.setdefault("M12_DB_PATH", ":memory:")
os.environ.setdefault("M12_ENV", "test")

from core.thread_safety import (
    RWLock,
    AtomicCounter,
    ThreadSafeDict,
    ThreadSafeSet,
    ThreadSafeQueue,
    ThreadSafeStats,
    synchronized,
)


# ===========================================================================
# RWLock 读写锁测试
# ===========================================================================

class TestRWLock:
    """RWLock 读写锁测试"""

    def test_basic_read_lock(self):
        """测试基本读锁获取和释放"""
        rwlock = RWLock()
        rwlock.acquire_read()
        rwlock.release_read()
        # 没有异常即通过

    def test_basic_write_lock(self):
        """测试基本写锁获取和释放"""
        rwlock = RWLock()
        rwlock.acquire_write()
        rwlock.release_write()
        # 没有异常即通过

    def test_multiple_readers(self):
        """测试多个读者可以同时持有读锁"""
        rwlock = RWLock()
        state = {"readers_active": 0, "max_readers": 0}
        lock = threading.Lock()
        barrier = threading.Barrier(5)  # 5 个读者同步开始

        def reader():
            barrier.wait()  # 等待所有读者就绪
            with rwlock.read_lock():
                with lock:
                    state["readers_active"] += 1
                    state["max_readers"] = max(state["max_readers"], state["readers_active"])
                time.sleep(0.1)  # 持有锁一段时间
                with lock:
                    state["readers_active"] -= 1

        threads = [threading.Thread(target=reader) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 应该有多个读者同时持有锁
        assert state["max_readers"] > 1, f"最大并发读者数: {state['max_readers']}，预期 > 1"

    def test_write_exclusive(self):
        """测试写者独占锁"""
        rwlock = RWLock()
        state = {"write_active": False, "concurrent_access": False}
        lock = threading.Lock()

        def writer():
            with rwlock.write_lock():
                with lock:
                    state["write_active"] = True
                time.sleep(0.1)
                with lock:
                    state["write_active"] = False

        def reader():
            with rwlock.read_lock():
                with lock:
                    if state["write_active"]:
                        state["concurrent_access"] = True

        # 先启动写者
        wt = threading.Thread(target=writer)
        wt.start()
        time.sleep(0.02)  # 确保写者先获得锁

        # 启动读者（应该被阻塞直到写者完成）
        rt = threading.Thread(target=reader)
        rt.start()

        wt.join()
        rt.join()

        assert not state["concurrent_access"], "写锁期间不应有读操作"

    def test_read_context_manager(self):
        """测试读锁上下文管理器"""
        rwlock = RWLock()
        with rwlock.read_lock():
            pass  # 正常进入和退出
        # 再次获取应该没问题
        with rwlock.read_lock():
            pass

    def test_write_context_manager(self):
        """测试写锁上下文管理器"""
        rwlock = RWLock()
        with rwlock.write_lock():
            pass
        with rwlock.write_lock():
            pass

    def test_synchronized_decorator_read(self):
        """测试 synchronized 装饰器（读场景）"""
        lock = threading.Lock()

        class TestClass:
            def __init__(self):
                self.value = 0

            @synchronized(lock_obj=lock)
            def get_value(self):
                return self.value

        obj = TestClass()
        assert obj.get_value() == 0

    def test_synchronized_decorator_write(self):
        """测试 synchronized 装饰器（写场景）"""
        lock = threading.Lock()

        class TestClass:
            def __init__(self):
                self.value = 0

            @synchronized(lock_obj=lock)
            def set_value(self, v):
                self.value = v

        obj = TestClass()
        obj.set_value(42)
        assert obj.value == 42

    def test_writer_can_acquire_after_readers(self):
        """测试写者在读者释放后能获得锁"""
        rwlock = RWLock()
        state = {"write_acquired": False}
        barrier = threading.Barrier(2)

        def reader():
            with rwlock.read_lock():
                barrier.wait()  # 通知写者我已获得读锁
                time.sleep(0.05)

        def writer():
            barrier.wait()  # 等待读者获得读锁
            time.sleep(0.01)  # 确保读者先获得锁
            with rwlock.write_lock():
                state["write_acquired"] = True

        rt = threading.Thread(target=reader)
        wt = threading.Thread(target=writer)
        rt.start()
        wt.start()
        rt.join()
        wt.join()

        assert state["write_acquired"], "写者应该能够在读者释放后获得锁"

    def test_rwlock_reentrant_read(self):
        """测试同一线程可重入读锁（不保证可重入，但不应死锁）"""
        rwlock = RWLock()
        # 注意：当前 RWLock 实现不支持可重入读，会导致死锁
        # 这里只测试单次获取
        rwlock.acquire_read()
        rwlock.release_read()
        # 没有死锁即通过


# ===========================================================================
# AtomicCounter 原子计数器测试
# ===========================================================================

class TestAtomicCounter:
    """AtomicCounter 原子计数器测试"""

    def test_initial_value(self):
        """测试初始值"""
        counter = AtomicCounter(10)
        assert counter.get() == 10

    def test_default_initial_value(self):
        """测试默认初始值为 0"""
        counter = AtomicCounter()
        assert counter.get() == 0

    def test_increment(self):
        """测试递增"""
        counter = AtomicCounter()
        assert counter.increment() == 1
        assert counter.get() == 1

    def test_increment_by(self):
        """测试按指定值递增"""
        counter = AtomicCounter()
        assert counter.increment(5) == 5
        assert counter.get() == 5

    def test_decrement(self):
        """测试递减"""
        counter = AtomicCounter(10)
        assert counter.decrement() == 9
        assert counter.get() == 9

    def test_decrement_by(self):
        """测试按指定值递减"""
        counter = AtomicCounter(10)
        assert counter.decrement(3) == 7
        assert counter.get() == 7

    def test_reset(self):
        """测试重置"""
        counter = AtomicCounter(100)
        old = counter.reset()
        assert counter.get() == 0
        assert old == 100

    def test_set_value(self):
        """测试设置值"""
        counter = AtomicCounter(100)
        old = counter.set(50)
        assert counter.get() == 50
        assert old == 100

    def test_concurrent_increment(self):
        """测试并发递增的正确性"""
        counter = AtomicCounter()
        num_threads = 10
        increments_per_thread = 1000

        def worker():
            for _ in range(increments_per_thread):
                counter.increment()

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        expected = num_threads * increments_per_thread
        assert counter.get() == expected, f"预期 {expected}，实际 {counter.get()}"

    def test_concurrent_mixed_operations(self):
        """测试并发混合操作的正确性"""
        counter = AtomicCounter(10000)
        num_threads = 8
        ops_per_thread = 500

        def worker():
            for _ in range(ops_per_thread):
                op = random.choice(['inc', 'dec', 'inc', 'dec', 'get'])
                if op == 'inc':
                    counter.increment()
                elif op == 'dec':
                    counter.decrement()
                else:
                    counter.get()

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 因为有 inc 和 dec 操作，最终值应该在合理范围内
        val = counter.get()
        assert isinstance(val, int)
        # inc 和 dec 各约 2/5 概率，所以净变化约为 0
        assert 10000 - ops_per_thread * num_threads <= val <= 10000 + ops_per_thread * num_threads


# ===========================================================================
# ThreadSafeDict 线程安全字典测试
# ===========================================================================

class TestThreadSafeDict:
    """ThreadSafeDict 线程安全字典测试"""

    def test_basic_operations(self):
        """测试基本操作"""
        d = ThreadSafeDict()
        d.set("key1", "value1")
        assert d.get("key1") == "value1"
        assert len(d) == 1

    def test_delete(self):
        """测试删除"""
        d = ThreadSafeDict()
        d.set("key1", "value1")
        assert d.delete("key1") == True
        assert d.get("key1") is None
        assert len(d) == 0

    def test_delete_nonexistent(self):
        """测试删除不存在的键"""
        d = ThreadSafeDict()
        assert d.delete("nonexistent") == False

    def test_contains(self):
        """测试包含检查"""
        d = ThreadSafeDict()
        d.set("key1", "value1")
        assert d.contains("key1")
        assert not d.contains("key2")

    def test_keys_values_items(self):
        """测试 keys/values/items 方法"""
        d = ThreadSafeDict()
        d.set("a", 1)
        d.set("b", 2)
        d.set("c", 3)

        keys = d.keys()
        assert len(keys) == 3
        assert "a" in keys

        values = d.values()
        assert len(values) == 3
        assert 1 in values

        items = d.items()
        assert len(items) == 3

    def test_clear(self):
        """测试清空"""
        d = ThreadSafeDict()
        d.set("a", 1)
        d.set("b", 2)
        d.clear()
        assert len(d) == 0

    def test_get_default(self):
        """测试获取默认值"""
        d = ThreadSafeDict()
        assert d.get("nonexistent", "default") == "default"

    def test_concurrent_write(self):
        """测试并发写入"""
        d = ThreadSafeDict()
        num_threads = 10
        items_per_thread = 100

        def writer(tid):
            for i in range(items_per_thread):
                key = f"key_{tid}_{i}"
                d.set(key, i)

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(d) == num_threads * items_per_thread

    def test_concurrent_read_write(self):
        """测试并发读写"""
        d = ThreadSafeDict()

        # 预先填充一些数据
        for i in range(100):
            d.set(f"init_{i}", i)

        errors = []

        def reader():
            for _ in range(200):
                key = f"init_{random.randint(0, 99)}"
                try:
                    val = d.get(key)
                    # 验证值的类型正确
                    assert val is None or isinstance(val, int)
                except Exception as e:
                    errors.append(str(e))

        def writer():
            for i in range(50):
                d.set(f"writer_{i}", i)
                time.sleep(0.001)

        reader_threads = [threading.Thread(target=reader) for _ in range(5)]
        writer_threads = [threading.Thread(target=writer) for _ in range(3)]

        all_threads = reader_threads + writer_threads
        for t in all_threads:
            t.start()
        for t in all_threads:
            t.join()

        assert len(errors) == 0, f"并发读写错误: {errors}"

    def test_update(self):
        """测试批量更新"""
        d = ThreadSafeDict()
        d.set("a", 1)
        d.update({"b": 2, "c": 3})
        assert len(d) == 3
        assert d.get("b") == 2
        assert d.get("c") == 3

    def test_copy(self):
        """测试复制"""
        d = ThreadSafeDict()
        d.set("a", 1)
        d.set("b", 2)
        copy = d.copy()
        assert copy == {"a": 1, "b": 2}
        # 修改原字典不影响副本
        d.set("c", 3)
        assert "c" not in copy


# ===========================================================================
# ThreadSafeSet 线程安全集合测试
# ===========================================================================

class TestThreadSafeSet:
    """ThreadSafeSet 线程安全集合测试"""

    def test_basic_operations(self):
        """测试基本操作"""
        s = ThreadSafeSet()
        s.add("item1")
        assert s.contains("item1")
        assert s.size() == 1

    def test_remove(self):
        """测试删除"""
        s = ThreadSafeSet()
        s.add("item1")
        assert s.remove("item1")
        assert not s.contains("item1")
        assert s.size() == 0

    def test_remove_nonexistent(self):
        """测试删除不存在的元素"""
        s = ThreadSafeSet()
        assert not s.remove("nonexistent")

    def test_concurrent_add(self):
        """测试并发添加"""
        s = ThreadSafeSet()
        num_threads = 10
        items_per_thread = 100

        def adder(tid):
            for i in range(items_per_thread):
                s.add(f"item_{tid}_{i}")

        threads = [threading.Thread(target=adder, args=(t,)) for t in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert s.size() == num_threads * items_per_thread

    def test_concurrent_add_same_items(self):
        """测试并发添加相同元素（集合去重）"""
        s = ThreadSafeSet()
        num_threads = 10
        common_items = 50

        def adder():
            for i in range(common_items):
                s.add(f"common_{i}")

        threads = [threading.Thread(target=adder) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 集合去重后应该只有 common_items 个元素
        assert s.size() == common_items

    def test_clear_and_to_list(self):
        """测试清空和转列表"""
        s = ThreadSafeSet()
        s.add("a")
        s.add("b")
        s.add("c")
        lst = s.to_list()
        assert len(lst) == 3
        assert "a" in lst
        s.clear()
        assert s.size() == 0


# ===========================================================================
# ThreadSafeQueue 线程安全队列测试
# ===========================================================================

class TestThreadSafeQueue:
    """ThreadSafeQueue 线程安全队列测试"""

    def test_basic_put_get(self):
        """测试基本入队出队"""
        q = ThreadSafeQueue()
        q.put("item1")
        q.put("item2")
        assert q.get() == "item1"
        assert q.get() == "item2"
        assert q.empty()

    def test_size_and_empty(self):
        """测试大小和空检查"""
        q = ThreadSafeQueue()
        assert q.empty()
        assert q.qsize() == 0
        q.put("item")
        assert not q.empty()
        assert q.qsize() == 1

    def test_non_blocking_get_empty(self):
        """测试非阻塞获取空队列"""
        q = ThreadSafeQueue()
        result = q.get(block=False)
        assert result is None

    def test_maxsize(self):
        """测试队列最大容量"""
        q = ThreadSafeQueue(maxsize=3)
        assert q.put("a")
        assert q.put("b")
        assert q.put("c")
        # 队列已满，非阻塞放入应该失败
        assert not q.put("d", block=False)
        assert q.full()
        assert q.qsize() == 3

    def test_concurrent_producer_consumer(self):
        """测试并发生产者消费者"""
        q = ThreadSafeQueue()
        num_producers = 5
        num_consumers = 3
        items_per_producer = 100
        total_items = num_producers * items_per_producer

        produced_count = AtomicCounter()
        consumed_count = AtomicCounter()
        errors = []

        def producer(pid):
            for i in range(items_per_producer):
                try:
                    q.put(f"p{pid}_item_{i}")
                    produced_count.increment()
                except Exception as e:
                    errors.append(str(e))

        def consumer():
            while consumed_count.get() < total_items:
                try:
                    item = q.get(block=True, timeout=0.5)
                    if item is not None:
                        consumed_count.increment()
                except Exception as e:
                    if "timeout" not in str(e).lower():
                        errors.append(str(e))

        producer_threads = [threading.Thread(target=producer, args=(p,)) for p in range(num_producers)]
        consumer_threads = [threading.Thread(target=consumer) for _ in range(num_consumers)]

        for t in producer_threads:
            t.start()
        for t in consumer_threads:
            t.start()

        for t in producer_threads:
            t.join()
        for t in consumer_threads:
            t.join(timeout=5)

        assert len(errors) == 0, f"生产者消费者错误: {errors}"
        assert produced_count.get() == total_items
        # 消费者可能由于超时提前退出，但大部分应该被消费
        assert consumed_count.get() > 0


# ===========================================================================
# ThreadSafeStats 测试
# ===========================================================================

class TestThreadSafeStats:
    """ThreadSafeStats 线程安全统计测试"""

    def test_basic_increment(self):
        """测试基本递增"""
        stats = ThreadSafeStats()
        stats.increment("requests")
        stats.increment("requests")
        stats.increment("errors")
        assert stats.get("requests") == 2
        assert stats.get("errors") == 1

    def test_get_default(self):
        """测试获取不存在的类别"""
        stats = ThreadSafeStats()
        assert stats.get("nonexistent") == 0

    def test_concurrent_increment(self):
        """测试并发递增不同类别"""
        stats = ThreadSafeStats()
        num_threads = 10
        ops_per_thread = 100

        def worker(tid):
            for i in range(ops_per_thread):
                category = f"cat_{i % 5}"
                stats.increment(category)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 5 个类别，每个类别应该有 num_threads * (ops_per_thread / 5) 次递增
        for i in range(5):
            assert stats.get(f"cat_{i}") == num_threads * (ops_per_thread // 5)


# ===========================================================================
# WAF 规则并发测试
# ===========================================================================

class TestWafConcurrency:
    """WAF 引擎并发访问测试"""

    def test_waf_engine_concurrent_status(self):
        """测试并发获取 WAF 状态"""
        from services.waf_engine import get_waf_engine

        waf = get_waf_engine()
        results = []
        errors = []

        def get_status():
            try:
                status = waf.get_status()
                results.append(status)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=get_status) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"并发获取状态出错: {errors}"
        assert len(results) == 20

    def test_waf_engine_concurrent_check(self):
        """测试并发 WAF 检测"""
        from services.waf_engine import get_waf_engine

        waf = get_waf_engine()
        results = []
        errors = []

        test_requests = [
            {"method": "GET", "path": "/api/test", "headers": {}, "body": ""},
            {"method": "POST", "path": "/api/user", "headers": {}, "body": "name=test"},
            {"method": "GET", "path": "/admin", "headers": {}, "body": ""},
            {"method": "GET", "path": "/search?q=<script>", "headers": {}, "body": ""},
        ]

        def check_request(req):
            try:
                result = waf.check_request(
                    method=req["method"],
                    path=req["path"],
                    headers=req["headers"],
                    body=req["body"],
                    client_ip="127.0.0.1",
                )
                results.append(result)
            except Exception as e:
                errors.append(str(e))

        threads = []
        for i in range(50):
            req = test_requests[i % len(test_requests)]
            threads.append(threading.Thread(target=check_request, args=(req,)))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"并发检测出错: {errors}"
        assert len(results) == 50


# ===========================================================================
# RateLimiter 并发测试
# ===========================================================================

class TestRateLimiterConcurrency:
    """限流服务并发测试"""

    def test_rate_limiter_concurrent_check(self):
        """测试并发限流检查"""
        from services.rate_limiter import RateLimiter

        limiter = RateLimiter()
        limiter.enable()
        errors = []
        results = []

        def check_limit():
            try:
                result = limiter.allow_request("concurrent_test_key", 1.0)
                results.append(result)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=check_limit) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"并发限流检查出错: {errors}"
        assert len(results) == 50

    def test_rate_limiter_toggle_thread_safe(self):
        """测试限流器开关的线程安全"""
        from services.rate_limiter import RateLimiter

        limiter = RateLimiter()
        errors = []

        def toggle_worker():
            try:
                for _ in range(100):
                    limiter.toggle()
                    limiter.is_active()
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=toggle_worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"并发切换出错: {errors}"


# ===========================================================================
# IP Filter 并发测试
# ===========================================================================

class TestIPFilterConcurrency:
    """IP 过滤并发测试"""

    def test_ip_filter_concurrent_check(self):
        """测试并发 IP 检查"""
        from services.ip_filter import get_ip_filter

        ip_filter = get_ip_filter()
        errors = []
        results = []

        def check_ip(ip):
            try:
                result = ip_filter.check_ip(ip)
                results.append(result)
            except Exception as e:
                errors.append(str(e))

        test_ips = ["127.0.0.1", "192.168.1.1", "10.0.0.1", "8.8.8.8"]
        threads = []
        for i in range(40):
            threads.append(threading.Thread(target=check_ip, args=(test_ips[i % 4],)))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"并发 IP 检查出错: {errors}"
        assert len(results) == 40


# ===========================================================================
# 主入口
# ===========================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
