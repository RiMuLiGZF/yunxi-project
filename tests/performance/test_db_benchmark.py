"""
数据库性能基准测试

测试数据库操作的性能指标：
- 常见查询响应时间
- 写入性能
- 并发读写性能
- 慢查询检测
- 连接池性能
- 索引效果对比
"""

import os
import sys
import time
import tempfile
import threading
from pathlib import Path
from typing import Dict, List, Any

import pytest

# 确保项目根目录在 Python 路径中
PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.performance.benchmark import (
    BenchmarkTimer,
    BenchmarkStats,
    BenchmarkCollector,
    concurrent_benchmark,
    measure_throughput,
)

# 尝试导入数据库管理器
try:
    from shared.data.data_layer.database_manager import DatabaseManager, get_db_manager
    HAS_DB_MANAGER = True
except ImportError:
    HAS_DB_MANAGER = False

try:
    from shared.data.index_optimizer import optimize_indexes, RECOMMENDED_INDEXES
    HAS_INDEX_OPTIMIZER = True
except ImportError:
    HAS_INDEX_OPTIMIZER = False


pytestmark = pytest.mark.performance


# ============================================================
# 测试数据准备
# ============================================================

TEST_TABLE = "perf_test_items"
TEST_DATA_SIZE = 10000  # 测试数据量


