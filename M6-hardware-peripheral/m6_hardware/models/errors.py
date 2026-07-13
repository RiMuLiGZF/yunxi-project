"""
M6 硬件外设 - 统一错误码体系

P1-4 改造：定义标准化错误码枚举、自定义异常及 JSON 响应生成能力，
替代模块内各处的硬编码错误字符串与魔法数字。
"""

from enum import IntEnum
from typing import Any, Dict, Optional

from fastapi.responses import JSONResponse


class ErrorCode(IntEnum):
    """M6 标准错误码

    按业务域分层：
    - 0xx   通用 HTTP 语义错误
    - 1xx   设备域错误
    - 2xx   传感器域错误
    - 3xx   SSE 实时推送域错误
    """

    # 通用错误
    SUCCESS = 0
    BAD_REQUEST = 400
    UNAUTHORIZED = 401
    FORBIDDEN = 403
    NOT_FOUND = 404
    INTERNAL_ERROR = 500

    # 设备错误
    DEVICE_NOT_FOUND = 100
    DEVICE_OFFLINE = 101
    DEVICE_ALREADY_PAIRED = 102
    DEVICE_NOT_PAIRED = 103
    ACTION_NOT_SUPPORTED = 104
    ACTION_EXECUTION_ERROR = 105

    # 传感器错误
    SENSOR_NOT_FOUND = 200
    SENSOR_DATA_INVALID = 201

    # SSE 错误
    SSE_TOKEN_INVALID = 300
    SSE_TOKEN_EXPIRED = 301
    SSE_LIMIT_EXCEEDED = 302


class M6Exception(Exception):
    """M6 业务异常

    携带结构化错误码、可读消息及建议的 HTTP 状态码，
    可在 FastAPI exception_handler 中统一转换为标准 JSONResponse。
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        http_status: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.code = code
        self.message = message
        self.http_status = http_status or self._infer_http_status(code)
        self.details = details or {}
        super().__init__(self.message)

    @staticmethod
    def _infer_http_status(code: ErrorCode) -> int:
        """根据错误码推断默认 HTTP 状态码"""
        if code == ErrorCode.SUCCESS:
            return 200
        if code in (ErrorCode.BAD_REQUEST, ErrorCode.SENSOR_DATA_INVALID):
            return 400
        if code == ErrorCode.UNAUTHORIZED:
            return 401
        if code == ErrorCode.FORBIDDEN:
            return 403
        if code in (
            ErrorCode.NOT_FOUND,
            ErrorCode.DEVICE_NOT_FOUND,
            ErrorCode.SENSOR_NOT_FOUND,
        ):
            return 404
        if code in (
            ErrorCode.DEVICE_OFFLINE,
            ErrorCode.DEVICE_ALREADY_PAIRED,
            ErrorCode.DEVICE_NOT_PAIRED,
            ErrorCode.ACTION_NOT_SUPPORTED,
            ErrorCode.SSE_TOKEN_INVALID,
            ErrorCode.SSE_TOKEN_EXPIRED,
            ErrorCode.SSE_LIMIT_EXCEEDED,
        ):
            return 409  # Conflict / 业务条件不满足
        return 500

    def to_dict(self) -> Dict[str, Any]:
        """转换为标准错误字典"""
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }

    def to_json_response(self) -> JSONResponse:
        """生成 FastAPI JSONResponse"""
        return JSONResponse(
            status_code=self.http_status,
            content=self.to_dict(),
        )
