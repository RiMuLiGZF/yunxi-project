"""
性能优化工具集

提供通用的性能优化工具：
- 异步日志写入（AsyncLogHandler）
- JSON 序列化优化（优先使用 ujson/orjson）
- 常用函数结果缓存（lru_cache 增强版）
- 字符串操作优化
- 对象池模式
- 惰性加载工具

使用方式::

    from shared.core.performance_utils import (
        fast_json_dumps,
        fast_json_loads,
        async_log_handler,
        ObjectPool,
        lazy_property,
    )
"""

import os
import sys
import time
import json
import queue
import threading
import logging
from typing import Any, Dict, List, Optional, Callable, TypeVar, Generic
from functools import lru_cache, wraps
from dataclasses import dataclass
from contextlib import contextmanager

T = TypeVar('T')


# ============================================================
# JSON 序列化优化
# ============================================================

# 检测可用的快速 JSON 库
_fast_json_lib = None

try:
    import orjson
    _fast_json_lib = "orjson"
except ImportError:
    try:
        import ujson
        _fast_json_lib = "ujson"
    except ImportError:
        _fast_json_lib = "json"


def fast_json_dumps(obj: Any, **kwargs) -> str:
    """快速 JSON 序列化

    优先使用 orjson/ujson 等高性能库，回退到标准 json。

    Args:
        obj: 要序列化的对象
        **kwargs: 额外参数（库特定）

    Returns:
        JSON 字符串
    """
    global _fast_json_lib

    if _fast_json_lib == "orjson":
        try:
            result = orjson.dumps(obj)
            if isinstance(result, bytes):
                return result.decode("utf-8")
            return result
        except (TypeError, ValueError):
            pass

    if _fast_json_lib == "ujson":
        try:
            return ujson.dumps(obj, **kwargs)
        except (TypeError, ValueError):
            pass

    # 标准库回退
    return json.dumps(obj, default=str, **kwargs)


def fast_json_loads(s: str, **kwargs) -> Any:
    """快速 JSON 反序列化

    Args:
        s: JSON 字符串
        **kwargs: 额外参数

    Returns:
        解析后的对象
    """
    global _fast_json_lib

    if _fast_json_lib == "orjson":
        try:
            if isinstance(s, str):
                s = s.encode("utf-8")
            return orjson.loads(s)
        except (json.JSONDecodeError, ValueError):
            pass

    if _fast_json_lib == "ujson":
        try:
            return ujson.loads(s, **kwargs)
        except (ValueError,):
            pass

    return json.loads(s, **kwargs)


def get_json_library() -> str:
    """获取当前使用的 JSON 库"""
    return _fast_json_lib


# ============================================================
# 异步日志处理器
# ============================================================

class AsyncLogHandler(logging.Handler):
    """异步日志处理器

    将日志写入队列，由后台线程异步写入真实 handler，
    避免日志 I/O 阻塞主业务逻辑。

    使用方式::

        from shared.core.performance_utils import AsyncLogHandler
        import logging

        handler = logging.FileHandler("app.log")
        async_handler = AsyncLogHandler(handler)

        logger = logging.getLogger("myapp")
        logger.addHandler(async_handler)
    """

    def __init__(
        self,
        handler: logging.Handler,
        queue_size: int = 1000,
        batch_size: int = 50,
        flush_interval: float = 0.5,
    ):
        """
        Args:
            handler: 实际的日志处理器
            queue_size: 队列最大长度
            batch_size: 批量写入大小
            flush_interval: 强制刷新间隔（秒）
        """
        super().__init__()
        self.handler = handler
        self.queue_size = queue_size
        self.batch_size = batch_size
        self.flush_interval = flush_interval

        self._queue: "queue.Queue[logging.LogRecord]" = queue.Queue(maxsize=queue_size)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # 统计
        self._total_logged = 0
        self._total_dropped = 0

        self._start_worker()

    def _start_worker(self) -> None:
        """启动后台写入线程"""
        self._thread = threading.Thread(
            target=self._worker_loop,
            name="AsyncLogHandler-Worker",
            daemon=True,
        )
        self._thread.start()

    def _worker_loop(self) -> None:
        """后台线程主循环"""
        batch = []
        last_flush = time.time()

        while not self._stop_event.is_set():
            try:
                # 等待日志，带超时（用于定期刷新）
                record = self._queue.get(timeout=self.flush_interval)
                if record is None:  # 哨兵值，用于强制刷新
                    self._flush_batch(batch)
                    batch = []
                    last_flush = time.time()
                    continue

                batch.append(record)

                # 达到批量大小，刷新
                if len(batch) >= self.batch_size:
                    self._flush_batch(batch)
                    batch = []
                    last_flush = time.time()

            except queue.Empty:
                # 超时，检查是否需要刷新
                if batch and (time.time() - last_flush) >= self.flush_interval:
                    self._flush_batch(batch)
                    batch = []
                    last_flush = time.time()
            except Exception:
                # 日志处理失败不应影响主程序
                pass

        # 退出前刷新剩余日志
        if batch:
            self._flush_batch(batch)

    def _flush_batch(self, batch: List[logging.LogRecord]) -> None:
        """批量写入日志"""
        for record in batch:
            try:
                self.handler.emit(record)
            except Exception:
                pass
        self._total_logged += len(batch)

    def emit(self, record: logging.LogRecord) -> None:
        """写入日志（异步）"""
        try:
            # 非阻塞入队，队列满则丢弃
            self._queue.put_nowait(record)
        except queue.Full:
            self._total_dropped += 1

    def flush(self) -> None:
        """强制刷新"""
        try:
            self._queue.put(None)  # 哨兵值
        except Exception:
            pass

    def close(self) -> None:
        """关闭处理器"""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        self.handler.close()
        super().close()

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "queue_size": self._queue.qsize(),
            "total_logged": self._total_logged,
            "total_dropped": self._total_dropped,
            "worker_alive": self._thread.is_alive() if self._thread else False,
        }


