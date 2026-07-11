"""M11 MCP Bus - M8 标准健康检查路由.

提供 M8 标准的 health、metrics、config 接口，
以及简化的健康检查端点。
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter
from sqlalchemy import text

from ..config import get_settings
from ..db import get_session
from ..models import ConfigResponse, HealthResponse, MetricsResponse
from ..models_db import McpServer, McpTool
from ..services.monitor import mcp_monitor
from ..services.registry import mcp_registry

router = APIRouter(tags=["health"])

# 服务启动时间
_start_time = time.time()


def _get_uptime_seconds() -> float:
    """获取服务运行时长（秒）."""
    return time.time() - start_time if False else time.time() - _start_time


def _check_db_status() -> str:
    """检查数据库连接状态.

    Returns:
        "healthy" 或 "unhealthy"
    """
    try:
        db = get_session()
        # 执行一个简单查询验证连接
        db.execute(text("SELECT 1"))
        db.close()
        return "healthy"
    except Exception:
        return "unhealthy"


@router.get("/m8/health", response_model=HealthResponse, summary="M8 标准健康检查")
async def m8_health() -> HealthResponse:
    """M8 标准健康检查接口.

    返回服务状态、版本、运行时长、数据库状态等信息。
    """
    settings = get_settings()
    uptime = _get_uptime_seconds()
    db_status = _check_db_status()

    # 获取服务器数量统计
    try:
        servers = mcp_registry.list_servers()
        online_count = sum(1 for s in servers if s.status == "online")
    except Exception:
        online_count = 0
        servers = []

    return HealthResponse(
        status="healthy" if db_status == "healthy" else "degraded",
        module="m11",
        version="0.1.0",
        timestamp=datetime.utcnow(),
        details={
            "uptime_seconds": round(uptime, 2),
            "uptime_human": _format_uptime(uptime),
            "db_status": db_status,
            "total_servers": len(servers),
            "online_servers": online_count,
            "env": settings.env,
        },
    )


@router.get("/m8/metrics", response_model=MetricsResponse, summary="M8 标准性能指标")
async def m8_metrics() -> MetricsResponse:
    """M8 标准性能指标接口.

    返回服务器状态、工具数量、调用统计、系统资源等指标。
    """
    settings = get_settings()

    # 服务器和工具统计
    try:
        servers = mcp_registry.list_servers()
        online_count = sum(1 for s in servers if s.status == "online")
    except Exception:
        servers = []
        online_count = 0

    try:
        db = get_session()
        total_tools = db.query(McpTool).count()
        db.close()
    except Exception:
        total_tools = 0

    # 调用统计
    stats = mcp_monitor.get_stats()

    # 系统指标
    system_metrics = mcp_monitor.get_system_metrics()

    return MetricsResponse(
        module="m11",
        timestamp=datetime.utcnow(),
        total_servers=len(servers),
        online_servers=online_count,
        total_tools=total_tools,
        total_calls=stats["total_calls"],
        success_rate=stats["success_rate"],
        avg_duration_ms=stats["avg_duration_ms"],
        cpu_percent=system_metrics.get("cpu_percent", 0.0),
        memory_percent=system_metrics.get("memory_percent", 0.0),
    )


@router.get("/m8/config", response_model=ConfigResponse, summary="M8 标准配置查询")
async def m8_config() -> ConfigResponse:
    """M8 标准配置查询接口.

    返回可公开的配置信息，不含密钥等敏感数据。
    """
    settings = get_settings()

    return ConfigResponse(
        module="m11",
        version="0.1.0",
        env=settings.env,
        port=settings.port,
        heartbeat_timeout=settings.heartbeat_timeout,
        tool_refresh_interval=settings.tool_refresh_interval,
        db_path=str(settings.db_file_path),
        log_level=settings.log_level,
    )


@router.get("/health", summary="简化健康检查")
async def simple_health() -> Dict[str, Any]:
    """简化健康检查接口.

    仅返回基本状态信息，用于负载均衡等简单场景。
    """
    db_status = _check_db_status()
    return {
        "status": "ok" if db_status == "healthy" else "degraded",
        "module": "M11 MCP Bus",
        "version": "0.1.0",
        "timestamp": datetime.utcnow().isoformat(),
    }


def _format_uptime(seconds: float) -> str:
    """格式化运行时长为人类可读格式.

    Args:
        seconds: 秒数

    Returns:
        格式化后的字符串，如 "2天 3小时 15分"
    """
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    parts = []
    if days > 0:
        parts.append(f"{days}天")
    if hours > 0:
        parts.append(f"{hours}小时")
    if minutes > 0:
        parts.append(f"{minutes}分")
    parts.append(f"{secs}秒")

    return " ".join(parts)
