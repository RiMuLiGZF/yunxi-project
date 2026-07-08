"""
云汐 M10 系统卫士 - 告警通知 API
提供告警列表、告警统计、告警确认/解决、告警设置等接口
"""

from fastapi import APIRouter, Query
from typing import Optional

# 兼容相对导入和直接运行
try:
    from ..services.alert_manager import get_alert_manager
    from ..models import make_response, make_error_response
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from services.alert_manager import get_alert_manager
    from models import make_response, make_error_response

router = APIRouter(prefix="/api/m10/alerts", tags=["M10-告警通知"])


# ===== 告警列表 =====

@router.get("", summary="获取告警列表")
def get_alerts(
    level: Optional[str] = Query(None, description="告警级别: info/warning/critical/emergency"),
    resolved: Optional[bool] = Query(None, description="是否已解决"),
    limit: int = Query(50, description="返回数量限制", ge=1, le=500),
    offset: int = Query(0, description="偏移量", ge=0),
):
    """
    获取告警记录列表，支持按级别和解决状态筛选
    """
    try:
        manager = get_alert_manager()
        result = manager.get_alerts(
            level=level,
            resolved=resolved,
            limit=limit,
            offset=offset,
        )
        return make_response(data=result)
    except Exception as e:
        return make_error_response(f"获取告警列表失败: {str(e)}")


# ===== 未解决告警数 =====

@router.get("/unresolved", summary="获取未解决告警数")
def get_unresolved_count():
    """
    获取各级别未解决告警的数量统计
    """
    try:
        manager = get_alert_manager()
        count = manager.get_unresolved_count()
        return make_response(data=count)
    except Exception as e:
        return make_error_response(f"获取未解决告警数失败: {str(e)}")


# ===== 确认告警 =====

@router.post("/{alert_id}/acknowledge", summary="确认告警")
def acknowledge_alert(alert_id: int):
    """
    确认指定告警，标记为已读
    """
    try:
        manager = get_alert_manager()
        success = manager.acknowledge_alert(alert_id)
        if success:
            return make_response(data={"acknowledged": True}, message="告警已确认")
        else:
            return make_error_response("告警不存在或确认失败", code=404)
    except Exception as e:
        return make_error_response(f"确认告警失败: {str(e)}")


# ===== 标记已解决 =====

@router.post("/{alert_id}/resolve", summary="标记告警已解决")
def resolve_alert(
    alert_id: int,
    note: str = Query("", description="解决说明"),
):
    """
    标记指定告警为已解决状态
    """
    try:
        manager = get_alert_manager()
        success = manager.resolve_alert(alert_id, note=note)
        if success:
            return make_response(data={"resolved": True}, message="告警已解决")
        else:
            return make_error_response("告警不存在或解决失败", code=404)
    except Exception as e:
        return make_error_response(f"解决告警失败: {str(e)}")


# ===== 告警设置 =====

@router.get("/settings", summary="获取告警设置")
def get_alert_settings():
    """
    获取告警系统的配置参数
    """
    try:
        manager = get_alert_manager()
        settings = manager.get_alert_settings()
        return make_response(data=settings)
    except Exception as e:
        return make_error_response(f"获取告警设置失败: {str(e)}")


@router.post("/settings", summary="更新告警设置")
def update_alert_settings(
    memory_warning_threshold: Optional[float] = Query(None, description="内存警告阈值(%)"),
    memory_danger_threshold: Optional[float] = Query(None, description="内存危险阈值(%)"),
    cpu_warning_threshold: Optional[float] = Query(None, description="CPU警告阈值(%)"),
    cpu_danger_threshold: Optional[float] = Query(None, description="CPU危险阈值(%)"),
    alert_suppression_minutes: Optional[int] = Query(None, description="告警抑制时间(分钟)"),
    enabled: Optional[bool] = Query(None, description="是否启用告警"),
):
    """
    更新告警系统的配置参数
    """
    try:
        manager = get_alert_manager()
        settings = {}
        if memory_warning_threshold is not None:
            settings["memory_warning_threshold"] = memory_warning_threshold
        if memory_danger_threshold is not None:
            settings["memory_danger_threshold"] = memory_danger_threshold
        if cpu_warning_threshold is not None:
            settings["cpu_warning_threshold"] = cpu_warning_threshold
        if cpu_danger_threshold is not None:
            settings["cpu_danger_threshold"] = cpu_danger_threshold
        if alert_suppression_minutes is not None:
            settings["alert_suppression_minutes"] = alert_suppression_minutes
        if enabled is not None:
            settings["enabled"] = enabled

        updated = manager.update_alert_settings(settings)
        return make_response(data=updated, message="设置已更新")
    except Exception as e:
        return make_error_response(f"更新告警设置失败: {str(e)}")


# ===== 告警统计 =====

@router.get("/statistics", summary="获取告警统计")
def get_alert_statistics(
    days: int = Query(7, description="统计天数", ge=1, le=90),
):
    """
    获取指定时间范围内的告警统计数据
    """
    try:
        manager = get_alert_manager()
        stats = manager.get_alert_statistics(days=days)
        return make_response(data=stats)
    except Exception as e:
        return make_error_response(f"获取告警统计失败: {str(e)}")


# ===== 检查生成告警 =====

@router.post("/check", summary="检查并生成告警")
def check_and_generate_alerts():
    """
    手动触发一次告警检查，根据当前系统状态生成新告警
    """
    try:
        manager = get_alert_manager()
        new_alerts = manager.check_and_generate_alerts()
        return make_response(data={
            "new_alert_count": len(new_alerts),
            "new_alerts": new_alerts,
        }, message="告警检查完成")
    except Exception as e:
        return make_error_response(f"告警检查失败: {str(e)}")
