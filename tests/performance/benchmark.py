"""
性能基准测试工具类

提供计时、统计、内存/CPU 监测、基准对比等功能。

核心组件：
- BenchmarkTimer: 高精度计时器（装饰器 + 上下文管理器）
- BenchmarkStats: 基准测试统计（平均值、中位数、P95、P99 等）
- MemoryProfiler: 内存使用监测
- BenchmarkResult: 基准结果对比（与历史基线对比）
- benchmark: 便捷的基准测试装饰器

使用方式::

    from tests.performance.benchmark import (
        BenchmarkTimer, BenchmarkStats, benchmark,
        measure_memory, compare_with_baseline,
    )

    # 作为上下文管理器
    with BenchmarkTimer() as timer:
        do_something()
    print(f"耗时: {timer.elapsed_ms:.2f}ms")

    # 作为装饰器
    @benchmark(name="my_function", iterations=100)
    def my_function():
        ...

    # 多次运行统计
    stats = BenchmarkStats()
    for i in range(100):
        with BenchmarkTimer() as t:
            do_something()
        stats.add_measurement(t.elapsed_ms)
    print(f"P95: {stats.p95:.2f}ms")
"""

import os
import sys
import time
import json
import tracemalloc
import threading
import statistics
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Callable
from functools import wraps
from dataclasses import dataclass, field, asdict
from collections import defaultdict
from contextlib import contextmanager


# ============================================================
# 高精度计时器
# ============================================================

class BenchmarkTimer:
    """高精度计时器

    支持作为上下文管理器和装饰器使用。
    使用 time.perf_counter() 获得最高精度。

    用法::

        # 上下文管理器
        with BenchmarkTimer() as timer:
            do_work()
        print(timer.elapsed_ms)

        # 装饰器
        @BenchmarkTimer.decorator
        def my_func():
            ...
    """

    __slots__ = ("_start", "_end", "elapsed_ms", "name")

    def __init__(self, name: str = ""):
        self.name = name
        self._start = 0.0
        self._end = 0.0
        self.elapsed_ms = 0.0

    def __enter__(self) -> "BenchmarkTimer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._end = time.perf_counter()
        self.elapsed_ms = (self._end - self._start) * 1000
        return False

    @property
    def elapsed_seconds(self) -> float:
        """耗时（秒）"""
        return self.elapsed_ms / 1000

    @property
    def elapsed_us(self) -> float:
        """耗时（微秒）"""
        return self.elapsed_ms * 1000

    def reset(self) -> None:
        """重置计时器"""
        self._start = 0.0
        self._end = 0.0
        self.elapsed_ms = 0.0

    def lap(self) -> float:
        """计次（记录当前耗时但不停止）

        Returns:
            从开始到现在的耗时（毫秒）
        """
        now = time.perf_counter()
        return (now - self._start) * 1000

    @staticmethod
    def decorator(name: Optional[str] = None):
        """装饰器形式使用计时器

        Args:
            name: 计时器名称，默认使用函数名
        """
        def actual_decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                timer_name = name or f"{func.__module__}.{func.__qualname__}"
                with BenchmarkTimer(name=timer_name) as timer:
                    result = func(*args, **kwargs)
                wrapper.last_elapsed_ms = timer.elapsed_ms  # type: ignore
                return result
            wrapper.last_elapsed_ms = 0.0  # type: ignore
            return wrapper
        return actual_decorator


# ============================================================
# 基准测试统计
# ============================================================

