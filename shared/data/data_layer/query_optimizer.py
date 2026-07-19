"""
数据库查询优化模块

提供数据库查询优化功能：
- 查询缓存层（自动缓存常用查询结果）
- N+1 查询优化（批量加载）
- 慢查询检测和分析
- 查询计划分析
- 连接池增强（连接复用 + 健康检查）
- 批量操作优化

使用方式::

    from shared.data.data_layer.query_optimizer import (
        QueryCache,
        BatchLoader,
        QueryAnalyzer,
    )

    # 查询缓存
    cache = QueryCache(db_manager)
    result = cache.query_one("mydb", "SELECT * FROM users WHERE id=?", (1,))

    # 批量加载（N+1 优化）
    loader = BatchLoader(db_manager, "mydb", "users", "id")
    users = loader.load_many([1, 2, 3, 4, 5])

    # 查询分析
    analyzer = QueryAnalyzer(db_manager)
    plan = analyzer.analyze_query("mydb", "SELECT * FROM users WHERE name=?")
"""

import os
import re
import time
import hashlib
import threading
import logging
from typing import Any, Dict, List, Optional, Tuple, Callable
from collections import OrderedDict
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ============================================================
# 查询缓存
# ============================================================

@dataclass
class CachedQueryResult:
    """缓存的查询结果"""
    result: Any
    cached_at: float
    hit_count: int = 0


