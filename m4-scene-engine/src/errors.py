"""
M4 场景引擎 - 统一错误码定义

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
"""

from __future__ import annotations

from enum import IntEnum
from typing import Any, Dict, Optional


class ErrorCode(IntEnum):
    """统一错误码枚举"""

    # ---- 通用错误 (400xx) ----
    SUCCESS = 0
    BAD_REQUEST = 40000
    INVALID_PARAMETER = 40001
    MISSING_PARAMETER = 40002
    RESOURCE_NOT_FOUND = 40004
    METHOD_NOT_ALLOWED = 40005
    RATE_LIMITED = 40029

    # ---- 场景相关 (410xx) ----
    SCENE_NOT_FOUND = 41001
    SCENE_SWITCH_FAILED = 41002
    SCENE_ALREADY_ACTIVE = 41003
    SCENE_INVALID_CONFIG = 41004
    SCENE_ENGINE_ERROR = 41005

    # ---- 上下文相关 (420xx) ----
    CONTEXT_NOT_FOUND = 42001
    CONTEXT_STORE_ERROR = 42002
    CONTEXT_TOO_LARGE = 42003

    # ---- 配置相关 (430xx) ----
    CONFIG_NOT_FOUND = 43001
    CONFIG_INVALID = 43002
    CONFIG_READ_ONLY = 43003

    # ---- 鉴权相关 (440xx) ----
    TOKEN_MISSING = 44001
    TOKEN_INVALID = 44002
    PERMISSION_DENIED = 44003

    # ---- 服务端错误 (500xx) ----
    INTERNAL_ERROR = 50000
    SERVICE_UNAVAILABLE = 50003
    TIMEOUT = 50004


# 错误消息映射
ERROR_MESSAGES: Dict[int, str] = {
    ErrorCode.SUCCESS: "成功",
    ErrorCode.BAD_REQUEST: "请求参数错误",
    ErrorCode.INVALID_PARAMETER: "参数无效",
    ErrorCode.MISSING_PARAMETER: "缺少必需参数",
    ErrorCode.RESOURCE_NOT_FOUND: "资源不存在",
    ErrorCode.METHOD_NOT_ALLOWED: "方法不允许",
    ErrorCode.RATE_LIMITED: "请求过于频繁",
    ErrorCode.SCENE_NOT_FOUND: "场景不存在",
    ErrorCode.SCENE_SWITCH_FAILED: "场景切换失败",
    ErrorCode.SCENE_ALREADY_ACTIVE: "场景已在运行",
    ErrorCode.SCENE_INVALID_CONFIG: "场景配置无效",
    ErrorCode.SCENE_ENGINE_ERROR: "场景引擎内部错误",
    ErrorCode.CONTEXT_NOT_FOUND: "上下文不存在",
    ErrorCode.CONTEXT_STORE_ERROR: "上下文存储错误",
    ErrorCode.CONTEXT_TOO_LARGE: "上下文内容过大",
    ErrorCode.CONFIG_NOT_FOUND: "配置不存在",
    ErrorCode.CONFIG_INVALID: "配置无效",
    ErrorCode.CONFIG_READ_ONLY: "配置为只读",
    ErrorCode.TOKEN_MISSING: "未提供认证令牌",
    ErrorCode.TOKEN_INVALID: "认证令牌无效",
    ErrorCode.PERMISSION_DENIED: "权限不足",
    ErrorCode.INTERNAL_ERROR: "服务器内部错误",
    ErrorCode.SERVICE_UNAVAILABLE: "服务暂不可用",
    ErrorCode.TIMEOUT: "请求超时",
}


def get_error_message(code: int) -> str:
    """获取错误码对应的消息"""
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