@dataclass
class BenchmarkStats:
    """基准测试统计信息

    收集多次运行的耗时数据，计算各种统计指标。
    """

    measurements: List[float] = field(default_factory=list)
    name: str = ""

    def add_measurement(self, elapsed_ms: float) -> None:
        """添加一次测量值"""
        self.measurements.append(elapsed_ms)

    def add_measurements(self, values: List[float]) -> None:
        """批量添加测量值"""
        self.measurements.extend(values)

    @property
    def count(self) -> int:
        """测量次数"""
        return len(self.measurements)

    @property
    def total_ms(self) -> float:
        """总耗时（毫秒）"""
        return sum(self.measurements) if self.measurements else 0.0

    @property
    def mean(self) -> float:
        """平均值"""
        if not self.measurements:
            return 0.0
        return statistics.mean(self.measurements)

    @property
    def median(self) -> float:
        """中位数"""
        if not self.measurements:
            return 0.0
        return statistics.median(self.measurements)

    @property
    def stdev(self) -> float:
        """标准差"""
        if len(self.measurements) < 2:
            return 0.0
        return statistics.stdev(self.measurements)

    @property
    def min(self) -> float:
        """最小值"""
        return min(self.measurements) if self.measurements else 0.0

    @property
    def max(self) -> float:
        """最大值"""
        return max(self.measurements) if self.measurements else 0.0

    def percentile(self, p: float) -> float:
        """百分位数

        Args:
            p: 百分比 (0-100)
        """
        if not self.measurements:
            return 0.0
        sorted_data = sorted(self.measurements)
        k = (len(sorted_data) - 1) * (p / 100)
        f = int(k)
        c = f + 1 if f + 1 < len(sorted_data) else f
        d0 = sorted_data[f] * (c - k)
        d1 = sorted_data[c] * (k - f)
        return d0 + d1

    @property
    def p50(self) -> float:
        """P50 百分位数（等同于中位数）"""
        return self.percentile(50)

    @property
    def p90(self) -> float:
        """P90 百分位数"""
        return self.percentile(90)

    @property
    def p95(self) -> float:
        """P95 百分位数"""
        return self.percentile(95)

    @property
    def p99(self) -> float:
        """P99 百分位数"""
        return self.percentile(99)

    @property
    def p999(self) -> float:
        """P99.9 百分位数"""
        return self.percentile(99.9)

    @property
    def qps(self) -> float:
        """每秒查询数（基于总耗时）"""
        if self.total_ms <= 0:
            return 0.0
        return self.count / (self.total_ms / 1000)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "name": self.name,
            "count": self.count,
            "total_ms": round(self.total_ms, 4),
            "mean_ms": round(self.mean, 4),
            "median_ms": round(self.median, 4),
            "min_ms": round(self.min, 4),
            "max_ms": round(self.max, 4),
            "stdev_ms": round(self.stdev, 4),
            "p50_ms": round(self.p50, 4),
            "p90_ms": round(self.p90, 4),
            "p95_ms": round(self.p95, 4),
            "p99_ms": round(self.p99, 4),
            "p999_ms": round(self.p999, 4),
            "qps": round(self.qps, 2),
        }

    def summary(self) -> str:
        """生成文本摘要"""
        if not self.measurements:
            return f"[{self.name}] 无测量数据"
        return (
            f"[{self.name}] count={self.count} | "
            f"mean={self.mean:.3f}ms | median={self.median:.3f}ms | "
            f"p95={self.p95:.3f}ms | p99={self.p99:.3f}ms | "
            f"min={self.min:.3f}ms | max={self.max:.3f}ms | "
            f"qps={self.qps:.1f}"
        )

    def reset(self) -> None:
        """重置统计"""
        self.measurements.clear()


# ============================================================
# 内存监测
# ============================================================

@dataclass
class MemorySnapshot:
    """内存快照"""
    current_kb: float = 0.0
    peak_kb: float = 0.0
    current_mb: float = 0.0
    peak_mb: float = 0.0


