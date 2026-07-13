"""M7 积木平台 - FastAPI 主应用.

负责创建 FastAPI 应用、注册中间件和路由。
"""

from __future__ import annotations

import os
import time
import uuid
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

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

    # P1-07: 启动时清理遗留临时文件
    _cleanup_temp_files(max_age_seconds=3600)

    # P1-07: 启动定期临时文件清理任务
    cleanup_task = asyncio.create_task(_periodic_temp_cleanup())

    print(f"[M7] Service started successfully on port {os.environ.get('M7_PORT', '8007')}")

    yield

    # 关闭时
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    print("[M7] Shutting down M7 Workflow Builder...")


async def _periodic_temp_cleanup():
    """P1-07: 定期清理临时文件（每小时一次）."""
    while True:
        await asyncio.sleep(3600)  # 1小时
        try:
            _cleanup_temp_files(max_age_seconds=3600)
        except Exception as e:
            print(f"[M7] 临时文件清理失败: {e}")


def _cleanup_temp_files(max_age_seconds: int = 3600):
    """P1-07: 清理超过指定时间的临时文件.

    清理 M7_TEMP_DIR 目录下超过 max_age_seconds 的文件。
    """
    try:
        from .utils.security import get_temp_dir
        temp_dir = get_temp_dir()
    except Exception:
        temp_dir = os.path.join(os.path.expanduser("~"), ".yunxi", "m7_temp")

    if not os.path.isdir(temp_dir):
        return

    now = time.time()
    cleaned = 0
    for filename in os.listdir(temp_dir):
        filepath = os.path.join(temp_dir, filename)
        if os.path.isfile(filepath):
            try:
                if now - os.path.getmtime(filepath) > max_age_seconds:
                    os.remove(filepath)
                    cleaned += 1
            except Exception:
                pass

    if cleaned > 0:
        print(f"[M7-P1-07] 清理了 {cleaned} 个过期临时文件")


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

    # ===== 全局异常处理器 =====
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        """HTTP 异常统一处理."""
        request_id = _get_request_id(request)
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.status_code,
                "message": exc.detail if isinstance(exc.detail, str) else "请求错误",
                "data": None,
                "request_id": request_id,
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """请求参数校验异常统一处理."""
        request_id = _get_request_id(request)
        errors = exc.errors()
        # 格式化错误信息
        error_msgs = []
        for err in errors:
            loc = " -> ".join(str(x) for x in err.get("loc", []))
            msg = err.get("msg", "参数错误")
            error_msgs.append(f"{loc}: {msg}" if loc else msg)

        return JSONResponse(
            status_code=422,
            content={
                "code": 422,
                "message": "参数校验失败",
                "data": {
                    "errors": error_msgs,
                },
                "request_id": request_id,
            },
        )

    @app.exception_handler(PermissionError)
    async def permission_exception_handler(request: Request, exc: PermissionError):
        """权限异常处理."""
        request_id = _get_request_id(request)
        return JSONResponse(
            status_code=403,
            content={
                "code": 403,
                "message": str(exc) or "无权限访问",
                "data": None,
                "request_id": request_id,
            },
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        """值错误处理（业务参数错误）."""
        request_id = _get_request_id(request)
        return JSONResponse(
            status_code=400,
            content={
                "code": 400,
                "message": str(exc) or "参数错误",
                "data": None,
                "request_id": request_id,
            },
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """全局未捕获异常处理（兜底）."""
        request_id = _get_request_id(request)
        # 记录错误日志
        import traceback
        error_detail = traceback.format_exc()
        print(f"[M7-ERROR][{request_id}] Unhandled exception: {exc}")
        print(error_detail)

        # 生产环境不返回详细错误信息
        env = os.environ.get("M7_ENV", "development")
        if env == "production":
            message = "服务器内部错误"
            data = None
        else:
            message = str(exc)
            data = {"traceback": error_detail.splitlines()[-5:]}

        return JSONResponse(
            status_code=500,
            content={
                "code": 500,
                "message": message,
                "data": data,
                "request_id": request_id,
            },
        )

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
