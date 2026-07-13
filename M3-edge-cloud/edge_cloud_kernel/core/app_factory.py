"""FastAPI 应用工厂.

创建 FastAPI 应用实例，注册路由、中间件、全局异常处理器和生命周期事件。

全局异常处理器：
    1. SyncKernelError - 内核异常基类，映射到对应 HTTP 状态码
    2. RequestValidationError - FastAPI 请求参数校验错误
    3. Exception - 兜底异常，不泄露堆栈
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from edge_cloud_kernel.common.logging_setup import (
    clear_context,
    set_trace_id,
    setup_logging,
)
from edge_cloud_kernel.core.kernel_manager import KernelManager
from edge_cloud_kernel.models.exceptions import SyncKernelError
from edge_cloud_kernel.m8_api.error_codes import (
    ERR_INVALID_PARAM,
    ERR_UNKNOWN,
    ErrorCode,
)

logger = structlog.get_logger(__name__)

# 全局 KernelManager 实例（单例）
_kernel_manager: KernelManager | None = None


def get_kernel_manager() -> KernelManager | None:
    """获取全局 KernelManager 实例.

    Returns:
        KernelManager 实例，未初始化则返回 None.
    """
    return _kernel_manager


# ---------------------------------------------------------------------------
# 异常码映射
# ---------------------------------------------------------------------------

# SyncKernelError error_code 到 ErrorCode 的映射
_ERROR_CODE_MAP: dict[str, ErrorCode] = {
    # 通用
    "KERNEL_ERROR": ERR_UNKNOWN,
    # 同步相关
    "SYNC_ERROR": ERR_UNKNOWN,
    "SYNC_INVALID_DEVICE_ID": ERR_INVALID_PARAM,
    "SYNC_SESSION_NOT_FOUND": ERR_UNKNOWN,
    "SYNC_SESSION_EXPIRED": ERR_UNKNOWN,
    "SYNC_CONTROLLER_UNAVAILABLE": ERR_UNKNOWN,
    "SYNC_MANAGER_UNAVAILABLE": ERR_UNKNOWN,
    "SYNC_INVALID_REQUEST": ERR_INVALID_PARAM,
    "SYNC_MISSING_PARAMETER": ERR_INVALID_PARAM,
    "SYNC_INVALID_PARAMETER": ERR_INVALID_PARAM,
    "SYNC_INVALID_RESOLUTION": ERR_INVALID_PARAM,
    # 路由
    "ROUTE_ERROR": ERR_UNKNOWN,
    # 推理
    "INFERENCE_ERROR": ERR_UNKNOWN,
    # 熔断器
    "CIRCUIT_OPEN": ERR_UNKNOWN,
    # 显存
    "VRAM_OVERFLOW": ERR_UNKNOWN,
    # Provider
    "PROVIDER_ERROR": ERR_UNKNOWN,
}


def _map_kernel_error_to_code(exc: SyncKernelError) -> ErrorCode:
    """将 SyncKernelError 映射为对应的错误码.

    Args:
        exc: SyncKernelError 异常实例.

    Returns:
        对应的 ErrorCode.
    """
    return _ERROR_CODE_MAP.get(exc.error_code, ERR_UNKNOWN)


# ---------------------------------------------------------------------------
# 全局异常处理器
# ---------------------------------------------------------------------------

def _register_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器.

    Args:
        app: FastAPI 应用实例.
    """

    @app.exception_handler(SyncKernelError)
    async def sync_kernel_exception_handler(
        request: Request, exc: SyncKernelError
    ) -> JSONResponse:
        """处理内核异常.

        Args:
            request: FastAPI 请求对象.
            exc: SyncKernelError 异常实例.

        Returns:
            标准错误响应 JSON.
        """
        trace_id = getattr(request.state, "trace_id", uuid.uuid4().hex[:16])
        error_code = _map_kernel_error_to_code(exc)

        logger.warning(
            "exception.sync_kernel_error",
            error_code=exc.error_code,
            message=exc.message,
            trace_id=trace_id,
            context=exc.context,
        )

        return JSONResponse(
            status_code=error_code.http_status,
            content={
                "code": error_code.code,
                "message": exc.message or error_code.message,
                "data": exc.context if exc.context else None,
                "trace_id": trace_id,
                "timestamp": time.time(),
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """处理请求参数校验错误.

        Args:
            request: FastAPI 请求对象.
            exc: RequestValidationError 异常实例.

        Returns:
            字段级错误详情 JSON.
        """
        trace_id = getattr(request.state, "trace_id", uuid.uuid4().hex[:16])

        # 提取字段级错误详情
        errors: list[dict[str, Any]] = []
        for err in exc.errors():
            errors.append({
                "field": ".".join(str(loc) for loc in err.get("loc", [])),
                "message": err.get("msg", ""),
                "type": err.get("type", ""),
            })

        logger.warning(
            "exception.validation_error",
            trace_id=trace_id,
            error_count=len(errors),
            errors=errors,
        )

        return JSONResponse(
            status_code=ERR_INVALID_PARAM.http_status,
            content={
                "code": ERR_INVALID_PARAM.code,
                "message": ERR_INVALID_PARAM.message,
                "data": {"errors": errors},
                "trace_id": trace_id,
                "timestamp": time.time(),
            },
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        """兜底异常处理器.

        不泄露堆栈信息，返回通用内部错误响应。

        Args:
            request: FastAPI 请求对象.
            exc: 异常实例.

        Returns:
            通用内部错误 JSON.
        """
        trace_id = getattr(request.state, "trace_id", uuid.uuid4().hex[:16])

        logger.error(
            "exception.unhandled_error",
            trace_id=trace_id,
            error_type=type(exc).__name__,
            error_message=str(exc),
            path=request.url.path,
            method=request.method,
        )

        return JSONResponse(
            status_code=ERR_UNKNOWN.http_status,
            content={
                "code": ERR_UNKNOWN.code,
                "message": ERR_UNKNOWN.message,
                "data": None,
                "trace_id": trace_id,
                "timestamp": time.time(),
            },
        )


# ---------------------------------------------------------------------------
# 中间件
# ---------------------------------------------------------------------------

def _register_middleware(app: FastAPI) -> None:
    """注册中间件.

    Args:
        app: FastAPI 应用实例.
    """
    # CORS 中间件
    cors_origins = os.environ.get("CORS_ORIGINS", "*")
    if cors_origins == "*":
        allow_origins = ["*"]
    else:
        allow_origins = cors_origins.split(",")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 弹性中间件：限流 + 熔断（从环境变量读取开关）
    rate_limit_enabled = os.environ.get("M3_RATE_LIMIT_ENABLED", "true").lower() == "true"
    circuit_breaker_enabled = os.environ.get("M3_CIRCUIT_BREAKER_ENABLED", "true").lower() == "true"

    if rate_limit_enabled or circuit_breaker_enabled:
        from edge_cloud_kernel.api.middleware import (
            CircuitBreakerMiddleware,
            RateLimitMiddleware,
        )

        if rate_limit_enabled:
            app.add_middleware(RateLimitMiddleware)

        if circuit_breaker_enabled:
            app.add_middleware(CircuitBreakerMiddleware)

    # trace_id 注入 + 链路追踪 + 指标记录中间件
    @app.middleware("http")
    async def add_trace_id_and_metrics(request: Request, call_next):
        """为每个请求注入 trace_id，设置上下文追踪，并记录请求指标."""
        start_time = time.time()
        trace_id = uuid.uuid4().hex[:16]

        # 将 trace_id 存入 request state（向后兼容）
        request.state.trace_id = trace_id

        # 将 kernel_manager 存入 request state
        request.state.kernel_manager = _kernel_manager

        # 注入 contextvars 链路追踪
        set_trace_id(trace_id)
        try:
            response = await call_next(request)
        finally:
            # 清理上下文，避免上下文泄漏
            clear_context()

        # 记录响应时间到指标收集器
        elapsed_ms = (time.time() - start_time) * 1000
        if _kernel_manager is not None:
            health_metrics = _kernel_manager.get_component("health_metrics")
            if (
                health_metrics is not None
                and not _kernel_manager.is_mock("health_metrics")
                and hasattr(health_metrics, "metrics")
            ):
                success = response.status_code < 500
                health_metrics.metrics.record_request(
                    success=success, response_ms=elapsed_ms
                )

        response.headers["X-Trace-Id"] = trace_id
        return response


# ---------------------------------------------------------------------------
# 路由注册
# ---------------------------------------------------------------------------

def _register_routers(app: FastAPI) -> None:
    """注册所有路由.

    Args:
        app: FastAPI 应用实例.
    """
    from edge_cloud_kernel.api import (
        config_router,
        device_router,
        health_router,
        m8_router,
        sync_router,
    )

    # 健康检查路由（包含 /health, /api/v3/health, /api/v3/metrics, v1别名）
    app.include_router(health_router)

    # 配置管理路由
    app.include_router(config_router)

    # 同步管理路由
    app.include_router(sync_router)

    # 设备管理路由
    app.include_router(device_router)

    # M8 标准接口路由（/m8/*）
    app.include_router(m8_router)


# ---------------------------------------------------------------------------
# 日志初始化
# ---------------------------------------------------------------------------

def _init_logging_from_config(kernel: KernelManager) -> None:
    """从配置中读取日志设置并初始化结构化日志.

    Args:
        kernel: 内核管理器实例.
    """
    config_manager = kernel.get_component("config_manager")

    # 默认设置
    log_level = "info"
    log_format = "console"
    log_file = None
    max_size_mb = 100
    max_files = 10
    sensitive_fields: list[str] = []

    # 从配置中读取（如果可用）
    if config_manager is not None and not kernel.is_mock("config_manager"):
        try:
            cfg = config_manager.get("logging", {})
            log_level = cfg.get("level", log_level)
            log_format = cfg.get("format", log_format)
            log_file = cfg.get("file", None) or None
            max_size = cfg.get("max_size", "100MB")
            if isinstance(max_size, str):
                max_size_mb = int(max_size.replace("MB", "").replace("mb", ""))
            max_files = cfg.get("max_files", max_files)
            sensitive_fields = cfg.get("sensitive_fields", []) or []
        except Exception:
            pass

    setup_logging(
        level=log_level,
        format_type=log_format,
        log_file=log_file,
        max_size_mb=max_size_mb,
        max_files=max_files,
        sensitive_fields=sensitive_fields,
    )


# ---------------------------------------------------------------------------
# 根路径
# ---------------------------------------------------------------------------

def _register_root_endpoint(app: FastAPI) -> None:
    """注册根路径端点.

    Args:
        app: FastAPI 应用实例.
    """

    @app.get("/", tags=["Info"], summary="服务信息")
    async def root():
        """根路径：返回服务基本信息."""
        if _kernel_manager is None:
            mock_components: list[str] = []
            real_components: list[str] = []
        else:
            mock_components = _kernel_manager.get_mock_components()
            real_components = _kernel_manager.get_real_components()

        return {
            "name": "M3 端云协同内核 API",
            "version": "2.1.2",
            "status": "running",
            "docs": "/docs",
            "openapi": "/openapi.json",
            "components": {
                "initialized": real_components,
                "mock_mode": mock_components,
            },
            "endpoints": {
                "health": "/health",
                "m8_health": "/api/v3/health",
                "m8_metrics": "/api/v3/metrics",
                "config": "/api/v3/config",
                "sync_status": "/api/v3/sync/status",
                "sync_conflict_resolve": "/api/v3/sync/conflicts/{id}/resolve",
                "devices": "/api/v3/devices",
                "device_remove": "/api/v3/devices/{id}/remove",
            },
        }


# ---------------------------------------------------------------------------
# 应用工厂
# ---------------------------------------------------------------------------

def create_app(
    base_dir: Any = None,
    project_root: Any = None,
    config_path: Any = None,
) -> FastAPI:
    """创建 FastAPI 应用实例.

    初始化内核组件、注册中间件、路由、异常处理器和生命周期事件。

    Args:
        base_dir: 基础目录路径.
        project_root: 项目根目录路径.
        config_path: 配置文件路径.

    Returns:
        FastAPI 应用实例.
    """
    global _kernel_manager

    # 创建并初始化内核管理器
    _kernel_manager = KernelManager(
        base_dir=base_dir,
        project_root=project_root,
        config_path=config_path,
    )
    _kernel_manager.init_all()

    # 初始化结构化日志系统
    _init_logging_from_config(_kernel_manager)

    # 创建 FastAPI 应用
    app = FastAPI(
        title="M3 端云协同内核 API",
        description="云汐项目模块三：端云数据同步、通信网关、资源监控与硬件桥接能力",
        version="0.4.0",
    )

    # 注册中间件
    _register_middleware(app)

    # 注册全局异常处理器
    _register_exception_handlers(app)

    # 注册路由
    _register_routers(app)

    # 注册根路径
    _register_root_endpoint(app)

    logger.info("app.created", version="0.4.0")

    return app
