"""M4 场景引擎 - 统一错误码定义（已迁移至统一 6 位错误码体系）

.. deprecated::
    新代码请使用 ``src.unified_errors.M4ErrorCode``。

错误码已从旧版 5 位体系（4xxxx/5xxxx）迁移至统一 6 位体系（04YYZZ）。
所有旧错误码常量仍然可用，但其底层值已映射为新的 6 位编码。

使用方式:
    from src.errors import ErrorCode, M4Error, error_response
    # 方式1: 直接返回字典
    return error_response(ErrorCode.SCENE_NOT_FOUND)
    # 方式2: 抛出异常
    raise M4Error(ErrorCode.SCENE_NOT_FOUND)
    # 方式3: 获取错误消息
    msg = ErrorCode.SCENE_NOT_FOUND.message
"""

from __future__ import annotations

import warnings
from enum import IntEnum
from typing import Any, Dict, Optional

from .unified_errors import (
    M4ErrorCode,
    M4_LEGACY_ERROR_MAP,
    m4_normalize_error_code,
    _UNIFIED_ERRORS_AVAILABLE,
)


# ---------------------------------------------------------------------------
# 兼容层：旧版 ErrorCode 枚举（保持 IntEnum + message 属性）
# ---------------------------------------------------------------------------

class ErrorCode(IntEnum):
    """统一错误码枚举（已迁移至统一 6 位错误码体系）.

    .. deprecated::
        请使用 ``M4ErrorCode`` 替代。

    每个枚举成员的 value 为新的 6 位错误码，同时保留 message 属性。
    旧代码中通过 ``ErrorCode.SCENE_NOT_FOUND`` 获取的常量值已自动更新为新编码。
    """

    # ---- 通用错误 ----
    SUCCESS = (0, "成功")
    BAD_REQUEST = (M4ErrorCode.BAD_REQUEST, "请求参数错误")
    INVALID_PARAMETER = (M4ErrorCode.INVALID_PARAMETER, "参数无效")
    MISSING_PARAMETER = (M4ErrorCode.MISSING_PARAMETER, "缺少必需参数")
    RESOURCE_NOT_FOUND = (M4ErrorCode.RESOURCE_NOT_FOUND, "资源不存在")
    METHOD_NOT_ALLOWED = (M4ErrorCode.METHOD_NOT_ALLOWED, "方法不允许")
    RATE_LIMITED = (M4ErrorCode.RATE_LIMITED, "请求过于频繁")

    # ---- 场景相关 ----
    SCENE_NOT_FOUND = (M4ErrorCode.SCENE_NOT_FOUND, "场景不存在")
    SCENE_SWITCH_FAILED = (M4ErrorCode.SCENE_SWITCH_FAILED, "场景切换失败")
    SCENE_ALREADY_ACTIVE = (M4ErrorCode.SCENE_ALREADY_ACTIVE, "场景已在运行")
    SCENE_INVALID_CONFIG = (M4ErrorCode.INVALID_SCENE_CONFIG, "场景配置无效")
    SCENE_ENGINE_ERROR = (M4ErrorCode.SCENE_ENGINE_ERROR, "场景引擎内部错误")

    # ---- 上下文相关 ----
    CONTEXT_NOT_FOUND = (M4ErrorCode.CONTEXT_NOT_FOUND, "上下文不存在")
    CONTEXT_STORE_ERROR = (M4ErrorCode.CONTEXT_STORE_ERROR, "上下文存储错误")
    CONTEXT_TOO_LARGE = (M4ErrorCode.CONTEXT_TOO_LARGE, "上下文内容过大")

    # ---- 配置相关 ----
    CONFIG_NOT_FOUND = (M4ErrorCode.CONFIG_NOT_FOUND, "配置不存在")
    CONFIG_INVALID = (M4ErrorCode.CONFIG_INVALID, "配置无效")
    CONFIG_READ_ONLY = (M4ErrorCode.CONFIG_READ_ONLY, "配置为只读")

    # ---- 鉴权相关 ----
    TOKEN_MISSING = (M4ErrorCode.TOKEN_MISSING, "未提供认证令牌")
    TOKEN_INVALID = (M4ErrorCode.TOKEN_INVALID, "认证令牌无效")
    PERMISSION_DENIED = (M4ErrorCode.PERMISSION_DENIED, "权限不足")

    # ---- 服务端错误 ----
    INTERNAL_ERROR = (M4ErrorCode.INTERNAL_ERROR, "服务器内部错误")
    SERVICE_UNAVAILABLE = (M4ErrorCode.SERVICE_UNAVAILABLE, "服务暂不可用")
    TIMEOUT = (M4ErrorCode.TIMEOUT, "请求超时")

    def __new__(cls, code: int, message: str = "") -> "ErrorCode":
        """自定义构造方法，支持 (code, message) 元组赋值."""
        obj = int.__new__(cls, code)
        obj._value_ = code
        obj._message_ = message
        return obj

    @property
    def code(self) -> int:
        """获取错误码数值."""
        return self._value_  # type: ignore[attr-defined]

    @property
    def message(self) -> str:
        """获取错误消息."""
        return self._message_  # type: ignore[attr-defined]

    def __str__(self) -> str:
        return f"{self.name}({self.code}): {self.message}"


