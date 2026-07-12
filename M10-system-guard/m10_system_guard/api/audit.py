"""
M10 系统卫士 - 审计日志 API

审计日志查询、统计、导出等接口。
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from ..models import make_response
from ..audit_logger import get_audit_logger

router = APIRouter()


def _success(data=None, message: str = "ok"):
    """构造成功响应."""
    return make_response(data=data, message=message)


@router.get("", summary="审计日志列表")
async def audit_logs(
    limit: int = Query(100, ge=1, le=1000, description="返回数量"),
    level: str = Query(None, description="按级别过滤: info/warning/critical"),
    log_type: str = Query(None, description="按类型过滤"),
):
    """查询审计日志列表."""
    logger = get_audit_logger()
    logs = logger.get_logs(limit=limit, level=level, log_type=log_type)
    return _success({
        "total": len(logs),
        "logs": [l.to_dict() for l in logs],
    })


@router.get("/stats", summary="审计统计")
async def audit_stats():
    """获取审计日志统计信息."""
    logger = get_audit_logger()
    stats = logger.get_stats()
    return _success(stats)


@router.get("/types", summary="日志类型列表")
async def audit_types():
    """获取所有日志类型."""
    logger = get_audit_logger()
    types = logger.get_log_types()
    return _success({"types": types})


@router.get("/export", summary="导出审计日志")
async def export_audit(
    format: str = Query("json", description="导出格式: json/csv"),
    level: str = Query(None, description="级别过滤"),
):
    """导出审计日志."""
    logger = get_audit_logger()
    content = logger.export_logs(format=format, level=level)
    return _success({
        "format": format,
        "content": content,
        "size": len(content),
    })


@router.delete("/clear", summary="清空审计日志")
async def clear_audit():
    """清空所有审计日志."""
    logger = get_audit_logger()
    count = logger.clear_logs()
    return _success({"cleared_count": count})
