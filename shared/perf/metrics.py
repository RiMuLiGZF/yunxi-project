"""
性能指标收集 (Metrics Collector)

收集的指标:
- API 响应时间统计 (P50/P95/P99)
- 吞吐量 (QPS)
- 错误率
- 并发数
- 内存/CPU 使用情况
- 数据库查询耗时

使用方式::

    from shared.perf.metrics import MetricsCollector

    metrics = MetricsCollector()

    # 记录请求
    metrics.record_request("/api/users", 200, 12.5)  # path, status, duration_ms

    # 记录数据库查询
    metrics.record_db_query("SELECT * FROM users", 5.2)

    # 获取指标
    summary = metrics.get_summary()
    api_metrics = metrics.get_api_metrics()
"""

from __future__ import annotations

import os
import time
import threading
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict, deque


# ============================================================
# 数据结构
# ============================================================

@dataclass
class RequestMetrics:
    """单路径请求指标"""
    path: str
    request_count: int = 0
    error_count: int = 0
    total_time_ms: float = 0.0
    durations: deque = field(default_factory=lambda: deque(maxlen=1000))

    @property
    def error_rate(self) -> float:
        return self.error_count / self.request_count if self.request_count > 0 else 0.0

    @property
    def avg_time_ms(self) -> float:
        return self.total_time_ms / self.request_count if self.request_count > 0 else 0.0

    def percentiles(self) -> Dict[str, float]:
        """计算百分位"""
        if not self.durations:
            return {"p50": 0.0, "p95": 0.0, "p99": 0.0}
        sorted_d = sorted(self.durations)
        n = len(sorted_d)
        return {
            "p50": sorted_d[int(n * 0.50)],
            "p95": sorted_d[int(n * 0.95)],
            "p99": sorted_d[int(n * 0.99)],
        }

    def to_dict(self) -> Dict[str, Any]:
        pct = self.percentiles()
        return {
            "path": self.path,
            "request_count": self.request_count,
            "error_count": self.error_count,
            "error_rate": round(self.error_rate, 4),
            "avg_time_ms": round(self.avg_time_ms, 3),
            "p50_ms": round(pct["p50"], 3),
            "p95_ms": round(pct["p95"], 3),
            "p99_ms": round(pct["p99"], 3),
        }


@dataclass
class DbQueryMetrics:
    """数据库查询指标"""
    query_count: int = 0
    slow_count: int = 0
    total_time_ms: float = 0.0
    durations: deque = field(default_factory=lambda: deque(maxlen=1000))
    slow_queries: deque = field(default_factory=lambda: deque(maxlen=100))

    @property
    def avg_time_ms(self) -> float:
        return self.total_time_ms / self.query_count if self.query_count > 0 else 0.0

    def percentiles(self) -> Dict[str, float]:
        if not self.durations:
            return {"p50": 0.0, "p95": 0.0, "p99": 0.0}
        sorted_d = sorted(self.durations)
        n = len(sorted_d)
        return {
            "p50": sorted_d[int(n * 0.50)],
            "p95": sorted_d[int(n * 0.95)],
            "p99": sorted_d[int(n * 0.99)],
        }

    def to_dict(self) -> Dict[str, Any]:
        pct = self.percentiles()
        return {
            "query_count": self.query_count,
            "slow_count": self.slow_count,
            "avg_time_ms": round(self.avg_time_ms, 3),
            "p50_ms": round(pct["p50"], 3),
            "p95_ms": round(pct["p95"], 3),
            "p99_ms": round(pct["p99"], 3),
            "slow_queries": list(self.slow_queries),
        }


# ============================================================
# 滑动窗口 QPS 计算器
# ============================================================

class SlidingWindowQPS:
    """滑动窗口 QPS 计算器

    使用时间窗口计算 QPS，支持 1m/5m/15m 等多窗口。
    """

    def __init__(self, window_seconds: int = 60, bucket_count: int = 60):
        self.window_seconds = window_seconds
        self.bucket_count = bucket_count
        self.bucket_seconds = window_seconds / bucket_count
        self._buckets: deque = deque(maxlen=bucket_count)
        self._current_bucket_time = 0.0
        self._current_bucket_count = 0
        self._lock = threading.Lock()

    def record(self, count: int = 1) -> None:
        """记录一次请求"""
        now = time.time()
        with self._lock:
            bucket_start = int(now / self.bucket_seconds) * self.bucket_seconds
            if bucket_start != self._current_bucket_time:
                # 推进到新的 bucket
                self._buckets.append((self._current_bucket_time, self._current_bucket_count))
                self._current_bucket_time = bucket_start
                self._current_bucket_count = 0
            self._current_bucket_count += count

    def get_qps(self) -> float:
        """获取当前 QPS"""
        now = time.time()
        with self._lock:
            # 计算窗口内的总请求数
            cutoff = now - self.window_seconds
            total = 0
            for bucket_time, bucket_count in self._buckets:
                if bucket_time >= cutoff:
                    total += bucket_count
            # 当前 bucket (部分时间)
            if self._current_bucket_time >= cutoff:
                total += self._current_bucket_count
            return total / self.window_seconds

    def get_count(self) -> int:
        """获取窗口内的总请求数"""
        now = time.time()
        with self._lock:
            cutoff = now - self.window_seconds
            total = 0
            for bucket_time, bucket_count in self._buckets:
                if bucket_time >= cutoff:
                    total += bucket_count
            if self._current_bucket_time >= cutoff:
                total += self._current_bucket_count
            return total


