"""
云汐系统 - 统一响应 FastAPI 集成
================================

提供 FastAPI 框架集成工具：
- UnifiedResponseMiddleware: 自动包装响应和异常
- response_model 装饰器工具：自动包装路由返回值
- 全局异常处理器

使用方式：
    from fastapi import FastAPI
    from shared.unified_response.fastapi_integration import (
        UnifiedResponseMiddleware,
        register_unified_response,
    )

    app = FastAPI()
    register_unified_response(app)

    # 或者手动添加中间件：
    app.add_middleware(UnifiedResponseMiddleware)
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Callable, Dict, Optional

from .base import ApiResponse, generate_trace_id
from .constants import (
    ERR_INTERNAL,
    ERR_VALIDATION,
    ERR_NOT_FOUND,
    ERR_ENDPOINT_NOT_FOUND,
    ERR_AUTH_FAILED,
    ERR_PERMISSION_DENIED,
    ERR_RATE_LIMITED,
    ERR_SERVICE_UNAVAILABLE,
    ERR_UPSTREAM_ERROR,
    ERR_UPSTREAM_TIMEOUT,
    get_standard_message,
    HTTP_INTERNAL_SERVER_ERROR,
)


# ============================================================
# 统一响应中间件
# ============================================================

class UnifiedResponseMiddleware:
    """FastAPI 统一响应中间件.

    功能：
    1. 自动为所有响应添加 X-Trace-Id 响应头
    2. 自动捕获未处理的异常并包装为标准响应格式
    3. 为响应注入 trace_id 和 timestamp
    4. 与 FastAPI 的 JSONResponse / StreamingResponse 兼容

    Usage:
        from fastapi import FastAPI
        app = FastAPI()
        app.add_middleware(UnifiedResponseMiddleware)
    """

    def __init__(
        self,
        app,
        *,
        wrap_success: bool = False,
        catch_exceptions: bool = True,
        add_trace_header: bool = True,
        exclude_paths: Optional[list] = None,
        logger=None,
    ):
        """初始化中间件.

        Args:
            app: FastAPI/Starlette 应用实例
            wrap_success: 是否自动包装成功响应（默认 False，由路由层控制）
            catch_exceptions: 是否捕获异常并包装为标准格式（默认 True）
            add_trace_header: 是否添加 X-Trace-Id 响应头（默认 True）
            exclude_paths: 排除的路径列表（如健康检查）
            logger: 日志记录器（可选）
        """
        self.app = app
        self.wrap_success = wrap_success
        self.catch_exceptions = catch_exceptions
        self.add_trace_header = add_trace_header
        self.exclude_paths = exclude_paths or ["/health", "/healthz", "/ping"]
        self._logger = logger

    async def __call__(self, scope, receive, send):
        """ASGI 中间件入口."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # 生成或获取 trace_id
        trace_id = self._get_trace_id(scope)

        # 将 trace_id 存入 scope 供下游使用
        if "state" not in scope:
            scope["state"] = {}
        scope["state"]["trace_id"] = trace_id

        # 检查是否排除路径
        path = scope.get("path", "")
        is_excluded = any(path.startswith(p) for p in self.exclude_paths)

        if not self.catch_exceptions or is_excluded:
            # 不捕获异常，直接透传（但仍添加 trace_id header）
            await self._pass_through(scope, receive, send, trace_id)
            return

        # 捕获异常模式
        await self._handle_with_exception_catch(scope, receive, send, trace_id)

    def _get_trace_id(self, scope) -> str:
        """从请求头获取或生成 trace_id."""
        headers = dict(scope.get("headers", []))
        # 查找 X-Trace-Id
        trace_id_bytes = headers.get(b"x-trace-id")
        if trace_id_bytes:
            return trace_id_bytes.decode("utf-8")
        # 查找 X-Request-Id 作为备选
        request_id_bytes = headers.get(b"x-request-id")
        if request_id_bytes:
            return request_id_bytes.decode("utf-8")
        # 生成新的
        return generate_trace_id()

    async def _pass_through(self, scope, receive, send, trace_id: str):
        """直接透传，仅添加 trace_id 响应头."""
        if not self.add_trace_header:
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                # 检查是否已有 trace_id
                has_trace = any(
                    k.lower() == b"x-trace-id"
                    for k, _ in headers
                )
                if not has_trace:
                    headers.append((b"x-trace-id", trace_id.encode("utf-8")))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)

    async def _handle_with_exception_catch(self, scope, receive, send, trace_id: str):
        """带异常捕获的请求处理."""
        # 收集响应消息
        response_started = False
        status_code = 200
        response_headers: list = []
        response_body = b""
        is_streaming = False
        exception_occurred = None

        async def receive_wrapper():
            return await receive()

        async def send_wrapper(message):
            nonlocal response_started, status_code, response_headers, response_body, is_streaming
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                response_headers = list(message.get("headers", []))
                # 添加 trace_id 响应头
                if self.add_trace_header:
                    has_trace = any(
                        k.lower() == b"x-trace-id"
                        for k, _ in response_headers
                    )
                    if not has_trace:
                        response_headers.append(
                            (b"x-trace-id", trace_id.encode("utf-8"))
                        )
            elif message["type"] == "http.response.body":
                if message.get("more_body", False):
                    is_streaming = True
                response_body += message.get("body", b"")

        try:
            await self.app(scope, receive_wrapper, send_wrapper)
        except Exception as exc:
            exception_occurred = exc

        if exception_occurred is not None:
            # 构造标准错误响应
            error_resp = ApiResponse.error(
                code=ERR_INTERNAL,
                message=str(exception_occurred) or get_standard_message(ERR_INTERNAL),
                trace_id=trace_id,
            )
            # 记录日志
            if self._logger is not None:
                try:
                    self._logger.error(
                        f"UnifiedResponseMiddleware caught exception: {exception_occurred}",
                        exc_info=exception_occurred,
                        trace_id=trace_id,
                    )
                except Exception:
                    pass

            body = error_resp.to_json().encode("utf-8")
            headers = [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"x-trace-id", trace_id.encode("utf-8")),
                (b"content-length", str(len(body)).encode("utf-8")),
            ]

            await send({
                "type": "http.response.start",
                "status": HTTP_INTERNAL_SERVER_ERROR,
                "headers": headers,
            })
            await send({
                "type": "http.response.body",
                "body": body,
                "more_body": False,
            })
            return

        # 正常响应：重新发送
        if response_started:
            await send({
                "type": "http.response.start",
                "status": status_code,
                "headers": response_headers,
            })
            await send({
                "type": "http.response.body",
                "body": response_body,
                "more_body": False,
            })


