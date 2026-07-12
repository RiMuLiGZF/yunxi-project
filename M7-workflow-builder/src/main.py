"""M7 积木平台 - FastAPI 主应用.

负责创建 FastAPI 应用、注册中间件和路由。
"""

from __future__ import annotations

import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from . import __version__, __module_name__
from .m8_api.m8_auth_middleware import M8AuthMiddleware
from .m8_api.health_endpoints import (
    router as health_router,
    record_request,
    set_workflow_count,
)
from .routers.workflows import router as workflows_router
from .routers.blocks import router as blocks_router
from .routers.templates import router as templates_router
from .routers.runs import router as runs_router
from .routers.custom_blocks import router as custom_blocks_router
from .services.storage import get_storage


# 加载全局配置（在中间件初始化之前）
def _load_global_env():
    """加载全局配置文件 config/yunxi.env."""
    src_dir = Path(__file__).resolve().parent
    module_dir = src_dir.parent
    project_root = module_dir.parent
    env_path = project_root / "config" / "yunxi.env"
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(str(env_path), override=False)
    except ImportError:
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key and key not in os.environ:
                        os.environ[key] = value
        except Exception:
            pass

_load_global_env()


def _get_request_id(request: Request) -> str:
    """从请求中获取或生成 request_id."""
    rid = request.headers.get("X-Request-ID", "")
    return rid or uuid.uuid4().hex[:16]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理."""
    # 启动时
    print(f"[M7] Starting M7 Workflow Builder v{__version__}...")
    print(f"[M7] Module: {__module_name__}")
    print(f"[M7] Environment: {os.environ.get('M7_ENV', 'development')}")
    print(f"[M7] Data directory: {os.path.join(os.path.expanduser('~'), '.yunxi')}")

    # 初始化存储
    storage = get_storage()
    stats = storage.get_stats()
    set_workflow_count(stats.get("total_workflows", 0))
    print(f"[M7] Loaded {stats.get('total_workflows', 0)} workflows from storage")

    print(f"[M7] Service started successfully on port {os.environ.get('M7_PORT', '8007')}")

    yield

    # 关闭时
    print("[M7] Shutting down M7 Workflow Builder...")


def create_app() -> FastAPI:
    """创建 FastAPI 应用实例.

    Returns:
        FastAPI 应用实例
    """
    app = FastAPI(
        title="M7 积木平台 API",
        version=__version__,
        description="云汐系统 M7 积木平台 - 工作流编排与执行服务",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # CORS 中间件
    cors_origins = os.environ.get("M7_CORS_ORIGINS", "*")
    cors_list = [o.strip() for o in cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_list if cors_list else ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Token 鉴权中间件
    app.add_middleware(M8AuthMiddleware)

    # 请求计时中间件（记录指标）
    @app.middleware("http")
    async def add_request_metrics(request: Request, call_next):
        start_time = time.time()
        response = await call_next(request)
        duration_ms = (time.time() - start_time) * 1000
        success = response.status_code < 500
        record_request(success=success, response_ms=duration_ms)

        # 添加 X-Request-ID 响应头
        request_id = _get_request_id(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Module"] = __module_name__
        response.headers["X-Version"] = __version__

        return response

    # 注册健康检查路由（包含根路径 /health）
    # 注意：health_router 自己定义了 /health 和 /api/v1/health 等路径
    app.include_router(health_router)

    # 注册业务路由
    app.include_router(workflows_router)
    app.include_router(blocks_router)
    app.include_router(templates_router)
    app.include_router(runs_router)
    app.include_router(custom_blocks_router)

    # 根路径
    @app.get("/", tags=["系统"])
    async def root(request: Request):
        """服务根路径，返回基本信息."""
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "name": "M7 Workflow Builder",
                "module": __module_name__,
                "version": __version__,
                "docs": "/docs",
                "health": "/api/v1/health",
                "api_prefix": "/api/v1",
            },
            "request_id": _get_request_id(request),
        }

    return app


app = create_app()
