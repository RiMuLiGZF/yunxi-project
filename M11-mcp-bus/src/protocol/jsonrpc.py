"""M11 MCP Bus - JSON-RPC 2.0 协议解析器.

完整实现 JSON-RPC 2.0 规范，包括：
- 请求/响应/错误数据模型
- 请求解析与校验
- 响应构建
- 错误构建
- 批量请求支持
- 通知支持（无 id 的请求）

参考规范: https://www.jsonrpc.org/specification
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, field_validator

from .types import (
    ERROR_CODE_FIELD,
    ERROR_DATA_FIELD,
    ERROR_FIELD,
    ERROR_MESSAGE_FIELD,
    ID_FIELD,
    JSONRPC_FIELD,
    JSONRPC_VERSION,
    METHOD_FIELD,
    PARAMS_FIELD,
    RESULT_FIELD,
    JsonRpcErrorCode,
    JsonRpcMessage,
    ParamsType,
    RequestId,
    ResultType,
    get_error_message,
    is_valid_request_id,
)


# ============================================================
# JSON-RPC 错误模型
# ============================================================

class JSONRPCError(BaseModel):
    """JSON-RPC 2.0 错误对象.

    当 RPC 调用出错时，响应对象中包含 error 字段。

    属性:
        code: 错误码，使用整数表示
        message: 错误消息，简短描述
        data: 可选的附加数据，用于调试
    """

    code: int = Field(..., description="错误码，整数类型")
    message: str = Field(..., description="错误消息，简短描述")
    data: Optional[Any] = Field(default=None, description="附加数据，用于调试")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "code": -32601,
                    "message": "Method not found",
                    "data": None,
                }
            ]
        }
    }

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典.

        Returns:
            字典形式的错误对象，不含 None 值
        """
        result: Dict[str, Any] = {
            ERROR_CODE_FIELD: self.code,
            ERROR_MESSAGE_FIELD: self.message,
        }
        if self.data is not None:
            result[ERROR_DATA_FIELD] = self.data
        return result

    @classmethod
    def from_code(
        cls,
        code: int,
        message: Optional[str] = None,
        data: Optional[Any] = None,
    ) -> "JSONRPCError":
        """根据错误码创建错误对象.

        Args:
            code: 错误码
            message: 自定义错误消息，为 None 则使用标准消息
            data: 附加数据

        Returns:
            JSONRPCError 实例
        """
        if message is None:
            message = get_error_message(code)
        return cls(code=code, message=message, data=data)

    @classmethod
    def parse_error(cls, data: Optional[Any] = None) -> "JSONRPCError":
        """创建 Parse Error 错误对象（-32700）.

        Args:
            data: 附加数据

        Returns:
            JSONRPCError 实例
        """
        return cls.from_code(JsonRpcErrorCode.PARSE_ERROR, data=data)

    @classmethod
    def invalid_request(cls, data: Optional[Any] = None) -> "JSONRPCError":
        """创建 Invalid Request 错误对象（-32600）.

        Args:
            data: 附加数据

        Returns:
            JSONRPCError 实例
        """
        return cls.from_code(JsonRpcErrorCode.INVALID_REQUEST, data=data)

    @classmethod
    def method_not_found(cls, data: Optional[Any] = None) -> "JSONRPCError":
        """创建 Method Not Found 错误对象（-32601）.

        Args:
            data: 附加数据

        Returns:
            JSONRPCError 实例
        """
        return cls.from_code(JsonRpcErrorCode.METHOD_NOT_FOUND, data=data)

    @classmethod
    def invalid_params(cls, data: Optional[Any] = None) -> "JSONRPCError":
        """创建 Invalid Params 错误对象（-32602）.

        Args:
            data: 附加数据

        Returns:
            JSONRPCError 实例
        """
        return cls.from_code(JsonRpcErrorCode.INVALID_PARAMS, data=data)

    @classmethod
    def internal_error(cls, data: Optional[Any] = None) -> "JSONRPCError":
        """创建 Internal Error 错误对象（-32603）.

        Args:
            data: 附加数据

        Returns:
            JSONRPCError 实例
        """
        return cls.from_code(JsonRpcErrorCode.INTERNAL_ERROR, data=data)

    @classmethod
    def server_error(cls, code: int = -32000, data: Optional[Any] = None) -> "JSONRPCError":
        """创建 Server Error 错误对象（-32000 ~ -32099）.

        Args:
            code: 服务器错误码（必须在 -32099 ~ -32000 范围内）
            data: 附加数据

        Returns:
            JSONRPCError 实例
        """
        # 确保在保留范围内
        if not (-32099 <= code <= -32000):
            code = -32000
        return cls.from_code(code, data=data)


# ============================================================
# JSON-RPC 请求模型
# ============================================================

class JSONRPCRequest(BaseModel):
    """JSON-RPC 2.0 请求对象.

    表示一个 JSON-RPC 请求，包含方法名、参数和可选的请求 ID。
    如果没有 id，则表示这是一个通知（notification）。

    属性:
        jsonrpc: JSON-RPC 版本号，必须为 "2.0"
        method: 调用的方法名
        params: 方法参数，可以是数组（位置参数）或对象（命名参数）
        id: 请求标识符，通知时为 None
    """

    jsonrpc: str = Field(default=JSONRPC_VERSION, description="JSON-RPC 版本号")
    method: str = Field(..., min_length=1, description="调用的方法名")
    params: Optional[ParamsType] = Field(default=None, description="方法参数")
    id: Optional[RequestId] = Field(default=None, description="请求标识符")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "jsonrpc": "2.0",
                    "method": "tools/list",
                    "params": {},
                    "id": 1,
                }
            ]
        }
    }

    @field_validator("jsonrpc")
    @classmethod
    def validate_jsonrpc_version(cls, v: str) -> str:
        """验证 JSON-RPC 版本号.

        Args:
            v: 版本号

        Returns:
            验证后的版本号

        Raises:
            ValueError: 版本号不是 "2.0"
        """
        if v != JSONRPC_VERSION:
            raise ValueError(f"jsonrpc must be '{JSONRPC_VERSION}', got '{v}'")
        return v

    @field_validator("method")
    @classmethod
    def validate_method_name(cls, v: str) -> str:
        """验证方法名.

        方法名不能以 "rpc." 开头（保留给内部使用）。

        Args:
            v: 方法名

        Returns:
            验证后的方法名

        Raises:
            ValueError: 方法名以 "rpc." 开头
        """
        if v.startswith("rpc."):
            raise ValueError("method name cannot start with 'rpc.' (reserved)")
        return v

    @property
    def is_notification(self) -> bool:
        """是否为通知（无 id）.

        Returns:
            True 表示是通知消息
        """
        return self.id is None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典.

        Returns:
            字典形式的请求对象
        """
        result: Dict[str, Any] = {
            JSONRPC_FIELD: self.jsonrpc,
            METHOD_FIELD: self.method,
        }
        if self.params is not None:
            result[PARAMS_FIELD] = self.params
        if self.id is not None:
            result[ID_FIELD] = self.id
        return result


# ============================================================
# JSON-RPC 响应模型
# ============================================================

class JSONRPCResponse(BaseModel):
    """JSON-RPC 2.0 响应对象.

    表示一个 JSON-RPC 响应，成功时包含 result，失败时包含 error。

    属性:
        jsonrpc: JSON-RPC 版本号，必须为 "2.0"
        result: 调用结果（成功时）
        error: 错误对象（失败时）
        id: 请求标识符，与请求中的 id 对应
    """

    jsonrpc: str = Field(default=JSONRPC_VERSION, description="JSON-RPC 版本号")
    result: Optional[ResultType] = Field(default=None, description="调用结果")
    error: Optional[JSONRPCError] = Field(default=None, description="错误对象")
    id: Optional[RequestId] = Field(default=None, description="请求标识符")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "jsonrpc": "2.0",
                    "result": {"tools": []},
                    "id": 1,
                }
            ]
        }
    }

    @field_validator("jsonrpc")
    @classmethod
    def validate_jsonrpc_version(cls, v: str) -> str:
        """验证 JSON-RPC 版本号."""
        if v != JSONRPC_VERSION:
            raise ValueError(f"jsonrpc must be '{JSONRPC_VERSION}', got '{v}'")
        return v

    @property
    def is_success(self) -> bool:
        """是否为成功响应.

        Returns:
            True 表示调用成功
        """
        return self.error is None

    @property
    def is_error(self) -> bool:
        """是否为错误响应.

        Returns:
            True 表示调用失败
        """
        return self.error is not None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典.

        Returns:
            字典形式的响应对象
        """
        result: Dict[str, Any] = {
            JSONRPC_FIELD: self.jsonrpc,
            ID_FIELD: self.id,
        }
        if self.error is not None:
            result[ERROR_FIELD] = self.error.to_dict()
        else:
            result[RESULT_FIELD] = self.result
        return result


# ============================================================
# 请求解析函数
# ============================================================

def parse_request(raw: Union[str, bytes, Dict[str, Any]]) -> Union[JSONRPCRequest, List[JSONRPCRequest]]:
    """解析 JSON-RPC 请求.

    支持单条请求和批量请求。自动识别 JSON 字符串或字典输入。

    Args:
        raw: 原始请求数据，可以是 JSON 字符串、字节或字典

    Returns:
        单条 JSONRPCRequest 或列表（批量请求）

    Raises:
        ValueError: 解析失败或请求格式无效
    """
    # 解析 JSON
    if isinstance(raw, (str, bytes)):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"Parse error: {e}") from e
    else:
        data = raw

    # 批量请求
    if isinstance(data, list):
        if len(data) == 0:
            raise ValueError("Invalid Request: empty batch")
        return [_parse_single_request(item) for item in data]

    # 单条请求
    return _parse_single_request(data)


def _parse_single_request(data: Dict[str, Any]) -> JSONRPCRequest:
    """解析单条 JSON-RPC 请求.

    Args:
        data: 请求字典

    Returns:
        JSONRPCRequest 实例

    Raises:
        ValueError: 请求格式无效
    """
    if not isinstance(data, dict):
        raise ValueError("Invalid Request: not a JSON object")

    # 检查必填字段
    if JSONRPC_FIELD not in data:
        raise ValueError("Invalid Request: missing 'jsonrpc' field")

    if METHOD_FIELD not in data:
        raise ValueError("Invalid Request: missing 'method' field")

    # 验证 jsonrpc 版本
    if data[JSONRPC_FIELD] != JSONRPC_VERSION:
        raise ValueError(
            f"Invalid Request: jsonrpc must be '{JSONRPC_VERSION}', "
            f"got '{data[JSONRPC_FIELD]}'"
        )

    # 验证 method
    method = data[METHOD_FIELD]
    if not isinstance(method, str) or not method:
        raise ValueError("Invalid Request: 'method' must be a non-empty string")

    # 验证 id（可选）
    request_id = data.get(ID_FIELD)
    if request_id is not None and not is_valid_request_id(request_id):
        raise ValueError(
            "Invalid Request: 'id' must be a string, number, or null"
        )

    # 验证 params（可选）
    params = data.get(PARAMS_FIELD)
    if params is not None and not isinstance(params, (list, dict)):
        raise ValueError("Invalid Request: 'params' must be an array or object")

    return JSONRPCRequest(
        jsonrpc=data[JSONRPC_FIELD],
        method=method,
        params=params,
        id=request_id,
    )


def parse_response(raw: Union[str, bytes, Dict[str, Any]]) -> Union[JSONRPCResponse, List[JSONRPCResponse]]:
    """解析 JSON-RPC 响应.

    支持单条响应和批量响应。

    Args:
        raw: 原始响应数据

    Returns:
        单条 JSONRPCResponse 或列表（批量响应）

    Raises:
        ValueError: 解析失败或响应格式无效
    """
    if isinstance(raw, (str, bytes)):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"Parse error: {e}") from e
    else:
        data = raw

    if isinstance(data, list):
        if len(data) == 0:
            raise ValueError("Invalid Response: empty batch")
        return [_parse_single_response(item) for item in data]

    return _parse_single_response(data)