class MemoryProfiler:
    """内存使用监测器

    使用 tracemalloc 监测内存分配。

    用法::

        profiler = MemoryProfiler()
        profiler.start()
        do_work()
        snapshot = profiler.stop()
        print(f"内存增长: {snapshot.peak_mb:.2f}MB")
    """

    def __init__(self):
        self._started = False
        self._start_snapshot: Optional[tracemalloc.Snapshot] = None
        self._peak_kb = 0.0

    def start(self) -> None:
        """开始监测"""
        if not tracemalloc.is_tracing():
            tracemalloc.start()
        self._start_snapshot = tracemalloc.take_snapshot()
        self._peak_kb = self._get_current_kb()
        self._started = True

    def stop(self) -> MemorySnapshot:
        """停止监测并返回结果"""
        if not self._started:
            return MemorySnapshot()

        current_kb = self._get_current_kb()
        _, peak_kb = tracemalloc.get_traced_memory()

        # 计算相对于起始点的增长
        start_kb = self._get_snapshot_size_kb(self._start_snapshot) if self._start_snapshot else 0
        growth_kb = max(0, current_kb - start_kb)
        peak_growth_kb = max(0, (peak_kb / 1024) - start_kb)

        self._started = False

        return MemorySnapshot(
            current_kb=growth_kb,
            peak_kb=peak_growth_kb,
            current_mb=growth_kb / 1024,
            peak_mb=peak_growth_kb / 1024,
        )

    def _get_current_kb(self) -> float:
        """获取当前已分配内存（KB）"""
        current, _ = tracemalloc.get_traced_memory()
        return current / 1024

    def _get_snapshot_size_kb(self, snapshot: tracemalloc.Snapshot) -> float:
        """估算快照的总内存大小（KB）"""
        total = sum(stat.size for stat in snapshot.statistics("lineno"))
        return total / 1024

    @contextmanager
    def monitor(self):
        """上下文管理器形式"""
        self.start()
        try:
            yield self
        finally:
            self._last_snapshot = self.stop()

    def get_top_allocations(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取 top 内存分配位置"""
        if not tracemalloc.is_tracing():
            return []
        snapshot = tracemalloc.take_snapshot()
        top_stats = snapshot.statistics("lineno")[:limit]
        return [
            {
                "file": str(stat.traceback[0].filename) if stat.traceback else "unknown",
                "line": stat.traceback[0].lineno if stat.traceback else 0,
                "size_kb": stat.size / 1024,
                "count": stat.count,
            }
            for stat in top_stats
        ]


def measure_memory(func: Callable, *args, **kwargs) -> Tuple[Any, MemorySnapshot]:
    """测量函数执行的内存使用

    Returns:
        (函数返回值, 内存快照)
    """
    profiler = MemoryProfiler()
    profiler.start()
    try:
        result = func(*args, **kwargs)
    finally:
        snapshot = profiler.stop()
    return result, snapshot


# ============================================================
# 并发性能测试
# ============================================================

def concurrent_benchmark(
    func: Callable,
    iterations: int = 100,
    concurrency: int = 10,
    *args, **kwargs,
) -> BenchmarkStats:
    """并发性能测试

    使用多线程模拟并发请求，测量整体性能。

    Args:
        func: 要测试的函数
        iterations: 总迭代次数
        concurrency: 并发数
        *args, **kwargs: 传递给函数的参数

    Returns:
        基准测试统计
    """
    stats = BenchmarkStats(name=f"concurrent:{func.__name__}")
    stats_lock = threading.Lock()

    def worker(n: int):
        for _ in range(n):
            with BenchmarkTimer() as timer:
                func(*args, **kwargs)
            with stats_lock:
                stats.add_measurement(timer.elapsed_ms)

    per_worker = iterations // concurrency
    remainder = iterations % concurrency

    threads = []
    for i in range(concurrency):
        count = per_worker + (1 if i < remainder else 0)
        if count > 0:
            t = threading.Thread(target=worker, args=(count,))
            threads.append(t)
            t.start()

    for t in threads:
        t.join()

    return stats


# ============================================================
# 基准测试便捷装饰器
# ============================================================

def benchmark(
    name: Optional[str] = None,
    iterations: int = 100,
    warmup: int = 5,
    record_stats: bool = True,
):
    """基准测试装饰器

    多次运行函数并收集性能数据。

    Args:
        name: 基准名称
        iterations: 迭代次数
        warmup: 预热次数（不计入统计）
        record_stats: 是否记录统计结果

    用法::

        @benchmark(iterations=1000, warmup=10)
        def test_query():
            db.query("SELECT 1")
    """
    def decorator(func):
        bench_name = name or f"{func.__module__}.{func.__qualname__}"

        @wraps(func)
        def wrapper(*args, **kwargs):
            stats = BenchmarkStats(name=bench_name)

            # 预热
            for _ in range(warmup):
                func(*args, **kwargs)

            # 正式测量
            for _ in range(iterations):
                with BenchmarkTimer() as timer:
                    func(*args, **kwargs)
                stats.add_measurement(timer.elapsed_ms)

            wrapper.last_stats = stats  # type: ignore
            return stats

        wrapper.last_stats = BenchmarkStats(name=bench_name)  # type: ignore
        return wrapper
    return decorator


# ============================================================
# 历史基线对比
# ============================================================

class BaselineManager:
    """基准测试历史基线管理

    保存历史基准测试结果，用于对比性能变化。

    基线数据保存在 JSON 文件中。
    """

    def __init__(self, baseline_file: Optional[str] = None):
        if baseline_file is None:
            baseline_file = os.path.join(
                os.path.dirname(__file__),
                "..",
                "..",
                ".benchmark_baselines.json",
            )
        self.baseline_file = Path(baseline_file).resolve()
        self._baselines: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        """加载基线数据"""
        if self.baseline_file.exists():
            try:
                with open(self.baseline_file, "r", encoding="utf-8") as f:
                    self._baselines = json.load(f)
            except (json.JSONDecodeError, IOError):
                self._baselines = {}

    def _save(self) -> None:
        """保存基线数据"""
        try:
            self.baseline_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.baseline_file, "w", encoding="utf-8") as f:
                json.dump(self._baselines, f, indent=2, ensure_ascii=False)
        except IOError:
            pass

    def save_baseline(self, name: str, stats: BenchmarkStats, version: str = "current") -> None:
        """保存基准结果作为基线

        Args:
            name: 基准项名称
            stats: 基准统计数据
            version: 基线版本标识
        """
        if name not in self._baselines:
            self._baselines[name] = {}
        self._baselines[name][version] = {
            **stats.to_dict(),
            "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._save()

    def get_baseline(self, name: str, version: str = "current") -> Optional[Dict[str, Any]]:
        """获取指定基线"""
        return self._baselines.get(name, {}).get(version)

    def compare(
        self,
        name: str,
        current_stats: BenchmarkStats,
        baseline_version: str = "current",
        threshold_pct: float = 20.0,
    ) -> Dict[str, Any]:
        """对比当前结果与基线

        Args:
            name: 基准项名称
            current_stats: 当前统计数据
            baseline_version: 基线版本
            threshold_pct: 退化告警阈值（百分比）

        Returns:
            对比结果字典
        """
        baseline = self.get_baseline(name, baseline_version)
        if baseline is None:
            return {
                "name": name,
                "status": "no_baseline",
                "message": f"没有找到 {name} 的基线数据",
                "current": current_stats.to_dict(),
            }

        baseline_mean = baseline.get("mean_ms", 0)
        current_mean = current_stats.mean

        if baseline_mean <= 0:
            change_pct = 0.0
        else:
            change_pct = ((current_mean - baseline_mean) / baseline_mean) * 100

        is_regression = change_pct > threshold_pct
        is_improvement = change_pct < -threshold_pct

        if is_regression:
            status = "regression"
            message = f"性能退化 {change_pct:.1f}% (超过 {threshold_pct}% 阈值)"
        elif is_improvement:
            status = "improvement"
            message = f"性能提升 {abs(change_pct):.1f}%"
        else:
            status = "ok"
            message = f"性能变化 {change_pct:+.1f}% (在 {threshold_pct}% 阈值内)"

        return {
            "name": name,
            "status": status,
            "message": message,
            "change_pct": round(change_pct, 2),
            "threshold_pct": threshold_pct,
            "baseline": baseline,
            "current": current_stats.to_dict(),
        }

    def list_baselines(self) -> Dict[str, List[str]]:
        """列出所有基线项和版本"""
        return {name: list(versions.keys()) for name, versions in self._baselines.items()}


def compare_with_baseline(
    name: str,
    stats: BenchmarkStats,
    baseline_file: Optional[str] = None,
    threshold_pct: float = 20.0,
) -> Dict[str, Any]:
    """便捷函数：对比当前结果与基线"""
    manager = BaselineManager(baseline_file)
    return manager.compare(name, stats, threshold_pct=threshold_pct)


# ============================================================
# 全局基准测试结果收集器
# ============================================================

class BenchmarkCollector:
    """全局基准测试结果收集器

    在测试运行期间收集所有基准结果，最后统一输出。
    """

    _instance: Optional["BenchmarkCollector"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._results: Dict[str, BenchmarkStats] = {}
        self._memory_results: Dict[str, MemorySnapshot] = {}

    @classmethod
    def get_instance(cls) -> "BenchmarkCollector":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def add_result(self, name: str, stats: BenchmarkStats) -> None:
        self._results[name] = stats

    def add_memory_result(self, name: str, snapshot: MemorySnapshot) -> None:
        self._memory_results[name] = snapshot

    def get_all_results(self) -> Dict[str, Dict[str, Any]]:
        return {name: stats.to_dict() for name, stats in self._results.items()}

    def get_memory_results(self) -> Dict[str, Dict[str, Any]]:
        return {name: asdict(snapshot) for name, snapshot in self._memory_results.items()}

    def clear(self) -> None:
        self._results.clear()
        self._memory_results.clear()


# ============================================================
# 吞吐量测试辅助
# ============================================================

def measure_throughput(
    func: Callable,
    duration_seconds: float = 5.0,
    concurrency: int = 1,
    *args, **kwargs,
) -> Dict[str, Any]:
    """测量函数吞吐量（每秒操作数）

    Args:
        func: 要测试的函数
        duration_seconds: 测试持续时间（秒）
        concurrency: 并发数
        *args, **kwargs: 传递给函数的参数

    Returns:
        吞吐量结果字典
    """
    counter = {"count": 0, "errors": 0}
    counter_lock = threading.Lock()
    stop_event = threading.Event()

    def worker():
        local_count = 0
        local_errors = 0
        while not stop_event.is_set():
            try:
                func(*args, **kwargs)
                local_count += 1
            except Exception:
                local_errors += 1
        with counter_lock:
            counter["count"] += local_count
            counter["errors"] += local_errors

    threads = []
    with BenchmarkTimer() as total_timer:
        for _ in range(concurrency):
            t = threading.Thread(target=worker)
            threads.append(t)
            t.start()

        # 等待指定时间
        time.sleep(duration_seconds)
        stop_event.set()

        for t in threads:
            t.join()

    actual_duration = total_timer.elapsed_seconds
    ops_per_second = counter["count"] / actual_duration if actual_duration > 0 else 0

    return {
        "total_ops": counter["count"],
        "total_errors": counter["errors"],
        "duration_seconds": round(actual_duration, 3),
        "concurrency": concurrency,
        "ops_per_second": round(ops_per_second, 2),
        "avg_latency_ms": round((actual_duration / counter["count"]) * 1000, 4) if counter["count"] > 0 else 0,
    }
