"""
M10 系统卫士 - 审计日志 API

审计日志查询、统计、导出等接口。
优先从数据库读取，支持分页和时间范围查询。
"""

from __future__ import annotations

import json
import time
from typing import Optional

from fastapi import APIRouter, Query

from ..models import make_response
from ..audit_logger import get_audit_logger

router = APIRouter()


def _success(data=None, message: str = "ok"):
    """构造成功响应."""
    return make_response(data=data, message=message)


def _try_db_query(func_name: str, *args, **kwargs):
    """尝试通过数据库查询，失败则回退到内存."""
    logger = get_audit_logger()
    if not logger._db_enabled:
        return None
    try:
        from ..repositories.audit_repository import AuditRepository
        return getattr(AuditRepository, func_name)(*args, **kwargs)
    except Exception:
        return None


@router.get("", summary="审计日志列表")
async def audit_logs(
    limit: int = Query(100, ge=1, le=1000, description="返回数量"),
    page: int = Query(1, ge=1, description="页码"),
    level: str = Query(None, description="按级别过滤: info/warning/critical"),
    log_type: str = Query(None, description="按类型过滤"),
    start_time: Optional[float] = Query(None, description="开始时间戳"),
    end_time: Optional[float] = Query(None, description="结束时间戳"),
    source: str = Query("auto", description="数据来源: auto/memory/database"),
):
    """查询审计日志列表.

    source=auto: 当数据库持久化已启用时自动从数据库查询，否则从内存查询
    source=memory: 强制从内存缓存查询
    source=database: 强制从数据库查询
    """
    logger = get_audit_logger()

    # 判断是否使用数据库
    use_db = source == "database" or (source == "auto" and logger._db_enabled)

    if use_db:
        offset = (page - 1) * limit
        db_logs = _try_db_query(
            "get_logs",
            limit=limit,
            offset=offset,
            level=level,
            log_type=log_type,
            start_time=start_time,
            end_time=end_time,
        )
        if db_logs is not None:
            db_total = _try_db_query(
                "count_logs",
                level=level,
                log_type=log_type,
                start_time=start_time,
                end_time=end_time,
            )
            return _success({
                "total": db_total or 0,
                "page": page,
                "limit": limit,
                "source": "database",
                "logs": db_logs,
            })

    # 回退：从内存查询
    logs = logger.get_logs(limit=limit, level=level, log_type=log_type,
                           start_time=start_time, end_time=end_time)
    log_dicts = []
    for l in logs:
        if isinstance(l, dict):
            log_dicts.append(l)
        else:
            log_dicts.append(l.to_dict())
    return _success({
        "total": len(log_dicts),
        "page": page,
        "limit": limit,
        "source": "memory",
        "logs": log_dicts,
    })


@router.get("/stats", summary="审计统计")
async def audit_stats():
    """获取审计日志统计信息.

    当数据库持久化已启用时，合并数据库统计结果。
    """
    logger = get_audit_logger()
    stats = logger.get_stats()

    # 如果启用了数据库，额外合并数据库统计
    if logger._db_enabled:
        try:
            db_stats = _try_db_query("get_stats")
            if db_stats:
                # 合并级别统计：数据库数据更全面
                db_total = db_stats.get("total", 0)
                stats["total"] = max(stats.get("total", 0), db_total)
                if "by_level" in db_stats:
                    db_by_level = db_stats["by_level"]
                    for lvl in ("info", "warning", "critical"):
                        stats["by_level"][lvl] = max(
                            stats["by_level"].get(lvl, 0),
                            db_by_level.get(lvl, 0),
                        )
                stats["db_storage"] = True
        except Exception:
            pass

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
    start_time: Optional[float] = Query(None, description="开始时间戳"),
    end_time: Optional[float] = Query(None, description="结束时间戳"),
    source: str = Query("auto", description="数据来源: auto/memory/database"),
):
    """导出审计日志.

    优先从数据库导出，获取更完整的历史数据。
    """
    logger = get_audit_logger()

    # 判断是否使用数据库
    use_db = source == "database" or (source == "auto" and logger._db_enabled)

    if use_db:
        db_logs = _try_db_query(
            "get_logs",
            limit=10000,
            offset=0,
            level=level,
            start_time=start_time,
            end_time=end_time,
        )
        if db_logs is not None:
            content = _format_logs(db_logs, format)
            return _success({
                "format": format,
                "content": content,
                "size": len(content),
                "source": "database",
            })

    # 回退：从内存导出
    content = logger.export_logs(
        format=format, level=level,
        start_time=start_time, end_time=end_time,
    )
    return _success({
        "format": format,
        "content": content,
        "size": len(content),
        "source": "memory",
    })


def _format_logs(logs: list[dict], format: str) -> str:
    """将日志字典列表格式化为指定格式的字符串."""
    if format == "csv":
        lines = ["log_id,timestamp,level,log_type,trigger_condition,action,result"]
        for log in logs:
            line = ",".join([
                str(log.get("log_id", "")),
                str(log.get("timestamp", "")),
                str(log.get("level", "")),
                str(log.get("log_type", "")),
                '"{}"'.format(log.get("trigger_condition", "")),
                '"{}"'.format(log.get("action", "")),
                '"{}"'.format(log.get("result", "")),
            ])
            lines.append(line)
        return "\n".join(lines)
    else:
        return json.dumps(logs, ensure_ascii=False, indent=2)


@router.delete("/clear", summary="清空审计日志")
async def clear_audit():
    """清空所有审计日志.

    同时清空内存缓存和数据库中的审计日志。
    """
    logger = get_audit_logger()
    count = logger.clear_logs()

    # logger.clear_logs 已处理内存和数据库双重清空，
    # 此处再确认数据库也清空（防御性编程）
    if logger._db_enabled:
        try:
            from ..repositories.audit_repository import AuditRepository
            db_count = AuditRepository.clear_logs()
            count = max(count, db_count)
        except Exception:
            pass

    return _success({"cleared_count": count})