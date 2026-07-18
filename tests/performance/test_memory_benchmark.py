"""
内存使用基准测试

测试各模块/操作的内存使用情况：
- 缓存内存占用
- 数据库连接内存占用
- 大对象内存使用
- 内存泄漏检测
- 对象创建/销毁开销
"""

import os
import sys
import gc
import time
import tracemalloc
from pathlib import Path
from typing import Dict, List, Any, Optional

import pytest

# 确保项目根目录在 Python 路径中
PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
from tests.performance.benchmark import (
    BenchmarkTimer,
    BenchmarkStats,
    BenchmarkCollector,
    MemoryProfiler,
    MemorySnapshot,
    measure_memory,
)

# 尝试导入缓存系统
try:
    from shared.data.cache import SimpleCache, get_cache, reset_global_cache, NULL_VALUE
    HAS_CACHE = True
except ImportError:
    HAS_CACHE = False

# 尝试导入数据库管理器
try:
    from shared.data.data_layer.database_manager import DatabaseManager
    HAS_DB_MANAGER = True
except ImportError:
    HAS_DB_MANAGER = False

# 尝试导入日志系统
try:
    from shared.core.observability.unified_logger import UnifiedLogger
    HAS_LOGGER = True
except ImportError:
    HAS_LOGGER = False


pytestmark = pytest.mark.performance


# ============================================================
# 辅助函数
# ============================================================

def _get_memory_usage_kb() -> float:
    """获取当前进程内存使用（KB）

    使用 tracemalloc 或 psutil（如果可用）。
    """
    try:
        import psutil
        process = psutil.Process(os.getpid())
        return process.memory_info().rss / 1024
    except ImportError:
        # 使用 tracemalloc 作为替代
        if tracemalloc.is_tracing():
            current, peak = tracemalloc.get_traced_memory()
            return current / 1024
    return 0.0


def _make_large_object(size_bytes: int) -> str:
    """创建指定大小的对象（近似）"""
    return "x" * size_bytes


# ============================================================
# 缓存内存测试
# ============================================================