# ---------------------------------------------------------------------------
# 向后兼容：ERROR_MESSAGES 字典（从枚举自动生成）
# ---------------------------------------------------------------------------

ERROR_MESSAGES: Dict[int, str] = {code: code.message for code in ErrorCode}


def get_error_message(code: int) -> str:
    """获取错误码对应的消息.

    自动规范化旧版 5 位错误码为新版 6 位编码。

    Args:
        code: 错误码（整数或 ErrorCode 枚举）

    Returns:
        错误消息字符串，未知错误码返回"未知错误"
    """
    if isinstance(code, ErrorCode):
        return code.message
    normalized = m4_normalize_error_code(code)
    return ERROR_MESSAGES.get(normalized, "未知错误")


def error_response(
    code: int,
    message: Optional[str] = None,
    data: Optional[Any] = None,
    request_id: Optional[str] = None,
) -> Dict[str, Any]:
    """构造统一错误响应（已迁移至统一错误码体系）.

    旧版 5 位错误码会自动映射为新版 6 位编码。

    Args:
        code: 错误码
        message: 自定义错误消息（None 则使用默认）
        data: 附加数据
        request_id: 请求ID

    Returns:
        统一格式的响应字典
    """
    import uuid
    normalized_code = m4_normalize_error_code(code)
    return {
        "code": int(normalized_code),
        "message": message or get_error_message(normalized_code),
        "data": data,
        "request_id": request_id or uuid.uuid4().hex[:16],
    }


class M4Error(Exception):
    """M4 业务异常基类（已迁移至统一错误码体系）.

    可以在路由中抛出此异常，配合全局异常处理器返回统一格式。
    旧版 5 位错误码会自动规范化为新版 6 位编码。
    """

    def __init__(
        self,
        code: int,
        message: Optional[str] = None,
        data: Optional[Any] = None,
    ):
        normalized_code = m4_normalize_error_code(code)
        self.code = int(normalized_code)
        self.message = message or get_error_message(normalized_code)
        self.data = data
        super().__init__(self.message)

    def to_response(self, request_id: Optional[str] = None) -> Dict[str, Any]:
        """转换为统一响应格式"""
        return error_response(self.code, self.message, self.data, request_id)


# 发出废弃警告（模块级别）
warnings.warn(
    "src.errors 已迁移至统一错误码体系。"
    "新代码请使用 src.unified_errors.M4ErrorCode。"
    "旧错误码常量仍然可用但已映射为新的 6 位编码。",
    DeprecationWarning,
    stacklevel=2,
)
