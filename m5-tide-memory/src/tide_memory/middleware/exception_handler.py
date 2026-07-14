"""
全局异常处理器

注册到 FastAPI 应用，统一捕获并格式化所有异常响应。
使用 structlog 记录异常日志，确保错误响应格式一致。
"""

from __future__ import annotations

import uuid
import traceback
from datetime import datetime
from typing import Any, Dict, Optional

import structlog
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = structlog.get_logger(__name__)

from tide_memory.errors import (
    ErrorCode,
    TideMemoryError,
    error_response,
)


def _get_request_id(request: Optional[Request] = None) -> str:
    """
    获取或生成请求ID

    优先从 request.state.request_id 读取，其次从 header 读取，否则生成新的。
    """
    if request is not None:
        # 尝试从 state 中获取
        req_id = getattr(request.state, "request_id", None)
        if req_id:
            return req_id
        # 尝试从 header 中获取
        req_id = request.headers.get("x-request-id", "")
        if req_id:
            return req_id
    return f"m5-{uuid.uuid4().hex[:12]}"


def _http_status_from_code(code: ErrorCode) -> int:
    """
    根据错误码映射 HTTP 状态码

    Args:
        code: 业务错误码

    Returns:
        对应的 HTTP 状态码
    """
    code_value = code.value

    # 通用错误映射
    if code_value == 0:
        return status.HTTP_200_OK
    if code_value == 50001:  # INVALID_PARAMS
        return status.HTTP_400_BAD_REQUEST
    if code_value == 50002:  # UNAUTHORIZED
        return status.HTTP_401_UNAUTHORIZED
    if code_value in (50003, 50201, 50202, 50203, 50204):  # 权限类
        return status.HTTP_403_FORBIDDEN
    if code_value in (50004, 50101):  # NOT_FOUND / MEMORY_NOT_FOUND
        return status.HTTP_404_NOT_FOUND
    if code_value == 50005:  # RATE_LIMITED
        return status.HTTP_429_TOO_MANY_REQUESTS
    if code_value in (50006, 50007, 50300, 50301, 50302, 50303, 50304):
        return status.HTTP_500_INTERNAL_SERVER_ERROR
    if code_value in (50400, 50401, 50402, 50403, 50404):  # 检索类
        return status.HTTP_500_INTERNAL_SERVER_ERROR
    if code_value in (50500, 50501, 50502, 50503):  # 巩固类
        return status.HTTP_500_INTERNAL_SERVER_ERROR

    # 默认 400
    if 50100 <= code_value < 50200:  # 记忆相关
        return status.HTTP_400_BAD_REQUEST
    if 50600 <= code_value < 50700:  # 验证相关
        return status.HTTP_400_BAD_REQUEST

    return status.HTTP_500_INTERNAL_SERVER_ERROR