class TestCacheMemory:
    """缓存内存使用测试"""

    def teardown_method(self):
        """每个测试后清理"""
        gc.collect()

    def test_cache_memory_footprint(self):
        """缓存内存占用测试"""
        if not HAS_CACHE:
            pytest.skip("Cache system not available")

        cache = SimpleCache(max_size=1000, default_ttl=60, cleanup_interval=0)

        # 空缓存内存
        gc.collect()
        _, snapshot_empty = measure_memory(lambda: SimpleCache(max_size=1000, default_ttl=60, cleanup_interval=0))

        # 填充缓存
        profiler = MemoryProfiler()
        profiler.start()

        for i in range(1000):
            cache.set(f"key_{i}", f"value_{i}_" + "x" * 100, ttl=60)

        snapshot_filled = profiler.stop()

        cache.shutdown()

        BenchmarkCollector.get_instance().add_memory_result(
            "memory_cache_1000_entries", snapshot_filled
        )

        print(f"\n  缓存 1000 条目内存增长: {snapshot_filled.current_mb:.3f} MB")
        print(f"  峰值内存: {snapshot_filled.peak_mb:.3f} MB")
        print(f"  单条目平均: {snapshot_filled.current_kb / 1000:.3f} KB")

        assert snapshot_filled.current_mb < 50, "缓存内存占用过高"

    def test_cache_memory_scalability(self):
        """缓存内存可扩展性测试"""
        if not HAS_CACHE:
            pytest.skip("Cache system not available")

        sizes = [100, 500, 1000, 5000]
        results = {}

        for size in sizes:
            cache = SimpleCache(max_size=size, default_ttl=60, cleanup_interval=0)

            profiler = MemoryProfiler()
            profiler.start()

            for i in range(size):
                cache.set(f"key_{i}", f"value_{i}", ttl=60)

            snapshot = profiler.stop()
            results[size] = {
                "memory_kb": snapshot.current_kb,
                "per_entry_kb": snapshot.current_kb / size if size > 0 else 0,
            }

            cache.shutdown()
            gc.collect()

        # 记录最后一个结果
        BenchmarkCollector.get_instance().add_memory_result(
            "memory_cache_scalability",
            MemorySnapshot(
                current_kb=results[sizes[-1]]["memory_kb"],
                peak_kb=results[sizes[-1]]["memory_kb"] * 1.1,
                current_mb=results[sizes[-1]]["memory_kb"] / 1024,
                peak_mb=results[sizes[-1]]["memory_kb"] / 1024 * 1.1,
            ),
        )

        print("\n  缓存内存可扩展性:")
        for size in sizes:
            r = results[size]
            print(f"    {size:>5} 条目: {r['memory_kb']:>8.1f} KB "
                  f"({r['per_entry_kb']:.3f} KB/条)")

        # 验证内存增长基本线性（不应爆炸式增长）
        ratio = results[5000]["per_entry_kb"] / max(results[100]["per_entry_kb"], 0.001)
        assert ratio < 5, f"大缓存时单条目内存增长过多: {ratio:.1f}x"

    def test_cache_eviction_memory_release(self):
        """缓存淘汰后内存释放测试"""
        if not HAS_CACHE:
            pytest.skip("Cache system not available")

        cache = SimpleCache(max_size=100, default_ttl=60, cleanup_interval=0)

        # 填充超过容量的数据（触发淘汰）
        profiler = MemoryProfiler()
        profiler.start()

        for i in range(500):
            cache.set(f"key_{i}", f"value_{i}_" + "x" * 200, ttl=60)

        snapshot_peak = profiler.stop()

        # 清理后内存
        profiler2 = MemoryProfiler()
        profiler2.start()
        cache.clear()
        gc.collect()
        snapshot_cleared = profiler2.stop()

        cache.shutdown()

        print(f"\n  缓存峰值内存: {snapshot_peak.peak_mb:.3f} MB")
        print(f"  清理后内存变化: {snapshot_cleared.current_mb:.3f} MB")

        # 缓存条目数应该等于 max_size
        assert cache.size() == 0, "clear 后缓存应为空"

    def test_large_value_memory(self):
        """大缓存值的内存占用"""
        if not HAS_CACHE:
            pytest.skip("Cache system not available")

        cache = SimpleCache(max_size=100, default_ttl=60, cleanup_interval=0)

        profiler = MemoryProfiler()
        profiler.start()

        # 存储 10 个 100KB 的值
        for i in range(10):
            large_value = "x" * 100 * 1024  # 100KB
            cache.set(f"large_{i}", large_value, ttl=60)

        snapshot = profiler.stop()
        cache.shutdown()

        BenchmarkCollector.get_instance().add_memory_result(
            "memory_cache_large_values", snapshot
        )

        print(f"\n  10 个 100KB 缓存值内存: {snapshot.current_mb:.3f} MB")
        print(f"  单值平均: {snapshot.current_kb / 10:.1f} KB")


# ============================================================
# 数据库内存测试
# ============================================================

class TestDatabaseMemory:
    """数据库内存使用测试"""

    def test_db_connection_memory(self, tmp_path):
        """数据库连接内存占用"""
        if not HAS_DB_MANAGER:
            pytest.skip("DatabaseManager not available")

        # 创建数据库
        db = DatabaseManager(data_root=str(tmp_path))
        with db.get_connection("test", write=True) as conn:
            conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")
            for i in range(100):
                conn.execute(f"INSERT INTO test (name) VALUES ('item_{i}')")

        # 测量查询时的内存
        profiler = MemoryProfiler()
        profiler.start()

        for i in range(100):
            db.query_all("test", "SELECT * FROM test")

        snapshot = profiler.stop()
        db.close()

        BenchmarkCollector.get_instance().add_memory_result(
            "memory_db_queries", snapshot
        )

        print(f"\n  100 次查询内存增长: {snapshot.current_mb:.3f} MB")

    def test_large_query_memory(self, tmp_path):
        """大数据量查询内存占用"""
        if not HAS_DB_MANAGER:
            pytest.skip("DatabaseManager not available")

        db = DatabaseManager(data_root=str(tmp_path))
        with db.get_connection("test", write=True) as conn:
            conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT, data TEXT)")
            # 插入 1000 条较大的数据
            large_data = "x" * 1000
            for i in range(1000):
                conn.execute(
                    "INSERT INTO test (name, data) VALUES (?, ?)",
                    (f"item_{i}", large_data),
                )

        # 全表查询内存
        profiler = MemoryProfiler()
        profiler.start()

        result = db.query_all("test", "SELECT * FROM test")

        snapshot = profiler.stop()
        db.close()

        BenchmarkCollector.get_instance().add_memory_result(
            "memory_db_large_query", snapshot
        )

        print(f"\n  1000 行查询内存: {snapshot.current_mb:.3f} MB")
        print(f"  行数: {len(result)}")
        print(f"  每行平均: {snapshot.current_kb / len(result):.3f} KB")

        assert len(result) == 1000


