"""
云汐 M12 安全盾 - 线程安全管理模块

统一管理全局锁对象、原子计数器和并发安全工具，
确保核心数据结构在多线程环境下的安全访问。

设计原则：
1. 优先使用读写锁（多读少写场景）
2. 统计计数优先用原子操作或 Lock
3. 不要过度加锁，只保护共享状态
4. 锁的粒度要适中，避免死锁
"""

import threading
import logging
from typing import Any, Optional, Callable
from collections import defaultdict, deque
from contextlib import contextmanager
from functools import wraps

logger = logging.getLogger(__name__)


# ===========================================================================
# 读写锁实现（多读少写场景优化）
# ===========================================================================

class RWLock:
    """读写锁

    支持多个读者同时持有读锁，写者独占写锁。
    适用于读多写少的场景，比普通 Lock 有更好的并发性能。

    写优先策略：当有写者等待时，新的读者需要等待，避免写者饥饿。
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._read_ready = threading.Condition(self._lock)
        self._readers = 0
        self._writers_waiting = 0
        self._writer_active = False

    def acquire_read(self) -> None:
        """获取读锁"""
        with self._lock:
            while self._writer_active or self._writers_waiting > 0:
                self._read_ready.wait()
            self._readers += 1

    def release_read(self) -> None:
        """释放读锁"""
        with self._lock:
            self._readers -= 1
            if self._readers == 0:
                self._read_ready.notify_all()

    def acquire_write(self) -> None:
        """获取写锁"""
        with self._lock:
            self._writers_waiting += 1
            while self._readers > 0 or self._writer_active:
                self._read_ready.wait()
            self._writers_waiting -= 1
            self._writer_active = True

    def release_write(self) -> None:
        """释放写锁"""
        with self._lock:
            self._writer_active = False
            self._read_ready.notify_all()

    @contextmanager
    def read_lock(self):
        """读锁上下文管理器"""
        self.acquire_read()
        try:
            yield
        finally:
            self.release_read()

    @contextmanager
    def write_lock(self):
        """写锁上下文管理器"""
        self.acquire_write()
        try:
            yield
        finally:
            self.release_write()


# ===========================================================================
# 原子计数器
# ===========================================================================

class AtomicCounter:
    """线程安全的原子计数器

    支持递增、递减、获取当前值等操作，使用 Lock 保证原子性。
    """

    def __init__(self, initial: int = 0):
        self._value = initial
        self._lock = threading.Lock()

    def increment(self, delta: int = 1) -> int:
        """递增计数器

        Args:
            delta: 增量，默认为 1

        Returns:
            递增后的值
        """
        with self._lock:
            self._value += delta
            return self._value

    def decrement(self, delta: int = 1) -> int:
        """递减计数器

        Args:
            delta: 减量，默认为 1

        Returns:
            递减后的值
        """
        with self._lock:
            self._value -= delta
            return self._value

    def get(self) -> int:
        """获取当前值"""
        with self._lock:
            return self._value

    def set(self, value: int) -> int:
        """设置新值

        Args:
            value: 新值

        Returns:
            旧值
        """
        with self._lock:
            old = self._value
            self._value = value
            return old

    def reset(self) -> int:
        """重置为 0，返回旧值"""
        return self.set(0)


# ===========================================================================
# 线程安全的字典
# ===========================================================================

class ThreadSafeDict:
    """线程安全的字典

    使用读写锁保护字典操作，读操作并发、写操作互斥。
    适用于读多写少的共享字典场景。
    """

    def __init__(self):
        self._data: dict = {}
        self._lock = RWLock()

    def get(self, key: Any, default: Any = None) -> Any:
        with self._lock.read_lock():
            return self._data.get(key, default)

    def set(self, key: Any, value: Any) -> None:
        with self._lock.write_lock():
            self._data[key] = value

    def delete(self, key: Any) -> bool:
        with self._lock.write_lock():
            if key in self._data:
                del self._data[key]
                return True
            return False

    def contains(self, key: Any) -> bool:
        with self._lock.read_lock():
            return key in self._data

    def keys(self) -> list:
        with self._lock.read_lock():
            return list(self._data.keys())

    def values(self) -> list:
        with self._lock.read_lock():
            return list(self._data.values())

    def items(self) -> list:
        with self._lock.read_lock():
            return list(self._data.items())

    def __len__(self) -> int:
        with self._lock.read_lock():
            return len(self._data)

    def __getitem__(self, key: Any) -> Any:
        with self._lock.read_lock():
            return self._data[key]

    def __setitem__(self, key: Any, value: Any) -> None:
        self.set(key, value)

    def __delitem__(self, key: Any) -> None:
        self.delete(key)

    def __contains__(self, key: Any) -> bool:
        return self.contains(key)

    def copy(self) -> dict:
        """获取字典的副本"""
        with self._lock.read_lock():
            return dict(self._data)

    def update(self, other: dict) -> None:
        """批量更新"""
        with self._lock.write_lock():
            self._data.update(other)

    def clear(self) -> None:
        """清空字典"""
        with self._lock.write_lock():
            self._data.clear()


# ===========================================================================
# 线程安全的集合
# ===========================================================================

class ThreadSafeSet:
    """线程安全的集合

    使用读写锁保护，适用于读多写少的场景。
    """

    def __init__(self):
        self._set: set = set()
        self._lock = RWLock()

    def add(self, item) -> None:
        """添加元素"""
        with self._lock.write_lock():
            self._set.add(item)

    def remove(self, item) -> bool:
        """移除元素

        Returns:
            True 表示元素存在并被移除，False 表示元素不存在
        """
        with self._lock.write_lock():
            if item in self._set:
                self._set.remove(item)
                return True
            return False

    def contains(self, item) -> bool:
        """检查元素是否存在"""
        with self._lock.read_lock():
            return item in self._set

    def size(self) -> int:
        """获取集合大小"""
        with self._lock.read_lock():
            return len(self._set)

    def clear(self) -> None:
        """清空集合"""
        with self._lock.write_lock():
            self._set.clear()

    def to_list(self) -> list:
        """转换为列表（快照）"""
        with self._lock.read_lock():
            return list(self._set)

    @contextmanager
    def locked(self):
        """获取写锁的上下文管理器（用于批量操作）"""
        with self._lock.write_lock():
            yield self._set


# ===========================================================================
# 线程安全的队列
# ===========================================================================

class ThreadSafeQueue:
    """线程安全的队列

    基于 collections.deque 和 Lock 实现，支持阻塞和非阻塞操作。
    """

    def __init__(self, maxsize: int = 0):
        self._queue: deque = deque()
        self._lock = threading.Lock()
        self._not_empty = threading.Condition(self._lock)
        self._maxsize = maxsize

    def put(self, item, block: bool = True, timeout: Optional[float] = None) -> bool:
        """放入元素

        Args:
            item: 要放入的元素
            block: 是否阻塞等待
            timeout: 超时时间（秒）

        Returns:
            True 表示成功放入，False 表示队列已满
        """
        with self._not_empty:
            if self._maxsize > 0 and len(self._queue) >= self._maxsize:
                if not block:
                    return False
                if not self._not_empty.wait_for(
                    lambda: len(self._queue) < self._maxsize,
                    timeout=timeout,
                ):
                    return False
            self._queue.append(item)
            self._not_empty.notify()
            return True

    def get(self, block: bool = True, timeout: Optional[float] = None) -> Optional[Any]:
        """取出元素

        Args:
            block: 是否阻塞等待
            timeout: 超时时间（秒）

        Returns:
            取出的元素，队列为空时返回 None
        """
        with self._not_empty:
            if not self._queue:
                if not block:
                    return None
                if not self._not_empty.wait_for(
                    lambda: len(self._queue) > 0,
                    timeout=timeout,
                ):
                    return None
            item = self._queue.popleft()
            self._not_empty.notify()
            return item

    def qsize(self) -> int:
        """获取队列大小"""
        with self._lock:
            return len(self._queue)

    def empty(self) -> bool:
        """检查队列是否为空"""
        with self._lock:
            return len(self._queue) == 0

    def full(self) -> bool:
        """检查队列是否已满"""
        with self._lock:
            return self._maxsize > 0 and len(self._queue) >= self._maxsize

    def clear(self) -> None:
        """清空队列"""
        with self._lock:
            self._queue.clear()

    def get_all(self) -> list:
        """获取所有元素并清空队列"""
        with self._lock:
            items = list(self._queue)
            self._queue.clear()
            return items


# ===========================================================================
# 线程安全的统计计数器（按类别统计）
# ===========================================================================

class ThreadSafeStats:
    """线程安全的统计计数器

    支持按类别统计，使用读写锁保护。
    适用于多维度统计计数场景。
    """

    def __init__(self):
        self._counters: defaultdict = defaultdict(int)
        self._lock = RWLock()

    def increment(self, key: str, delta: int = 1) -> int:
        """递增指定类别的计数

        Args:
            key: 类别键名
            delta: 增量

        Returns:
            递增后的值
        """
        with self._lock.write_lock():
            self._counters[key] += delta
            return self._counters[key]

    def get(self, key: str) -> int:
        """获取指定类别的计数"""
        with self._lock.read_lock():
            return self._counters.get(key, 0)

    def get_all(self) -> dict:
        """获取所有统计数据的副本"""
        with self._lock.read_lock():
            return dict(self._counters)

    def reset(self, key: Optional[str] = None) -> None:
        """重置计数

        Args:
            key: 指定类别，None 表示重置所有
        """
        with self._lock.write_lock():
            if key is None:
                self._counters.clear()
            else:
                self._counters[key] = 0

    def items(self) -> list:
        with self._lock.read_lock():
            return list(self._counters.items())

    def top_n(self, n: int = 10) -> list:
        """获取计数最高的前 N 项

        Args:
            n: 返回数量

        Returns:
            [(key, count), ...] 按计数降序排列
        """
        with self._lock.read_lock():
            sorted_items = sorted(
                self._counters.items(),
                key=lambda x: x[1],
                reverse=True
            )
            return sorted_items[:n]


# ===========================================================================
# 全局锁注册表（统一管理）
# ===========================================================================

class LockRegistry:
    """全局锁注册表

    集中管理所有模块的锁对象，方便统一监控和调试。
    每个模块通过注册获取自己的锁，避免分散创建。
    """

    def __init__(self):
        self._locks: dict = {}
        self._rw_locks: dict = {}
        self._counters: dict = {}
        self._stats: dict = {}
        self._registry_lock = threading.Lock()

    def get_lock(self, name: str) -> threading.Lock:
        """获取或创建一个普通锁

        Args:
            name: 锁名称（唯一标识）

        Returns:
            threading.Lock 实例
        """
        with self._registry_lock:
            if name not in self._locks:
                self._locks[name] = threading.Lock()
                logger.debug("创建锁: %s", name)
            return self._locks[name]

    def get_rw_lock(self, name: str) -> RWLock:
        """获取或创建一个读写锁

        Args:
            name: 锁名称（唯一标识）

        Returns:
            RWLock 实例
        """
        with self._registry_lock:
            if name not in self._rw_locks:
                self._rw_locks[name] = RWLock()
                logger.debug("创建读写锁: %s", name)
            return self._rw_locks[name]

    def get_counter(self, name: str, initial: int = 0) -> AtomicCounter:
        """获取或创建一个原子计数器

        Args:
            name: 计数器名称
            initial: 初始值

        Returns:
            AtomicCounter 实例
        """
        with self._registry_lock:
            if name not in self._counters:
                self._counters[name] = AtomicCounter(initial)
                logger.debug("创建原子计数器: %s", name)
            return self._counters[name]

    def get_stats(self, name: str) -> ThreadSafeStats:
        """获取或创建一个统计计数器

        Args:
            name: 统计名称

        Returns:
            ThreadSafeStats 实例
        """
        with self._registry_lock:
            if name not in self._stats:
                self._stats[name] = ThreadSafeStats()
                logger.debug("创建统计计数器: %s", name)
            return self._stats[name]

    def get_lock_info(self) -> dict:
        """获取锁注册表状态信息（用于调试）"""
        with self._registry_lock:
            return {
                "locks_count": len(self._locks),
                "rw_locks_count": len(self._rw_locks),
                "counters_count": len(self._counters),
                "stats_count": len(self._stats),
                "locks": list(self._locks.keys()),
                "rw_locks": list(self._rw_locks.keys()),
                "counters": list(self._counters.keys()),
                "stats": list(self._stats.keys()),
            }


# 全局锁注册表单例
_lock_registry = LockRegistry()


def get_lock_registry() -> LockRegistry:
    """获取全局锁注册表单例"""
    return _lock_registry


# ===========================================================================
# 便捷函数：常用锁直接获取
# ===========================================================================

def get_waf_rules_lock() -> RWLock:
    """获取 WAF 规则的读写锁"""
    return _lock_registry.get_rw_lock("waf_rules")


def get_ip_blacklist_lock() -> RWLock:
    """获取 IP 黑名单的读写锁"""
    return _lock_registry.get_rw_lock("ip_blacklist")


def get_ip_whitelist_lock() -> RWLock:
    """获取 IP 白名单的读写锁"""
    return _lock_registry.get_rw_lock("ip_whitelist")


def get_audit_log_lock() -> threading.Lock:
    """获取审计日志写入锁"""
    return _lock_registry.get_lock("audit_log")


def get_security_event_lock() -> threading.Lock:
    """获取安全事件写入锁"""
    return _lock_registry.get_lock("security_event")


def get_waf_stats_counter() -> ThreadSafeStats:
    """获取 WAF 统计计数器"""
    return _lock_registry.get_stats("waf_stats")


def get_audit_stats_counter() -> ThreadSafeStats:
    """获取审计统计计数器"""
    return _lock_registry.get_stats("audit_stats")


# ===========================================================================
# 线程安全装饰器
# ===========================================================================

def synchronized(lock_name: Optional[str] = None, lock_obj: Optional[threading.Lock] = None):
    """方法级同步装饰器

    确保被装饰的方法在执行时持有指定的锁。

    Args:
        lock_name: 锁名称（从注册表获取）
        lock_obj: 直接传入锁对象（优先级高于 lock_name）

    Usage:
        @synchronized(lock_name="my_lock")
        def my_method(self):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            lock = lock_obj
            if lock is None and lock_name:
                lock = _lock_registry.get_lock(lock_name)
            if lock is None:
                # 没有指定锁，直接执行
                return func(*args, **kwargs)
            with lock:
                return func(*args, **kwargs)
        return wrapper
    return decorator


# ===========================================================================
# 线程安全的单例基类
# ===========================================================================

class ThreadSafeSingleton:
    """线程安全的单例基类

    使用双重检查锁定模式确保单例的线程安全。

    Usage:
        class MyService(ThreadSafeSingleton):
            def __init__(self):
                # 只在首次实例化时执行
                ...

        service = MyService.get_instance()
    """
    _instance = None
    _instance_lock = threading.Lock()

    @classmethod
    def get_instance(cls):
        """获取单例实例"""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls):
        """重置单例（主要用于测试）"""
        with cls._instance_lock:
            cls._instance = None


# ===========================================================================
# 有界队列（线程安全，用于日志/事件缓冲）
# ===========================================================================

class BoundedQueue:
    """线程安全的有界队列

    使用 deque + Lock 实现，支持有界缓冲，自动淘汰最旧元素。
    适用于日志缓冲、事件记录等场景。
    """

    def __init__(self, maxsize: int = 10000):
        from collections import deque
        self._maxsize = maxsize
        self._queue: deque = deque(maxlen=maxsize)
        self._lock = threading.Lock()
        self._dropped_count = 0

    def put(self, item: Any) -> bool:
        """添加元素

        Args:
            item: 要添加的元素

        Returns:
            True 表示添加成功，False 表示队列满但被自动淘汰了旧元素
        """
        with self._lock:
            was_full = len(self._queue) >= self._maxsize
            if was_full:
                self._dropped_count += 1
            self._queue.append(item)
            return not was_full

    def get_all(self) -> list:
        """获取所有元素（不删除）"""
        with self._lock:
            return list(self._queue)

    def clear(self) -> int:
        """清空队列，返回被清空的元素数量"""
        with self._lock:
            count = len(self._queue)
            self._queue.clear()
            return count

    def __len__(self) -> int:
        with self._lock:
            return len(self._queue)

    @property
    def maxsize(self) -> int:
        return self._maxsize

    @property
    def dropped_count(self) -> int:
        with self._lock:
            return self._dropped_count


# ===========================================================================
# 直接运行测试
# ===========================================================================

if __name__ == "__main__":
    import time

    logging.basicConfig(level=logging.INFO)

    print("=== RWLock 测试 ===")
    rw_lock = RWLock()

    # 读锁可重入测试
    with rw_lock.read_lock():
        print("  获取读锁成功")
        with rw_lock.read_lock():
            print("  嵌套读锁成功")
    print("  读锁释放成功")

    # 写锁测试
    with rw_lock.write_lock():
        print("  获取写锁成功")
    print("  写锁释放成功")

    print("\n=== AtomicCounter 测试 ===")
    counter = AtomicCounter(0)
    counter.increment()
    counter.increment(5)
    print(f"  计数: {counter.get()} (预期 6)")
    counter.decrement(2)
    print(f"  递减后: {counter.get()} (预期 4)")

    print("\n=== ThreadSafeDict 测试 ===")
    ts_dict = ThreadSafeDict()
    ts_dict["a"] = 1
    ts_dict["b"] = 2
    print(f"  a = {ts_dict['a']}")
    print(f"  b 在字典中: {'b' in ts_dict}")
    print(f"  长度: {len(ts_dict)}")
    del ts_dict["a"]
    print(f"  删除后长度: {len(ts_dict)}")

    print("\n=== ThreadSafeStats 测试 ===")
    stats = ThreadSafeStats()
    stats.increment("sql_injection")
    stats.increment("sql_injection")
    stats.increment("xss", 3)
    print(f"  sql_injection: {stats.get('sql_injection')}")
    print(f"  Top 2: {stats.top_n(2)}")

    print("\n=== LockRegistry 测试 ===")
    registry = get_lock_registry()
    lock1 = registry.get_lock("test_lock")
    lock2 = registry.get_lock("test_lock")
    print(f"  同一锁对象: {lock1 is lock2}")
    print(f"  注册信息: {registry.get_lock_info()['locks_count']} 个锁")

    print("\n=== BoundedQueue 测试 ===")
    queue = BoundedQueue(maxsize=5)
    for i in range(7):
        queue.put(i)
    print(f"  队列长度: {len(queue)} (预期 5)")
    print(f"  丢弃数量: {queue.dropped_count} (预期 2)")

    print("\n所有测试通过!")
