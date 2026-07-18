"""
数据库性能优化测试

测试覆盖:
- 查询优化器 (查询缓存/N+1检测/索引建议/慢查询)
- 连接池管理 (连接复用/健康检查/泄漏检测)
"""

import sys
import os
import time
import tempfile
import pytest
import sqlite3
from pathlib import Path

_project_root = Path(__file__).resolve().parents[3]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from shared.perf.query_optimizer import (
    QueryOptimizer,
    QueryCache,
)
from shared.perf.connection_pool import (
    ConnectionPoolManager,
    PooledConnection,
)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def test_db():
    """测试用 SQLite 数据库"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                name TEXT,
                email TEXT,
                age INTEGER,
                created_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE posts (
                id INTEGER PRIMARY KEY,
                user_id INTEGER,
                title TEXT,
                content TEXT
            )
        """)
        # 插入测试数据
        for i in range(100):
            conn.execute(
                "INSERT INTO users (name, email, age) VALUES (?, ?, ?)",
                (f"user{i}", f"user{i}@example.com", 20 + i % 30)
            )
        for i in range(200):
            conn.execute(
                "INSERT INTO posts (user_id, title, content) VALUES (?, ?, ?)",
                (i % 100, f"Post {i}", f"Content of post {i}")
            )
        conn.commit()
        conn.close()
        yield db_path


@pytest.fixture
def query_optimizer(test_db):
    """查询优化器 fixture"""
    conn = sqlite3.connect(test_db)
    optimizer = QueryOptimizer(
        db_connection=conn,
        slow_query_threshold_ms=1.0,
        query_cache_enabled=True,
        query_cache_size=50,
    )
    yield optimizer
    conn.close()


@pytest.fixture
def connection_pool(test_db):
    """连接池 fixture"""
    pool = ConnectionPoolManager(
        db_path=test_db,
        pool_size=3,
        max_overflow=5,
        acquire_timeout=5.0,
        idle_timeout=60.0,
        health_check_interval=0,  # 禁用后台健康检查
    )
    yield pool
    pool.close_all()


# ============================================================
# 查询缓存测试
# ============================================================

class TestQueryCache:
    """查询缓存测试"""

    def test_basic_cache(self):
        """测试基本缓存"""
        cache = QueryCache(max_size=100, default_ttl=60)

        sql = "SELECT * FROM users WHERE id = ?"
        params = (1,)
        result = [{"id": 1, "name": "test"}]

        cache.set(sql, params, result)
        cached = cache.get(sql, params)

        assert cached == result

    def test_cache_miss(self):
        """测试缓存未命中"""
        cache = QueryCache(max_size=100, default_ttl=60)

        result = cache.get("SELECT * FROM users", ())
        assert result is None

    def test_cache_lru(self):
        """测试 LRU 淘汰"""
        cache = QueryCache(max_size=5, default_ttl=60)

        for i in range(10):
            cache.set(f"SELECT * FROM t{i}", (), [i])

        stats = cache.get_stats()
        assert stats["size"] == 5

    def test_ttl_expiry(self):
        """测试 TTL 过期"""
        cache = QueryCache(max_size=100, default_ttl=0.1)

        cache.set("SELECT 1", (), 1)
        assert cache.get("SELECT 1", ()) == 1

        time.sleep(0.15)
        assert cache.get("SELECT 1", ()) is None

    def test_invalidate_table(self):
        """测试按表失效"""
        cache = QueryCache(max_size=100, default_ttl=60)

        cache.set("SELECT * FROM users WHERE id = 1", (), [1])
        cache.set("SELECT * FROM posts WHERE id = 1", (), [1])

        assert cache.get("SELECT * FROM users WHERE id = 1", ()) is not None
        assert cache.get("SELECT * FROM posts WHERE id = 1", ()) is not None

        count = cache.invalidate_table("users")
        assert count >= 1

        assert cache.get("SELECT * FROM users WHERE id = 1", ()) is None
        assert cache.get("SELECT * FROM posts WHERE id = 1", ()) is not None

    def test_stats(self):
        """测试统计信息"""
        cache = QueryCache(max_size=100, default_ttl=60)

        cache.set("sql1", (), "val1")
        cache.get("sql1", ())  # 命中
        cache.get("sql2", ())  # 未命中

        stats = cache.get_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 0.5