def _parse_single_response(data: Dict[str, Any]) -> JSONRPCResponse:
    """解析单条 JSON-RPC 响应.

    Args:
        data: 响应字典

    Returns:
        JSONRPCResponse 实例

    Raises:
        ValueError: 响应格式无效
    """
    if not isinstance(data, dict):
        raise ValueError("Invalid Response: not a JSON object")

    if JSONRPC_FIELD not in data:
        raise ValueError("Invalid Response: missing 'jsonrpc' field")

    if ID_FIELD not in data:
        raise ValueError("Invalid Response: missing 'id' field")

    # 检查 result 或 error（必须有一个，且只能有一个）
    has_result = RESULT_FIELD in data
    has_error = ERROR_FIELD in data

    if not has_result and not has_error:
        raise ValueError("Invalid Response: missing both 'result' and 'error'")

    if has_result and has_error:
        raise ValueError("Invalid Response: cannot have both 'result' and 'error'")

    error_obj = None
    if has_error:
        error_data = data[ERROR_FIELD]
        if not isinstance(error_data, dict):
            raise ValueError("Invalid Response: 'error' must be an object")
        if ERROR_CODE_FIELD not in error_data:
            raise ValueError("Invalid Response: error missing 'code'")
        if ERROR_MESSAGE_FIELD not in error_data:
            raise ValueError("Invalid Response: error missing 'message'")
        error_obj = JSONRPCError(
            code=error_data[ERROR_CODE_FIELD],
            message=error_data[ERROR_MESSAGE_FIELD],
            data=error_data.get(ERROR_DATA_FIELD),
        )

    return JSONRPCResponse(
        jsonrpc=data[JSONRPC_FIELD],
        result=data.get(RESULT_FIELD),
        error=error_obj,
        id=data.get(ID_FIELD),
    )


# ============================================================
# 响应构建函数
# ============================================================

def build_response(
    request_id: Optional[RequestId],
    result: ResultType,
) -> Dict[str, Any]:
    """构建成功响应.

    Args:
        request_id: 请求 ID（通知时为 None）
        result: 调用结果

    Returns:
        JSON-RPC 成功响应字典
    """
    return {
        JSONRPC_FIELD: JSONRPC_VERSION,
        RESULT_FIELD: result,
        ID_FIELD: request_id,
    }


def build_error(
    request_id: Optional[RequestId],
    code: int,
    message: Optional[str] = None,
    data: Optional[Any] = None,
) -> Dict[str, Any]:
    """构建错误响应.

    Args:
        request_id: 请求 ID
        code: 错误码
        message: 错误消息，为 None 则使用标准消息
        data: 附加数据

    Returns:
        JSON-RPC 错误响应字典
    """
    error = JSONRPCError.from_code(code=code, message=message, data=data)
    return {
        JSONRPC_FIELD: JSONRPC_VERSION,
        ERROR_FIELD: error.to_dict(),
        ID_FIELD: request_id,
    }


def build_error_from_exception(
    request_id: Optional[RequestId],
    exc: Exception,
    code: Optional[int] = None,
) -> Dict[str, Any]:
    """从异常构建错误响应.

    Args:
        request_id: 请求 ID
        exc: 异常对象
        code: 自定义错误码，默认使用 Internal Error

    Returns:
        JSON-RPC 错误响应字典
    """
    if code is None:
        code = JsonRpcErrorCode.INTERNAL_ERROR
    return build_error(
        request_id=request_id,
        code=code,
        message=str(exc),
    )


# ============================================================
# 批量响应构建
# ============================================================

def build_batch_response(
    responses: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """构建批量响应.

    过滤掉通知的响应（不需要返回），返回批量响应列表。

    Args:
        responses: 所有响应字典的列表

    Returns:
        批量响应列表（已过滤通知）
    """
    # 过滤掉通知响应（id 为 None 的响应，通常不需要返回）
    return [r for r in responses if r.get(ID_FIELD) is not None]


# ============================================================
# 便捷工具：将原始 JSON 字符串直接转为响应（错误时）
# ============================================================

def handle_parse_error(raw: Union[str, bytes]) -> Dict[str, Any]:
    """处理 JSON 解析错误，返回标准 Parse Error 响应.

    Args:
        raw: 原始 JSON 数据

    Returns:
        Parse Error 响应字典（id 为 null）
    """
    return build_error(
        request_id=None,
        code=JsonRpcErrorCode.PARSE_ERROR,
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
    "JsonRpcMessage",
]
