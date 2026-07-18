"""
性能分析器 (Performance Profiler)

功能:
- 函数耗时统计装饰器 @profile_time
- 慢请求检测 (可配置阈值)
- 性能瓶颈分析
- 调用链追踪 (配合 trace_id)
- 性能数据持久化

使用方式::

    from shared.perf.profiler import PerformanceProfiler, profile_time

    profiler = PerformanceProfiler(slow_threshold_ms=1000)

    # 装饰器用法
    @profile_time(name="db_query", slow_threshold_ms=500)
    def query_database(sql: str):
        ...

    # 上下文管理器
    with profiler.profile("some_operation"):
        do_something()

    # 获取慢请求
    slow_requests = profiler.get_slow_requests()

    # 性能统计
    stats = profiler.get_stats()
"""

from __future__ import annotations

import time
import json
import uuid
import threading
import functools
from typing import Any, Dict, List, Optional, Callable, Tuple
from dataclasses import dataclass, field
from collections import defaultdict, deque
from contextlib import contextmanager


# ============================================================
# 数据模型
# ============================================================

@dataclass
class ProfileRecord:
    """单次性能记录"""
    name: str
    duration_ms: float
    start_time: float
    end_time: float
    trace_id: str = ""
    tags: Dict[str, str] = field(default_factory=dict)
    is_slow: bool = False
    error: Optional[str] = None


@dataclass
class FunctionStats:
    """函数性能统计"""
    name: str
    call_count: int = 0
    total_time_ms: float = 0.0
    avg_time_ms: float = 0.0
    min_time_ms: float = float("inf")
    max_time_ms: float = 0.0
    p50_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    slow_count: int = 0
    error_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "call_count": self.call_count,
            "total_time_ms": round(self.total_time_ms, 3),
            "avg_time_ms": round(self.avg_time_ms, 3),
            "min_time_ms": round(self.min_time_ms, 3) if self.min_time_ms != float("inf") else 0,
            "max_time_ms": round(self.max_time_ms, 3),
            "p50_ms": round(self.p50_ms, 3),
            "p95_ms": round(self.p95_ms, 3),
            "p99_ms": round(self.p99_ms, 3),
            "slow_count": self.slow_count,
            "error_count": self.error_count,
        }


@dataclass
class CallChain:
    """调用链"""
    trace_id: str
    entries: List[ProfileRecord] = field(default_factory=list)

    def add(self, record: ProfileRecord) -> None:
        self.entries.append(record)

    @property
    def total_duration_ms(self) -> float:
        if not self.entries:
            return 0.0
        return self.entries[-1].end_time - self.entries[0].start_time

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "total_duration_ms": round(self.total_duration_ms * 1000, 3),
            "entry_count": len(self.entries),
            "entries": [
                {
                    "name": r.name,
                    "duration_ms": round(r.duration_ms, 3),
                    "is_slow": r.is_slow,
                    "tags": r.tags,
                }
                for r in self.entries
            ],
        }


# ============================================================
# 性能分析器
# ============================================================

