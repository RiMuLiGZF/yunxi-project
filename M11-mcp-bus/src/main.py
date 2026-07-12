"""M11 MCP Bus - FastAPI 主应用.

MCP 总线服务的主入口，整合所有路由和中间件。
提供 MCP 协议端点、管理 API、健康检查等接口。
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

    - 启动时：初始化数据库、启动后台任务
    - 关闭时：清理资源
    """
    # 启动事件
    settings = get_settings()
    print(f"[M11] 初始化数据库: {settings.db_file_path}")
    init_db()
    print("[M11] 数据库初始化完成")

    # 检查离线服务器（后台任务可由调度器负责，这里做一次初始检查）
    from .services.registry import mcp_registry
    offline_count = mcp_registry.check_offline_servers()
    if offline_count > 0:
        print(f"[M11] 检测到 {offline_count} 个离线服务器")

    # 启动健康检查巡检线程
    from .services.health_checker import mcp_health_checker
    mcp_health_checker.start()

    print("[M11] MCP Bus 服务启动完成")

    yield

    # 关闭事件
    print("[M11] MCP Bus 服务正在关闭...")

    # 停止健康检查巡检
    from .services.health_checker import mcp_health_checker
    mcp_health_checker.stop()


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

    # ---------- CORS 中间件 ----------
    # 开发环境允许所有来源，生产环境应配置具体来源
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
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