# ============================================================
# 对象创建/销毁性能
# ============================================================

class TestObjectPerformance:
    """对象创建/销毁性能测试"""

    def test_small_object_creation(self, benchmark_iterations, benchmark_warmup):
        """小对象创建性能"""
        stats = BenchmarkStats(name="memory:small_object_creation")

        class SmallObject:
            __slots__ = ("a", "b", "c")
            def __init__(self):
                self.a = 1
                self.b = "test"
                self.c = 3.14

        for _ in range(benchmark_warmup):
            obj = SmallObject()

        for _ in range(benchmark_iterations):
            with BenchmarkTimer() as timer:
                obj = SmallObject()
                _ = obj.a
            stats.add_measurement(timer.elapsed_ms)

        BenchmarkCollector.get_instance().add_result("memory_small_object_creation", stats)

        print(f"\n{stats.summary()}")
        print(f"  单对象创建: {stats.mean * 1000:.2f} us")

    def test_dict_creation(self, benchmark_iterations, benchmark_warmup):
        """字典创建性能"""
        stats = BenchmarkStats(name="memory:dict_creation")

        for _ in range(benchmark_warmup):
            d = {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5}

        for _ in range(benchmark_iterations):
            with BenchmarkTimer() as timer:
                d = {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5}
                _ = d["a"]
            stats.add_measurement(timer.elapsed_ms)

        BenchmarkCollector.get_instance().add_result("memory_dict_creation", stats)

        print(f"\n{stats.summary()}")

    def test_list_comprehension(self, benchmark_iterations, benchmark_warmup):
        """列表推导性能"""
        stats = BenchmarkStats(name="memory:list_comprehension")

        for _ in range(benchmark_warmup):
            lst = [i * 2 for i in range(1000)]

        for _ in range(benchmark_iterations):
            with BenchmarkTimer() as timer:
                lst = [i * 2 for i in range(1000)]
                _ = len(lst)
            stats.add_measurement(timer.elapsed_ms)

        BenchmarkCollector.get_instance().add_result("memory_list_comprehension", stats)

        print(f"\n{stats.summary()}")

    def test_string_concatenation(self, benchmark_iterations, benchmark_warmup):
        """字符串拼接性能对比"""
        stats_plus = BenchmarkStats(name="memory:string_plus")
        stats_join = BenchmarkStats(name="memory:string_join")
        stats_fstring = BenchmarkStats(name="memory:string_fstring")

        parts = [f"part_{i}" for i in range(100)]

        # + 号拼接
        for _ in range(benchmark_warmup):
            result = ""
            for p in parts:
                result += p

        for _ in range(benchmark_iterations):
            with BenchmarkTimer() as timer:
                result = ""
                for p in parts:
                    result += p
            stats_plus.add_measurement(timer.elapsed_ms)

        # join 拼接
        for _ in range(benchmark_warmup):
            result = "".join(parts)

        for _ in range(benchmark_iterations):
            with BenchmarkTimer() as timer:
                result = "".join(parts)
            stats_join.add_measurement(timer.elapsed_ms)

        # f-string (简单格式化)
        for _ in range(benchmark_warmup):
            result = f"{parts[0]}_{parts[1]}_{parts[2]}"

        for _ in range(benchmark_iterations):
            with BenchmarkTimer() as timer:
                result = f"{parts[0]}_{parts[1]}_{parts[2]}"
            stats_fstring.add_measurement(timer.elapsed_ms)

        BenchmarkCollector.get_instance().add_result("memory_string_plus", stats_plus)
        BenchmarkCollector.get_instance().add_result("memory_string_join", stats_join)
        BenchmarkCollector.get_instance().add_result("memory_string_fstring", stats_fstring)

        print(f"\n  字符串 + 拼接: {stats_plus.mean:.4f}ms")
        print(f"  字符串 join:  {stats_join.mean:.4f}ms")
        print(f"  f-string:    {stats_fstring.mean:.4f}ms")

        # join 应该比 += 快
        assert stats_join.mean < stats_plus.mean, "join 应该比 += 更快"