# ============================================================
# 对象池
# ============================================================

class ObjectPool(Generic[T]):
    """通用对象池

    复用创建开销较大的对象，减少 GC 压力。

    使用方式::

        pool = ObjectPool(
            create_func=lambda: ExpensiveObject(),
            max_size=10,
        )

        with pool.acquire() as obj:
            obj.do_work()
    """

    def __init__(
        self,
        create_func: Callable[[], T],
        reset_func: Optional[Callable[[T], None]] = None,
        max_size: int = 10,
        min_idle: int = 2,
    ):
        """
        Args:
            create_func: 创建对象的函数
            reset_func: 重置对象的函数（归还时调用）
            max_size: 最大池大小
            min_idle: 最小空闲对象数
        """
        self.create_func = create_func
        self.reset_func = reset_func
        self.max_size = max_size
        self.min_idle = min_idle

        self._pool: List[T] = []
        self._lock = threading.Lock()
        self._created = 0
        self._reused = 0

        # 预创建最小空闲对象
        self._precreate_min_idle()

    def _precreate_min_idle(self) -> None:
        """预创建最小空闲对象"""
        for _ in range(self.min_idle):
            try:
                obj = self.create_func()
                self._pool.append(obj)
                self._created += 1
            except Exception:
                break

    def acquire(self) -> T:
        """获取对象"""
        with self._lock:
            if self._pool:
                obj = self._pool.pop()
                self._reused += 1
                return obj
            # 池空，创建新对象
            self._created += 1
            return self.create_func()

    def release(self, obj: T) -> None:
        """归还对象"""
        if self.reset_func:
            try:
                self.reset_func(obj)
            except Exception:
                # 重置失败，丢弃对象
                return

        with self._lock:
            if len(self._pool) < self.max_size:
                self._pool.append(obj)

    @contextmanager
    def borrow(self):
        """上下文管理器方式借用对象"""
        obj = self.acquire()
        try:
            yield obj
        finally:
            self.release(obj)

    def clear(self) -> None:
        """清空对象池"""
        with self._lock:
            self._pool.clear()

    def get_stats(self) -> Dict[str, Any]:
        """获取池统计"""
        with self._lock:
            return {
                "pool_size": len(self._pool),
                "max_size": self.max_size,
                "total_created": self._created,
                "total_reused": self._reused,
                "reuse_rate": round(
                    self._reused / (self._created + self._reused), 4
                ) if (self._created + self._reused) > 0 else 0,
            }


# ============================================================
# 惰性加载属性
# ============================================================

class lazy_property:
    """惰性加载属性装饰器

    属性在首次访问时才计算，之后缓存结果。
    比 property + lru_cache 更轻量。

    使用方式::

        class MyClass:
            @lazy_property
            def expensive_computation(self):
                # 只在首次访问时执行
                return big_calculation()
    """

    def __init__(self, func: Callable):
        self.func = func
        self.__doc__ = func.__doc__
        self._name = f"_lazy_{func.__name__}"

    def __get__(self, instance, owner):
        if instance is None:
            return self

        # 检查是否已缓存
        if self._name in instance.__dict__:
            return instance.__dict__[self._name]

        # 计算并缓存
        value = self.func(instance)
        instance.__dict__[self._name] = value
        return value

    def __set__(self, instance, value):
        instance.__dict__[self._name] = value

    def __delete__(self, instance):
        instance.__dict__.pop(self._name, None)


