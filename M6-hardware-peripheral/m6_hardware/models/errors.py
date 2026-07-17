"""
M6 硬件外设 - 统一错误码体系

P1-4 改造：定义标准化错误码枚举、自定义异常及 JSON 响应生成能力，
替代模块内各处的硬编码错误字符串与魔法数字。

CQ-015 升级：接入云汐系统统一 6 位错误码体系
- M6Exception 继承 YunxiError（当统一框架可用时）
- 旧错误码通过 M6_LEGACY_ERROR_MAP 映射到新的 6 位错误码
- 保持完全向后兼容：旧的 ErrorCode 枚举和 M6Exception 接口不变
"""

from __future__ import annotations

import sys
from enum import IntEnum
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi.responses import JSONResponse


# ============================================================
# 尝试导入统一错误框架
# ============================================================

try:
    _current = Path(__file__).resolve()
    for _ in range(10):
        _current = _current.parent
        if (_current / "shared" / "core" / "errors.py").exists():
            if str(_current) not in sys.path:
                sys.path.insert(0, str(_current))
            break
    from shared.core.errors import YunxiError, ErrorCode as SystemErrorCode
    _UNIFIED_ERRORS_AVAILABLE = True
except ImportError:
    _UNIFIED_ERRORS_AVAILABLE = False
    YunxiError = Exception  # type: ignore
    SystemErrorCode = None  # type: ignore


# ============================================================
# 旧版错误码枚举（保留向后兼容，标记 deprecated）
# ============================================================

