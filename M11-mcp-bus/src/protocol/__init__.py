"""M11 MCP Bus - Protocol 协议层.

提供 JSON-RPC 2.0 协议的完整实现，包括请求解析、响应构建、
错误处理和批量请求支持。

使用方式:
    from src.protocol import JSONRPCRequest, JSONRPCResponse, JSONRPCError
    from src.protocol import parse_request, build_response, build_error

架构定位:
    Protocol 层是 M11 架构的最底层，负责 JSON-RPC 2.0 协议的编解码，
    不涉及任何传输层或业务逻辑。上层（Transport、Services）通过
    Protocol 层与外部系统通信。
"""

from .jsonrpc import (
    JSONRPCError,
    JSONRPCRequest,
    JSONRPCResponse,
    build_batch_response,
    build_error,
    build_error_from_exception,
    build_response,
    handle_parse_error,
    parse_request,
    parse_response,
)
from .types import (
    ERROR_CODE_FIELD,
    ERROR_DATA_FIELD,
    ERROR_FIELD,
    ERROR_MESSAGE_FIELD,
    ID_FIELD,
    JSONRPC_ERROR_MESSAGES,
    JSONRPC_FIELD,
    JSONRPC_VERSION,
    METHOD_FIELD,
    MCP_METHODS,
    MCP_PROTOCOL_VERSION,
    PARAMS_FIELD,
    RESULT_FIELD,
    JsonRpcErrorCode,
    JsonRpcMessage,
    ParamsType,
    RequestId,
    ResultType,
    get_error_message,
    is_notification,
    is_valid_request_id,
)

__all__ = [
    # 模型类
    "JSONRPCError",
    "JSONRPCRequest",
    "JSONRPCResponse",
    # 解析函数
    "parse_request",
    "parse_response",
    # 构建函数
    "build_response",
    "build_error",
    "build_error_from_exception",
    "build_batch_response",
    "handle_parse_error",
    # 类型
    "JsonRpcErrorCode",
    "JsonRpcMessage",
    "RequestId",
    "ParamsType",
    "ResultType",
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
    "JSONRPC_ERROR_MESSAGES",
    # MCP 常量
    "MCP_PROTOCOL_VERSION",
    "MCP_METHODS",
    # 工具函数
    "get_error_message",
    "is_valid_request_id",
    "is_notification",
]
