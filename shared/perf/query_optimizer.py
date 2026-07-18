"""
查询优化器 (Query Optimizer)

功能:
- 查询缓存
- N+1 查询检测
- 索引建议
- 慢查询日志
- 查询耗时统计

使用方式::

    from shared.perf.query_optimizer import QueryOptimizer

    optimizer = QueryOptimizer(db_connection)

    # 执行查询 (自动记录)
    rows = optimizer.query_all("SELECT * FROM users WHERE id > ?", (100,))

    # 慢查询日志
    slow_log = optimizer.get_slow_queries()

    # 索引建议
    suggestions = optimizer.get_index_suggestions()

    # N+1 检测
    n1_issues = optimizer.detect_n_plus_one()
"""

from __future__ import annotations

import re
import time
import hashlib
import threading
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import deque, defaultdict
from collections import OrderedDict


# ============================================================
# 数据模型
# ============================================================

@dataclass
class QueryRecord:
    """查询记录"""
    sql: str
    params: str
    duration_ms: float
    timestamp: float
    rows_returned: int = 0
    is_slow: bool = False
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sql": self.sql[:500] + "..." if len(self.sql) > 500 else self.sql,
            "params": self.params[:200],
            "duration_ms": round(self.duration_ms, 3),
            "timestamp": self.timestamp,
            "rows_returned": self.rows_returned,
            "is_slow": self.is_slow,
            "error": self.error,
        }


@dataclass
class NPlusOnePattern:
    """N+1 查询模式"""
    base_sql: str
    count: int
    total_duration_ms: float
    avg_duration_ms: float
    parent_context: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "base_sql": self.base_sql[:300],
            "count": count if False else self.count,
            "total_duration_ms": round(self.total_duration_ms, 3),
            "avg_duration_ms": round(self.avg_duration_ms, 3),
            "parent_context": self.parent_context,
        }


@dataclass
class IndexSuggestion:
    """索引建议"""
    table: str
    columns: List[str]
    reason: str
    estimated_benefit: str = "medium"
    sample_query: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "table": self.table,
            "columns": self.columns,
            "reason": self.reason,
            "estimated_benefit": self.estimated_benefit,
            "sample_query": self.sample_query[:300],
        }


# ============================================================
# 查询缓存
# ============================================================

class QueryCache:
    """查询缓存 (LRU + TTL)"""

    def __init__(self, max_size: int = 500, default_ttl: float = 30.0):
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._cache: "OrderedDict[str, Tuple[Any, float]]" = OrderedDict()
        self._table_index: Dict[str, set] = defaultdict(set)
        self._lock = threading.Lock()

        # 统计
        self.hits = 0
        self.misses = 0

    def _make_key(self, sql: str, params: tuple) -> str:
        raw = f"{sql}|{params}"
        return hashlib.md5(raw.encode()).hexdigest()

    def _extract_tables(self, sql: str) -> List[str]:
        tables = []
        matches = re.findall(r'(?:FROM|JOIN|INTO|UPDATE)\s+["`]?(\w+)["`]?', sql, re.IGNORECASE)
        for match in matches:
            if match not in tables and not match.startswith("sqlite_"):
                tables.append(match)
        return tables

    def get(self, sql: str, params: tuple) -> Optional[Any]:
        key = self._make_key(sql, params)
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self.misses += 1
                return None
            result, expire_at = entry
            if expire_at <= time.time():
                del self._cache[key]
                self.misses += 1
                return None
            self._cache.move_to_end(key)
            self.hits += 1
            return result

    def set(self, sql: str, params: tuple, result: Any, ttl: Optional[float] = None) -> None:
        key = self._make_key(sql, params)
        expire_at = time.time() + (ttl or self.default_ttl)
        tables = self._extract_tables(sql)

        with self._lock:
            if key in self._cache:
                del self._cache[key]
            self._cache[key] = (result, expire_at)

            for table in tables:
                self._table_index[table].add(key)

            # LRU 淘汰
            while len(self._cache) > self.max_size:
                old_key, _ = self._cache.popitem(last=False)
                for keys in self._table_index.values():
                    keys.discard(old_key)

    def invalidate_table(self, table: str) -> int:
        """按表名失效缓存"""
        with self._lock:
            keys = self._table_index.get(table, set()).copy()
            for key in keys:
                if key in self._cache:
                    del self._cache[key]
            if table in self._table_index:
                del self._table_index[table]
            # 从其他表索引中移除
            for other_keys in self._table_index.values():
                other_keys -= keys
            return len(keys)

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            total = self.hits + self.misses
            return {
                "size": len(self._cache),
                "max_size": self.max_size,
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": round(self.hits / total, 4) if total > 0 else 0,
                "tables_tracked": len(self._table_index),
            }


