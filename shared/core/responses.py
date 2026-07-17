"""
云汐系统统一 API 响应格式模块
============================

提供标准化的成功/失败/分页响应结构，支持链式调用，
以及与 FastAPI 集成的响应工具。

响应格式规范：

成功响应：
{
    "code": 0,
    "message": "success",
    "data": {...},
    "trace_id": "xxx"
}

错误响应：
{
    "code": 101,
    "message": "参数验证失败",
    "details": {...},
    "trace_id": "xxx"
}

分页响应：
{
    "code": 0,
    "message": "success",
    "data": {
        "items": [...],
        "total": 100,
        "page": 1,
        "page_size": 20
    },
    "trace_id": "xxx"
}

向后兼容：
- 保留旧版常量（SUCCESS, ERROR_INVALID_PARAMS 等）并映射到新码
- ApiResponse 类保留原有接口，新增能力
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from .errors import (
    ErrorCode,
    YunxiError,
    error_to_dict,
    normalize_error_code,
    get_http_status,
    get_default_message,
)


# ============================================================
# 旧版错误码常量（向后兼容，映射到新 6 位体系）
# ============================================================

SUCCESS = ErrorCode.SUCCESS
"""成功（0）"""

ERROR_INVALID_PARAMS = ErrorCode.VALIDATION_ERROR
"""参数错误（000101）"""

ERROR_UNAUTHORIZED = ErrorCode.AUTH_FAILED
"""未认证（000201）"""

ERROR_FORBIDDEN = ErrorCode.PERMISSION_DENIED
"""无权限（000301）"""

ERROR_NOT_FOUND = ErrorCode.NOT_FOUND
"""资源不存在（000401）"""

ERROR_INTERNAL = ErrorCode.INTERNAL_ERROR
"""服务器内部错误（000601）"""

ERROR_MODULE_UNAVAILABLE = ErrorCode.SERVICE_UNAVAILABLE
"""模块不可用（000602）"""


# ============================================================
# 统一响应类
# ============================================================

class ApiResponse:
    """统一 API 响应类.

    提供标准化的响应结构，所有模块的 API 响应应使用此类生成，
    以保证前后端交互格式的一致性。

    支持链式调用：
        >>> ApiResponse.success(data).with_trace_id(tid).to_dict()

    Attributes:
        code: 状态码，0 表示成功，非 0 表示错误
        message: 状态描述
        data: 响应数据（成功时）
        details: 错误详情（错误时）
        trace_id: 请求追踪 ID
        http_status: 建议的 HTTP 状态码
    """

    def __init__(
        self,
        code: int = SUCCESS,
        message: str = "操作成功",
        data: Optional[Any] = None,
        details: Optional[Dict[str, Any]] = None,
        trace_id: Optional[str] = None,
        http_status: Optional[int] = None,
    ):
        self.code = code
        self.message = message
        self.data = data
        self.details = details or {}
        self.trace_id = trace_id
        self._http_status = http_status

    # ---- 工厂方法 ----

    @classmethod
    def success(
        cls,
        data: Optional[Any] = None,
        message: str = "操作成功",
        trace_id: Optional[str] = None,
    ) -> "ApiResponse":
        """创建成功响应.

        Args:
            data: 响应数据
            message: 成功描述信息
            trace_id: 请求追踪 ID

        Returns:
            ApiResponse 实例，code 为 0
        """
        return cls(
            code=SUCCESS,
            message=message,
            data=data,
            trace_id=trace_id,
            http_status=200,
        )

    @classmethod
    def error(
        cls,
        code: int = ERROR_INTERNAL,
        message: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        trace_id: Optional[str] = None,
        http_status: Optional[int] = None,
    ) -> "ApiResponse":
        """创建错误响应.

        Args:
            code: 错误码
            message: 错误描述信息（为 None 时使用默认消息）
            details: 错误详情字典
            trace_id: 请求追踪 ID
            http_status: HTTP 状态码（为 None 时根据错误码推断）

        Returns:
            ApiResponse 实例
        """
        normalized_code = normalize_error_code(code)
        final_message = message or get_default_message(normalized_code)
        final_http_status = http_status if http_status is not None else get_http_status(normalized_code)
        return cls(
            code=normalized_code,
            message=final_message,
            details=details or {},
            trace_id=trace_id,
            http_status=final_http_status,
        )

    @classmethod
    def from_error(cls, error: Exception, trace_id: Optional[str] = None) -> "ApiResponse":
        """从异常创建错误响应.

        Args:
            error: 异常实例
            trace_id: 请求追踪 ID

        Returns:
            ApiResponse 实例
        """
        err_dict = error_to_dict(error)
        code = err_dict["code"]
        message = err_dict["message"]
        details = err_dict["details"]
        http_status = getattr(error, "http_status", None)
        return cls.error(
            code=code,
            message=message,
            details=details,
            trace_id=trace_id,
            http_status=http_status,
        )

    @classmethod
    def from_yunxi_error(cls, error: YunxiError, trace_id: Optional[str] = None) -> "ApiResponse":
        """从 YunxiError 创建错误响应.

        Args:
            error: YunxiError 异常实例
            trace_id: 请求追踪 ID

        Returns:
            ApiResponse 实例
        """
        return cls.error(
            code=error.code,
            message=error.message,
            details=error.details,
            trace_id=trace_id,
            http_status=error.http_status,
        )

    @classmethod
    def paginated(
        cls,
        items: List[Any],
        total: int,
        page: int = 1,
        page_size: int = 20,
        message: str = "操作成功",
        trace_id: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> "ApiResponse":
        """创建分页响应.

        Args:
            items: 数据列表
            total: 总记录数
            page: 当前页码（从 1 开始）
            page_size: 每页数量
            message: 成功描述
            trace_id: 请求追踪 ID
            extra: 额外附加到 data 的字段

        Returns:
            ApiResponse 实例，data 为分页结构
        """
        data: Dict[str, Any] = {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size if page_size > 0 else 0,
        }
        if extra:
            data.update(extra)
        return cls.success(data=data, message=message, trace_id=trace_id)

    # ---- 链式调用方法 ----

    def with_data(self, data: Any) -> "ApiResponse":
        """设置响应数据（链式调用）."""
        self.data = data
        return self

    def with_message(self, message: str) -> "ApiResponse":
        """设置响应消息（链式调用）."""
        self.message = message
        return self

    def with_trace_id(self, trace_id: str) -> "ApiResponse":
        """设置追踪 ID（链式调用）."""
        self.trace_id = trace_id
        return self

    def with_details(self, **details: Any) -> "ApiResponse":
        """添加错误详情（链式调用）."""
        self.details.update(details)
        return self

    def with_http_status(self, status: int) -> "ApiResponse":
        """设置 HTTP 状态码（链式调用）."""
        self._http_status = status
        return self

    # ---- 属性 ----

    @property
    def is_success(self) -> bool:
        """判断是否为成功响应."""
        return self.code == SUCCESS

    @property
    def http_status(self) -> int:
        """获取 HTTP 状态码."""
        if self._http_status is not None:
            return self._http_status
        return get_http_status(self.code)

    # ---- 输出方法 ----

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式.

        Returns:
            标准响应字典
        """
        result: Dict[str, Any] = {
            "code": self.code,
            "message": self.message,
        }

        if self.is_success:
            result["data"] = self.data
        else:
            # 错误响应包含 details
            result["details"] = self.details if self.details else {}
            # 错误响应也可能有 data（部分旧接口需要）
            if self.data is not None:
                result["data"] = self.data

        if self.trace_id is not None:
            result["trace_id"] = self.trace_id

        return result

    def to_json_response(self):
        """转换为 FastAPI JSONResponse.

        Returns:
            fastapi.responses.JSONResponse 实例
        """
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=self.http_status,
            content=self.to_dict(),
        )

    # ---- 特殊方法 ----

    def __str__(self) -> str:
        status = "OK" if self.is_success else "ERR"
        return f"ApiResponse[{status}] code={self.code}, message={self.message!r}"

    def __repr__(self) -> str:
        return (
            f"ApiResponse(code={self.code}, message={self.message!r}, "
            f"data={self.data!r}, details={self.details!r}, "
            f"trace_id={self.trace_id!r}, http_status={self.http_status})"
        )


# ============================================================
# 便捷响应函数
# ============================================================

def ok(data: Any = None, message: str = "操作成功", trace_id: Optional[str] = None) -> Dict[str, Any]:
    """快速构建成功响应字典.

    Args:
        data: 响应数据
        message: 成功描述
        trace_id: 追踪 ID

    Returns:
        标准成功响应字典
    """
    return ApiResponse.success(data=data, message=message, trace_id=trace_id).to_dict()


def fail(
    code: int = ERROR_INTERNAL,
    message: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """快速构建错误响应字典.

    Args:
        code: 错误码
        message: 错误描述
        details: 错误详情
        trace_id: 追踪 ID

    Returns:
        标准错误响应字典
    """
    return ApiResponse.error(code=code, message=message, details=details, trace_id=trace_id).to_dict()


def paginated(
    items: List[Any],
    total: int,
    page: int = 1,
    page_size: int = 20,
    message: str = "操作成功",
    trace_id: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """快速构建分页响应字典.

    Args:
        items: 数据列表
        total: 总记录数
        page: 当前页码
        page_size: 每页数量
        message: 成功描述
        trace_id: 追踪 ID
        extra: 额外字段

    Returns:
        标准分页响应字典
    """
    return ApiResponse.paginated(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        message=message,
        trace_id=trace_id,
        extra=extra,
    ).to_dict()


# ============================================================
# FastAPI 全局异常处理器
# ============================================================

class GlobalExceptionHandler:
    """FastAPI 全局异常处理器.

    自动捕获所有已知异常，转换为统一响应格式。
    支持自定义异常映射。

    Usage:
        >>> from fastapi import FastAPI
        >>> app = FastAPI()
        >>> handler = GlobalExceptionHandler(app)
        >>> handler.register()

    或者手动注册：
        >>> handler = GlobalExceptionHandler()
        >>> handler.register_to(app)
    """

    def __init__(self, app=None, logger=None, custom_mapping: Optional[Dict[type, int]] = None):
        """初始化全局异常处理器.

        Args:
            app: FastAPI 应用实例（可选，可后续注册）
            logger: 日志记录器（可选，默认使用 structlog）
            custom_mapping: 自定义异常类型到错误码的映射
        """
        self._app = app
        self._custom_mapping = custom_mapping or {}
        self._logger = logger

        if app is not None:
            self.register_to(app)

    def _get_logger(self):
        """获取日志记录器."""
        if self._logger is not None:
            return self._logger
        try:
            import structlog
            return structlog.get_logger("yunxi.exception_handler")
        except ImportError:
            import logging
            return logging.getLogger("yunxi.exception_handler")

    def _get_trace_id(self, request) -> str:
        """从请求中获取 trace_id."""
        # 优先从请求 state 获取（由追踪中间件设置）
        trace_id = getattr(getattr(request, "state", None), "trace_id", None)
        if trace_id:
            return trace_id
        # 从 header 获取
        trace_id = request.headers.get("x-trace-id", "")
        if trace_id:
            return trace_id
        # 从 header 获取 request_id 作为备选
        request_id = request.headers.get("x-request-id", "")
        if request_id:
            return request_id
        # 生成新的
        import uuid
        return uuid.uuid4().hex[:16]

    def register_to(self, app) -> None:
        """注册异常处理器到 FastAPI 应用.

        Args:
            app: FastAPI 应用实例
        """
        from fastapi import FastAPI
        from fastapi.exceptions import RequestValidationError
        from starlette.exceptions import HTTPException as StarletteHTTPException

        # 注册自定义异常
        @app.exception_handler(YunxiError)
        async def yunxi_error_handler(request, exc: YunxiError):
            """处理 YunxiError 及其子类."""
            trace_id = self._get_trace_id(request)
            logger = self._get_logger()
            logger.warning(
                "yunxi_error",
                code=exc.code,
                message=exc.message,
                path=request.url.path,
                method=request.method,
                trace_id=trace_id,
            )
            response = ApiResponse.from_yunxi_error(exc, trace_id=trace_id)
            return response.to_json_response()

        # 注册 FastAPI 验证错误
        @app.exception_handler(RequestValidationError)
        async def validation_exception_handler(request, exc: RequestValidationError):
            """处理请求参数验证错误."""
            trace_id = self._get_trace_id(request)
            logger = self._get_logger()

            # 格式化验证错误详情
            errors = []
            for err in exc.errors():
                loc = " -> ".join(str(loc) for loc in err.get("loc", []))
                errors.append({
                    "field": loc,
                    "message": err.get("msg", ""),
                    "type": err.get("type", ""),
                })

            details = {
                "errors": errors,
                "error_count": len(errors),
            }

            logger.warning(
                "validation_error",
                path=request.url.path,
                method=request.method,
                error_count=len(errors),
                trace_id=trace_id,
            )

            response = ApiResponse.error(
                code=ErrorCode.VALIDATION_ERROR,
                message="参数验证失败",
                details=details,
                trace_id=trace_id,
                http_status=422,
            )
            return response.to_json_response()

        # 注册 Starlette HTTPException
        @app.exception_handler(StarletteHTTPException)
        async def http_exception_handler(request, exc: StarletteHTTPException):
            """处理 HTTP 异常（如 404、405 等）."""
            trace_id = self._get_trace_id(request)
            logger = self._get_logger()

            status_code = exc.status_code
            # 将 HTTP 状态码映射到错误码
            error_code_map = {
                400: ErrorCode.VALIDATION_ERROR,
                401: ErrorCode.AUTH_FAILED,
                403: ErrorCode.PERMISSION_DENIED,
                404: ErrorCode.ENDPOINT_NOT_FOUND,
                405: ErrorCode.PERMISSION_DENIED,
                429: ErrorCode.RATE_LIMITED,
                500: ErrorCode.INTERNAL_ERROR,
                502: ErrorCode.UPSTREAM_ERROR,
                503: ErrorCode.SERVICE_UNAVAILABLE,
                504: ErrorCode.UPSTREAM_TIMEOUT,
            }
            code = error_code_map.get(status_code, ErrorCode.INTERNAL_ERROR)
            message = exc.detail if isinstance(exc.detail, str) else str(exc.detail)

            if status_code >= 500:
                logger.error(
                    "http_exception",
                    status_code=status_code,
                    message=message,
                    path=request.url.path,
                    method=request.method,
                    trace_id=trace_id,
                )
            else:
                logger.warning(
                    "http_exception",
                    status_code=status_code,
                    message=message,
                    path=request.url.path,
                    method=request.method,
                    trace_id=trace_id,
                )

            response = ApiResponse.error(
                code=code,
                message=message,
                trace_id=trace_id,
                http_status=status_code,
            )
            return response.to_json_response()

        # 注册自定义异常映射
        for exc_type, err_code in self._custom_mapping.items():
            def _make_handler(ec):
                async def _handler(request, exc):
                    trace_id = self._get_trace_id(request)
                    logger = self._get_logger()
                    logger.warning(
                        "custom_exception",
                        error_type=type(exc).__name__,
                        code=ec,
                        path=request.url.path,
                        method=request.method,
                        trace_id=trace_id,
                    )
                    response = ApiResponse.error(
                        code=ec,
                        message=str(exc) or get_default_message(ec),
                        trace_id=trace_id,
                    )
                    return response.to_json_response()
                return _handler
            app.add_exception_handler(exc_type, _make_handler(err_code))

        # 注册兜底异常处理器
        @app.exception_handler(Exception)
        async def generic_exception_handler(request, exc: Exception):
            """处理所有未捕获的异常."""
            trace_id = self._get_trace_id(request)
            logger = self._get_logger()

            logger.error(
                "unhandled_exception",
                error_type=type(exc).__name__,
                error_message=str(exc),
                path=request.url.path,
                method=request.method,
                trace_id=trace_id,
                exc_info=exc,
            )

            # 生产环境不暴露详细错误信息
            response = ApiResponse.error(
                code=ErrorCode.INTERNAL_ERROR,
                message="服务器内部错误",
                details={
                    "trace_id": trace_id,
                    "error_type": type(exc).__name__,
                },
                trace_id=trace_id,
                http_status=500,
            )
            return response.to_json_response()

    # 兼容旧接口
    def register(self) -> None:
        """注册异常处理器（兼容旧调用方式）."""
        if self._app is not None:
            self.register_to(self._app)


def register_global_exception_handler(
    app,
    logger=None,
    custom_mapping: Optional[Dict[type, int]] = None,
) -> GlobalExceptionHandler:
    """快速注册全局异常处理器.

    Args:
        app: FastAPI 应用实例
        logger: 日志记录器（可选）
        custom_mapping: 自定义异常映射

    Returns:
        GlobalExceptionHandler 实例
    """
    return GlobalExceptionHandler(app=app, logger=logger, custom_mapping=custom_mapping)
