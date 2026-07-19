"""
性能监控 API 路由
- 性能仪表盘
- 性能指标
- 慢请求列表
- 缓存统计
- 清空缓存
- 每日性能报告
- 性能告警
- 告警确认
- 异步任务列表
- 任务详情
- 慢查询日志

大二轮 P3 级体验优化 - 性能监控 API
"""

import sys
import os
import time
from pathlib import Path
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, Field

# 项目根路径
project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from ...schemas import ApiResponse
from ...auth import get_current_user
from ...models import get_db, User

router = APIRouter(prefix="/performance", tags=["性能监控"])

# 延迟导入性能模块（避免循环依赖）
_cache_manager = None
_profiler = None
_metrics = None
_report_gen = None
_task_queue = None
_query_optimizer = None


def _get_cache_manager():
    """获取缓存管理器"""
    global _cache_manager
    if _cache_manager is None:
        from shared.perf.cache_manager import CacheManager
        _cache_manager = CacheManager.from_env()
    return _cache_manager


def _get_profiler():
    """获取性能分析器"""
    global _profiler
    if _profiler is None:
        from shared.perf.profiler import PerformanceProfiler
        _profiler = PerformanceProfiler()
    return _profiler


def _get_metrics():
    """获取指标收集器"""
    global _metrics
    if _metrics is None:
        from shared.perf.metrics import MetricsCollector
        _metrics = MetricsCollector()
    return _metrics


def _get_report_gen():
    """获取报告生成器"""
    global _report_gen
    if _report_gen is None:
        from shared.perf.performance_report import PerformanceReportGenerator
        _report_gen = PerformanceReportGenerator(
            metrics_collector=_get_metrics(),
            cache_manager=_get_cache_manager(),
            profiler=_get_profiler(),
        )
    return _report_gen


def _get_task_queue():
    """获取任务队列"""
    global _task_queue
    if _task_queue is None:
        from shared.perf.async_tasks import AsyncTaskQueue
        _task_queue = AsyncTaskQueue.from_env()
        _task_queue.start()
    return _task_queue


def _get_query_optimizer():
    """获取查询优化器"""
    global _query_optimizer
    if _query_optimizer is None:
        from shared.perf.query_optimizer import QueryOptimizer
        _query_optimizer = QueryOptimizer(
            db_connection=None,
            slow_query_threshold_ms=100.0,
        )
    return _query_optimizer


# ============================================================
# 请求/响应模型
# ============================================================

class ClearCacheRequest(BaseModel):
    pattern: Optional[str] = Field(None, description="缓存键模式，如 user:*，不传则全部清空")


class AckAlertRequest(BaseModel):
    acknowledged_by: str = Field("admin", description="确认者")


# ============================================================
# 1. 性能仪表盘
# ============================================================

@router.get("/dashboard", summary="性能仪表盘")
async def performance_dashboard(
    current_user: User = Depends(get_current_user),
):
    """获取实时性能仪表盘数据"""
    try:
        report_gen = _get_report_gen()
        dashboard = report_gen.get_dashboard()
        return ApiResponse.success(data=dashboard)
    except Exception as e:
        return ApiResponse.error(message=f"获取仪表盘失败: {str(e)}")


# ============================================================
# 2. 性能指标
# ============================================================

@router.get("/metrics", summary="性能指标")
async def performance_metrics(
    metric_type: Optional[str] = Query(None, description="指标类型: api/db/system/all"),
    current_user: User = Depends(get_current_user),
):
    """获取性能指标数据"""
    try:
        metrics = _get_metrics()
        result = {}

        if metric_type in (None, "all", "api"):
            result["api"] = metrics.get_summary()
            result["api_paths"] = metrics.get_api_metrics(limit=50)

        if metric_type in (None, "all", "db"):
            result["db"] = metrics.get_db_metrics()

        if metric_type in (None, "all", "system"):
            result["system"] = metrics.get_system_metrics()

        return ApiResponse.success(data=result)
    except Exception as e:
        return ApiResponse.error(message=f"获取指标失败: {str(e)}")


# ============================================================
# 3. 慢请求列表
# ============================================================

@router.get("/slow-requests", summary="慢请求列表")
async def slow_requests(
    limit: int = Query(50, ge=1, le=500),
    name_filter: Optional[str] = Query(None, description="按名称过滤"),
    current_user: User = Depends(get_current_user),
):
    """获取慢请求列表"""
    try:
        profiler = _get_profiler()
        slow_list = profiler.get_slow_requests(limit=limit, name_filter=name_filter)
        return ApiResponse.success(data={
            "total": len(slow_list),
            "items": slow_list,
        })
    except Exception as e:
        return ApiResponse.error(message=f"获取慢请求失败: {str(e)}")


# ============================================================
# 4. 缓存统计
# ============================================================

@router.get("/cache-stats", summary="缓存统计")
async def cache_stats(
    current_user: User = Depends(get_current_user),
):
    """获取缓存统计信息"""
    try:
        cm = _get_cache_manager()
        stats = cm.get_stats()
        return ApiResponse.success(data=stats)
    except Exception as e:
        return ApiResponse.error(message=f"获取缓存统计失败: {str(e)}")


# ============================================================
# 5. 清空缓存
# ============================================================

@router.post("/cache/clear", summary="清空缓存")
async def clear_cache(
    request: ClearCacheRequest,
    current_user: User = Depends(get_current_user),
):
    """清空缓存，支持按模式匹配"""
    try:
        cm = _get_cache_manager()
        count = cm.clear(pattern=request.pattern)
        return ApiResponse.success(data={
            "cleared_count": count,
            "pattern": request.pattern or "all",
        })
    except Exception as e:
        return ApiResponse.error(message=f"清空缓存失败: {str(e)}")


# ============================================================
# 6. 每日性能报告
# ============================================================

@router.get("/report/daily", summary="每日性能报告")
async def daily_report(
    date: Optional[str] = Query(None, description="日期 YYYY-MM-DD，默认今天"),
    current_user: User = Depends(get_current_user),
):
    """获取每日性能报告"""
    try:
        report_gen = _get_report_gen()
        report = report_gen.get_daily_report(date=date)
        return ApiResponse.success(data=report)
    except Exception as e:
        return ApiResponse.error(message=f"获取日报失败: {str(e)}")


# ============================================================
# 7. 性能告警
# ============================================================

@router.get("/alerts", summary="性能告警列表")
async def performance_alerts(
    level: Optional[str] = Query(None, description="告警级别: info/warning/critical"),
    limit: int = Query(100, ge=1, le=500),
    acknowledged: Optional[bool] = Query(None, description="是否已确认"),
    current_user: User = Depends(get_current_user),
):
    """获取性能告警列表"""
    try:
        from shared.perf.performance_report import AlertLevel
        report_gen = _get_report_gen()

        # 先触发一次告警检查
        report_gen.check_alerts()

        alert_level = None
        if level:
            level_map = {
                "info": AlertLevel.INFO,
                "warning": AlertLevel.WARNING,
                "critical": AlertLevel.CRITICAL,
            }
            alert_level = level_map.get(level.lower())

        alerts = report_gen.get_alerts(
            level=alert_level,
            limit=limit,
            acknowledged=acknowledged,
        )
        return ApiResponse.success(data={
            "total": len(alerts),
            "items": alerts,
        })
    except Exception as e:
        return ApiResponse.error(message=f"获取告警失败: {str(e)}")


# ============================================================
# 8. 确认告警
# ============================================================

@router.post("/alerts/{alert_id}/ack", summary="确认告警")
async def acknowledge_alert(
    alert_id: str,
    request: AckAlertRequest,
    current_user: User = Depends(get_current_user),
):
    """确认指定告警"""
    try:
        report_gen = _get_report_gen()
        success = report_gen.acknowledge_alert(
            alert_id=alert_id,
            acknowledged_by=request.acknowledged_by,
        )
        if not success:
            raise HTTPException(status_code=404, detail="告警不存在")
        return ApiResponse.success(data={"acknowledged": True})
    except HTTPException:
        raise
    except Exception as e:
        return ApiResponse.error(message=f"确认告警失败: {str(e)}")


# ============================================================
# 9. 异步任务列表
# ============================================================

@router.get("/tasks", summary="异步任务列表")
async def task_list(
    status: Optional[str] = Query(None, description="任务状态: pending/running/completed/failed/cancelled"),
    queue: Optional[str] = Query(None, description="队列名"),
    limit: int = Query(100, ge=1, le=500),
    current_user: User = Depends(get_current_user),
):
    """获取异步任务列表"""
    try:
        from shared.perf.async_tasks import TaskStatus
        task_queue = _get_task_queue()

        task_status = None
        if status:
            status_map = {
                "pending": TaskStatus.PENDING,
                "running": TaskStatus.RUNNING,
                "completed": TaskStatus.COMPLETED,
                "failed": TaskStatus.FAILED,
                "cancelled": TaskStatus.CANCELLED,
            }
            task_status = status_map.get(status.lower())

        tasks = task_queue.list_tasks(
            status=task_status,
            queue=queue,
            limit=limit,
        )
        stats = task_queue.get_stats()

        return ApiResponse.success(data={
            "total": len(tasks),
            "items": tasks,
            "stats": stats,
        })
    except Exception as e:
        return ApiResponse.error(message=f"获取任务列表失败: {str(e)}")


# ============================================================
# 10. 任务详情
# ============================================================

@router.get("/tasks/{task_id}", summary="任务详情")
async def task_detail(
    task_id: str,
    current_user: User = Depends(get_current_user),
):
    """获取任务详情"""
    try:
        task_queue = _get_task_queue()
        status = task_queue.get_task_status(task_id)
        if status is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        return ApiResponse.success(data=status)
    except HTTPException:
        raise
    except Exception as e:
        return ApiResponse.error(message=f"获取任务详情失败: {str(e)}")


# ============================================================
# 11. 慢查询日志
# ============================================================

@router.get("/db/slow-queries", summary="慢查询日志")
async def slow_queries(
    limit: int = Query(50, ge=1, le=500),
    min_duration_ms: Optional[float] = Query(None, description="最小耗时(ms)"),
    current_user: User = Depends(get_current_user),
):
    """获取慢查询日志"""
    try:
        optimizer = _get_query_optimizer()
        slow_list = optimizer.get_slow_queries(
            limit=limit,
            min_duration_ms=min_duration_ms,
        )

        # 同时获取指标收集器中的慢查询
        metrics = _get_metrics()
        metrics_slow = metrics.get_slow_queries(limit=limit)

        # 合并去重
        all_slow = slow_list + metrics_slow

        # 索引建议
        suggestions = [s.to_dict() for s in optimizer.get_index_suggestions()]

        return ApiResponse.success(data={
            "total": len(all_slow),
            "items": all_slow[:limit],
            "index_suggestions": suggestions,
        })
    except Exception as e:
        return ApiResponse.error(message=f"获取慢查询失败: {str(e)}")