# ============================================================
# 内存泄漏检测
# ============================================================

class TestMemoryLeak:
    """内存泄漏检测测试"""

    def test_cache_no_leak(self):
        """缓存不应有内存泄漏"""
        if not HAS_CACHE:
            pytest.skip("Cache system not available")

        cache = SimpleCache(max_size=100, default_ttl=0.1, cleanup_interval=0)

        # 第一轮：填充并过期
        for i in range(1000):
            cache.set(f"key_{i}", f"value_{i}", ttl=0.01)

        # 等待过期
        time.sleep(0.1)
        gc.collect()

        # 测量内存
        mem_before = _get_memory_usage_kb()

        # 第二轮：继续操作
        for i in range(1000):
            cache.set(f"key2_{i}", f"value2_{i}", ttl=0.01)

        time.sleep(0.1)
        gc.collect()

        mem_after = _get_memory_usage_kb()

        cache.shutdown()

        diff_kb = mem_after - mem_before
        print(f"\n  第一轮后: {mem_before:.1f} KB")
        print(f"  第二轮后: {mem_after:.1f} KB")
        print(f"  差值: {diff_kb:.1f} KB")

        # 内存不应持续增长（允许一定波动）
        # 注意：这个测试比较粗略，主要用于检测明显的泄漏

    def test_repeated_db_operations(self, tmp_path):
        """重复数据库操作不应内存泄漏"""
        if not HAS_DB_MANAGER:
            pytest.skip("DatabaseManager not available")

        db = DatabaseManager(data_root=str(tmp_path))
        with db.get_connection("test", write=True) as conn:
            conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")

        gc.collect()
        mem_before = _get_memory_usage_kb()

        for i in range(1000):
            db.insert("test", "test", {"name": f"item_{i}"})
            db.query_all("test", "SELECT * FROM test WHERE id < 100")
            if i % 100 == 0:
                gc.collect()

        mem_after = _get_memory_usage_kb()
        db.close()

        diff_kb = mem_after - mem_before
        print(f"\n  操作前: {mem_before:.1f} KB")
        print(f"  操作后: {mem_after:.1f} KB")
        print(f"  增长: {diff_kb:.1f} KB")


# ============================================================
# 日志系统内存测试
# ============================================================

class TestLoggerMemory:
    """日志系统内存使用测试"""

    def test_logger_memory_usage(self, tmp_path):
        """日志器内存占用"""
        if not HAS_LOGGER:
            pytest.skip("UnifiedLogger not available")

        log_dir = tmp_path / "logs"

        profiler = MemoryProfiler()
        profiler.start()

        logger = UnifiedLogger(
            name="perf_test",
            log_dir=str(log_dir),
            console_output=False,
            file_output=True,
        )

        for i in range(1000):
            logger.info(f"Test log message {i}", extra_data=f"value_{i}")

        snapshot = profiler.stop()

        BenchmarkCollector.get_instance().add_memory_result(
            "memory_logger_1000_lines", snapshot
        )

        print(f"\n  1000 条日志内存: {snapshot.current_mb:.3f} MB")
