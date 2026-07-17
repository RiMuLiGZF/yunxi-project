"""M11 MCP Bus - FastAPI 主应用.

MCP 总线服务的主入口，整合所有路由和中间件。
提供 MCP 协议端点、管理 API、健康检查等接口。

Phase 1 安全加固：
- 管理接口（/api/admin/*, /api/console/*, /api/v1/monitor/*）接入 API Key 鉴权
- 鉴权通过 FastAPI 依赖注入（Depends(get_current_api_key)）实现
- 公开接口保持不变：/health, /m8/*, /docs, /redoc, /openapi.json
- MCP 端点（/mcp, /mcp/sse, /api/v1/*）有独立的 API Key 鉴权机制
- 关键操作接入审计日志（服务注册/注销、API Key 管理、工具调用）
- 数据库会话统一使用 Depends(get_db) 依赖注入
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .db import init_db
from .routers import admin as admin_router
from .routers import console as console_router
from .routers import health as health_router
from .routers import mcp as mcp_router
from .routers import monitor as monitor_router


# ============================================================
# 应用生命周期
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理.

    - 启动时：初始化数据库、初始化 Redis、启动后台任务
    - 关闭时：清理资源、关闭 Redis 连接
    """
    # 启动事件
    settings = get_settings()
    print(f"[M11] 初始化数据库: {settings.db_file_path}")
    init_db()
    print("[M11] 数据库初始化完成")

    # 初始化 Redis 连接
    from .services.redis_client import redis_client
    if settings.use_redis:
        print(f"[M11] 正在连接 Redis: {settings.redis_url}")
        redis_ok = redis_client.connect()
        if redis_ok:
            print("[M11] Redis 连接成功")
        else:
            print("[M11] Redis 连接失败，将降级为内存模式")
    else:
        print("[M11] 未配置 Redis，使用内存模式")

    # 初始化限流器（根据 Redis 状态选择后端）
    from .services.rate_limiter import init_rate_limiter
    rl = init_rate_limiter()
    print(f"[M11] 限流器后端: {rl.get_stats().get('backend', 'unknown')}")

    # 重新加载缓存后端（Redis 连接后刷新）
    if settings.use_redis and redis_client.is_available():
        from .services.cache import CacheService
        CacheService().reload_backend()

    # 检查离线服务器（后台任务可由调度器负责，这里做一次初始检查）
    from .services.registry import mcp_registry
    offline_count = mcp_registry.check_offline_servers()
    if offline_count > 0:
        print(f"[M11] 检测到 {offline_count} 个离线服务器")

    # 启动健康检查巡检线程
    from .services.health_checker import mcp_health_checker
    mcp_health_checker.start()

    # 启动后台定时任务调度器（工具自动刷新等）
    from .services.scheduler import task_scheduler
    task_scheduler.start()

    # 初始化 stdio 管理器（如果启用）
    if settings.stdio_enabled:
        from .services.stdio_manager import stdio_manager
        print("[M11] stdio 传输支持已启用")
    else:
        print("[M11] stdio 传输支持已禁用")

    print("[M11] MCP Bus 服务启动完成")

    yield

    # 关闭事件
    print("[M11] MCP Bus 服务正在关闭...")

    # 停止所有 stdio 服务（如果启用）
    settings = get_settings()
    if settings.stdio_enabled:
        from .services.stdio_manager import stdio_manager
        await stdio_manager.shutdown_all()

    # 停止后台定时任务调度器
    from .services.scheduler import task_scheduler
    task_scheduler.stop()

    # 停止健康检查巡检
    from .services.health_checker import mcp_health_checker
    mcp_health_checker.stop()

    # 关闭 Redis 连接
    from .services.redis_client import redis_client
    if redis_client.is_available():
        redis_client.disconnect()
        print("[M11] Redis 连接已关闭")


# ============================================================
# 创建 FastAPI 应用
# ============================================================

def create_app() -> FastAPI:
    """创建 FastAPI 应用实例.

    Returns:
        配置好的 FastAPI 应用
    """
    settings = get_settings()

    app = FastAPI(
        title="M11 MCP Bus",
        description="MCP 总线服务 - 统一管理和路由所有 MCP 工具服务",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # ---------- CORS 中间件（统一安全策略：生产环境禁用通配符） ----------
    import os as _os_m11_cors
    _cors_env = _os_m11_cors.environ.get("YUNXI_ENV", _os_m11_cors.environ.get("ENV", "development")).lower()
    _cors_is_prod = _cors_env in ("production", "prod", "release")
    _cors_list = settings.cors_origin_list
    _cors_has_wildcard = any(o == "*" for o in _cors_list)

    if _cors_is_prod and (not _cors_list or _cors_has_wildcard):
        raise RuntimeError(
            "[CORS] 生产环境安全校验失败：M11 MCP 总线的 CORS origins "
            "包含通配符或为空。生产环境必须显式配置具体的允许来源，"
            "禁止使用通配符 '*'。请设置 M11_CORS_ORIGINS 或 CORS_ORIGINS 环境变量。"
        )

    # 开发环境如果配置为 "*" 或空，替换为默认 localhost 列表
    if not _cors_is_prod and (not _cors_list or _cors_has_wildcard):
        _cors_dev_ports = [3000, 5173, 8080] + list(range(8000, 8013))
        _cors_list = [f"http://localhost:{p}" for p in _cors_dev_ports] + \
                     [f"http://127.0.0.1:{p}" for p in _cors_dev_ports]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---------- 路由注册 ----------
    # M8 标准接口（health, metrics, config）- 挂载到 /m8/*
    app.include_router(health_router.router)

    # 管理 API - /api/admin/*
    app.include_router(admin_router.router)

    # MCP 协议端点和 REST API - /mcp 和 /api/v1/*
    app.include_router(mcp_router.router)

    # 管理控制台 - /console 和 /api/console/*
    app.include_router(console_router.router)

    # 监控统计 API - /api/v1/monitor/*
    app.include_router(monitor_router.router)

    # ---------- 根路径 ----------
    @app.get("/", summary="根路径 - 服务状态", tags=["root"])
    async def root() -> Dict[str, Any]:
        """根路径，返回服务基本信息."""
        return {
            "status": "ok",
            "module": "M11 MCP Bus",
            "version": "0.1.0",
            "description": "MCP 总线服务 - 统一管理和路由所有 MCP 工具服务",
            "endpoints": {
                "mcp": "/mcp",
                "m8_health": "/m8/health",
                "m8_metrics": "/m8/metrics",
                "m8_config": "/m8/config",
                "health": "/health",
                "admin_servers": "/api/admin/servers",
                "admin_tools": "/api/admin/tools",
                "admin_stdio": "/api/admin/stdio",
                "api_tools": "/api/v1/tools",
                "monitor_overview": "/api/v1/monitor/overview",
                "monitor_server_stats": "/api/v1/monitor/server-stats",
                "monitor_tool_stats": "/api/v1/monitor/tool-stats",
                "monitor_recent_calls": "/api/v1/monitor/recent-calls",
                "monitor_health_status": "/api/v1/monitor/health-status",
                "docs": "/docs",
            },
        }

    return app


# ============================================================
# 全局应用实例
# ============================================================

app = create_app()