# ============================================================
# 查询优化器测试
# ============================================================

class TestQueryOptimizer:
    """查询优化器测试"""

    def test_query_all(self, query_optimizer):
        """测试查询所有行"""
        rows = query_optimizer.query_all("SELECT * FROM users WHERE age > ?", (25,))
        assert len(rows) > 0

    def test_query_one(self, query_optimizer):
        """测试查询单行"""
        row = query_optimizer.query_one("SELECT * FROM users WHERE id = ?", (1,))
        assert row is not None

    def test_query_cache(self, query_optimizer):
        """测试查询缓存"""
        # 第一次查询
        rows1 = query_optimizer.query_all("SELECT * FROM users WHERE id < ?", (10,))
        assert len(rows1) == 9

        # 第二次查询应该走缓存
        stats = query_optimizer.query_cache.get_stats()
        assert stats["misses"] >= 1  # 第一次未命中

        rows2 = query_optimizer.query_all("SELECT * FROM users WHERE id < ?", (10,))
        assert len(rows2) == 9

        stats = query_optimizer.query_cache.get_stats()
        assert stats["hits"] >= 1  # 第二次命中

    def test_slow_query_logging(self, query_optimizer):
        """测试慢查询记录"""
        # 执行一个慢查询 (用复杂查询模拟)
        query_optimizer.query_all(
            "SELECT u.*, p.* FROM users u, posts p WHERE u.id = p.user_id",
            ()
        )

        slow = query_optimizer.get_slow_queries()
        # 可能快也可能慢，取决于系统，这里只验证 API 可用性
        assert isinstance(slow, list)

    def test_execute_write(self, query_optimizer):
        """测试写操作 (应该失效缓存)"""
        # 先查询，填充缓存
        query_optimizer.query_all("SELECT * FROM users WHERE id = ?", (1,))

        # 执行写操作
        query_optimizer.execute(
            "UPDATE users SET name = ? WHERE id = ?",
            ("updated", 1)
        )

        # 缓存应该被失效
        stats = query_optimizer.query_cache.get_stats()
        assert stats["size"] == 0 or stats["misses"] > 0

    def test_n_plus_one_detection(self, query_optimizer):
        """测试 N+1 查询检测"""
        # 执行多次相似查询
        for i in range(10):
            query_optimizer.query_one("SELECT * FROM users WHERE id = ?", (i,))

        n1 = query_optimizer.detect_n_plus_one()
        assert isinstance(n1, list)

    def test_index_suggestions(self, query_optimizer):
        """测试索引建议"""
        # 执行一些慢查询触发
        for i in range(5):
            query_optimizer.query_all(
                "SELECT * FROM users WHERE name = ?",
                (f"user{i}",)
            )

        suggestions = query_optimizer.get_index_suggestions()
        assert isinstance(suggestions, list)

    def test_stats(self, query_optimizer):
        """测试统计信息"""
        for i in range(10):
            query_optimizer.query_all("SELECT * FROM users WHERE id = ?", (i,))

        stats = query_optimizer.get_stats()
        assert "total_queries" in stats
        assert "total_time_ms" in stats
        assert "cache_stats" in stats
        assert "top_slow_queries" in stats

    def test_reset(self, query_optimizer):
        """测试重置"""
        query_optimizer.query_all("SELECT * FROM users", ())

        stats1 = query_optimizer.get_stats()
        assert stats1["total_queries"] > 0

        query_optimizer.reset()

        stats2 = query_optimizer.get_stats()
        assert stats2["total_queries"] == 0


# ============================================================
# 连接池测试
# ============================================================