# ============================================================
# 全局异常处理器注册
# ============================================================

def register_unified_response(
    app,
    *,
    logger=None,
    custom_exception_handlers: Optional[Dict[type, Callable]] = None,
) -> None:
    """为 FastAPI 应用注册统一响应体系.

    包括：
    1. 添加 UnifiedResponseMiddleware
    2. 注册全局异常处理器（YunxiError、ValidationError、HTTPException 等）
    3. 注册自定义异常处理器

    Args:
        app: FastAPI 应用实例
        logger: 日志记录器（可选）
        custom_exception_handlers: 自定义异常类型到处理函数的映射
    """
    # 1. 添加中间件
    app.add_middleware(UnifiedResponseMiddleware, logger=logger)

    # 2. 注册全局异常处理器
    _register_exception_handlers(app, logger=logger)

    # 3. 注册自定义异常处理器
    if custom_exception_handlers:
        for exc_type, handler in custom_exception_handlers.items():
            app.add_exception_handler(exc_type, handler)


def _register_exception_handlers(app, logger=None) -> None:
    """注册标准异常处理器."""
    from fastapi.exceptions import RequestValidationError
    from starlette.exceptions import HTTPException as StarletteHTTPException

    # 尝试注册 YunxiError 处理器
    try:
        from shared.core.errors import YunxiError  # type: ignore

        @app.exception_handler(YunxiError)
        async def yunxi_error_handler(request, exc: YunxiError):
            trace_id = getattr(getattr(request, "state", None), "trace_id", None) or \
                       request.headers.get("x-trace-id") or generate_trace_id()
            resp = ApiResponse.error(
                code=exc.code,
                message=exc.message,
                data=getattr(exc, "details", None),
                trace_id=trace_id,
            )
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=getattr(exc, "http_status", 500),
                content=resp.to_dict(),
                headers={"X-Trace-Id": trace_id},
            )
    except ImportError:
        pass

    # FastAPI 验证错误
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request, exc: RequestValidationError):
        trace_id = getattr(getattr(request, "state", None), "trace_id", None) or \
                   request.headers.get("x-trace-id") or generate_trace_id()
        errors = []
        for err in exc.errors():
            loc = " -> ".join(str(loc) for loc in err.get("loc", []))
            errors.append({
                "field": loc,
                "message": err.get("msg", ""),
                "type": err.get("type", ""),
            })
        resp = ApiResponse.error(
            code=ERR_VALIDATION,
            message="参数验证失败",
            data={"errors": errors, "error_count": len(errors)},
            trace_id=trace_id,
        )
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=422,
            content=resp.to_dict(),
            headers={"X-Trace-Id": trace_id},
        )

    # Starlette HTTPException
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request, exc: StarletteHTTPException):
        trace_id = getattr(getattr(request, "state", None), "trace_id", None) or \
                   request.headers.get("x-trace-id") or generate_trace_id()

        # HTTP 状态码映射到错误码
        error_code_map = {
            400: ERR_VALIDATION,
            401: ERR_AUTH_FAILED,
            403: ERR_PERMISSION_DENIED,
            404: ERR_ENDPOINT_NOT_FOUND,
            405: ERR_PERMISSION_DENIED,
            429: ERR_RATE_LIMITED,
            500: ERR_INTERNAL,
            502: ERR_UPSTREAM_ERROR,
            503: ERR_SERVICE_UNAVAILABLE,
            504: ERR_UPSTREAM_TIMEOUT,
        }
        code = error_code_map.get(exc.status_code, ERR_INTERNAL)
        message = exc.detail if isinstance(exc.detail, str) else str(exc.detail)

        resp = ApiResponse.error(
            code=code,
            message=message,
            trace_id=trace_id,
        )
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=exc.status_code,
            content=resp.to_dict(),
            headers={"X-Trace-Id": trace_id},
        )

    # 兜底异常处理器
    @app.exception_handler(Exception)
    async def generic_exception_handler(request, exc: Exception):
        trace_id = getattr(getattr(request, "state", None), "trace_id", None) or \
                   request.headers.get("x-trace-id") or generate_trace_id()
        if logger is not None:
            try:
                logger.error(
                    f"Unhandled exception: {exc}",
                    exc_info=exc,
                    trace_id=trace_id,
                    path=request.url.path,
                )
            except Exception:
                pass

        resp = ApiResponse.error(
            code=ERR_INTERNAL,
            message="服务器内部错误",
            trace_id=trace_id,
        )
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=500,
            content=resp.to_dict(),
            headers={"X-Trace-Id": trace_id},
        )


