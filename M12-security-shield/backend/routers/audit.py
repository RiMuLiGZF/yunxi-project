"""
云汐 M12 安全盾 - 安全审计 API
提供安全事件查询、审计日志、统计分析等接口
"""

from fastapi import APIRouter, Query
from typing import Optional

# 兼容相对导入和直接运行
try:
    from ..models import make_response, make_error_response
    from ..services.audit_service import get_audit_service
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from models import make_response, make_error_response
    from services.audit_service import get_audit_service

router = APIRouter(prefix="/api/m12/audit", tags=["M12-安全审计"])


# ===========================================================================
# 安全事件
# ===========================================================================

@router.get("/events", summary="安全事件列表")
def list_events(
    event_type: Optional[str] = Query(None, description="事件类型筛选"),
    severity: Optional[str] = Query(None, description="严重级别筛选"),
    source_ip: Optional[str] = Query(None, description="来源 IP 筛选"),
    status: Optional[str] = Query(None, description="事件状态筛选"),
    keyword: Optional[str] = Query(None, description="关键词搜索"),
    start_time: Optional[str] = Query(None, description="开始时间"),
    end_time: Optional[str] = Query(None, description="结束时间"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
):
    """
    查询安全事件列表，支持多条件筛选和分页
    """
    try:
        audit = get_audit_service()
        result = audit.get_security_events(
            event_type=event_type,
            severity=severity,
            source_ip=source_ip,
            status=status,
            keyword=keyword,
            start_time=start_time,
            end_time=end_time,
            page=page,
            page_size=page_size,
        )
        return make_response(data=result)
    except Exception as e:
        return make_error_response(f"查询安全事件失败: {str(e)}")


@router.get("/events/{event_id}", summary="事件详情")
def get_event_detail(event_id: int):
    """
    获取单个安全事件的详细信息
    """
    try:
        audit = get_audit_service()
        event = audit.get_event_by_id(event_id)
        if not event:
            return make_error_response(f"事件不存在: {event_id}", code=404)
        return make_response(data=event)
    except Exception as e:
        return make_error_response(f"获取事件详情失败: {str(e)}")


@router.post("/events/{event_id}/resolve", summary="处理事件")
def resolve_event(
    event_id: int,
    resolution_note: str = "",
    status: str = "resolved",
):
    """
    处理安全事件（标记为已解决/已忽略等）
    """
    try:
        audit = get_audit_service()
        event = audit.resolve_event(
            event_id=event_id,
            resolution_note=resolution_note,
            status=status,
        )
        if not event:
            return make_error_response(f"事件不存在: {event_id}", code=404)
        return make_response(data=event, message="事件处理完成")
    except Exception as e:
        return make_error_response(f"处理事件失败: {str(e)}")


# ===========================================================================
# 审计日志
# ===========================================================================

@router.get("/logs", summary="审计日志列表")
def list_audit_logs(
    user_id: Optional[str] = Query(None, description="用户 ID 筛选"),
    module: Optional[str] = Query(None, description="模块筛选"),
    action: Optional[str] = Query(None, description="操作类型筛选"),
    status: Optional[str] = Query(None, description="操作状态筛选"),
    source_ip: Optional[str] = Query(None, description="来源 IP 筛选"),
    keyword: Optional[str] = Query(None, description="关键词搜索"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
):
    """
    查询操作审计日志，支持多条件筛选和分页
    """
    try:
        audit = get_audit_service()
        result = audit.get_audit_logs(
            user_id=user_id,
            module=module,
            action=action,
            status=status,
            source_ip=source_ip,
            keyword=keyword,
            page=page,
            page_size=page_size,
        )
        return make_response(data=result)
    except Exception as e:
        return make_error_response(f"查询审计日志失败: {str(e)}")


# ===========================================================================
# 统计分析
# ===========================================================================

@router.get("/stats", summary="审计统计")
def audit_stats():
    """
    获取安全审计的统计数据，包括事件总数、按类型/级别分布等
    """
    try:
        audit = get_audit_service()
        stats = audit.get_stats()
        return make_response(data=stats)
    except Exception as e:
        return make_error_response(f"获取统计数据失败: {str(e)}")


@router.get("/stats/summary", summary="统计概览")
def stats_summary():
    """
    获取安全审计的简要统计概览
    """
    try:
        audit = get_audit_service()
        stats = audit.get_stats()

        summary = {
            "total_events": stats["total_events"],
            "today_events": stats["events_today"],
            "week_events": stats["events_this_week"],
            "high_risk_count": stats["high_severity_count"],
            "medium_risk_count": stats["medium_severity_count"],
            "low_risk_count": stats["low_severity_count"],
            "total_audit_logs": stats["total_audit_logs"],
            "waf_blocks_today": stats["waf_blocks_today"],
        }

        return make_response(data=summary)
    except Exception as e:
        return make_error_response(f"获取统计概览失败: {str(e)}")


@router.get("/stats/by-type", summary="按类型统计")
def stats_by_type():
    """
    按事件类型统计安全事件分布
    """
    try:
        audit = get_audit_service()
        stats = audit.get_stats()

        # 转换为列表格式
        type_list = [
            {"type": k, "count": v}
            for k, v in stats["events_by_type"].items()
        ]
        type_list.sort(key=lambda x: x["count"], reverse=True)

        return make_response(data={
            "items": type_list,
            "total": stats["total_events"],
        })
    except Exception as e:
        return make_error_response(f"获取类型统计失败: {str(e)}")


@router.get("/stats/by-severity", summary="按级别统计")
def stats_by_severity():
    """
    按严重级别统计安全事件分布
    """
    try:
        audit = get_audit_service()
        stats = audit.get_stats()

        # 转换为列表格式
        severity_list = [
            {"level": k, "count": v}
            for k, v in stats["events_by_severity"].items()
        ]

        return make_response(data={
            "items": severity_list,
            "total": stats["total_events"],
        })
    except Exception as e:
        return make_error_response(f"获取级别统计失败: {str(e)}")


@router.get("/stats/trend", summary="趋势数据")
def stats_trend():
    """
    获取安全事件的趋势数据（最近 24 小时，按小时统计）
    """
    try:
        audit = get_audit_service()
        stats = audit.get_stats()
        return make_response(data={
            "trend_data": stats["trend_data"],
            "period": "24h",
            "granularity": "hour",
        })
    except Exception as e:
        return make_error_response(f"获取趋势数据失败: {str(e)}")


@router.get("/stats/top-ips", summary="攻击来源 IP 排行")
def stats_top_ips(
    limit: int = Query(10, ge=1, le=100, description="返回数量"),
):
    """
    获取攻击来源 IP 排行 TOP N
    """
    try:
        audit = get_audit_service()
        stats = audit.get_stats()

        top_ips = stats["top_source_ips"][:limit]

        return make_response(data={
            "items": top_ips,
            "total": len(top_ips),
        })
    except Exception as e:
        return make_error_response(f"获取 IP 排行失败: {str(e)}")