# ============================================================
# 指标收集器
# ============================================================

class MetricsCollector:
    """性能指标收集器

    收集的指标:
    - API 响应时间 (按路径)
    - 吞吐量 (QPS, 1m/5m/15m)
    - 错误率
    - 并发数
    - 数据库查询耗时
    - 内存/CPU 使用情况 (可选)
    """

    def __init__(
        self,
        max_paths: int = 200,
        slow_query_threshold_ms: float = 100.0,
        enable_system_metrics: bool = True,
    ):
        self.max_paths = max_paths
        self.slow_query_threshold_ms = slow_query_threshold_ms
        self.enable_system_metrics = enable_system_metrics

        # API 指标 (按路径)
        self._api_metrics: Dict[str, RequestMetrics] = {}
        self._api_lock = threading.Lock()

        # 数据库查询指标
        self._db_metrics = DbQueryMetrics()
        self._db_lock = threading.Lock()

        # QPS 计算器 (多窗口)
        self._qps_1m = SlidingWindowQPS(window_seconds=60)
        self._qps_5m = SlidingWindowQPS(window_seconds=300)
        self._qps_15m = SlidingWindowQPS(window_seconds=900)

        # 并发数
        self._concurrent_requests = 0
        self._peak_concurrent = 0
        self._concurrent_lock = threading.Lock()

        # 启动时间
        self._start_time = time.time()
        self._total_requests = 0

        # 系统指标缓存
        self._system_metrics_cache: Dict[str, Any] = {}
        self._system_metrics_time = 0.0
        self._system_metrics_ttl = 1.0  # 1 秒缓存

    # ---------- API 请求 ----------

    def record_request(
        self,
        path: str,
        status_code: int,
        duration_ms: float,
        method: str = "GET",
    ) -> None:
        """记录 API 请求

        Args:
            path: 请求路径
            status_code: HTTP 状态码
            duration_ms: 耗时 (毫秒)
            method: HTTP 方法
        """
        self._total_requests += 1

        # 更新 QPS
        self._qps_1m.record()
        self._qps_5m.record()
        self._qps_15m.record()

        # 更新路径统计
        with self._api_lock:
            metrics = self._api_metrics.get(path)
            if metrics is None:
                # 限制路径数量
                if len(self._api_metrics) >= self.max_paths:
                    # 移除请求最少的
                    min_path = min(self._api_metrics.keys(), key=lambda p: self._api_metrics[p].request_count)
                    del self._api_metrics[min_path]
                metrics = RequestMetrics(path=path)
                self._api_metrics[path] = metrics

            metrics.request_count += 1
            metrics.total_time_ms += duration_ms
            metrics.durations.append(duration_ms)

            if status_code >= 400:
                metrics.error_count += 1

    def record_request_start(self) -> None:
        """记录请求开始 (用于并发数统计)"""
        with self._concurrent_lock:
            self._concurrent_requests += 1
            if self._concurrent_requests > self._peak_concurrent:
                self._peak_concurrent = self._concurrent_requests

    def record_request_end(self) -> None:
        """记录请求结束 (用于并发数统计)"""
        with self._concurrent_lock:
            self._concurrent_requests = max(0, self._concurrent_requests - 1)

    # ---------- 数据库查询 ----------

    def record_db_query(
        self,
        sql: str,
        duration_ms: float,
        rows_affected: int = 0,
    ) -> None:
        """记录数据库查询

        Args:
            sql: SQL 语句 (简化/摘要)
            duration_ms: 耗时 (毫秒)
            rows_affected: 影响行数
        """
        with self._db_lock:
            self._db_metrics.query_count += 1
            self._db_metrics.total_time_ms += duration_ms
            self._db_metrics.durations.append(duration_ms)

            if duration_ms > self.slow_query_threshold_ms:
                self._db_metrics.slow_count += 1
                # 记录慢查询 (截取 SQL)
                short_sql = sql[:200] + "..." if len(sql) > 200 else sql
                self._db_metrics.slow_queries.append({
                    "sql": short_sql,
                    "duration_ms": round(duration_ms, 3),
                    "timestamp": time.time(),
                    "rows_affected": rows_affected,
                })

    # ---------- 系统指标 ----------

    def get_system_metrics(self) -> Dict[str, Any]:
        """获取系统资源使用情况 (内存/CPU)

        需要 psutil 库，不可用时返回空字典。
        """
        now = time.time()
        if now - self._system_metrics_time < self._system_metrics_ttl:
            return self._system_metrics_cache

        if not self.enable_system_metrics:
            return {}

        try:
            import psutil  # type: ignore

            process = psutil.Process(os.getpid())
            mem_info = process.memory_info()

            metrics = {
                "memory": {
                    "rss_mb": round(mem_info.rss / 1024 / 1024, 2),
                    "vms_mb": round(mem_info.vms / 1024 / 1024, 2),
                    "percent": round(process.memory_percent(), 2),
                },
                "cpu": {
                    "percent": round(process.cpu_percent(interval=0.1), 2),
                    "num_threads": process.num_threads(),
                },
                "system_memory": {
                    "total_mb": round(psutil.virtual_memory().total / 1024 / 1024, 2),
                    "available_mb": round(psutil.virtual_memory().available / 1024 / 1024, 2),
                    "percent": psutil.virtual_memory().percent,
                },
                "system_cpu": {
                    "percent": round(psutil.cpu_percent(interval=0.1), 2),
                    "count": psutil.cpu_count(),
                },
            }

            self._system_metrics_cache = metrics
            self._system_metrics_time = now
            return metrics

        except ImportError:
            return {"error": "psutil not installed"}
        except Exception:
            return {}

    # ---------- 获取指标 ----------

    def get_summary(self) -> Dict[str, Any]:
        """获取总体指标摘要"""
        with self._api_lock:
            total_requests = sum(m.request_count for m in self._api_metrics.values())
            total_errors = sum(m.error_count for m in self._api_metrics.values())
            all_durations: List[float] = []
            for m in self._api_metrics.values():
                all_durations.extend(m.durations)

        error_rate = total_errors / total_requests if total_requests > 0 else 0.0

        # 总体百分位
        p50 = p95 = p99 = 0.0
        if all_durations:
            sorted_d = sorted(all_durations)
            n = len(sorted_d)
            p50 = sorted_d[int(n * 0.50)]
            p95 = sorted_d[int(n * 0.95)]
            p99 = sorted_d[int(n * 0.99)]

        with self._concurrent_lock:
            concurrent = self._concurrent_requests
            peak_concurrent = self._peak_concurrent

        uptime_seconds = time.time() - self._start_time

        return {
            "uptime_seconds": round(uptime_seconds, 1),
            "total_requests": self._total_requests,
            "total_errors": total_errors,
            "error_rate": round(error_rate, 4),
            "avg_response_time_ms": round(
                sum(d for m in self._api_metrics.values() for d in m.durations) / len(all_durations)
                if all_durations else 0,
                3,
            ),
            "p50_ms": round(p50, 3),
            "p95_ms": round(p95, 3),
            "p99_ms": round(p99, 3),
            "qps": {
                "1m": round(self._qps_1m.get_qps(), 2),
                "5m": round(self._qps_5m.get_qps(), 2),
                "15m": round(self._qps_15m.get_qps(), 2),
            },
            "concurrent_requests": concurrent,
            "peak_concurrent_requests": peak_concurrent,
            "tracked_paths": len(self._api_metrics),
        }

    def get_api_metrics(
        self,
        path: Optional[str] = None,
        sort_by: str = "request_count",
        limit: int = 50,
    ) -> Any:
        """获取 API 指标

        Args:
            path: 指定路径，None 返回所有
            sort_by: 排序字段
            limit: 返回数量

        Returns:
            指标数据
        """
        with self._api_lock:
            if path:
                metrics = self._api_metrics.get(path)
                return metrics.to_dict() if metrics else {}

            all_metrics = list(self._api_metrics.values())

        all_metrics.sort(key=lambda m: getattr(m, sort_by, 0), reverse=True)

        return [m.to_dict() for m in all_metrics[:limit]]

    def get_db_metrics(self) -> Dict[str, Any]:
        """获取数据库指标"""
        with self._db_lock:
            return self._db_metrics.to_dict()

    def get_slow_queries(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取慢查询列表"""
        with self._db_lock:
            queries = list(self._db_metrics.slow_queries)
        queries.reverse()  # 最新的在前
        return queries[:limit]

    # ---------- 重置 ----------

    def reset(self) -> None:
        """重置所有指标"""
        with self._api_lock:
            self._api_metrics.clear()
        with self._db_lock:
            self._db_metrics = DbQueryMetrics()
        with self._concurrent_lock:
            self._concurrent_requests = 0
            self._peak_concurrent = 0
        self._start_time = time.time()
        self._total_requests = 0
        self._qps_1m = SlidingWindowQPS(window_seconds=60)
        self._qps_5m = SlidingWindowQPS(window_seconds=300)
        self._qps_15m = SlidingWindowQPS(window_seconds=900)