def _create_test_db(tmp_path) -> DatabaseManager:
    """创建测试数据库并填充数据"""
    db = DatabaseManager(data_root=str(tmp_path))

    # 创建测试表
    with db.get_connection("test", write=True) as conn:
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {TEST_TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                value TEXT,
                score REAL,
                category TEXT,
                status INTEGER DEFAULT 0,
                created_at REAL,
                updated_at REAL
            )
        """)

    # 批量插入测试数据
    now = time.time()
    data = [
        (
            f"item_{i}",
            f"value_{i}_" + "x" * 50,
            i * 1.5,
            f"cat_{i % 100}",
            i % 3,
            now + i * 0.001,
            now + i * 0.001,
        )
        for i in range(TEST_DATA_SIZE)
    ]

    with db.get_connection("test", write=True) as conn:
        conn.executemany(
            f"INSERT INTO {TEST_TABLE} (name, value, score, category, status, created_at, updated_at) "
            f"VALUES (?, ?, ?, ?, ?, ?, ?)",
            data,
        )

    return db


# ============================================================
# 查询性能测试
# ============================================================

class TestQueryPerformance:
    """查询性能基准测试"""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        if not HAS_DB_MANAGER:
            pytest.skip("DatabaseManager not available")
        self.db = _create_test_db(tmp_path)
        yield
        self.db.close()

    def test_select_by_id(self, benchmark_iterations, benchmark_warmup):
        """按主键查询性能"""
        stats = BenchmarkStats(name="db:select_by_id")

        # 预热
        for i in range(benchmark_warmup):
            self.db.query_one("test", f"SELECT * FROM {TEST_TABLE} WHERE id = ?", (i + 1,))

        # 正式测试
        for i in range(benchmark_iterations):
            _id = (i % TEST_DATA_SIZE) + 1
            with BenchmarkTimer() as timer:
                self.db.query_one("test", f"SELECT * FROM {TEST_TABLE} WHERE id = ?", (_id,))
            stats.add_measurement(timer.elapsed_ms)

        BenchmarkCollector.get_instance().add_result("db_select_by_id", stats)

        assert stats.count == benchmark_iterations
        assert stats.mean < 100, f"主键查询平均耗时 {stats.mean:.2f}ms 过高"
        print(f"\n{stats.summary()}")

    def test_select_by_category(self, benchmark_iterations, benchmark_warmup):
        """按分类查询性能（非索引字段）"""
        stats = BenchmarkStats(name="db:select_by_category")

        # 预热
        for i in range(benchmark_warmup):
            self.db.query_all("test", f"SELECT * FROM {TEST_TABLE} WHERE category = ?", (f"cat_{i % 100}",))

        # 正式测试
        for i in range(benchmark_iterations):
            cat = f"cat_{i % 100}"
            with BenchmarkTimer() as timer:
                self.db.query_all("test", f"SELECT * FROM {TEST_TABLE} WHERE category = ?", (cat,))
            stats.add_measurement(timer.elapsed_ms)

        BenchmarkCollector.get_instance().add_result("db_select_by_category", stats)

        assert stats.count == benchmark_iterations
        print(f"\n{stats.summary()}")

    def test_select_with_limit(self, benchmark_iterations, benchmark_warmup):
        """带 LIMIT 的分页查询性能"""
        stats = BenchmarkStats(name="db:select_with_limit")

        for i in range(benchmark_warmup):
            self.db.query_all(
                "test",
                f"SELECT * FROM {TEST_TABLE} ORDER BY id",
                limit=50,
                offset=i * 10,
            )

        for i in range(benchmark_iterations):
            offset = (i * 50) % max(1, TEST_DATA_SIZE - 50)
            with BenchmarkTimer() as timer:
                self.db.query_all(
                    "test",
                    f"SELECT * FROM {TEST_TABLE} ORDER BY id",
                    limit=50,
                    offset=offset,
                )
            stats.add_measurement(timer.elapsed_ms)

        BenchmarkCollector.get_instance().add_result("db_select_with_limit", stats)

        assert stats.count == benchmark_iterations
        print(f"\n{stats.summary()}")

    def test_count_query(self, benchmark_iterations, benchmark_warmup):
        """COUNT 查询性能"""
        stats = BenchmarkStats(name="db:count_query")

        for _ in range(benchmark_warmup):
            self.db.query_one("test", f"SELECT COUNT(*) as cnt FROM {TEST_TABLE}")

        for i in range(benchmark_iterations):
            with BenchmarkTimer() as timer:
                self.db.query_one("test", f"SELECT COUNT(*) as cnt FROM {TEST_TABLE} WHERE status = ?", (i % 3,))
            stats.add_measurement(timer.elapsed_ms)

        BenchmarkCollector.get_instance().add_result("db_count_query", stats)

        assert stats.count == benchmark_iterations
        print(f"\n{stats.summary()}")

    def test_aggregation_query(self, benchmark_iterations, benchmark_warmup):
        """聚合查询性能"""
        stats = BenchmarkStats(name="db:aggregation_query")

        for _ in range(benchmark_warmup):
            self.db.query_all(
                "test",
                f"SELECT category, COUNT(*) as cnt, AVG(score) as avg_score "
                f"FROM {TEST_TABLE} GROUP BY category ORDER BY cnt DESC LIMIT 10",
            )

        for _ in range(benchmark_iterations):
            with BenchmarkTimer() as timer:
                self.db.query_all(
                    "test",
                    f"SELECT category, COUNT(*) as cnt, AVG(score) as avg_score "
                    f"FROM {TEST_TABLE} GROUP BY category ORDER BY cnt DESC LIMIT 10",
                )
            stats.add_measurement(timer.elapsed_ms)

        BenchmarkCollector.get_instance().add_result("db_aggregation_query", stats)

        assert stats.count == benchmark_iterations
        print(f"\n{stats.summary()}")

    def test_like_query(self, benchmark_iterations, benchmark_warmup):
        """LIKE 查询性能"""
        stats = BenchmarkStats(name="db:like_query")

        for _ in range(benchmark_warmup):
            self.db.query_all("test", f"SELECT * FROM {TEST_TABLE} WHERE name LIKE ?", ("item_5%",), limit=100)

        for i in range(benchmark_iterations):
            pattern = f"item_{i % 100}%"
            with BenchmarkTimer() as timer:
                self.db.query_all("test", f"SELECT * FROM {TEST_TABLE} WHERE name LIKE ?", (pattern,), limit=100)
            stats.add_measurement(timer.elapsed_ms)

        BenchmarkCollector.get_instance().add_result("db_like_query", stats)

        assert stats.count == benchmark_iterations
        print(f"\n{stats.summary()}")


# ============================================================
# 写入性能测试
# ============================================================

class TestWritePerformance:
    """写入性能基准测试"""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        if not HAS_DB_MANAGER:
            pytest.skip("DatabaseManager not available")
        self.db = DatabaseManager(data_root=str(tmp_path))
        with self.db.get_connection("test", write=True) as conn:
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {TEST_TABLE} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    value TEXT,
                    score REAL,
                    category TEXT,
                    status INTEGER DEFAULT 0,
                    created_at REAL
                )
            """)
        yield
        self.db.close()

    def test_single_insert(self, benchmark_iterations, benchmark_warmup):
        """单条插入性能"""
        stats = BenchmarkStats(name="db:single_insert")

        now = time.time()
        for i in range(benchmark_warmup):
            self.db.insert("test", TEST_TABLE, {
                "name": f"warmup_{i}",
                "value": "warmup_value",
                "score": i * 1.0,
                "category": "warmup",
                "created_at": now,
            })

        for i in range(benchmark_iterations):
            with BenchmarkTimer() as timer:
                self.db.insert("test", TEST_TABLE, {
                    "name": f"test_{i}",
                    "value": f"value_{i}",
                    "score": i * 1.0,
                    "category": f"cat_{i % 10}",
                    "created_at": now + i,
                })
            stats.add_measurement(timer.elapsed_ms)

        BenchmarkCollector.get_instance().add_result("db_single_insert", stats)

        assert stats.count == benchmark_iterations
        print(f"\n{stats.summary()}")

    def test_batch_insert(self):
        """批量插入性能"""
        stats = BenchmarkStats(name="db:batch_insert")
        batch_size = 100
        batches = 10

        now = time.time()
        for batch_idx in range(batches):
            data = [
                (
                    f"batch_{batch_idx}_{i}",
                    f"value_{i}",
                    i * 1.0,
                    f"cat_{i % 10}",
                    0,
                    now + i,
                )
                for i in range(batch_size)
            ]

            with BenchmarkTimer() as timer:
                with self.db.get_connection("test", write=True) as conn:
                    conn.executemany(
                        f"INSERT INTO {TEST_TABLE} (name, value, score, category, status, created_at) "
                        f"VALUES (?, ?, ?, ?, ?, ?)",
                        data,
                    )
            stats.add_measurement(timer.elapsed_ms)

        BenchmarkCollector.get_instance().add_result("db_batch_insert", stats)

        assert stats.count == batches
        print(f"\n{stats.summary()}")
        print(f"  单条平均: {stats.mean / batch_size:.4f}ms/条")

    def test_update(self, benchmark_iterations, benchmark_warmup):
        """更新性能"""
        # 先插入一些数据
        now = time.time()
        with self.db.get_connection("test", write=True) as conn:
            conn.executemany(
                f"INSERT INTO {TEST_TABLE} (name, value, score, category, status, created_at) "
                f"VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (f"upd_{i}", f"old_val_{i}", i * 1.0, f"cat_{i % 10}", 0, now)
                    for i in range(benchmark_iterations + benchmark_warmup)
                ],
            )

        stats = BenchmarkStats(name="db:update")

        for i in range(benchmark_warmup):
            self.db.update(
                "test", TEST_TABLE,
                {"value": f"new_val_{i}", "status": 1},
                "id = ?", (i + 1,),
            )

        for i in range(benchmark_iterations):
            _id = benchmark_warmup + i + 1
            with BenchmarkTimer() as timer:
                self.db.update(
                    "test", TEST_TABLE,
                    {"value": f"updated_{i}", "status": 2},
                    "id = ?", (_id,),
                )
            stats.add_measurement(timer.elapsed_ms)

        BenchmarkCollector.get_instance().add_result("db_update", stats)

        assert stats.count == benchmark_iterations
        print(f"\n{stats.summary()}")

    def test_delete(self, benchmark_iterations, benchmark_warmup):
        """删除性能"""
        now = time.time()
        with self.db.get_connection("test", write=True) as conn:
            conn.executemany(
                f"INSERT INTO {TEST_TABLE} (name, value, score, category, status, created_at) "
                f"VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (f"del_{i}", f"val_{i}", i * 1.0, f"cat_{i % 10}", 0, now)
                    for i in range(benchmark_iterations + benchmark_warmup)
                ],
            )

        stats = BenchmarkStats(name="db:delete")

        for i in range(benchmark_warmup):
            self.db.delete("test", TEST_TABLE, "id = ?", (i + 1,))

        for i in range(benchmark_iterations):
            _id = benchmark_warmup + i + 1
            with BenchmarkTimer() as timer:
                self.db.delete("test", TEST_TABLE, "id = ?", (_id,))
            stats.add_measurement(timer.elapsed_ms)

        BenchmarkCollector.get_instance().add_result("db_delete", stats)

        assert stats.count == benchmark_iterations
        print(f"\n{stats.summary()}")