def register_exception_handlers(app: FastAPI) -> None:
    """
    向 FastAPI 应用注册全局异常处理器

    处理的异常类型：
    1. TideMemoryError - 业务自定义异常
    2. RequestValidationError - Pydantic 参数验证错误
    3. HTTPException - FastAPI/Starlette HTTP 异常
    4. Exception - 通用兜底异常
    """

    @app.exception_handler(TideMemoryError)
    async def tide_memory_error_handler(
        request: Request, exc: TideMemoryError
    ) -> JSONResponse:
        """
        处理 M5 业务自定义异常

        记录结构化日志，返回统一格式的错误响应。
        """
        request_id = _get_request_id(request)

        # structlog 风格日志
        try:
            logger.warning(
                "tide_memory_error",
                error_type=exc.__class__.__name__,
                error_code=exc.code.value,
                error_message=exc.message,
                request_id=request_id,
                path=str(request.url.path) if request else "",
                method=request.method if request else "",
                data=exc.data,
            )
        except Exception:
            # 日志失败不影响响应
            pass

        resp = error_response(
            code=exc.code,
            message=exc.message,
            data=exc.data,
            request_id=request_id,
        )
        status_code = _http_status_from_code(exc.code)
        return JSONResponse(status_code=status_code, content=resp)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """
        处理 Pydantic 参数验证错误

        返回字段级别的错误详情，方便前端定位问题。
        """
        request_id = _get_request_id(request)

        # 整理字段错误详情
        field_errors = []
        for err in exc.errors():
            loc = err.get("loc", [])
            field = ".".join(str(x) for x in loc) if loc else "unknown"
            field_errors.append({
                "field": field,
                "message": err.get("msg", ""),
                "type": err.get("type", ""),
                "ctx": err.get("ctx", {}),
            })

        try:
            logger.warning(
                "validation_error",
                request_id=request_id,
                path=str(request.url.path) if request else "",
                method=request.method if request else "",
                error_count=len(field_errors),
                fields=[e["field"] for e in field_errors],
            )
        except Exception:
            pass

        resp = error_response(
            code=ErrorCode.VALIDATION_ERROR,
            message="请求参数验证失败",
            data={
                "errors": field_errors,
                "error_count": len(field_errors),
            },
            request_id=request_id,
        )
        # 兼容新旧版 starlette 的状态码常量
        status_422 = getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT",
                             getattr(status, "HTTP_422_UNPROCESSABLE_ENTITY", 422))
        return JSONResponse(
            status_code=status_422,
            content=resp,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        """
        处理 FastAPI/Starlette HTTPException

        保持原有 HTTP 状态码，但统一响应体格式。
        """
        request_id = _get_request_id(request)

        # 根据 HTTP 状态码映射业务错误码
        if exc.status_code == status.HTTP_400_BAD_REQUEST:
            code = ErrorCode.INVALID_PARAMS
        elif exc.status_code == status.HTTP_401_UNAUTHORIZED:
            code = ErrorCode.UNAUTHORIZED
        elif exc.status_code == status.HTTP_403_FORBIDDEN:
            code = ErrorCode.FORBIDDEN
        elif exc.status_code == status.HTTP_404_NOT_FOUND:
            code = ErrorCode.NOT_FOUND
        elif exc.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
            code = ErrorCode.RATE_LIMITED
        elif exc.status_code == status.HTTP_503_SERVICE_UNAVAILABLE:
            code = ErrorCode.SERVICE_UNAVAILABLE
        elif exc.status_code >= 500:
            code = ErrorCode.INTERNAL_ERROR
        else:
            code = ErrorCode.UNKNOWN_ERROR

        detail = exc.detail
        message = detail if isinstance(detail, str) else str(detail)

        try:
            log_level = logger.warning if exc.status_code < 500 else logger.error
            log_level(
                "http_exception",
                request_id=request_id,
                http_status=exc.status_code,
                error_code=code.value,
                message=message,
                path=str(request.url.path) if request else "",
                method=request.method if request else "",
            )
        except Exception:
            pass

        resp = error_response(
            code=code,
            message=message,
            data={"http_status": exc.status_code},
            request_id=request_id,
        )
        return JSONResponse(status_code=exc.status_code, content=resp)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        """
        处理未捕获的通用异常（兜底）

        返回 500 内部错误，记录完整错误栈和 request_id 便于排查。
        """
        request_id = _get_request_id(request)
        error_trace = traceback.format_exc()

        try:
            logger.error(
                "unhandled_exception",
                request_id=request_id,
                error_type=exc.__class__.__name__,
                error_message=str(exc),
                path=str(request.url.path) if request else "",
                method=request.method if request else "",
                traceback=error_trace,
            )
        except Exception:
            pass

        resp = error_response(
            code=ErrorCode.INTERNAL_ERROR,
            message="服务器内部错误",
            data={
                "request_id": request_id,
                "error_type": exc.__class__.__name__,
            },
            request_id=request_id,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=resp,
        )


__all__ = ["register_exception_handlers"]
# vim: set et ts=4 sw=4:
