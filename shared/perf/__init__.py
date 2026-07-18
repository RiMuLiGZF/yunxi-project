"""
云汐系统性能优化体系 (Performance Optimization Suite)

大二轮 P3 级体验优化 - 统一性能优化入口

模块结构:
- cache_manager:      多级缓存管理器 (L1 内存 + L2 文件 + L3 Redis)
- cache_middleware:   响应缓存中间件 (FastAPI)
- profiler:           性能分析器 (函数耗时/慢请求/调用链)
- metrics:            性能指标收集 (P50/P95/P99/QPS/错误率)
- performance_report: 性能报告 (仪表盘/日报/趋势/告警)
- async_tasks:        异步任务队列 (优先级/重试/Worker 池)
- background_tasks:   后台任务装饰器 (@background_task)
- query_optimizer:    查询优化器 (缓存/N+1检测/索引建议/慢查询)
- connection_pool:    连接池管理 (复用/健康检查/泄漏检测)

使用方式::

    from shared.perf import (
        get_cache_manager,
        get_perf_profiler,
        get_metrics_collector,
        get_async_task_queue,
        background_task,
        cache_result,
        profile_time,
    )
"""

from __future__ import annotations

import os
from typing import Any, Optional


# ============================================================
# 全局开关 - 默认开启但不强制
# ============================================================

PERF_ENABLED = os.getenv("PERF_ENABLED", "true").lower() in ("true", "1", "yes", "on")


# ============================================================
# 延迟导入 (避免循环依赖)
# ============================================================

_cache_manager = None
_profiler = None
_metrics_collector = None
_task_queue = None


def get_cache_manager():
    """获取全局缓存管理器"""
    global _cache_manager
    if _cache_manager is None:
        from shared.perf.cache_manager import CacheManager
        _cache_manager = CacheManager.from_env()
    return _cache_manager


def get_perf_profiler():
    """获取全局性能分析器"""
    global _profiler
    if _profiler is None:
        from shared.perf.profiler import PerformanceProfiler
        _profiler = PerformanceProfiler()
    return _profiler


def get_metrics_collector():
    """获取全局指标收集器"""
    global _metrics_collector
    if _metrics_collector is None:
        from shared.perf.metrics import MetricsCollector
        _metrics_collector = MetricsCollector()
    return _metrics_collector


def get_async_task_queue():
    """获取全局异步任务队列"""
    global _task_queue
    if _task_queue is None:
        from shared.perf.async_tasks import AsyncTaskQueue
        _task_queue = AsyncTaskQueue.from_env()
        _task_queue.start()
    return _task_queue


# ============================================================
# 便捷装饰器 (直接从这里导入使用)
# ============================================================

def cache_result(ttl: float = 60.0, key_prefix: Optional[str] = None):
    """函数结果缓存装饰器 (便捷入口)

    用法::

        @cache_result(ttl=300, key_prefix="user_info")
        def get_user(user_id: int) -> dict:
            ...
    """
    from shared.perf.cache_manager import cache_result as _cache_result
    return _cache_result(ttl=ttl, key_prefix=key_prefix)


def cache_invalidate(pattern: str):
    """缓存失效装饰器 (便捷入口)

    用法::

        @cache_invalidate("user_info:*")
        def update_user(user_id: int, data: dict):
            ...
    """
    from shared.perf.cache_manager import cache_invalidate as _cache_invalidate
    return _cache_invalidate(pattern=pattern)


def profile_time(name: Optional[str] = None, slow_threshold_ms: float = 1000.0):
    """函数耗时统计装饰器 (便捷入口)

    用法::

        @profile_time(name="db_query", slow_threshold_ms=500)
        def query_database(sql: str):
            ...
    """
    from shared.perf.profiler import profile_time as _profile_time
    return _profile_time(name=name, slow_threshold_ms=slow_threshold_ms)


def background_task(queue: str = "default", priority: int = 5, max_retries: int = 3):
    """后台任务装饰器 (便捷入口)

    用法::

        @background_task(queue="io", priority=3, max_retries=3)
        def send_email(to: str, subject: str, body: str):
            ...
    """
    from shared.perf.background_tasks import background_task as _bg_task
    return _bg_task(queue=queue, priority=priority, max_retries=max_retries)


# ============================================================
# 版本信息
# ============================================================

__version__ = "1.0.0"
__all__ = [
    "PERF_ENABLED",
    "get_cache_manager",
    "get_perf_profiler",
    "get_metrics_collector",
    "get_async_task_queue",
    "cache_result",
    "cache_invalidate",
    "profile_time",
    "background_task",
]
