"""
云汐系统 - 统一响应标准包
==========================

项目级权威统一响应格式工具包，所有模块的 API 响应都应遵循此标准。

标准字段：
    code: int       - 状态码，0 表示成功，非 0 表示错误
    message: str    - 状态描述
    data: Any       - 响应数据（可选）
    trace_id: str   - 链路追踪 ID（可选，统一使用 trace_id）
    timestamp: float - Unix 时间戳（秒级浮点数）

快速开始：
    from shared.unified_response import ApiResponse, ok, fail

    # 成功响应
    return ApiResponse.success(data={"key": "value"})

    # 错误响应
    return ApiResponse.error(code=404, message="Not Found")

    # 便捷函数（返回字典）
    return ok(data={"key": "value"})
    return fail(code=404, message="Not Found")

FastAPI 集成：
    from fastapi import FastAPI
    from shared.unified_response import register_unified_response

    app = FastAPI()
    register_unified_response(app)

模块：
    base.py              - 核心 ApiResponse 类（Pydantic/dataclass 双模式）
    fastapi_integration.py - FastAPI 中间件和异常处理
    constants.py         - 标准错误码常量和消息模板
"""

from .base import (
    ApiResponse,
    ok,
    fail,
    generate_trace_id,
    from_legacy_response,
)
from .constants import (
    # HTTP 状态码
    HTTP_OK,
    HTTP_CREATED,
    HTTP_ACCEPTED,
    HTTP_NO_CONTENT,
    HTTP_BAD_REQUEST,
    HTTP_UNAUTHORIZED,
    HTTP_FORBIDDEN,
    HTTP_NOT_FOUND,
    HTTP_METHOD_NOT_ALLOWED,
    HTTP_CONFLICT,
    HTTP_TOO_MANY_REQUESTS,
    HTTP_INTERNAL_SERVER_ERROR,
    HTTP_BAD_GATEWAY,
    HTTP_SERVICE_UNAVAILABLE,
    HTTP_GATEWAY_TIMEOUT,
    # 标准错误码
    SUCCESS,
    ERR_VALIDATION,
    ERR_MISSING_FIELD,
    ERR_INVALID_FORMAT,
    ERR_TOO_LONG,
    ERR_TOO_SHORT,
    ERR_INVALID_VALUE,
    ERR_AUTH_FAILED,
    ERR_TOKEN_EXPIRED,
    ERR_TOKEN_INVALID,
    ERR_LOGIN_REQUIRED,
    ERR_PERMISSION_DENIED,
    ERR_ROLE_REQUIRED,
    ERR_SCOPE_INSUFFICIENT,
    ERR_NOT_FOUND,
    ERR_ENDPOINT_NOT_FOUND,
    ERR_USER_NOT_FOUND,
    ERR_BUSINESS,
    ERR_OPERATION_FAILED,
    ERR_ALREADY_EXISTS,
    ERR_STATE_CONFLICT,
    ERR_INTERNAL,
    ERR_SERVICE_UNAVAILABLE,
    ERR_TIMEOUT,
    ERR_DEPENDENCY_FAILURE,
    ERR_UPSTREAM_ERROR,
    ERR_UPSTREAM_TIMEOUT,
    ERR_EXTERNAL_API,
    ERR_RATE_LIMITED,
    ERR_QUOTA_EXCEEDED,
    ERR_TOO_MANY_CONNECTIONS,
    ERR_DATA_INTEGRITY,
    ERR_DATA_CONFLICT,
    ERR_DATA_CORRUPTED,
    # 映射表
    MODULE_CODE_RANGES,
    STANDARD_MESSAGES,
    ERROR_HTTP_STATUS_MAP,
    # 工具函数
    get_standard_message,
    get_http_status,
)
from .fastapi_integration import (
    UnifiedResponseMiddleware,
    register_unified_response,
    unified_response,
)

__all__ = [
    # 核心类
    "ApiResponse",
    # 便捷函数
    "ok",
    "fail",
    "generate_trace_id",
    "from_legacy_response",
    # HTTP 状态码
    "HTTP_OK",
    "HTTP_CREATED",
    "HTTP_ACCEPTED",
    "HTTP_NO_CONTENT",
    "HTTP_BAD_REQUEST",
    "HTTP_UNAUTHORIZED",
    "HTTP_FORBIDDEN",
    "HTTP_NOT_FOUND",
    "HTTP_METHOD_NOT_ALLOWED",
    "HTTP_CONFLICT",
    "HTTP_TOO_MANY_REQUESTS",
    "HTTP_INTERNAL_SERVER_ERROR",
    "HTTP_BAD_GATEWAY",
    "HTTP_SERVICE_UNAVAILABLE",
    "HTTP_GATEWAY_TIMEOUT",
    # 标准错误码
    "SUCCESS",
    "ERR_VALIDATION",
    "ERR_MISSING_FIELD",
    "ERR_INVALID_FORMAT",
    "ERR_TOO_LONG",
    "ERR_TOO_SHORT",
    "ERR_INVALID_VALUE",
    "ERR_AUTH_FAILED",
    "ERR_TOKEN_EXPIRED",
    "ERR_TOKEN_INVALID",
    "ERR_LOGIN_REQUIRED",
    "ERR_PERMISSION_DENIED",
    "ERR_ROLE_REQUIRED",
    "ERR_SCOPE_INSUFFICIENT",
    "ERR_NOT_FOUND",
    "ERR_ENDPOINT_NOT_FOUND",
    "ERR_USER_NOT_FOUND",
    "ERR_BUSINESS",
    "ERR_OPERATION_FAILED",
    "ERR_ALREADY_EXISTS",
    "ERR_STATE_CONFLICT",
    "ERR_INTERNAL",
    "ERR_SERVICE_UNAVAILABLE",
    "ERR_TIMEOUT",
    "ERR_DEPENDENCY_FAILURE",
    "ERR_UPSTREAM_ERROR",
    "ERR_UPSTREAM_TIMEOUT",
    "ERR_EXTERNAL_API",
    "ERR_RATE_LIMITED",
    "ERR_QUOTA_EXCEEDED",
    "ERR_TOO_MANY_CONNECTIONS",
    "ERR_DATA_INTEGRITY",
    "ERR_DATA_CONFLICT",
    "ERR_DATA_CORRUPTED",
    # 映射表
    "MODULE_CODE_RANGES",
    "STANDARD_MESSAGES",
    "ERROR_HTTP_STATUS_MAP",
    # 工具函数
    "get_standard_message",
    "get_http_status",
    # FastAPI 集成
    "UnifiedResponseMiddleware",
    "register_unified_response",
    "unified_response",
]

__version__ = "1.0.0"