# ============================================================
# 响应包装装饰器
# ============================================================

def unified_response(func: Callable) -> Callable:
    """路由函数装饰器，自动将返回值包装为标准响应格式.

    支持的返回值类型：
    - None / 无返回值 -> ApiResponse.success()
    - dict / list / str / int 等 -> ApiResponse.success(data=返回值)
    - ApiResponse 实例 -> 直接返回
    - tuple (data, message) -> ApiResponse.success(data, message)
    - tuple (code, message, data) -> ApiResponse(code, message, data)

    Usage:
        @app.get("/items")
        @unified_response
        async def get_items():
            return {"items": [...]}
    """
    import functools

    @functools.wraps(func)
    async def async_wrapper(*args, **kwargs):
        result = await func(*args, **kwargs)
        return _wrap_result(result)

    @functools.wraps(func)
    def sync_wrapper(*args, **kwargs):
        result = func(*args, **kwargs)
        return _wrap_result(result)

    import asyncio
    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    return sync_wrapper


def _wrap_result(result: Any) -> ApiResponse:
    """将返回值包装为 ApiResponse."""
    # 已经是 ApiResponse 实例
    if isinstance(result, ApiResponse):
        if result.trace_id is None:
            result.trace_id = generate_trace_id()
        return result

    # None
    if result is None:
        return ApiResponse.success()

    # tuple: 长度判断
    if isinstance(result, tuple):
        if len(result) == 2:
            # (data, message)
            return ApiResponse.success(data=result[0], message=result[1])
        elif len(result) == 3:
            # (code, message, data)
            code, message, data = result
            if code == 0 or str(code).startswith("0"):
                return ApiResponse.success(data=data, message=message)
            return ApiResponse.error(code=code, message=message, data=data)

    # 其他类型：直接作为 data
    return ApiResponse.success(data=result)


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "UnifiedResponseMiddleware",
    "register_unified_response",
    "unified_response",
]
