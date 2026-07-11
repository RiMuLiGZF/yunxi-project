"""
云汐 M10 系统卫士 - 系统状态 API
提供实时状态、历史数据、健康评分、系统信息等接口
"""

from fastapi import APIRouter, Query
from typing import Optional

# 兼容相对导入和直接运行
try:
    from ..services.system_monitor import get_system_monitor
    from ..services.health_assessor import get_health_assessor
    from ..models import make_response, make_error_response
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from services.system_monitor import get_system_monitor
    from services.health_assessor import get_health_assessor
    from models import make_response, make_error_response

router = APIRouter(prefix="/api/m10/status", tags=["M10-系统状态"])


# ===== 实时状态 =====

@router.get("/realtime", summary="获取实时系统状态")
def get_realtime_status():
    """
    获取系统实时状态数据，包括CPU、内存、磁盘、网络、GPU、电池等全维度指标
    """
    try:
        monitor = get_system_monitor()
        status = monitor.get_realtime_status()
        return make_response(data=status)
    except Exception as e:
        return make_error_response(f"获取实时状态失败: {str(e)}")


# ===== 历史数据 =====

@router.get("/history", summary="获取历史数据")
def get_history(
    start_time: Optional[str] = Query(None, description="开始时间(ISO格式)"),
    end_time: Optional[str] = Query(None, description="结束时间(ISO格式)"),
    metric: Optional[str] = Query(None, description="指标名称，如 cpu_percent, mem_percent"),
    limit: int = Query(60, description="数据点数量限制", ge=1, le=1000),
):
    """
    获取系统指标历史数据，支持按时间范围和指标名称筛选
    """
    try:
        monitor = get_system_monitor()
        history = monitor.get_history(
            start_time=start_time,
            end_time=end_time,
            metric=metric,
            limit=limit,
        )
        return make_response(data={
            "count": len(history),
            "metric": metric,
            "data": history,
        })
    except Exception as e:
        return make_error_response(f"获取历史数据失败: {str(e)}")


# ===== 健康评分 =====

@router.get("/health-score", summary="获取健康评分")
def get_health_score():
    """
    获取系统综合健康评分及各维度评分
    """
    try:
        assessor = get_health_assessor()
        score = assessor.get_health_score()
        return make_response(data=score)
    except Exception as e:
        return make_error_response(f"获取健康评分失败: {str(e)}")


# ===== 系统信息 =====

@router.get("/system-info", summary="获取系统基本信息")
def get_system_info():
    """
    获取系统基本信息，包括操作系统、CPU、内存、GPU、磁盘、电池等硬件配置
    """
    try:
        monitor = get_system_monitor()
        info = monitor.get_system_info()
        return make_response(data=info)
    except Exception as e:
        return make_error_response(f"获取系统信息失败: {str(e)}")


# ===== 支持的指标列表 =====

@router.get("/metrics", summary="列出支持的监控指标")
def list_metrics():
    """
    列出所有支持的系统监控指标及其分类
    """
    try:
        monitor = get_system_monitor()
        metrics = monitor.list_supported_metrics()
        return make_response(data={
            "count": len(metrics),
            "metrics": metrics,
        })
    except Exception as e:
        return make_error_response(f"获取指标列表失败: {str(e)}")


# ===== 沙盒状态 =====

@router.get("/sandbox-status", summary="获取沙盒模式状态")
def get_sandbox_status():
    """
    获取当前沙盒模式的运行状态
    """
    try:
        from ..config import get_settings
        settings = get_settings()
        return make_response(data={
            "sandbox_mode": settings.sandbox_mode,
            "sampling_interval": settings.sampling_interval,
            "data_retention_days": settings.data_retention_days,
        })
    except Exception as e:
        return make_error_response(f"获取沙盒状态失败: {str(e)}")
