"""
M5 潮汐记忆系统 - 全局异常与错误码定义

统一错误码范围：50000-59999（与 M8 标准一致）
所有模块的自定义异常均继承自 TideMemoryError
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import IntEnum
from typing import Any, Dict, Optional


class ErrorCode(IntEnum):
    """
    M5 潮汐记忆系统错误码枚举

    分段规则：
    - 50000-50099：通用错误
    - 50100-50199：记忆相关错误
    - 50200-50299：权限相关错误
    - 50300-50399：存储相关错误
    - 50400-50499：检索相关错误
    - 50500-50599：巩固相关错误
    - 50600-50699：验证相关错误
    """

    # ========== 通用错误 (50000-50099) ==========
    SUCCESS = 0
    UNKNOWN_ERROR = 50000
    INVALID_PARAMS = 50001
    UNAUTHORIZED = 50002
    FORBIDDEN = 50003
    NOT_FOUND = 50004
    RATE_LIMITED = 50005
    INTERNAL_ERROR = 50006
    SERVICE_UNAVAILABLE = 50007

    # ========== 记忆相关错误 (50100-50199) ==========
    MEMORY_NOT_FOUND = 50101
    MEMORY_TOO_LARGE = 50102
    MEMORY_ENCRYPTION_FAILED = 50103
    MEMORY_DECRYPTION_FAILED = 50104
    MEMORY_ALREADY_EXISTS = 50105
    MEMORY_INVALID = 50106
    MEMORY_DELETE_FAILED = 50107

    # ========== 权限相关错误 (50200-50299) ==========
    PERMISSION_DENIED = 50201
    DOMAIN_NOT_ACCESSIBLE = 50202
    CLASSIFICATION_TOO_HIGH = 50203
    DOMAIN_PERMISSION_DENIED = 50204
    INVALID_AGENT_ID = 50205

    # ========== 存储相关错误 (50300-50399) ==========
    STORAGE_FULL = 50301
    STORAGE_ERROR = 50302
    SYNC_FAILED = 50303
    DATABASE_ERROR = 50304

    # ========== 检索相关错误 (50400-50499) ==========
    SEARCH_TIMEOUT = 50401
    VECTOR_INDEX_ERROR = 50402
    VECTOR_SEARCH_FAILED = 50403
    EMBEDDING_ERROR = 50404

    # ========== 巩固相关错误 (50500-50599) ==========
    CONSOLIDATION_RUNNING = 50501
    CONSOLIDATION_FAILED = 50502
    CONSOLIDATION_ABORTED = 50503

    # ========== 验证相关错误 (50600-50699) ==========
    VALIDATION_ERROR = 50601
    SCHEMA_MISMATCH = 50602


# 错误码默认消息映射
_ERROR_MESSAGES: Dict[ErrorCode, str] = {
    # 通用
    ErrorCode.SUCCESS: "success",
    ErrorCode.UNKNOWN_ERROR: "未知错误",
    ErrorCode.INVALID_PARAMS: "参数无效",
    ErrorCode.UNAUTHORIZED: "未授权访问",
    ErrorCode.FORBIDDEN: "禁止访问",
    ErrorCode.NOT_FOUND: "资源不存在",
    ErrorCode.RATE_LIMITED: "请求过于频繁",
    ErrorCode.INTERNAL_ERROR: "服务器内部错误",
    ErrorCode.SERVICE_UNAVAILABLE: "服务暂不可用",

    # 记忆
    ErrorCode.MEMORY_NOT_FOUND: "记忆不存在",
    ErrorCode.MEMORY_TOO_LARGE: "记忆内容过大",
    ErrorCode.MEMORY_ENCRYPTION_FAILED: "记忆加密失败",
    ErrorCode.MEMORY_DECRYPTION_FAILED: "记忆解密失败",
    ErrorCode.MEMORY_ALREADY_EXISTS: "记忆已存在",
    ErrorCode.MEMORY_INVALID: "记忆数据无效",
    ErrorCode.MEMORY_DELETE_FAILED: "记忆删除失败",

    # 权限
    ErrorCode.PERMISSION_DENIED: "权限不足",
    ErrorCode.DOMAIN_NOT_ACCESSIBLE: "域不可访问",
    ErrorCode.CLASSIFICATION_TOO_HIGH: "密级不足",
    ErrorCode.DOMAIN_PERMISSION_DENIED: "域权限不足",
    ErrorCode.INVALID_AGENT_ID: "无效的 Agent ID",

    # 存储
    ErrorCode.STORAGE_FULL: "存储空间已满",
    ErrorCode.STORAGE_ERROR: "存储错误",
    ErrorCode.SYNC_FAILED: "同步失败",
    ErrorCode.DATABASE_ERROR: "数据库错误",

    # 检索
    ErrorCode.SEARCH_TIMEOUT: "搜索超时",
    ErrorCode.VECTOR_INDEX_ERROR: "向量索引错误",
    ErrorCode.VECTOR_SEARCH_FAILED: "向量搜索失败",
    ErrorCode.EMBEDDING_ERROR: "嵌入计算错误",

    # 巩固
    ErrorCode.CONSOLIDATION_RUNNING: "巩固任务正在运行",
    ErrorCode.CONSOLIDATION_FAILED: "记忆巩固失败",
    ErrorCode.CONSOLIDATION_ABORTED: "巩固任务已中止",

    # 验证
    ErrorCode.VALIDATION_ERROR: "参数验证失败",
    ErrorCode.SCHEMA_MISMATCH: "数据模式不匹配",
}


class TideMemoryError(Exception):
    """
    M5 潮汐记忆系统自定义异常基类

    所有业务异常均应继承此类，由全局异常处理器统一捕获并返回标准格式响应。

    Attributes:
        code: 错误码（ErrorCode 枚举值）
        message: 错误消息
        data: 附加数据
    """

    def __init__(
        self,
        code: ErrorCode = ErrorCode.UNKNOWN_ERROR,
        message: Optional[str] = None,
        data: Any = None,
    ):
        self.code = code
        self.message = message or _ERROR_MESSAGES.get(code, "未知错误")
        self.data = data
        super().__init__(self.message)

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} code={self.code.value} message={self.message!r}>"

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "code": self.code.value,
            "message": self.message,
            "data": self.data,
        }


class MemoryNotFoundError(TideMemoryError):
    """记忆不存在异常"""

    def __init__(self, memory_id: str = "", message: Optional[str] = None, data: Any = None) -> None:
        super().__init__(
            code=ErrorCode.MEMORY_NOT_FOUND,
            message=message or f"记忆不存在: {memory_id}",
            data=data or {"memory_id": memory_id},
        )


class DomainPermissionError(TideMemoryError):
    """域权限异常"""

    def __init__(
        self,
        domain: str = "",
        agent_id: str = "",
        action: str = "",
        message: Optional[str] = None,
        data: Any = None,
    ) -> None:
        default_msg = "域权限不足"
        if domain and agent_id:
            default_msg = f"Agent {agent_id} 无权限访问域 {domain}"
            if action:
                default_msg += f"（操作: {action}）"

        super().__init__(
            code=ErrorCode.DOMAIN_PERMISSION_DENIED,
            message=message or default_msg,
            data=data or {
                "domain": domain,
                "agent_id": agent_id,
                "action": action,
            },
        )


class InvalidMemoryError(TideMemoryError):
    """无效记忆数据异常"""

    def __init__(self, message: Optional[str] = None, data: Any = None) -> None:
        super().__init__(
            code=ErrorCode.MEMORY_INVALID,
            message=message or _ERROR_MESSAGES[ErrorCode.MEMORY_INVALID],
            data=data,
        )


class ConsolidationError(TideMemoryError):
    """记忆巩固异常"""

    def __init__(self, message: Optional[str] = None, data: Any = None) -> None:
        super().__init__(
            code=ErrorCode.CONSOLIDATION_FAILED,
            message=message or _ERROR_MESSAGES[ErrorCode.CONSOLIDATION_FAILED],
            data=data,
        )


class VectorSearchError(TideMemoryError):
    """向量搜索异常"""

    def __init__(self, message: Optional[str] = None, data: Any = None) -> None:
        super().__init__(
            code=ErrorCode.VECTOR_SEARCH_FAILED,
            message=message or _ERROR_MESSAGES[ErrorCode.VECTOR_SEARCH_FAILED],
            data=data,
        )


def error_response(
    code: ErrorCode,
    message: Optional[str] = None,
    data: Any = None,
    request_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    生成统一格式的错误响应

    Args:
        code: 错误码（ErrorCode 枚举）
        message: 自定义错误消息，为 None 时使用默认消息
        data: 附加数据
        request_id: 请求ID，为 None 时自动生成

    Returns:
        标准错误响应字典: {code, message, data, request_id, timestamp}
    """
    return {
        "code": code.value,
        "message": message or _ERROR_MESSAGES.get(code, "未知错误"),
        "data": data,
        "request_id": request_id or f"m5-{uuid.uuid4().hex[:12]}",
        "timestamp": datetime.now().isoformat(),
    }


def success_response(
    data: Any = None,
    message: str = "success",
    request_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    生成统一格式的成功响应

    Args:
        data: 响应数据
        message: 响应消息
        request_id: 请求ID，为 None 时自动生成

    Returns:
        标准成功响应字典: {code, message, data, request_id, timestamp}
    """
    return {
        "code": ErrorCode.SUCCESS.value,
        "message": message,
        "data": data,
        "request_id": request_id or f"m5-{uuid.uuid4().hex[:12]}",
        "timestamp": datetime.now().isoformat(),
    }


def get_error_message(code: ErrorCode) -> str:
    """获取错误码对应的默认消息"""
    return _ERROR_MESSAGES.get(code, "未知错误")


__all__ = [
    "ErrorCode",
    "TideMemoryError",
    "MemoryNotFoundError",
    "DomainPermissionError",
    "InvalidMemoryError",
    "ConsolidationError",
    "VectorSearchError",
    "error_response",
    "success_response",
    "get_error_message",
]
# vim: set et ts=4 sw=4:
