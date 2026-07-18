"""M11 MCP Bus - JSON-RPC 2.0 协议类型定义与常量.

定义 JSON-RPC 2.0 协议相关的类型别名、常量和枚举，
供 protocol 层其他模块复用。
"""

from __future__ import annotations

from enum import IntEnum
from typing import Any, Dict, List, Union

# ============================================================
# 类型别名
# ============================================================

# JSON-RPC 请求 ID 类型（字符串或数字）
RequestId = Union[str, int, float]

# JSON-RPC 参数类型（位置参数或命名参数）
ParamsType = Union[List[Any], Dict[str, Any]]

# JSON-RPC 结果类型
ResultType = Any

# JSON-RPC 消息类型（单条或批量）
JsonRpcMessage = Union[Dict[str, Any], List[Dict[str, Any]]]


# ============================================================
# 标准错误码枚举（JSON-RPC 2.0 规范）
# ============================================================

class JsonRpcErrorCode(IntEnum):
    """JSON-RPC 2.0 标准错误码.

    参考: https://www.jsonrpc.org/specification#error_object

    错误码范围说明:
    - -32700 to -32000: 保留给预定义错误
    - -32000 to -32099: 保留给服务器端错误（Server error）
    - 其余: 应用层自定义错误
    """

    # 解析错误 - 服务器接收到的 JSON 不是有效的 JSON
    PARSE_ERROR = -32700

    # 无效请求 - 发送的 JSON 不是有效的请求对象
    INVALID_REQUEST = -32600

    # 方法未找到 - 调用的方法不存在或不可用
    METHOD_NOT_FOUND = -32601

    # 无效参数 - 方法参数无效
    INVALID_PARAMS = -32602

    # 内部错误 - JSON-RPC 服务器内部错误
    INTERNAL_ERROR = -32603

    # 服务器错误（保留范围 -32000 到 -32099）
    SERVER_ERROR = -32000


# ============================================================
# 标准错误消息映射
# ============================================================

JSONRPC_ERROR_MESSAGES: Dict[int, str] = {
    JsonRpcErrorCode.PARSE_ERROR: "Parse error",
    JsonRpcErrorCode.INVALID_REQUEST: "Invalid Request",
    JsonRpcErrorCode.METHOD_NOT_FOUND: "Method not found",
    JsonRpcErrorCode.INVALID_PARAMS: "Invalid params",
    JsonRpcErrorCode.INTERNAL_ERROR: "Internal error",
    JsonRpcErrorCode.SERVER_ERROR: "Server error",
}


# ============================================================
# 协议版本常量
# ============================================================

# JSON-RPC 版本号
JSONRPC_VERSION = "2.0"

# 协议版本字段名
JSONRPC_FIELD = "jsonrpc"

# 请求 ID 字段名
ID_FIELD = "id"

# 方法字段名
METHOD_FIELD = "method"

# 参数字段名
PARAMS_FIELD = "params"

# 结果字段名
RESULT_FIELD = "result"

# 错误字段名
ERROR_FIELD = "error"

# 错误码字段名
ERROR_CODE_FIELD = "code"

# 错误消息字段名
ERROR_MESSAGE_FIELD = "message"

# 错误数据字段名
ERROR_DATA_FIELD = "data"


# ============================================================
# MCP 协议常量
# ============================================================

# MCP 协议版本
MCP_PROTOCOL_VERSION = "2024-11-05"

# MCP 标准方法名
MCP_METHODS = {
    "initialize": "initialize",
    "initialized_notification": "notifications/initialized",
    "tools_list": "tools/list",
    "tools_call": "tools/call",
    "resources_list": "resources/list",
    "resources_read": "resources/read",
    "prompts_list": "prompts/list",
    "prompts_get": "prompts/get",
}


# ============================================================
# 工具函数
# ============================================================

def get_error_message(code: int) -> str:
    """根据错误码获取标准错误消息.

    Args:
        code: 错误码

    Returns:
        标准错误消息，如果不是标准错误码则返回 "Server error"
    """
    return JSONRPC_ERROR_MESSAGES.get(code, "Server error")


def is_valid_request_id(request_id: Any) -> bool:
    """检查值是否为有效的 JSON-RPC 请求 ID.

    JSON-RPC 2.0 规范要求 ID 为字符串、数字或 NULL。
    实际使用中通常不使用 NULL ID（NULL 用于通知的识别）。

    Args:
        request_id: 待检查的值

    Returns:
        True 表示是有效的请求 ID
    """
    if request_id is None:
        return False
    if isinstance(request_id, (str, int, float)):
        return True
    return False


def is_notification(message: Dict[str, Any]) -> bool:
    """判断一条 JSON-RPC 消息是否为通知（无 id）.

    Args:
        message: JSON-RPC 消息字典

    Returns:
        True 表示是通知消息
    """
    return "id" not in message or message.get("id") is None


__all__ = [
    # 类型别名
    "RequestId",
    "ParamsType",
    "ResultType",
    "JsonRpcMessage",
    # 错误码
    "JsonRpcErrorCode",
    "JSONRPC_ERROR_MESSAGES",
    # 常量
    "JSONRPC_VERSION",
    "JSONRPC_FIELD",
    "ID_FIELD",
    "METHOD_FIELD",
    "PARAMS_FIELD",
    "RESULT_FIELD",
    "ERROR_FIELD",
    "ERROR_CODE_FIELD",
    "ERROR_MESSAGE_FIELD",
    "ERROR_DATA_FIELD",
    # MCP 常量
    "MCP_PROTOCOL_VERSION",
    "MCP_METHODS",
    # 工具函数
    "get_error_message",
    "is_valid_request_id",
    "is_notification",
]
