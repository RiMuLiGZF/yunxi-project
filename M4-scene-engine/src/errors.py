"""M4 场景引擎 - 统一错误码定义

错误码规则:
- 4xxxx: 客户端错误 (40000-49999)
- 5xxxx: 服务端错误 (50000-59999)
- 4x0xx: 第2位表示子模块
  - 400xx: 通用错误
  - 410xx: 场景相关
  - 420xx: 上下文相关
  - 430xx: 配置相关
  - 440xx: 鉴权相关

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

from enum import IntEnum
from typing import Any, Dict, Optional, Tuple


class ErrorCode(IntEnum):
    """统一错误码枚举.

    每个枚举成员的 value 为 (code, message) 元组，
    通过 IntEnum 继承保证与整数的兼容性。
    新增错误码时只需在此处添加一项，消息与错误码集中管理。
    """

    # ---- 通用错误 (400xx) ----
    SUCCESS = (0, "成功")
    BAD_REQUEST = (40000, "请求参数错误")
    INVALID_PARAMETER = (40001, "参数无效")
    MISSING_PARAMETER = (40002, "缺少必需参数")
    RESOURCE_NOT_FOUND = (40004, "资源不存在")
    METHOD_NOT_ALLOWED = (40005, "方法不允许")
    RATE_LIMITED = (40029, "请求过于频繁")

    # ---- 场景相关 (410xx) ----
    SCENE_NOT_FOUND = (41001, "场景不存在")
    SCENE_SWITCH_FAILED = (41002, "场景切换失败")
    SCENE_ALREADY_ACTIVE = (41003, "场景已在运行")
    SCENE_INVALID_CONFIG = (41004, "场景配置无效")
    SCENE_ENGINE_ERROR = (41005, "场景引擎内部错误")

    # ---- 上下文相关 (420xx) ----
    CONTEXT_NOT_FOUND = (42001, "上下文不存在")
    CONTEXT_STORE_ERROR = (42002, "上下文存储错误")
    CONTEXT_TOO_LARGE = (42003, "上下文内容过大")

    # ---- 配置相关 (430xx) ----
    CONFIG_NOT_FOUND = (43001, "配置不存在")
    CONFIG_INVALID = (43002, "配置无效")
    CONFIG_READ_ONLY = (43003, "配置为只读")

    # ---- 鉴权相关 (440xx) ----
    TOKEN_MISSING = (44001, "未提供认证令牌")
    TOKEN_INVALID = (44002, "认证令牌无效")
    PERMISSION_DENIED = (44003, "权限不足")

    # ---- 服务端错误 (500xx) ----
    INTERNAL_ERROR = (50000, "服务器内部错误")
    SERVICE_UNAVAILABLE = (50003, "服务暂不可用")
    TIMEOUT = (50004, "请求超时")

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

    Args:
        code: 错误码（整数或 ErrorCode 枚举）

    Returns:
        错误消息字符串，未知错误码返回"未知错误"
    """
    if isinstance(code, ErrorCode):
        return code.message
    return ERROR_MESSAGES.get(code, "未知错误")


def error_response(
    code: int,
    message: Optional[str] = None,
    data: Optional[Any] = None,
    request_id: Optional[str] = None,
) -> Dict[str, Any]:
    """构造统一错误响应

    Args:
        code: 错误码
        message: 自定义错误消息（None 则使用默认）
        data: 附加数据
        request_id: 请求ID

    Returns:
        统一格式的响应字典
    """
    import uuid
    return {
        "code": int(code),
        "message": message or get_error_message(code),
        "data": data,
        "request_id": request_id or uuid.uuid4().hex[:16],
    }


class M4Error(Exception):
    """M4 业务异常基类

    可以在路由中抛出此异常，配合全局异常处理器返回统一格式。
    """

    def __init__(
        self,
        code: int,
        message: Optional[str] = None,
        data: Optional[Any] = None,
    ):
        self.code = int(code)
        self.message = message or get_error_message(self.code)
        self.data = data
        super().__init__(self.message)

    def to_response(self, request_id: Optional[str] = None) -> Dict[str, Any]:
        """转换为统一响应格式"""
        return error_response(self.code, self.message, self.data, request_id)