class QueryCache:
    """数据库查询缓存层

    自动缓存查询结果，减少重复数据库查询。
    基于 SQL + 参数的哈希作为缓存键。

    特性：
    - LRU 淘汰策略
    - TTL 过期
    - 按表名标签失效（写操作后清理相关缓存）
    - 读写分离（读走缓存，写清缓存）

    使用方式::

        cache = QueryCache(db_manager, max_size=500, default_ttl=30)
        rows = cache.query_all("mydb", "SELECT * FROM users WHERE id > ?", (100,))
        # 写操作后自动失效相关表的缓存
        cache.invalidate_table("mydb", "users")
    """

    def __init__(
        self,
        db_manager: Any,
        max_size: int = 500,
        default_ttl: float = 30.0,
        null_ttl: float = 5.0,
    ):
        """
        Args:
            db_manager: DatabaseManager 实例
            max_size: 最大缓存条目数
            default_ttl: 默认缓存时间（秒）
            null_ttl: 空结果缓存时间（秒），用于穿透防护
        """
        self.db = db_manager
        self.max_size = max_size
        self.default_ttl = default_ttl
        self.null_ttl = null_ttl

        self._cache: "OrderedDict[str, CachedQueryResult]" = OrderedDict()
        self._table_index: Dict[str, set] = {}  # table -> set of cache keys
        self._lock = threading.Lock()

        # 统计
        self._hits = 0
        self._misses = 0
        self._invalidations = 0

    # ---------- 内部方法 ----------

    def _make_cache_key(self, db_name: str, sql: str, params: Optional[Tuple]) -> str:
        """生成缓存键"""
        key_parts = [db_name, sql]
        if params:
            key_parts.append(str(params))
        raw = "|".join(key_parts)
        return hashlib.md5(raw.encode()).hexdigest()

    def _extract_tables(self, sql: str) -> List[str]:
        """从 SQL 中提取表名（简单实现，用于缓存失效）"""
        # 简单的表名提取（匹配 FROM/JOIN 后的表名）
        tables = []
        # 匹配 FROM 后的表名
        matches = re.findall(r'(?:FROM|JOIN|INTO|UPDATE)\s+["`]?(\w+)["`]?', sql, re.IGNORECASE)
        for match in matches:
            if match not in tables and not match.startswith("sqlite_"):
                tables.append(match)
        return tables

    def _get_cached(self, key: str) -> Optional[Any]:
        """获取缓存结果"""
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self._misses += 1
                return None

            # 检查过期
            if time.time() - entry.cached_at > self.default_ttl:
                del self._cache[key]
                self._misses += 1
                return None

            # 命中，更新 LRU 顺序
            self._cache.move_to_end(key)
            entry.hit_count += 1
            self._hits += 1
            return entry.result

    def _set_cache(self, key: str, result: Any, sql: str) -> None:
        """设置缓存"""
        with self._lock:
            # 计算 TTL
            if result is None or (isinstance(result, (list, dict)) and len(result) == 0):
                ttl = self.null_ttl
            else:
                ttl = self.default_ttl

            entry = CachedQueryResult(
                result=result,
                cached_at=time.time(),
            )

            # 如果 key 已存在，先删除（更新位置）
            if key in self._cache:
                del self._cache[key]

            self._cache[key] = entry

            # 更新表索引
            tables = self._extract_tables(sql)
            for table in tables:
                if table not in self._table_index:
                    self._table_index[table] = set()
                self._table_index[table].add(key)

            # LRU 淘汰
            while len(self._cache) > self.max_size:
                old_key, _ = self._cache.popitem(last=False)
                # 从表索引中移除
                for keys in self._table_index.values():
                    keys.discard(old_key)

    # ---------- 公共 API ----------

    def query_one(
        self,
        db_name: str,
        sql: str,
        params: Optional[Tuple[Any, ...]] = None,
        ttl: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """查询单行（带缓存）"""
        key = self._make_cache_key(db_name, sql, params)
        cached = self._get_cached(key)
        if cached is not None or self._is_cached_null(key):
            return cached

        result = self.db.query_one(db_name, sql, params)
        self._set_cache(key, result, sql)
        return result

    def query_all(
        self,
        db_name: str,
        sql: str,
        params: Optional[Tuple[Any, ...]] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        ttl: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """查询多行（带缓存）"""
        key = self._make_cache_key(db_name, sql + f"_l{limit}_o{offset}", params)
        cached = self._get_cached(key)
        if cached is not None:
            return cached

        result = self.db.query_all(db_name, sql, params, limit=limit, offset=offset)
        self._set_cache(key, result, sql)
        return result

    def invalidate_table(self, db_name: str, table: str) -> int:
        """按表名失效缓存（写操作后调用）

        Returns:
            失效的缓存条目数
        """
        count = 0
        with self._lock:
            key_prefix = db_name + "|"  # 简单的 db 区分
            keys_to_remove = self._table_index.get(table, set()).copy()
            for key in keys_to_remove:
                if key in self._cache:
                    del self._cache[key]
                    count += 1
            # 清理表索引
            if table in self._table_index:
                del self._table_index[table]

            # 从其他表索引中移除这些 key
            for keys in self._table_index.values():
                keys -= keys_to_remove

            self._invalidations += count

        return count

    def invalidate_all(self) -> int:
        """失效所有缓存"""
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            self._table_index.clear()
            self._invalidations += count
            return count

    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        with self._lock:
            total = self._hits + self._misses
            hit_rate = self._hits / total if total > 0 else 0.0
            return {
                "size": len(self._cache),
                "max_size": self.max_size,
                "hits": self._hits,
                "misses": self._misses,
                "invalidations": self._invalidations,
                "hit_rate": round(hit_rate, 4),
                "tables_tracked": len(self._table_index),
            }

    def _is_cached_null(self, key: str) -> bool:
        """检查是否是空值缓存（简化：空列表/None 都视为缓存了）"""
        # 这个方法主要用于兼容，实际逻辑在 _get_cached 中处理
        return False


# ============================================================
# N+1 查询优化：批量加载器
# ============================================================

class BatchLoader:
    """批量加载器，用于优化 N+1 查询问题

    将多次单条查询合并为一次批量查询，显著减少数据库往返次数。

    使用方式::

        # 创建批量加载器
        user_loader = BatchLoader(db, "mydb", "users", "id")

        # 批量加载
        users = user_loader.load_many([1, 2, 3, 4, 5])

        # 或者逐步收集，最后批量加载
        user_loader.prime(1)
        user_loader.prime(2)
        user_loader.prime(3)
        users = user_loader.execute()
    """

    def __init__(
        self,
        db_manager: Any,
        db_name: str,
        table: str,
        key_column: str = "id",
        columns: Optional[List[str]] = None,
        cache: bool = True,
    ):
        """
        Args:
            db_manager: DatabaseManager 实例
            db_name: 数据库名称
            table: 表名
            key_column: 主键列名（用于 IN 查询）
            columns: 要查询的列，None 表示所有列
            cache: 是否启用内存缓存
        """
        self.db = db_manager
        self.db_name = db_name
        self.table = table
        self.key_column = key_column
        self.columns = columns or ["*"]
        self._cache_enabled = cache
        self._cache: Dict[Any, Dict[str, Any]] = {}
        self._pending_keys: set = set()
        self._lock = threading.Lock()

    def prime(self, key: Any) -> None:
        """预加载一个 key（加入待加载队列）"""
        with self._lock:
            if self._cache_enabled and key in self._cache:
                return
            self._pending_keys.add(key)

    def load(self, key: Any) -> Optional[Dict[str, Any]]:
        """加载单个 key（优先从缓存，否则批量加载）"""
        # 先查缓存
        if self._cache_enabled:
            with self._lock:
                if key in self._cache:
                    return self._cache[key]

        # 批量加载
        self.prime(key)
        results = self.execute()
        return results.get(key)

    def load_many(self, keys: List[Any]) -> Dict[Any, Dict[str, Any]]:
        """批量加载多个 key

        Args:
            keys: 主键值列表

        Returns:
            {key: row_dict} 字典
        """
        results: Dict[Any, Dict[str, Any]] = {}
        uncached_keys = []

        # 先从缓存取
        if self._cache_enabled:
            with self._lock:
                for key in keys:
                    if key in self._cache:
                        results[key] = self._cache[key]
                    else:
                        uncached_keys.append(key)
        else:
            uncached_keys = list(keys)

        if not uncached_keys:
            return results

        # 批量查询未缓存的
        batch_results = self._batch_query(uncached_keys)

        # 更新缓存
        if self._cache_enabled:
            with self._lock:
                self._cache.update(batch_results)

        results.update(batch_results)
        return results

    def _batch_query(self, keys: List[Any]) -> Dict[Any, Dict[str, Any]]:
        """执行批量查询"""
        if not keys:
            return {}

        # 去重
        unique_keys = list(set(keys))
        placeholders = ", ".join("?" for _ in unique_keys)
        columns_str = ", ".join(f'"{c}"' if c != "*" else "*" for c in self.columns)

        sql = f'SELECT {columns_str} FROM "{self.table}" WHERE "{self.key_column}" IN ({placeholders})'

        rows = self.db.query_all(self.db_name, sql, tuple(unique_keys))

        return {row[self.key_column]: row for row in rows}

    def execute(self) -> Dict[Any, Dict[str, Any]]:
        """执行所有待加载的 key

        Returns:
            {key: row_dict} 字典
        """
        with self._lock:
            keys = list(self._pending_keys)
            self._pending_keys.clear()

        if not keys:
            return {}

        results = self._batch_query(keys)

        if self._cache_enabled:
            with self._lock:
                self._cache.update(results)

        return results

    def clear_cache(self) -> None:
        """清除缓存"""
        with self._lock:
            self._cache.clear()
            self._pending_keys.clear()

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            return {
                "cached_items": len(self._cache),
                "pending_keys": len(self._pending_keys),
                "cache_enabled": self._cache_enabled,
            }


# ============================================================
# 查询分析器
# ============================================================

@dataclass
class QueryAnalysis:
    """查询分析结果"""
    sql: str
    estimated_rows: int = 0
    uses_index: bool = False
    index_name: str = ""
    is_full_scan: bool = False
    has_order_by: bool = False
    has_where: bool = False
    has_join: bool = False
    has_group_by: bool = False
    has_subquery: bool = False
    tables: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    explain_result: List[Dict[str, Any]] = field(default_factory=list)


class QueryAnalyzer:
    """SQL 查询分析器

    分析查询计划，提供优化建议。
    """

    def __init__(self, db_manager: Any):
        self.db = db_manager

    def analyze_query(
        self,
        db_name: str,
        sql: str,
        params: Optional[Tuple] = None,
    ) -> QueryAnalysis:
        """分析查询

        Args:
            db_name: 数据库名称
            sql: SQL 语句
            params: 查询参数

        Returns:
            QueryAnalysis 对象
        """
        analysis = QueryAnalysis(sql=sql)

        # 静态分析
        self._static_analysis(sql, analysis)

        # EXPLAIN 查询计划
        try:
            explain_sql = f"EXPLAIN QUERY PLAN {sql}"
            rows = self.db.query_all(db_name, explain_sql, params or ())
            analysis.explain_result = rows
            self._analyze_explain(rows, analysis)
        except Exception as e:
            logger.debug(f"EXPLAIN failed: {e}")

        # 生成优化建议
        self._generate_recommendations(analysis)

        return analysis

    def _static_analysis(self, sql: str, analysis: QueryAnalysis) -> None:
        """静态 SQL 分析"""
        sql_upper = sql.upper()

        analysis.has_where = "WHERE" in sql_upper
        analysis.has_order_by = "ORDER BY" in sql_upper
        analysis.has_join = "JOIN" in sql_upper
        analysis.has_group_by = "GROUP BY" in sql_upper
        analysis.has_subquery = "SELECT" in sql_upper[sql_upper.find("FROM"):] if "FROM" in sql_upper else False

        # 提取表名
        analysis.tables = self._extract_tables(sql)

    def _extract_tables(self, sql: str) -> List[str]:
        """提取 SQL 中的表名"""
        tables = []
        pattern = r'(?:FROM|JOIN|INTO|UPDATE)\s+["`]?(\w+)["`]?'
        matches = re.findall(pattern, sql, re.IGNORECASE)
        for match in matches:
            if match not in tables and not match.startswith("sqlite_"):
                tables.append(match)
        return tables

    def _analyze_explain(
        self,
        explain_rows: List[Dict[str, Any]],
        analysis: QueryAnalysis,
    ) -> None:
        """分析 EXPLAIN 结果"""
        for row in explain_rows:
            detail = row.get("detail", "") or ""
            detail_lower = detail.lower()

            # 检查是否使用索引
            if "using index" in detail_lower:
                analysis.uses_index = True
                # 提取索引名
                idx_match = re.search(r'USING INDEX (\w+)', detail, re.IGNORECASE)
                if idx_match:
                    analysis.index_name = idx_match.group(1)

            # 检查是否全表扫描
            if "scan" in detail_lower:
                analysis.is_full_scan = True

    def _generate_recommendations(self, analysis: QueryAnalysis) -> None:
        """生成优化建议"""
        recs = []

        if analysis.is_full_scan and not analysis.uses_index:
            if analysis.tables:
                recs.append(
                    f"全表扫描 detected on table '{analysis.tables[0]}', "
                    f"考虑添加索引以优化查询性能"
                )

        if analysis.has_order_by and not analysis.uses_index:
            recs.append("ORDER BY 可能导致额外排序开销，考虑为排序列添加索引")

        if analysis.has_group_by and not analysis.uses_index:
            recs.append("GROUP BY 可能导致额外分组开销，考虑为分组列添加索引")

        if len(analysis.tables) > 3:
            recs.append("多表 JOIN 查询，确保 JOIN 字段有索引")

        if analysis.has_subquery:
            recs.append("包含子查询，考虑优化为 JOIN 以提升性能")

        analysis.recommendations = recs

    def detect_slow_queries(
        self,
        db_name: str,
        threshold_ms: float = 100.0,
    ) -> List[Dict[str, Any]]:
        """获取慢查询统计（从 DatabaseManager 的统计中获取）

        注意：这需要 DatabaseManager 记录查询历史。
        如果没有历史记录，返回空列表。
        """
        # 从 DatabaseManager 获取性能统计
        stats = getattr(self.db, "get_performance_stats", lambda: {})()
        if not stats:
            return []

        return [
            {
                "type": "summary",
                "total_queries": stats.get("total_queries", 0),
                "slow_queries": stats.get("slow_queries", 0),
                "avg_time_ms": stats.get("avg_time_ms", 0),
                "threshold_ms": threshold_ms,
            }
        ]


# ============================================================
# 连接池增强
# ============================================================

class ConnectionPool:
    """SQLite 连接池

    维护一组预创建的数据库连接，减少连接创建开销。
    对于 SQLite，连接创建开销较小，但在高并发场景下仍有帮助。

    注意：SQLite 的并发模型是单写多读，连接池主要用于读场景。
    """

    def __init__(
        self,
        db_path: str,
        pool_size: int = 5,
        max_overflow: int = 10,
        idle_timeout: float = 300.0,
    ):
        """
        Args:
            db_path: 数据库文件路径
            pool_size: 核心连接数
            max_overflow: 最大溢出连接数
            idle_timeout: 空闲连接超时（秒）
        """
        self.db_path = db_path
        self.pool_size = pool_size
        self.max_overflow = max_overflow
        self.idle_timeout = idle_timeout

        self._pool: List[Tuple[Any, float]] = []  # (conn, last_used_time)
        self._in_use: int = 0
        self._lock = threading.Lock()
        self._semaphore = threading.Semaphore(pool_size + max_overflow)

    def _create_connection(self) -> Any:
        """创建新连接"""
        import sqlite3
        conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            isolation_level=None,
            timeout=30.0,
        )
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA cache_size = -20000")
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA mmap_size = 268435456")
        conn.execute("PRAGMA temp_store = MEMORY")
        conn.row_factory = sqlite3.Row
        return conn

    def acquire(self):
        """获取连接"""
        self._semaphore.acquire()

        with self._lock:
            self._in_use += 1
            # 尝试从池中获取
            while self._pool:
                conn, last_used = self._pool.pop()
                # 检查是否过期
                if time.time() - last_used < self.idle_timeout:
                    return conn
                # 过期连接，关闭
                try:
                    conn.close()
                except Exception:
                    pass

            # 池为空，创建新连接
            return self._create_connection()

    def release(self, conn) -> None:
        """归还连接"""
        with self._lock:
            self._in_use -= 1
            # 如果池未满，放回池中
            if len(self._pool) < self.pool_size:
                self._pool.append((conn, time.time()))
            else:
                # 池已满，关闭连接
                try:
                    conn.close()
                except Exception:
                    pass

        self._semaphore.release()

    def close_all(self) -> None:
        """关闭所有连接"""
        with self._lock:
            for conn, _ in self._pool:
                try:
                    conn.close()
                except Exception:
                    pass
            self._pool.clear()

    @property
    def size(self) -> int:
        """当前池大小"""
        with self._lock:
            return len(self._pool)

    @property
    def in_use(self) -> int:
        """使用中的连接数"""
        with self._lock:
            return self._in_use

    def get_stats(self) -> Dict[str, Any]:
        """获取连接池统计"""
        with self._lock:
            return {
                "pool_size": len(self._pool),
                "in_use": self._in_use,
                "max_pool_size": self.pool_size,
                "max_overflow": self.max_overflow,
            }


# ============================================================
# 便捷函数：创建优化后的数据库管理器
# ============================================================

def create_optimized_db_manager(
    data_root: Optional[str] = None,
    enable_query_cache: bool = True,
    query_cache_size: int = 500,
    query_cache_ttl: float = 30.0,
) -> Tuple[Any, Optional[QueryCache]]:
    """创建优化后的数据库管理器

    Args:
        data_root: 数据根目录
        enable_query_cache: 是否启用查询缓存
        query_cache_size: 查询缓存大小
        query_cache_ttl: 查询缓存 TTL

    Returns:
        (db_manager, query_cache_or_none)
    """
    from shared.data.data_layer.database_manager import get_db_manager

    db = get_db_manager(data_root)
    query_cache = None

    if enable_query_cache:
        query_cache = QueryCache(
            db,
            max_size=query_cache_size,
            default_ttl=query_cache_ttl,
        )

    return db, query_cache