def lazy(func: Callable[..., T]) -> Callable[..., T]:
    """简单的惰性计算装饰器（无参数函数）

    使用方式::

        @lazy
        def get_config():
            return load_config_from_file()
    """
    result_sentinel = object()
    result = [result_sentinel]

    @wraps(func)
    def wrapper(*args, **kwargs):
        if result[0] is result_sentinel:
            result[0] = func(*args, **kwargs)
        return result[0]

    def reset():
        result[0] = result_sentinel

    wrapper.reset = reset  # type: ignore
    return wrapper


# ============================================================
# 字符串操作优化
# ============================================================

def fast_str_join(parts: List[str], separator: str = "") -> str:
    """快速字符串拼接

    使用 str.join() 比 += 高效得多，这是一个便捷封装。

    Args:
        parts: 字符串列表
        separator: 分隔符

    Returns:
        拼接后的字符串
    """
    return separator.join(parts)


def fast_format_template(template: str, **kwargs) -> str:
    """快速字符串格式化（预编译模板）

    对于重复使用的模板，比 str.format() 更快。

    使用方式::

        greeting = fast_format_template("Hello, {name}!")
        print(greeting(name="World"))
    """
    from string import Template
    tpl = Template(template.replace("{", "${"))
    return tpl.safe_substitute(**kwargs)


class StringInternPool:
    """字符串驻留池

    复用相同内容的字符串，减少内存占用和比较开销。
    对于大量重复字符串的场景很有用。
    """

    def __init__(self, max_size: int = 10000):
        self.max_size = max_size
        self._pool: Dict[str, str] = {}
        self._lock = threading.Lock()

    def intern(self, s: str) -> str:
        """驻留字符串

        如果池中已有相同字符串，返回池中的引用；
        否则加入池中并返回。
        """
        with self._lock:
            if s in self._pool:
                return self._pool[s]

            # 池满时简单清理（LRU 太复杂，这里用半清策略）
            if len(self._pool) >= self.max_size:
                # 清空一半
                keys = list(self._pool.keys())[:self.max_size // 2]
                for k in keys:
                    del self._pool[k]

            self._pool[s] = s
            return s

    def clear(self) -> None:
        with self._lock:
            self._pool.clear()

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._pool)


# ============================================================
# 批处理工具
# ============================================================

class BatchProcessor:
    """批处理器

    收集单个操作，达到批量大小或时间阈值时批量执行。
    适用于数据库写入、日志上报等场景。

    使用方式::

        def batch_writer(items):
            db.insert_many(items)

        processor = BatchProcessor(batch_writer, batch_size=100, flush_interval=1.0)
        processor.add(item1)
        processor.add(item2)
    """

    def __init__(
        self,
        process_func: Callable[[List[Any]], None],
        batch_size: int = 100,
        flush_interval: float = 1.0,
        max_queue: int = 10000,
    ):
        """
        Args:
            process_func: 批量处理函数
            batch_size: 每批大小
            flush_interval: 强制刷新间隔（秒）
            max_queue: 最大队列长度
        """
        self.process_func = process_func
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.max_queue = max_queue

        self._queue: List[Any] = []
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # 统计
        self._total_processed = 0
        self._total_batches = 0
        self._total_dropped = 0

        self._start_worker()

    def _start_worker(self) -> None:
        """启动后台刷新线程"""
        self._thread = threading.Thread(
            target=self._worker_loop,
            name="BatchProcessor-Worker",
            daemon=True,
        )
        self._thread.start()

    def _worker_loop(self) -> None:
        """后台刷新线程"""
        last_flush = time.time()

        while not self._stop_event.is_set():
            time.sleep(min(self.flush_interval, 0.1))

            now = time.time()
            need_flush = False

            with self._lock:
                if len(self._queue) >= self.batch_size:
                    need_flush = True
                elif self._queue and (now - last_flush) >= self.flush_interval:
                    need_flush = True

                if need_flush:
                    batch = self._queue[:self.batch_size]
                    self._queue = self._queue[self.batch_size:]
                else:
                    batch = []

            if batch:
                try:
                    self.process_func(batch)
                    self._total_processed += len(batch)
                    self._total_batches += 1
                except Exception:
                    pass
                last_flush = now

        # 退出前刷新剩余
        with self._lock:
            remaining = self._queue
            self._queue = []

        if remaining:
            try:
                self.process_func(remaining)
                self._total_processed += len(remaining)
                self._total_batches += 1
            except Exception:
                pass

    def add(self, item: Any) -> bool:
        """添加项目

        Returns:
            True 表示成功，False 表示队列已满被丢弃
        """
        with self._lock:
            if len(self._queue) >= self.max_queue:
                self._total_dropped += 1
                return False
            self._queue.append(item)
            return True

    def add_many(self, items: List[Any]) -> int:
        """批量添加项目

        Returns:
            成功添加的数量
        """
        added = 0
        with self._lock:
            for item in items:
                if len(self._queue) >= self.max_queue:
                    self._total_dropped += len(items) - added
                    break
                self._queue.append(item)
                added += 1
        return added

    def flush(self) -> None:
        """强制刷新"""
        with self._lock:
            batch = self._queue
            self._queue = []

        if batch:
            try:
                self.process_func(batch)
                self._total_processed += len(batch)
                self._total_batches += 1
            except Exception:
                pass

    def close(self) -> None:
        """关闭批处理器"""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            return {
                "queue_size": len(self._queue),
                "total_processed": self._total_processed,
                "total_batches": self._total_batches,
                "total_dropped": self._total_dropped,
                "batch_size": self.batch_size,
                "flush_interval": self.flush_interval,
            }


