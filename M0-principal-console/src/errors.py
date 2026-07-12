"""
M0 主理人管控台 - 错误处理

统一的异常定义和错误响应处理。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from .models import ApiResponse


# ---------------------------------------------------------------------------
# 自定义异常
# ---------------------------------------------------------------------------

class M0BaseError(Exception):
    """M0 基础异常类"""

    def __init__(
        self,
        message: str = "系统错误",
        code: int = -1,
        data: Optional[Dict[str, Any]] = None,
        status_code: int = 500,
    ) -> None:
        """
        初始化基础异常

        Args:
            message: 错误消息
            code: 业务错误码
            data: 附加数据
            status_code: HTTP 状态码
        """
        self.message = message
        self.code = code
        self.data = data or {}
        self.status_code = status_code
        super().__init__(message)


class AuthenticationError(M0BaseError):
    """认证失败异常"""

    def __init__(self, message: str = "认证失败", data: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message=message, code=40100, data=data, status_code=401)


class PermissionDeniedError(M0BaseError):
    """权限不足异常"""

    def __init__(self, message: str = "权限不足", data: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message=message, code=40300, data=data, status_code=403)


class NotFoundError(M0BaseError):
    """资源不存在异常"""

    def __init__(self, message: str = "资源不存在", data: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message=message, code=40400, data=data, status_code=404)


class ValidationError(M0BaseError):
    """参数验证失败异常"""

    def __init__(self, message: str = "参数验证失败", data: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message=message, code=40000, data=data, status_code=400)


class M8ConnectionError(M0BaseError):
    """M8 连接失败异常"""

    def __init__(self, message: str = "M8 服务连接失败", data: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message=message, code=50300, data=data, status_code=503)


class EmergencyLockError(M0BaseError):
    """紧急锁定异常"""

    def __init__(self, message: str = "系统处于紧急锁定状态", data: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message=message, code=50310, data=data, status_code=503)


# ---------------------------------------------------------------------------
# 异常处理器注册
# ---------------------------------------------------------------------------

def register_error_handlers(app: FastAPI) -> None:
    """
    向 FastAPI 应用注册所有错误处理器

    Args:
        app: FastAPI 应用实例
    """

    @app.exception_handler(M0BaseError)
    async def m0_base_error_handler(request: Request, exc: M0BaseError) -> JSONResponse:
        """处理 M0 自定义异常"""
        response = ApiResponse.error(code=exc.code, message=exc.message, data=exc.data)
        return JSONResponse(
            status_code=exc.status_code,
            content=response.model_dump(),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        """处理 HTTP 异常"""
        response = ApiResponse.error(
            code=exc.status_code * 100,
            message=str(exc.detail) if isinstance(exc.detail, str) else "请求错误",
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=response.model_dump(),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        """处理请求验证异常"""
        errors = []
        for err in exc.errors():
            loc = " -> ".join(str(l) for l in err.get("loc", []))
            errors.append(f"{loc}: {err.get('msg', '验证失败')}")
        response = ApiResponse.error(
            code=40000,
            message="参数验证失败",
            data={"errors": errors},
        )
        return JSONResponse(
            status_code=400,
            content=response.model_dump(),
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """处理未捕获的通用异常"""
        response = ApiResponse.error(
            code=50000,
            message=f"服务器内部错误: {str(exc)}",
        )
        return JSONResponse(
            status_code=500,
            content=response.model_dump(),
        )