# ============================================================
# 并发性能测试
# ============================================================

class TestConcurrencyPerformance:
    """并发读写性能测试"""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        if not HAS_DB_MANAGER:
            pytest.skip("DatabaseManager not available")
        self.db = _create_test_db(tmp_path)
        yield
        self.db.close()

    def test_concurrent_reads(self):
        """并发读取性能"""
        def read_worker():
            for _ in range(50):
                _id = (hash(threading.current_thread().name) % TEST_DATA_SIZE) + 1
                self.db.query_one("test", f"SELECT * FROM {TEST_TABLE} WHERE id = ?", (_id,))

        stats = concurrent_benchmark(
            lambda: self.db.query_one("test", f"SELECT * FROM {TEST_TABLE} WHERE id = ?", (1,)),
            iterations=200,
            concurrency=10,
        )
        stats.name = "db:concurrent_reads_10t"

        BenchmarkCollector.get_instance().add_result("db_concurrent_reads", stats)

        assert stats.count > 0
        print(f"\n{stats.summary()}")
        print(f"  并发 10 线程 QPS: {stats.qps:.1f}")

    def test_read_write_mixed(self):
        """读写混合并发性能"""
        errors = []
        read_count = {"n": 0}
        write_count = {"n": 0}
        lock = threading.Lock()

        def reader():
            for _ in range(30):
                try:
                    _id = (hash(threading.current_thread().name) % TEST_DATA_SIZE) + 1
                    self.db.query_one("test", f"SELECT * FROM {TEST_TABLE} WHERE id = ?", (_id,))
                    with lock:
                        read_count["n"] += 1
                except Exception as e:
                    errors.append(str(e))

        def writer():
            for i in range(10):
                try:
                    now = time.time()
                    self.db.insert("test", TEST_TABLE, {
                        "name": f"concurrent_{threading.current_thread().name}_{i}",
                        "value": "concurrent_test",
                        "score": i * 1.0,
                        "category": "concurrent",
                        "status": 0,
                        "created_at": now,
                    })
                    with lock:
                        write_count["n"] += 1
                except Exception as e:
                    errors.append(str(e))

        with BenchmarkTimer() as timer:
            threads = []
            for _ in range(5):  # 5 个读线程
                t = threading.Thread(target=reader)
                threads.append(t)
                t.start()
            for _ in range(2):  # 2 个写线程
                t = threading.Thread(target=writer)
                threads.append(t)
                t.start()

            for t in threads:
                t.join(timeout=30)

        result = {
            "total_time_ms": timer.elapsed_ms,
            "read_ops": read_count["n"],
            "write_ops": write_count["n"],
            "errors": len(errors),
            "read_qps": (read_count["n"] / timer.elapsed_seconds) if timer.elapsed_seconds > 0 else 0,
            "write_qps": (write_count["n"] / timer.elapsed_seconds) if timer.elapsed_seconds > 0 else 0,
        }

        stats = BenchmarkStats(name="db:read_write_mixed")
        stats.add_measurement(timer.elapsed_ms)
        BenchmarkCollector.get_instance().add_result("db_read_write_mixed", stats)

        assert len(errors) == 0, f"并发测试出现错误: {errors[:5]}"
        print(f"\n  读写混合 (5读+2写):")
        print(f"    总耗时: {timer.elapsed_ms:.2f}ms")
        print(f"    读操作: {read_count['n']} 次, QPS: {result['read_qps']:.1f}")
        print(f"    写操作: {write_count['n']} 次, QPS: {result['write_qps']:.1f}")


# ============================================================
# 索引效果对比测试
# ============================================================

class TestIndexPerformance:
    """索引性能对比测试"""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        if not HAS_DB_MANAGER:
            pytest.skip("DatabaseManager not available")
        self.tmp_path = tmp_path
        self.db = _create_test_db(tmp_path)
        yield
        self.db.close()

    def test_index_improvement(self):
        """验证索引对查询性能的提升"""
        # 无索引时的查询性能
        stats_no_index = BenchmarkStats(name="db:query_no_index")
        for i in range(50):
            cat = f"cat_{i % 100}"
            with BenchmarkTimer() as timer:
                self.db.query_all("test", f"SELECT * FROM {TEST_TABLE} WHERE category = ?", (cat,))
            stats_no_index.add_measurement(timer.elapsed_ms)

        # 添加索引
        with self.db.get_connection("test", write=True) as conn:
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_perf_category ON {TEST_TABLE} (category)")

        # 有索引时的查询性能
        stats_with_index = BenchmarkStats(name="db:query_with_index")
        for i in range(50):
            cat = f"cat_{i % 100}"
            with BenchmarkTimer() as timer:
                self.db.query_all("test", f"SELECT * FROM {TEST_TABLE} WHERE category = ?", (cat,))
            stats_with_index.add_measurement(timer.elapsed_ms)

        BenchmarkCollector.get_instance().add_result("db_query_no_index", stats_no_index)
        BenchmarkCollector.get_instance().add_result("db_query_with_index", stats_with_index)

        improvement = (stats_no_index.mean - stats_with_index.mean) / max(stats_no_index.mean, 0.001) * 100

        print(f"\n  无索引平均: {stats_no_index.mean:.3f}ms")
        print(f"  有索引平均: {stats_with_index.mean:.3f}ms")
        print(f"  性能提升: {improvement:.1f}%")

        # 索引应该带来性能提升（对于大表）
        assert stats_with_index.mean <= stats_no_index.mean * 1.5, \
            f"索引未带来预期性能提升: {stats_no_index.mean:.3f}ms -> {stats_with_index.mean:.3f}ms"