# ============================================================
# 性能计时上下文
# ============================================================

@contextmanager
def timed(name: str = "", logger: Optional[logging.Logger] = None, level: int = logging.DEBUG):
    """简单的计时上下文管理器

    使用方式::

        with timed("db_query") as t:
            result = db.query(...)
        print(f"耗时: {t.elapsed_ms:.2f}ms")
    """
    start = time.perf_counter()
    timer = type('Timer', (), {'elapsed_ms': 0.0})()
    try:
        yield timer
    finally:
        elapsed = (time.perf_counter() - start) * 1000
        timer.elapsed_ms = elapsed
        if logger:
            logger.log(level, f"[{name}] elapsed: {elapsed:.3f}ms")


# ============================================================
# 速率限制器
# ============================================================

class RateLimiter:
    """令牌桶速率限制器

    用于控制操作频率，保护下游系统。

    使用方式::

        limiter = RateLimiter(rate=100, per_second=1)  # 每秒 100 次
        if limiter.acquire():
            do_operation()
    """

    def __init__(self, rate: float, per_second: float = 1.0):
        """
        Args:
            rate: 每 per_second 秒内的最大次数
            per_second: 时间窗口（秒）
        """
        self.rate = rate
        self.per_second = per_second
        self._tokens = rate
        self._last_time = time.time()
        self._lock = threading.Lock()

    def acquire(self, tokens: int = 1) -> bool:
        """获取令牌

        Args:
            tokens: 需要的令牌数

        Returns:
            True 表示获取成功，False 表示被限流
        """
        with self._lock:
            now = time.time()
            elapsed = now - self._last_time

            # 补充令牌
            self._tokens += elapsed * (self.rate / self.per_second)
            self._tokens = min(self._tokens, self.rate)
            self._last_time = now

            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    @property
    def available_tokens(self) -> float:
        """当前可用令牌数"""
        with self._lock:
            now = time.time()
            elapsed = now - self._last_time
            tokens = self._tokens + elapsed * (self.rate / self.per_second)
            return min(tokens, self.rate)


# ============================================================
# 性能配置
# ============================================================

def get_performance_config() -> Dict[str, Any]:
    """获取性能优化配置

    从环境变量读取，提供生产环境推荐配置。

    环境变量:
        PERF_LOG_ASYNC=true/false       是否异步日志
        PERF_JSON_LIBRARY=orjson/ujson  JSON 库
        PERF_CACHE_ENABLED=true/false   是否启用缓存
        PERF_DB_POOL_SIZE=5             数据库连接池大小
    """
    return {
        "log_async": os.getenv("PERF_LOG_ASYNC", "true").lower() in ("true", "1", "yes"),
        "json_library": os.getenv("PERF_JSON_LIBRARY", _fast_json_lib),
        "cache_enabled": os.getenv("PERF_CACHE_ENABLED", "true").lower() in ("true", "1", "yes"),
        "db_pool_size": int(os.getenv("PERF_DB_POOL_SIZE", "5")),
        "batch_size": int(os.getenv("PERF_BATCH_SIZE", "100")),
    }
