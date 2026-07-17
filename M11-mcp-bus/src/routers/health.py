"""M11 MCP Bus - M8 标准健康检查路由.

提供 M8 标准的 health、metrics、config 接口，
以及简化的健康检查端点。

第三阶段增强：接入 shared.core.observability 标准化健康检查，
支持 deep 深度检查、Prometheus 指标输出。
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter, Query
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

# 标准化健康检查器（懒加载）
_m11_health_checker = None
_m11_obs_available = None


def _get_obs_available() -> bool:
    """检查标准化可观测性是否可用（带缓存）."""
    global _m11_obs_available
    if _m11_obs_available is not None:
        return _m11_obs_available

    try:
        from shared.core.observability import HealthChecker  # noqa: F401
        _m11_obs_available = True
    except ImportError:
        _m11_obs_available = False

    return _m11_obs_available


def _get_health_checker():
    """获取或创建 M11 标准化健康检查器."""
    global _m11_health_checker
    if _m11_health_checker is not None:
        return _m11_health_checker

    if not _get_obs_available():
        return None

    try:
        from shared.core.observability import HealthChecker
        from shared.core.health import CheckResult

        settings = get_settings()
        checker = HealthChecker(
            module_name="m11",
            version="0.1.0",
            module_display_name="MCP 总线",
        )

        # 注册轻量检查：内存
        checker.register_memory_check(threshold_percent=90.0, lightweight=True)

        # 注册轻量检查：磁盘
        checker.register_disk_check(
            path=".",
            threshold_percent=90.0,
            lightweight=True,
        )

        # 注册深度检查：数据库（核心）
        def _check_db() -> CheckResult:
            start_t = time.time()
            try:
                db = get_session()
                try:
                    db.execute(text("SELECT 1"))
                    resp_ms = (time.time() - start_t) * 1000
                    return CheckResult.healthy(
                        type="sqlalchemy",
                        response_time_ms=resp_ms,
                    )
                except Exception as e:
                    resp_ms = (time.time() - start_t) * 1000
                    return CheckResult.unhealthy(
                        error=str(e),
                        type="sqlalchemy",
                        response_time_ms=resp_ms,
                    )
                finally:
                    db.close()
            except Exception as e:
                resp_ms = (time.time() - start_t) * 1000
                return CheckResult.unhealthy(
                    error=str(e),
                    type="sqlalchemy",
                    response_time_ms=resp_ms,
                )

        checker.register_check("database", _check_db, critical=True, lightweight=False)

        # 注册深度检查：Redis（非核心）
        def _check_redis() -> CheckResult:
            start_t = time.time()
            try:
                from ..services.redis_client import redis_client
                if redis_client.is_available():
                    resp_ms = (time.time() - start_t) * 1000
                    return CheckResult.healthy(
                        type="redis",
                        response_time_ms=resp_ms,
                    )
                resp_ms = (time.time() - start_t) * 1000
                return CheckResult.degraded(
                    error="Redis not available (memory mode)",
                    type="redis",
                    response_time_ms=resp_ms,
                )
            except Exception as e:
                resp_ms = (time.time() - start_t) * 1000
                return CheckResult.degraded(
                    error=str(e),
                    type="redis",
                    response_time_ms=resp_ms,
                )

        checker.register_check("redis", _check_redis, critical=False, lightweight=False)

        # 注册深度检查：MCP 服务注册中心
        def _check_mcp_registry() -> CheckResult:
            start_t = time.time()
            try:
                servers = mcp_registry.list_servers()
                online_count = sum(1 for s in servers if s.status == "online")
                total_count = len(servers)
                resp_ms = (time.time() - start_t) * 1000
                return CheckResult.healthy(
                    total_servers=total_count,
                    online_servers=online_count,
                    offline_servers=total_count - online_count,
                    response_time_ms=resp_ms,
                )
            except Exception as e:
                resp_ms = (time.time() - start_t) * 1000
                return CheckResult.degraded(
                    error=str(e),
                    response_time_ms=resp_ms,
                )

        checker.register_check("mcp_registry", _check_mcp_registry, critical=False, lightweight=False)

        _m11_health_checker = checker
        return checker

    except Exception:
        return None


def _get_uptime_seconds() -> float:
    """获取服务运行时长（秒）."""
    return time.time() - _start_time


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
async def simple_health(
    deep: bool = Query(default=False, description="是否执行深度检查（检查所有依赖）"),
) -> Dict[str, Any]:
    """健康检查端点（标准化格式）.

    - 轻量检查（默认）：内存、磁盘等基础指标
    - 深度检查（deep=true）：数据库、Redis、MCP 注册中心等所有依赖

    返回标准健康检查格式。
    """
    # 优先使用标准化健康检查器
    checker = _get_health_checker()
    if checker is not None:
        result = await checker.async_check(deep=deep)
        return result.to_dict()

    # 回退到旧版实现
    db_status = _check_db_status()
    return {
        "status": "healthy" if db_status == "healthy" else "degraded",
        "module": "m11",
        "version": "0.1.0",
        "timestamp": datetime.utcnow().isoformat(),
        "uptime_seconds": round(_get_uptime_seconds(), 2),
    }


@router.get("/metrics", summary="Prometheus 指标")
async def prometheus_metrics():
    """Prometheus 格式的指标端点."""
    from fastapi import Response

    if _get_obs_available():
        try:
            from shared.core.observability import get_metrics
            metrics = get_metrics()
            metrics.register_module("m11")
            metrics.update_memory_usage("m11")
            return Response(
                content=metrics.to_prometheus(),
                media_type="text/plain; version=0.0.4; charset=utf-8",
            )
        except Exception:
            pass

    # 回退：返回 JSON 格式的基本指标
    return {
        "module": "m11",
        "version": "0.1.0",
        "uptime_seconds": round(_get_uptime_seconds(), 2),
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