class PerformanceProfiler:
    """性能分析器

    特性:
    - 函数耗时统计 (装饰器 + 上下文管理器)
    - 慢请求检测 (可配置阈值)
    - 百分位统计 (P50/P95/P99)
    - 调用链追踪 (trace_id)
    - 性能数据持久化 (可选)
    - 线程安全
    """

    def __init__(
        self,
        slow_threshold_ms: float = 1000.0,
        max_slow_requests: int = 1000,
        max_stats_functions: int = 500,
        max_trace_chains: int = 100,
        persist_path: Optional[str] = None,
    ):
        """
        Args:
            slow_threshold_ms: 慢请求阈值 (毫秒)
            max_slow_requests: 最大保留慢请求数
            max_stats_functions: 最大统计函数数
            max_trace_chains: 最大保留调用链数
            persist_path: 性能数据持久化路径 (JSON 文件)
        """
        self.slow_threshold_ms = slow_threshold_ms
        self.max_slow_requests = max_slow_requests
        self.max_stats_functions = max_stats_functions
        self.max_trace_chains = max_trace_chains
        self.persist_path = persist_path

        # 函数统计
        self._stats: Dict[str, FunctionStats] = {}
        self._durations: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=1000)
        )
        self._stats_lock = threading.Lock()

        # 慢请求列表 (FIFO)
        self._slow_requests: deque = deque(maxlen=max_slow_requests)
        self._slow_lock = threading.Lock()

        # 调用链 (按 trace_id)
        self._trace_chains: Dict[str, CallChain] = {}
        self._trace_lock = threading.Lock()

        # 线程本地 trace_id
        self._thread_local = threading.local()

    # ---------- 装饰器 ----------

    def profile(
        self,
        name: Optional[str] = None,
        slow_threshold_ms: Optional[float] = None,
        tags: Optional[Dict[str, str]] = None,
    ):
        """性能分析装饰器/上下文管理器

        可以作为装饰器或上下文管理器使用。

        用法::

            # 装饰器
            @profiler.profile("db_query", slow_threshold_ms=500)
            def query():
                ...

            # 上下文管理器
            with profiler.profile("operation"):
                ...
        """
        # 作为装饰器使用
        def decorator(func: Callable) -> Callable:
            func_name = name or f"{func.__module__}.{func.__qualname__}"

            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                start = time.perf_counter()
                trace_id = self._get_trace_id()
                error = None
                try:
                    result = func(*args, **kwargs)
                    return result
                except Exception as e:
                    error = str(e)
                    raise
                finally:
                    end = time.perf_counter()
                    duration = (end - start) * 1000
                    self._record(
                        name=func_name,
                        duration_ms=duration,
                        start_time=start,
                        end_time=end,
                        trace_id=trace_id,
                        tags=tags or {},
                        threshold=slow_threshold_ms or self.slow_threshold_ms,
                        error=error,
                    )

            return wrapper

        return decorator

    @contextmanager
    def profile_block(
        self,
        name: str,
        slow_threshold_ms: Optional[float] = None,
        tags: Optional[Dict[str, str]] = None,
    ):
        """性能分析上下文管理器"""
        start = time.perf_counter()
        trace_id = self._get_trace_id()
        error = None
        try:
            yield
        except Exception as e:
            error = str(e)
            raise
        finally:
            end = time.perf_counter()
            duration = (end - start) * 1000
            self._record(
                name=name,
                duration_ms=duration,
                start_time=start,
                end_time=end,
                trace_id=trace_id,
                tags=tags or {},
                threshold=slow_threshold_ms or self.slow_threshold_ms,
                error=error,
            )

    # ---------- 内部记录 ----------

    def _record(
        self,
        name: str,
        duration_ms: float,
        start_time: float,
        end_time: float,
        trace_id: str,
        tags: Dict[str, str],
        threshold: float,
        error: Optional[str],
    ) -> None:
        """记录性能数据"""
        is_slow = duration_ms > threshold
        record = ProfileRecord(
            name=name,
            duration_ms=duration_ms,
            start_time=start_time,
            end_time=end_time,
            trace_id=trace_id,
            tags=tags,
            is_slow=is_slow,
            error=error,
        )

        # 更新统计
        self._update_stats(name, duration_ms, is_slow, error)

        # 慢请求
        if is_slow:
            with self._slow_lock:
                self._slow_requests.append(record)

        # 调用链
        if trace_id:
            self._add_to_trace(trace_id, record)

        # 持久化 (简化: 异步或定期，这里只在配置了路径时同步追加到文件)
        if self.persist_path:
            self._persist_record(record)

    def _update_stats(
        self,
        name: str,
        duration_ms: float,
        is_slow: bool,
        error: Optional[str],
    ) -> None:
        """更新函数统计"""
        with self._stats_lock:
            stats = self._stats.get(name)
            if stats is None:
                # 限制函数数量
                if len(self._stats) >= self.max_stats_functions:
                    # 移除调用次数最少的
                    min_name = min(self._stats.keys(), key=lambda k: self._stats[k].call_count)
                    del self._stats[min_name]
                    del self._durations[min_name]
                stats = FunctionStats(name=name)
                self._stats[name] = stats

            stats.call_count += 1
            stats.total_time_ms += duration_ms
            stats.avg_time_ms = stats.total_time_ms / stats.call_count
            stats.min_time_ms = min(stats.min_time_ms, duration_ms)
            stats.max_time_ms = max(stats.max_time_ms, duration_ms)
            if is_slow:
                stats.slow_count += 1
            if error:
                stats.error_count += 1

            # 记录最近的耗时 (用于百分位计算)
            self._durations[name].append(duration_ms)

            # 计算百分位
            durations = sorted(self._durations[name])
            if durations:
                n = len(durations)
                stats.p50_ms = durations[int(n * 0.5)] if n > 0 else 0
                stats.p95_ms = durations[int(n * 0.95)] if n > 0 else 0
                stats.p99_ms = durations[int(n * 0.99)] if n > 0 else 0

    def _add_to_trace(self, trace_id: str, record: ProfileRecord) -> None:
        """添加到调用链"""
        with self._trace_lock:
            chain = self._trace_chains.get(trace_id)
            if chain is None:
                # 限制调用链数量
                if len(self._trace_chains) >= self.max_trace_chains:
                    # 移除最早的
                    oldest_id = next(iter(self._trace_chains))
                    del self._trace_chains[oldest_id]
                chain = CallChain(trace_id=trace_id)
                self._trace_chains[trace_id] = chain
            chain.add(record)

    def _persist_record(self, record: ProfileRecord) -> None:
        """持久化单条记录"""
        try:
            import os
            data = {
                "name": record.name,
                "duration_ms": record.duration_ms,
                "start_time": record.start_time,
                "end_time": record.end_time,
                "trace_id": record.trace_id,
                "tags": record.tags,
                "is_slow": record.is_slow,
                "error": record.error,
            }
            dir_path = os.path.dirname(self.persist_path)
            if dir_path:
                os.makedirs(dir_path, exist_ok=True)
            with open(self.persist_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(data, ensure_ascii=False) + "\n")
        except Exception:
            pass

    # ---------- Trace ID 管理 ----------

    def start_trace(self, trace_id: Optional[str] = None) -> str:
        """开始一个调用链"""
        tid = trace_id or str(uuid.uuid4())
        self._thread_local.trace_id = tid
        with self._trace_lock:
            if tid not in self._trace_chains:
                self._trace_chains[tid] = CallChain(trace_id=tid)
        return tid

    def end_trace(self) -> Optional[str]:
        """结束当前调用链"""
        trace_id = getattr(self._thread_local, "trace_id", None)
        if trace_id:
            delattr(self._thread_local, "trace_id")
        return trace_id

    def _get_trace_id(self) -> str:
        """获取当前 trace_id"""
        return getattr(self._thread_local, "trace_id", "")

    def get_trace_chain(self, trace_id: str) -> Optional[Dict[str, Any]]:
        """获取调用链详情"""
        with self._trace_lock:
            chain = self._trace_chains.get(trace_id)
            return chain.to_dict() if chain else None

    # ---------- 慢请求 ----------

    def get_slow_requests(
        self,
        limit: int = 100,
        name_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取慢请求列表

        Args:
            limit: 返回数量限制
            name_filter: 按名称过滤

        Returns:
            慢请求列表 (最新的在前)
        """
        with self._slow_lock:
            requests = list(self._slow_requests)

        # 最新的在前
        requests.reverse()

        if name_filter:
            requests = [r for r in requests if name_filter in r.name]

        return [
            {
                "name": r.name,
                "duration_ms": round(r.duration_ms, 3),
                "timestamp": r.start_time,
                "trace_id": r.trace_id,
                "tags": r.tags,
                "error": r.error,
            }
            for r in requests[:limit]
        ]

    # ---------- 统计信息 ----------

    def get_stats(
        self,
        name: Optional[str] = None,
        sort_by: str = "total_time_ms",
        limit: int = 50,
    ) -> Dict[str, Any]:
        """获取性能统计

        Args:
            name: 指定函数名，None 返回所有
            sort_by: 排序字段
            limit: 返回数量

        Returns:
            统计信息字典
        """
        with self._stats_lock:
            if name:
                stats = self._stats.get(name)
                return stats.to_dict() if stats else {}

            all_stats = list(self._stats.values())

        # 排序
        all_stats.sort(key=lambda s: getattr(s, sort_by, 0), reverse=True)

        return {
            "total_functions": len(all_stats),
            "top_functions": [s.to_dict() for s in all_stats[:limit]],
            "sort_by": sort_by,
            "slow_threshold_ms": self.slow_threshold_ms,
        }

    def get_bottlenecks(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取性能瓶颈 (按总耗时排序)

        返回最耗时的函数列表，帮助定位性能瓶颈。
        """
        with self._stats_lock:
            all_stats = list(self._stats.values())

        all_stats.sort(key=lambda s: s.total_time_ms, reverse=True)

        return [
            {
                "name": s.name,
                "total_time_ms": round(s.total_time_ms, 3),
                "call_count": s.call_count,
                "avg_time_ms": round(s.avg_time_ms, 3),
                "p95_ms": round(s.p95_ms, 3),
                "slow_count": s.slow_count,
            }
            for s in all_stats[:limit]
        ]

    # ---------- 重置 ----------

    def reset(self) -> None:
        """重置所有统计数据"""
        with self._stats_lock:
            self._stats.clear()
            self._durations.clear()
        with self._slow_lock:
            self._slow_requests.clear()
        with self._trace_lock:
            self._trace_chains.clear()


# ============================================================
# 便捷装饰器 (使用全局 profiler)
# ============================================================

_default_profiler: Optional[PerformanceProfiler] = None
_default_lock = threading.Lock()


def _get_default_profiler() -> PerformanceProfiler:
    """获取默认分析器"""
    global _default_profiler
    if _default_profiler is not None:
        return _default_profiler
    with _default_lock:
        if _default_profiler is None:
            _default_profiler = PerformanceProfiler()
        return _default_profiler


def profile_time(
    name: Optional[str] = None,
    slow_threshold_ms: float = 1000.0,
    tags: Optional[Dict[str, str]] = None,
):
    """函数耗时统计装饰器 (便捷入口)

    用法::

        @profile_time(name="db_query", slow_threshold_ms=500)
        def query_database(sql: str):
            ...
    """
    profiler = _get_default_profiler()
    return profiler.profile(name=name, slow_threshold_ms=slow_threshold_ms, tags=tags)


def reset_default_profiler() -> None:
    """重置默认分析器 (用于测试)"""
    global _default_profiler
    with _default_lock:
        if _default_profiler is not None:
            _default_profiler.reset()
            _default_profiler = None
