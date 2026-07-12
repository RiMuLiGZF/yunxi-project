"""
M0 主理人管控台 - 主应用入口

创建 FastAPI 应用，注册路由和中间件。
"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

# 将项目根目录加入 path
BASE_DIR = Path(__file__).parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse

from .config import settings
from .database import init_db
from .errors import register_error_handlers
from .m8_api.health_endpoints import router as health_router
from .m8_api.m8_auth_middleware import M8AuthMiddleware
from .routers import (
    auth_router,
    dashboard_router,
    modules_router,
    config_router,
    access_control_router,
    audit_router,
    upgrade_router,
    emergency_router,
    principal_tools_router,
)
from .services.m8_client import m8_client


# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------

def _get_logger(name: str):
    """获取日志记录器，优先使用 shared.logger，回退到标准 logging"""
    try:
        # 尝试使用 shared 模块的 logger
        from shared.logger import get_logger
        return get_logger(name)
    except Exception:
        import logging
        logger = logging.getLogger(name)
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
        return logger


logger = _get_logger("m0.principal")


# ---------------------------------------------------------------------------
# 应用生命周期
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理

    启动时：初始化数据库、记录启动日志
    关闭时：关闭 M8 客户端连接、记录关闭日志
    """
    # 启动时
    logger.info(f"Starting M0 Principal Console v{settings.version}...")
    init_db()
    logger.info("Database initialized")
    logger.info(f"M0 Principal Console started on {settings.host}:{settings.port}")

    yield

    # 关闭时
    logger.info("M0 Principal Console shutting down...")
    await m8_client.close()
    logger.info("M0 Principal Console shutdown complete")


# ---------------------------------------------------------------------------
# 创建应用
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    """
    创建 FastAPI 应用实例

    Returns:
        FastAPI: 配置好的 FastAPI 应用
    """
    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        description=settings.app.description,
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    # CORS 中间件
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors.origins if settings.cors.origins else ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # M8 认证中间件（不强制认证，由各路由自行控制）
    app.add_middleware(M8AuthMiddleware, require_auth=False)

    # 注册错误处理器
    register_error_handlers(app)

    # ------------------------------------------------------------------
    # 健康检查路由（无需认证）
    # ------------------------------------------------------------------
    app.include_router(health_router, tags=["健康检查"])

    # ------------------------------------------------------------------
    # API 路由（需要认证）
    # ------------------------------------------------------------------
    app.include_router(auth_router, prefix="/api/auth", tags=["认证"])
    app.include_router(dashboard_router, prefix="/api/dashboard", tags=["仪表盘"])
    app.include_router(modules_router, prefix="/api/modules", tags=["模块管理"])
    app.include_router(config_router, prefix="/api/config", tags=["配置中心"])
    app.include_router(access_control_router, prefix="/api/access", tags=["权限管理"])
    app.include_router(audit_router, prefix="/api/audit", tags=["审计日志"])
    app.include_router(upgrade_router, prefix="/api/upgrade", tags=["系统升级"])
    app.include_router(emergency_router, prefix="/api/emergency", tags=["紧急操作"])
    app.include_router(principal_tools_router, prefix="/api/principal", tags=["主理人工具"])

    # ------------------------------------------------------------------
    # 前端静态文件
    # ------------------------------------------------------------------
    frontend_dir = BASE_DIR / "frontend"
    if frontend_dir.exists():
        app.mount(
            "/static",
            StaticFiles(directory=str(frontend_dir)),
            name="static",
        )

        # 根路径重定向到 dashboard
        @app.get("/")
        async def root() -> RedirectResponse:
            """根路径重定向到登录页"""
            return RedirectResponse(url="/static/login.html")

        @app.get("/dashboard")
        async def dashboard_page() -> FileResponse:
            """仪表盘页面"""
            return FileResponse(str(frontend_dir / "dashboard.html"))

    return app


# 全局应用实例
app = create_app()