# ============================================================
# 查询优化器
# ============================================================

class QueryOptimizer:
    """查询优化器

    功能:
    - 查询缓存 (LRU + TTL，按表失效)
    - N+1 查询检测
    - 索引建议
    - 慢查询日志
    - 查询耗时统计
    """

    def __init__(
        self,
        db_connection=None,
        slow_query_threshold_ms: float = 100.0,
        query_cache_enabled: bool = True,
        query_cache_size: int = 500,
        query_cache_ttl: float = 30.0,
        max_slow_queries: int = 1000,
        max_query_stats: int = 500,
    ):
        self.db = db_connection
        self.slow_query_threshold_ms = slow_query_threshold_ms
        self.query_cache_enabled = query_cache_enabled
        self.max_slow_queries = max_slow_queries
        self.max_query_stats = max_query_stats

        # 查询缓存
        self.query_cache = QueryCache(max_size=query_cache_size, default_ttl=query_cache_ttl)

        # 慢查询日志
        self._slow_queries: deque = deque(maxlen=max_slow_queries)

        # 查询统计 (按规范化 SQL)
        self._query_stats: Dict[str, Dict[str, Any]] = {}
        self._stats_lock = threading.Lock()

        # N+1 检测 (线程本地调用栈)
        self._thread_local = threading.local()

    # ---------- 查询执行 ----------

    def execute_query(
        self,
        sql: str,
        params: Optional[tuple] = None,
        fetch: str = "all",
        use_cache: bool = True,
    ) -> Any:
        """执行查询并记录性能

        Args:
            sql: SQL 语句
            params: 参数
            fetch: "all" / "one" / "none"
            use_cache: 是否使用查询缓存

        Returns:
            查询结果
        """
        params = params or ()

        # 尝试缓存 (只缓存 SELECT)
        if use_cache and self.query_cache_enabled and sql.strip().upper().startswith("SELECT"):
            cached = self.query_cache.get(sql, params)
            if cached is not None:
                return cached

        # 执行查询
        start = time.perf_counter()
        error = None
        result = None
        rows = 0

        try:
            if self.db is None:
                # 无连接，只记录 (用于统计)
                result = []
            else:
                cursor = self.db.cursor()
                cursor.execute(sql, params)
                if fetch == "all":
                    result = cursor.fetchall()
                    rows = len(result) if result else 0
                elif fetch == "one":
                    result = cursor.fetchone()
                    rows = 1 if result else 0
                elif fetch == "none":
                    result = None
                    rows = cursor.rowcount
                cursor.close()
        except Exception as e:
            error = str(e)
            raise

        finally:
            duration = (time.perf_counter() - start) * 1000

            # 记录
            self._record_query(sql, params, duration, rows, error)

            # N+1 检测
            self._check_n_plus_one(sql, duration)

            # 写入缓存 (只缓存 SELECT 且成功的)
            if (
                use_cache
                and self.query_cache_enabled
                and sql.strip().upper().startswith("SELECT")
                and error is None
            ):
                self.query_cache.set(sql, params, result)

        return result

    def query_all(self, sql: str, params: Optional[tuple] = None) -> List[Any]:
        """查询所有行"""
        return self.execute_query(sql, params, fetch="all") or []

    def query_one(self, sql: str, params: Optional[tuple] = None) -> Optional[Any]:
        """查询单行"""
        return self.execute_query(sql, params, fetch="one")

    def execute(self, sql: str, params: Optional[tuple] = None) -> int:
        """执行写操作 (INSERT/UPDATE/DELETE)"""
        result = self.execute_query(sql, params, fetch="none", use_cache=False)

        # 失效相关表的缓存
        tables = self._extract_tables(sql)
        for table in tables:
            self.query_cache.invalidate_table(table)

        return result or 0

    # ---------- 记录与统计 ----------

    def _record_query(
        self,
        sql: str,
        params: tuple,
        duration_ms: float,
        rows_returned: int,
        error: Optional[str],
    ) -> None:
        """记录查询"""
        normalized_sql = self._normalize_sql(sql)
        params_str = str(params)

        # 慢查询
        is_slow = duration_ms > self.slow_query_threshold_ms
        if is_slow or error:
            record = QueryRecord(
                sql=sql,
                params=params_str,
                duration_ms=duration_ms,
                timestamp=time.time(),
                rows_returned=rows_returned,
                is_slow=is_slow,
                error=error,
            )
            self._slow_queries.append(record)

        # 更新统计
        with self._stats_lock:
            stats = self._query_stats.get(normalized_sql)
            if stats is None:
                if len(self._query_stats) >= self.max_query_stats:
                    # 移除调用最少的
                    min_key = min(
                        self._query_stats.keys(),
                        key=lambda k: self._query_stats[k]["count"]
                    )
                    del self._query_stats[min_key]
                stats = {
                    "sql": normalized_sql,
                    "count": 0,
                    "total_time_ms": 0.0,
                    "min_time_ms": float("inf"),
                    "max_time_ms": 0.0,
                    "slow_count": 0,
                    "error_count": 0,
                    "total_rows": 0,
                }
                self._query_stats[normalized_sql] = stats

            stats["count"] += 1
            stats["total_time_ms"] += duration_ms
            stats["min_time_ms"] = min(stats["min_time_ms"], duration_ms)
            stats["max_time_ms"] = max(stats["max_time_ms"], duration_ms)
            if is_slow:
                stats["slow_count"] += 1
            if error:
                stats["error_count"] += 1
            stats["total_rows"] += rows_returned

    def _normalize_sql(self, sql: str) -> str:
        """规范化 SQL (用于分组统计)

        将参数值替换为 ?，去除多余空白等。
        """
        # 去除多余空白
        normalized = re.sub(r'\s+', ' ', sql.strip())
        # 将数字替换为 ?
        normalized = re.sub(r'\b\d+\b', '?', normalized)
        # 将字符串字面量替换为 ?
        normalized = re.sub(r"'[^']*'", '?', normalized)
        normalized = re.sub(r'"[^"]*"', '?', normalized)
        return normalized[:300]

    def _extract_tables(self, sql: str) -> List[str]:
        """提取 SQL 中的表名"""
        tables = []
        matches = re.findall(r'(?:FROM|JOIN|INTO|UPDATE)\s+["`]?(\w+)["`]?', sql, re.IGNORECASE)
        for match in matches:
            if match not in tables and not match.startswith("sqlite_"):
                tables.append(match)
        return tables

    # ---------- N+1 检测 ----------

    def _check_n_plus_one(self, sql: str, duration_ms: float) -> None:
        """N+1 查询检测

        通过线程本地的调用栈检测重复的相似查询。
        """
        if not hasattr(self._thread_local, 'recent_queries'):
            self._thread_local.recent_queries = deque(maxlen=50)
            self._thread_local.n1_patterns: Dict[str, Dict[str, Any]] = {}

        normalized = self._normalize_sql(sql)
        self._thread_local.recent_queries.append({
            "sql": normalized,
            "duration_ms": duration_ms,
            "timestamp": time.time(),
        })

        # 检测模式: 同一规范化 SQL 在短时间内执行多次
        patterns: Dict[str, List[float]] = defaultdict(list)
        for q in self._thread_local.recent_queries:
            patterns[q["sql"]].append(q["duration_ms"])

        n1_detected = []
        for sql_pattern, durations in patterns.items():
            if len(durations) >= 5:  # 5 次以上视为 N+1
                n1_detected.append({
                    "sql": sql_pattern,
                    "count": len(durations),
                    "total_time": sum(durations),
                })

        # 记录检测结果 (简化: 只记录到内存)
        self._thread_local.last_n1_detected = n1_detected

    def detect_n_plus_one(self) -> List[Dict[str, Any]]:
        """获取检测到的 N+1 模式"""
        if hasattr(self._thread_local, 'last_n1_detected'):
            return self._thread_local.last_n1_detected
        return []

    # ---------- 慢查询 ----------

    def get_slow_queries(
        self,
        limit: int = 50,
        min_duration_ms: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """获取慢查询列表"""
        queries = list(self._slow_queries)
        queries.reverse()  # 最新的在前

        if min_duration_ms:
            queries = [q for q in queries if q.duration_ms >= min_duration_ms]

        return [q.to_dict() for q in queries[:limit]]

    # ---------- 索引建议 ----------

    def get_index_suggestions(self) -> List[IndexSuggestion]:
        """生成索引建议

        基于慢查询日志分析，推荐需要添加索引的列。
        """
        suggestions: List[IndexSuggestion] = []
        seen_tables = set()

        for record in self._slow_queries:
            tables = self._extract_tables(record.sql)
            if not tables:
                continue

            # 分析 WHERE 条件中的列
            where_cols = self._extract_where_columns(record.sql)

            for table in tables:
                for col in where_cols:
                    key = f"{table}.{col}"
                    if key in seen_tables:
                        continue
                    seen_tables.add(key)

                    suggestion = IndexSuggestion(
                        table=table,
                        columns=[col],
                        reason=f"慢查询中频繁使用的 WHERE 条件列，查询耗时 {record.duration_ms:.1f}ms",
                        estimated_benefit="high" if record.duration_ms > 500 else "medium",
                        sample_query=record.sql,
                    )
                    suggestions.append(suggestion)

        return suggestions[:20]

    def _extract_where_columns(self, sql: str) -> List[str]:
        """从 SQL 中提取 WHERE 条件的列名 (简单实现)"""
        columns = []
        # 匹配 WHERE 后 =/IN/>/</LIKE 等操作符前的列名
        where_match = re.search(r'WHERE\s+(.+?)(?:ORDER BY|GROUP BY|LIMIT|$)', sql, re.IGNORECASE | re.DOTALL)
        if where_match:
            where_clause = where_match.group(1)
            # 提取列名 (简单模式匹配)
            col_matches = re.findall(r'(\w+)\s*(?:=|!=|<>|>|<|>=|<=|IN|LIKE|BETWEEN)', where_clause, re.IGNORECASE)
            for col in col_matches:
                if col.lower() not in ('and', 'or', 'not', 'null', 'true', 'false') and col not in columns:
                    columns.append(col)
        return columns[:5]  # 最多返回 5 个列

    # ---------- 统计 ----------

    def get_stats(self) -> Dict[str, Any]:
        """获取查询优化统计"""
        with self._stats_lock:
            total_queries = sum(s["count"] for s in self._query_stats.values())
            total_time = sum(s["total_time_ms"] for s in self._query_stats.values())
            total_slow = sum(s["slow_count"] for s in self._query_stats.values())
            total_errors = sum(s["error_count"] for s in self._query_stats.values())

            # 最慢的查询
            sorted_queries = sorted(
                self._query_stats.values(),
                key=lambda s: s["total_time_ms"],
                reverse=True,
            )[:10]

        return {
            "total_queries": total_queries,
            "total_time_ms": round(total_time, 3),
            "avg_time_ms": round(total_time / total_queries, 3) if total_queries > 0 else 0,
            "slow_queries": total_slow,
            "errors": total_errors,
            "error_rate": round(total_errors / total_queries, 4) if total_queries > 0 else 0,
            "unique_queries": len(self._query_stats),
            "cache_stats": self.query_cache.get_stats(),
            "top_slow_queries": [
                {
                    "sql": s["sql"][:200],
                    "count": s["count"],
                    "total_time_ms": round(s["total_time_ms"], 3),
                    "avg_time_ms": round(s["total_time_ms"] / s["count"], 3),
                    "max_time_ms": round(s["max_time_ms"], 3),
                }
                for s in sorted_queries
            ],
        }

    def reset(self) -> None:
        """重置统计"""
        with self._stats_lock:
            self._query_stats.clear()
        self._slow_queries.clear()
        self.query_cache = QueryCache(
            max_size=self.query_cache.max_size,
            default_ttl=self.query_cache.default_ttl,
        )
