"""M11 MCP Bus - 管理控制台路由.

提供管理控制台页面和相关数据 API。
前端采用独立项目结构（frontend/ 目录），纯 HTML/CSS/JS 实现。

Phase 1 安全加固：
- 所有 /api/console/* 数据接口接入 API Key 鉴权
- /console HTML 页面增加鉴权检查（无有效token返回401）
- 数据库会话统一使用 Depends(get_db) 依赖注入

Phase 2 前端工程化升级：
- 前端从 Python 字符串迁移至独立 frontend/ 目录
- 静态文件通过 /static 路径提供
- /console 返回 frontend/index.html 文件
- 保持所有数据接口不变，向后兼容
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..middleware.auth import require_authenticated, get_current_api_key
from ..models_db import ApiKey, McpCall, McpServer, McpTool
from ..services.alert import alert_service
from ..services.monitor import mcp_monitor

router = APIRouter(tags=["console"])

# ============================================================
# 前端目录路径
# ============================================================

# frontend 目录位于项目根目录（src 的上一级）
_FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"
_INDEX_HTML_PATH = _FRONTEND_DIR / "index.html"


# ============================================================
# 路由：控制台页面
# ============================================================

@router.get("/console", response_class=HTMLResponse, summary="管理控制台页面")
async def console_page(
    request: Request,
    api_key: Optional[ApiKey] = Depends(get_current_api_key),
) -> HTMLResponse:
    """管理控制台首页.

    返回独立前端项目的 index.html 页面，展示服务器状态、工具统计、调用记录等信息。
    深色主题，现代简洁风格。

    需要鉴权：未提供有效 API Key 时返回 401 未授权页面。
    """
    # 鉴权检查：如果没有有效 API Key，返回 401
    if api_key is None:
        # 开发环境下 api_key 可能为 None（is_development 且未配置 admin_token）
        # 此时仍然允许访问，但生产环境会在 get_current_api_key 中直接抛出 401
        # 这里做双重检查，确保安全
        settings = get_settings()
        if not settings.is_development:
            raise HTTPException(
                status_code=401,
                detail="需要鉴权才能访问管理控制台",
                headers={"WWW-Authenticate": "Bearer"},
            )

    # 检查 index.html 是否存在
    if not _INDEX_HTML_PATH.exists():
        raise HTTPException(
            status_code=500,
            detail=f"控制台页面文件不存在: {_INDEX_HTML_PATH}",
        )

    return FileResponse(
        path=str(_INDEX_HTML_PATH),
        media_type="text/html",
    )


# ============================================================
# 路由：静态文件
# ============================================================

@router.get("/static/{file_path:path}", summary="控制台静态资源")
async def static_files(
    file_path: str,
    request: Request,
    api_key: Optional[ApiKey] = Depends(get_current_api_key),
):
    """提供控制台前端静态资源（CSS / JS / 图片等）.

    静态文件路径映射：/static/* -> frontend/*

    注意：静态文件通常不需要严格鉴权，但为了安全起见，
    生产环境下同样需要 API Key 才能访问。
    开发环境下可直接访问。
    """
    # 鉴权检查（与 /console 一致）
    if api_key is None:
        settings = get_settings()
        if not settings.is_development:
            raise HTTPException(
                status_code=401,
                detail="需要鉴权才能访问静态资源",
                headers={"WWW-Authenticate": "Bearer"},
            )

    # 安全检查：防止路径遍历攻击
    # 解析目标文件路径并确保它在 frontend 目录内
    target_path = (_FRONTEND_DIR / file_path).resolve()

    try:
        target_path.relative_to(_FRONTEND_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="禁止访问")

    if not target_path.exists() or not target_path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")

    # 根据文件后缀设置 MIME 类型
    return FileResponse(path=str(target_path))


# ============================================================
# 路由：控制台数据 API
# ============================================================

@router.get("/api/console/stats", summary="控制台统计数据")
async def console_stats(
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(require_authenticated),
) -> Dict[str, Any]:
    """获取控制台统计数据.

    返回服务器数、工具数、调用数、成功率、告警数等概览数据。

    需要鉴权。
    """
    # 服务器统计
    total_servers = db.query(McpServer).count()
    online_servers = db.query(McpServer).filter(McpServer.status == "online").count()
    offline_servers = total_servers - online_servers

    # 工具统计
    total_tools = db.query(McpTool).count()

    # 调用统计（从内存 + 数据库）
    monitor_stats = mcp_monitor.get_stats()

    # 告警统计
    alert_stats = alert_service.get_alert_stats()
    active_alerts = alert_service.get_active_alerts()
    alert_list = [a.to_dict() for a in active_alerts[:10]]

    critical_alerts = sum(1 for a in active_alerts if a.severity == "critical")
    warning_alerts = sum(1 for a in active_alerts if a.severity == "warning")

    return {
        "total_servers": total_servers,
        "online_servers": online_servers,
        "offline_servers": offline_servers,
        "total_tools": total_tools,
        "total_calls": monitor_stats.get("total_calls", 0),
        "success_calls": monitor_stats.get("success_calls", 0),
        "failed_calls": monitor_stats.get("failed_calls", 0),
        "success_rate": monitor_stats.get("success_rate", 0.0),
        "avg_duration_ms": monitor_stats.get("avg_duration_ms", 0.0),
        "active_alerts": alert_stats.get("total_active", 0),
        "critical_alerts": critical_alerts,
        "warning_alerts": warning_alerts,
        "alerts": alert_list,
        "popular_tools": monitor_stats.get("popular_tools", []),
    }


@router.get("/api/console/servers", summary="控制台服务器列表")
async def console_servers(
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(require_authenticated),
) -> Dict[str, Any]:
    """获取服务器列表（带状态和工具数量）.

    用于控制台服务器列表展示。

    需要鉴权。
    """
    servers = db.query(McpServer).order_by(McpServer.name.asc()).all()

    server_list = []
    for s in servers:
        tool_count = db.query(McpTool).filter(McpTool.server_id == s.id).count()
        server_list.append({
            "id": s.id,
            "name": s.name,
            "status": s.status,
            "transport_type": s.transport_type,
            "endpoint": s.endpoint or "",
            "tool_count": tool_count,
            "last_heartbeat": s.last_heartbeat.isoformat() if s.last_heartbeat else None,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        })

    return {
        "servers": server_list,
        "total": len(server_list),
    }


@router.get("/api/console/recent-calls", summary="控制台最近调用记录")
async def console_recent_calls(
    limit: int = Query(20, ge=1, le=100, description="返回数量"),
    api_key: ApiKey = Depends(require_authenticated),
) -> Dict[str, Any]:
    """获取最近的调用记录.

    优先从内存环形缓冲区读取，速度快。

    需要鉴权。

    Args:
        limit: 返回数量限制

    Returns:
        调用记录列表
    """
    calls = mcp_monitor.get_recent_calls(limit=limit)
    return {
        "calls": calls,
        "total": len(calls),
    }