class ErrorCode(IntEnum):
    """M6 标准错误码（旧版，已废弃）

    .. deprecated:: 2.0.0
        请使用 M6ErrorCode（6 位统一错误码）替代。
        旧错误码会自动映射到新的 6 位体系。

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

    # 可穿戴设备错误 (440-459 范围，避免与 HTTP 状态码冲突)
    WEARABLE_DEVICE_NOT_FOUND = 440
    WEARABLE_DEVICE_ALREADY_EXISTS = 441
    WEARABLE_DEVICE_TYPE_INVALID = 442
    WEARABLE_HEALTH_DATA_INVALID = 443
    WEARABLE_HEALTH_DATA_TYPE_UNSUPPORTED = 444
    WEARABLE_NOTIFICATION_NOT_FOUND = 445
    WEARABLE_SETTINGS_NOT_FOUND = 446
    WEARABLE_BATCH_SIZE_EXCEEDED = 447
    WEARABLE_MAC_ADDRESS_INVALID = 448


# ============================================================
# 旧错误码 -> 新 6 位错误码 映射
# ============================================================

def _build_legacy_map() -> Dict[int, int]:
    """构建旧错误码到新 6 位错误码的映射表"""
    if not _UNIFIED_ERRORS_AVAILABLE:
        return {}

    try:
        from m6_hardware.unified_errors import M6ErrorCode
    except ImportError:
        try:
            from ..unified_errors import M6ErrorCode
        except ImportError:
            return {}

    return {
        # 通用错误 -> 系统通用错误码
        ErrorCode.SUCCESS: 0,
        ErrorCode.BAD_REQUEST: SystemErrorCode.VALIDATION_ERROR,
        ErrorCode.UNAUTHORIZED: SystemErrorCode.AUTH_FAILED,
        ErrorCode.FORBIDDEN: SystemErrorCode.PERMISSION_DENIED,
        ErrorCode.NOT_FOUND: SystemErrorCode.NOT_FOUND,
        ErrorCode.INTERNAL_ERROR: SystemErrorCode.INTERNAL_ERROR,
        # 设备错误 -> M6 模块错误码
        ErrorCode.DEVICE_NOT_FOUND: M6ErrorCode.DEVICE_NOT_FOUND,
        ErrorCode.DEVICE_OFFLINE: M6ErrorCode.DEVICE_OFFLINE,
        ErrorCode.DEVICE_ALREADY_PAIRED: M6ErrorCode.DEVICE_BUSY,
        ErrorCode.DEVICE_NOT_PAIRED: M6ErrorCode.DEVICE_NOT_FOUND,
        ErrorCode.ACTION_NOT_SUPPORTED: M6ErrorCode.INVALID_COMMAND,
        ErrorCode.ACTION_EXECUTION_ERROR: M6ErrorCode.COMMAND_TIMEOUT,
        # 传感器错误 -> M6 模块错误码
        ErrorCode.SENSOR_NOT_FOUND: M6ErrorCode.SENSOR_NOT_FOUND,
        ErrorCode.SENSOR_DATA_INVALID: M6ErrorCode.INVALID_SENSOR_DATA,
        # SSE 错误 -> M6 模块错误码
        ErrorCode.SSE_TOKEN_INVALID: SystemErrorCode.AUTH_FAILED,
        ErrorCode.SSE_TOKEN_EXPIRED: SystemErrorCode.TOKEN_EXPIRED,
        ErrorCode.SSE_LIMIT_EXCEEDED: SystemErrorCode.RATE_LIMITED,
        # 可穿戴设备错误 -> M6 模块错误码
        ErrorCode.WEARABLE_DEVICE_NOT_FOUND: M6ErrorCode.DEVICE_NOT_FOUND,
        ErrorCode.WEARABLE_DEVICE_ALREADY_EXISTS: SystemErrorCode.ALREADY_EXISTS,
        ErrorCode.WEARABLE_DEVICE_TYPE_INVALID: M6ErrorCode.INVALID_DEVICE_TYPE,
        ErrorCode.WEARABLE_HEALTH_DATA_INVALID: M6ErrorCode.INVALID_SENSOR_DATA,
        ErrorCode.WEARABLE_HEALTH_DATA_TYPE_UNSUPPORTED: M6ErrorCode.INVALID_SENSOR_DATA,
        ErrorCode.WEARABLE_NOTIFICATION_NOT_FOUND: SystemErrorCode.NOT_FOUND,
        ErrorCode.WEARABLE_SETTINGS_NOT_FOUND: SystemErrorCode.NOT_FOUND,
        ErrorCode.WEARABLE_BATCH_SIZE_EXCEEDED: SystemErrorCode.VALIDATION_ERROR,
        ErrorCode.WEARABLE_MAC_ADDRESS_INVALID: M6ErrorCode.INVALID_DEVICE_ID,
    }


# 延迟加载映射表（避免循环导入）
_legacy_error_map: Optional[Dict[int, int]] = None


def _get_legacy_map() -> Dict[int, int]:
    """获取旧错误码映射表（延迟初始化）"""
    global _legacy_error_map
    if _legacy_error_map is None:
        _legacy_error_map = _build_legacy_map()
    return _legacy_error_map


def _normalize_m6_code(code: int) -> int:
    """将 M6 旧错误码规范化为 6 位统一错误码"""
    mapping = _get_legacy_map()
    if not mapping:
        return code
    return mapping.get(code, code)


# ============================================================
# M6 业务异常（接入统一错误体系）
# ============================================================

if _UNIFIED_ERRORS_AVAILABLE:

    class M6Exception(YunxiError):
        """M6 业务异常（接入统一错误体系版）

        继承自 YunxiError，自动获得：
        - 6 位统一错误码体系
        - 统一异常处理器自动捕获
        - 标准化的错误响应格式

        向后兼容：
        - 仍然接受旧版 ErrorCode 枚举作为 code 参数
        - 旧错误码自动映射到新的 6 位体系
        - to_dict() 和 to_json_response() 接口保持不变
        """

        def __init__(
            self,
            code: ErrorCode | int,
            message: str,
            http_status: Optional[int] = None,
            details: Optional[Dict[str, Any]] = None,
        ):
            # 将旧错误码转换为 6 位统一错误码
            normalized_code = _normalize_m6_code(int(code))

            # 调用父类构造
            super().__init__(
                message=message,
                code=normalized_code,
                details=details,
                http_status=http_status,
            )

            # 保存原始错误码（用于向后兼容）
            self._legacy_code = int(code)

        @property
        def legacy_code(self) -> int:
            """旧版错误码（向后兼容）"""
            return self._legacy_code

        def to_dict(self) -> Dict[str, Any]:
            """转换为标准错误字典（统一格式）"""
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

else:
    # 回退模式：不依赖统一框架
    class M6Exception(Exception):
        """M6 业务异常（回退模式）

        携带结构化错误码、可读消息及建议的 HTTP 状态码，
        可在 FastAPI exception_handler 中统一转换为标准 JSONResponse。
        """

        def __init__(
            self,
            code: ErrorCode | int,
            message: str,
            http_status: Optional[int] = None,
            details: Optional[Dict[str, Any]] = None,
        ):
            self.code = int(code)
            self.message = message
            self.http_status = http_status or self._infer_http_status(int(code))
            self.details = details or {}
            super().__init__(self.message)

        @staticmethod
        def _infer_http_status(code: int) -> int:
            """根据错误码推断默认 HTTP 状态码"""
            if code == 0:
                return 200
            # 404 - 资源不存在
            if code in (
                404, 100, 200, 440, 445, 446,
            ):
                return 404
            # 400 - 参数错误 / 数据无效
            if code in (400, 201, 443):
                return 400
            if code == 401:
                return 401
            if code == 403:
                return 403
            # 409 - 冲突 / 业务条件不满足
            if code in (
                101, 102, 103, 104, 105,
                300, 301, 302,
                441, 442, 444, 447, 448,
            ):
                return 409
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


# ============================================================
# 便捷工厂函数
# ============================================================

def raise_m6_error(
    code: ErrorCode | int,
    message: str,
    details: Optional[Dict[str, Any]] = None,
    http_status: Optional[int] = None,
) -> None:
    """抛出 M6 业务异常的便捷函数"""
    raise M6Exception(code=code, message=message, details=details, http_status=http_status)


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "ErrorCode",
    "M6Exception",
    "raise_m6_error",
    "_UNIFIED_ERRORS_AVAILABLE",
]