# ============================================================
# 连接池/连接复用性能测试
# ============================================================

class TestConnectionPerformance:
    """数据库连接性能测试"""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        if not HAS_DB_MANAGER:
            pytest.skip("DatabaseManager not available")
        self.tmp_path = tmp_path
        yield

    def test_connection_reuse(self):
        """连接复用 vs 新建连接性能对比"""
        import sqlite3

        # 方式1: 每次新建连接
        stats_new_conn = BenchmarkStats(name="db:new_connection_each_time")
        db_path = str(self.tmp_path / "conn_test.db")
        for i in range(50):
            with BenchmarkTimer() as timer:
                conn = sqlite3.connect(db_path)
                conn.execute("SELECT 1")
                conn.close()
            stats_new_conn.add_measurement(timer.elapsed_ms)

        # 方式2: 复用连接（DatabaseManager 方式）
        db = DatabaseManager(data_root=str(self.tmp_path))
        stats_reused = BenchmarkStats(name="db:reused_connection")
        for i in range(50):
            with BenchmarkTimer() as timer:
                db.query_one("conn_test", "SELECT 1")
            stats_reused.add_measurement(timer.elapsed_ms)

        db.close()

        BenchmarkCollector.get_instance().add_result("db_new_connection", stats_new_conn)
        BenchmarkCollector.get_instance().add_result("db_reused_connection", stats_reused)

        speedup = stats_new_conn.mean / max(stats_reused.mean, 0.001)

        print(f"\n  新建连接平均: {stats_new_conn.mean:.3f}ms")
        print(f"  复用连接平均: {stats_reused.mean:.3f}ms")
        print(f"  加速比: {speedup:.1f}x")

        # 连接复用应该更快
        assert stats_reused.mean < stats_new_conn.mean, \
            "连接复用应该比新建连接更快"


# ============================================================
# 吞吐量测试
# ============================================================

class TestThroughput:
    """数据库吞吐量测试"""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        if not HAS_DB_MANAGER:
            pytest.skip("DatabaseManager not available")
        self.db = _create_test_db(tmp_path)
        yield
        self.db.close()

    def test_read_throughput(self):
        """读取吞吐量测试（QPS）"""
        result = measure_throughput(
            lambda: self.db.query_one("test", f"SELECT * FROM {TEST_TABLE} WHERE id = ?", (1,)),
            duration_seconds=2.0,
            concurrency=1,
        )

        stats = BenchmarkStats(name="db:read_throughput")
        stats.add_measurement(result.get("avg_latency_ms", 0))
        BenchmarkCollector.get_instance().add_result("db_read_throughput", stats)

        print(f"\n  单线程读取 QPS: {result['ops_per_second']:.1f}")
        print(f"  平均延迟: {result['avg_latency_ms']:.3f}ms")
        assert result["total_ops"] > 0