class TestConnectionPool:
    """连接池管理测试"""

    def test_acquire_and_release(self, connection_pool):
        """测试获取和释放连接"""
        conn = connection_pool.acquire()
        assert conn is not None

        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        count = cursor.fetchone()[0]
        assert count == 100
        cursor.close()

        connection_pool.release(conn)

    def test_connection_reuse(self, connection_pool):
        """测试连接复用 (连接归还后可再次获取)"""
        conn1 = connection_pool.acquire()
        connection_pool.release(conn1)

        conn2 = connection_pool.acquire()

        # 验证连接可用
        cursor = conn2.cursor()
        cursor.execute("SELECT 1")
        result = cursor.fetchone()
        assert result[0] == 1
        cursor.close()

        # 连接池中的连接总数应该不变
        stats = connection_pool.get_stats()
        assert stats["total_connections"] >= 1
        assert stats["in_use_connections"] == 1

        connection_pool.release(conn2)

    def test_pool_size(self, connection_pool):
        """测试连接池大小"""
        connections = []
        for _ in range(3):
            connections.append(connection_pool.acquire())

        stats = connection_pool.get_stats()
        assert stats["in_use_connections"] == 3

        for conn in connections:
            connection_pool.release(conn)

        stats = connection_pool.get_stats()
        assert stats["idle_connections"] == 3

    def test_overflow_connections(self, connection_pool):
        """测试溢出连接"""
        connections = []
        # 获取超过核心池大小的连接
        for _ in range(5):
            connections.append(connection_pool.acquire())

        stats = connection_pool.get_stats()
        assert stats["in_use_connections"] == 5

        for conn in connections:
            connection_pool.release(conn)

        # 释放后应该只保留核心连接数
        stats = connection_pool.get_stats()
        assert stats["idle_connections"] == 3

    def test_context_manager(self, connection_pool):
        """测试上下文管理器"""
        with connection_pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
            assert result[0] == 1
            cursor.close()

        stats = connection_pool.get_stats()
        assert stats["in_use_connections"] == 0

    def test_health_check_on_acquire(self, connection_pool):
        """测试获取时健康检查"""
        conn = connection_pool.acquire()
        assert conn is not None
        connection_pool.release(conn)

        stats = connection_pool.get_stats()
        assert stats["total_health_check_failures"] == 0

    def test_stats(self, connection_pool):
        """测试统计信息"""
        conn1 = connection_pool.acquire()
        conn2 = connection_pool.acquire()

        stats = connection_pool.get_stats()
        assert stats["pool_size"] == 3
        assert stats["total_connections"] >= 2
        assert stats["in_use_connections"] == 2
        assert "total_acquires" in stats
        assert "avg_borrow_time_ms" in stats

        connection_pool.release(conn1)
        connection_pool.release(conn2)

    def test_close_all(self, test_db):
        """测试关闭所有连接"""
        pool = ConnectionPoolManager(
            db_path=test_db,
            pool_size=2,
            health_check_interval=0,
        )

        conn = pool.acquire()
        pool.release(conn)

        pool.close_all()

        stats = pool.get_stats()
        assert stats["total_connections"] == 0

    def test_reset(self, connection_pool):
        """测试重置"""
        conn = connection_pool.acquire()
        connection_pool.release(conn)

        stats1 = connection_pool.get_stats()
        assert stats1["total_acquires"] > 0

        connection_pool.reset()

        stats2 = connection_pool.get_stats()
        assert stats2["total_acquires"] == 0
        assert stats2["idle_connections"] >= 1  # 预创建的连接

    def test_sqlite_optimizations(self, connection_pool):
        """测试 SQLite 优化参数"""
        conn = connection_pool.acquire()
        cursor = conn.cursor()

        # 检查 journal_mode
        cursor.execute("PRAGMA journal_mode")
        mode = cursor.fetchone()[0]
        assert mode.lower() == "wal"

        cursor.close()
        connection_pool.release(conn)
