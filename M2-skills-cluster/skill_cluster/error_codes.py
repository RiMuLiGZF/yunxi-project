"""M2 错误码定义（已迁移至统一 6 位错误码体系）.

.. deprecated::
    此模块保留向后兼容，新代码请使用 ``skill_cluster.unified_errors``。

错误码已从旧版 5 位体系（2xxxx）迁移至统一 6 位体系（02YYZZ）。
所有旧错误码常量仍然可用，但底层值已映射为新的 6 位编码。
"""

from __future__ import annotations

import warnings
from typing import Any

from .unified_errors import (
    M2ErrorCode,
    M2_LEGACY_ERROR_MAP,
    m2_normalize_error_code,
    _UNIFIED_ERRORS_AVAILABLE,
)


# ============================================================
# 兼容层：旧版 ErrorCode 类
# ============================================================
# 保持旧的常量名，但其值已映射为新的 6 位错误码
# 旧版常量名（ErrorCode.SKILL_NOT_FOUND 等）仍然可用

class _LegacyErrorCodeMeta(type):
    """元类：让旧版 ErrorCode 常量的值自动映射为新编码."""

    def __getattr__(cls, name: str) -> int:
        # 优先从 M2ErrorCode 获取（如果名称匹配）
        if hasattr(M2ErrorCode, name):
            return getattr(M2ErrorCode, name)
        # 否则尝试在旧错误码表中查找并映射
        raise AttributeError(f"{cls.__name__} has no attribute {name!r}")


class ErrorCode(metaclass=_LegacyErrorCodeMeta):
    """错误码常量（已迁移至统一 6 位体系）.

    .. deprecated::
        请使用 ``M2ErrorCode`` 替代。

    所有旧常量名仍然可用，其值已自动映射为新的 6 位错误码。
    """

    # === 通用错误 20000-20999 ===
    SUCCESS = 0
    UNKNOWN_ERROR = M2ErrorCode.UNKNOWN_ERROR
    INVALID_PARAMS = M2ErrorCode.INVALID_PARAMS
    UNAUTHORIZED = M2ErrorCode.UNAUTHORIZED
    FORBIDDEN = M2ErrorCode.FORBIDDEN
    NOT_FOUND = M2ErrorCode.NOT_FOUND
    RATE_LIMITED = M2ErrorCode.RATE_LIMITED
    SERVICE_UNAVAILABLE = M2ErrorCode.SERVICE_UNAVAILABLE
    TIMEOUT = M2ErrorCode.EXECUTION_TIMEOUT  # 旧 TIMEOUT -> 执行超时
    INTERNAL_ERROR = M2ErrorCode.INTERNAL_ERROR
    CONFIG_ERROR = M2ErrorCode.CONFIG_ERROR

    # === 技能相关错误 21000-21999 ===
    SKILL_NOT_FOUND = M2ErrorCode.SKILL_NOT_FOUND
    SKILL_DISABLED = M2ErrorCode.SKILL_DISABLED
    SKILL_LOAD_FAILED = M2ErrorCode.SKILL_LOAD_FAILED
    SKILL_VERSION_MISMATCH = M2ErrorCode.SKILL_VERSION_MISMATCH
    SKILL_DEPENDENCY_MISSING = M2ErrorCode.SKILL_DEPENDENCY_MISSING
    SKILL_ALREADY_EXISTS = M2ErrorCode.SKILL_ALREADY_EXISTS
    SKILL_INVALID_MANIFEST = M2ErrorCode.INVALID_SKILL_MANIFEST
    SKILL_ACTION_NOT_FOUND = M2ErrorCode.SKILL_ACTION_NOT_FOUND
    SKILL_CATEGORY_NOT_FOUND = M2ErrorCode.SKILL_CATEGORY_NOT_FOUND

    # === 执行相关错误 22000-22999 ===
    EXECUTION_FAILED = M2ErrorCode.EXECUTION_FAILED
    EXECUTION_TIMEOUT = M2ErrorCode.EXECUTION_TIMEOUT
    EXECUTION_CANCELLED = M2ErrorCode.EXECUTION_CANCELLED
    EXECUTION_RETRY_EXHAUSTED = M2ErrorCode.EXECUTION_RETRY_EXHAUSTED
    EXECUTION_PARAMS_INVALID = M2ErrorCode.INVALID_EXECUTION_PARAMS
    EXECUTION_RESULT_INVALID = M2ErrorCode.EXECUTION_RESULT_INVALID

    # === 权限相关错误 23000-23999 ===
    PERMISSION_DENIED = M2ErrorCode.PERMISSION_DENIED
    PERMISSION_LEVEL_INSUFFICIENT = M2ErrorCode.PERMISSION_LEVEL_INSUFFICIENT
    PERMISSION_SCOPE_INVALID = M2ErrorCode.INVALID_PERMISSION_SCOPE
    PERMISSION_TOKEN_INVALID = M2ErrorCode.PERMISSION_TOKEN_INVALID
    PERMISSION_ROLE_NOT_FOUND = M2ErrorCode.PERMISSION_ROLE_NOT_FOUND

    # === MCP 相关错误 24000-24999 ===
    MCP_SERVER_NOT_FOUND = M2ErrorCode.MCP_SERVER_NOT_FOUND
    MCP_SERVER_UNAVAILABLE = M2ErrorCode.MCP_SERVER_UNAVAILABLE
    MCP_TOOL_NOT_FOUND = M2ErrorCode.MCP_TOOL_NOT_FOUND
    MCP_CALL_FAILED = M2ErrorCode.MCP_CALL_FAILED
    MCP_PROTOCOL_ERROR = M2ErrorCode.MCP_PROTOCOL_ERROR
    MCP_CONNECTION_FAILED = M2ErrorCode.MCP_CONNECTION_FAILED

    # === 代码执行相关错误 25000-25999 ===
    CODE_EXEC_FAILED = M2ErrorCode.CODE_EXEC_FAILED
    CODE_SYNTAX_ERROR = M2ErrorCode.INVALID_CODE_SYNTAX
    CODE_TIMEOUT = M2ErrorCode.CODE_TIMEOUT
    CODE_MEMORY_LIMIT = M2ErrorCode.CODE_MEMORY_LIMIT
    CODE_SECURITY_BLOCKED = M2ErrorCode.CODE_SECURITY_BLOCKED
    CODE_DEPENDENCY_MISSING = M2ErrorCode.CODE_DEPENDENCY_MISSING
    CODE_LANGUAGE_UNSUPPORTED = M2ErrorCode.INVALID_LANGUAGE
    CODE_REPL_NOT_FOUND = M2ErrorCode.CODE_REPL_NOT_FOUND
    CODE_REPL_LIMIT_EXCEEDED = M2ErrorCode.CODE_REPL_LIMIT_EXCEEDED
    CODE_INSTALL_FAILED = M2ErrorCode.CODE_INSTALL_FAILED

    # === 推荐相关错误 26000-26999 ===
    RECOMMEND_NO_RESULT = M2ErrorCode.RECOMMEND_NO_RESULT
    RECOMMEND_QUERY_EMPTY = M2ErrorCode.RECOMMEND_QUERY_EMPTY
    RECOMMEND_SCENE_INVALID = M2ErrorCode.INVALID_RECOMMEND_SCENE
    RECOMMEND_CACHE_ERROR = M2ErrorCode.RECOMMEND_CACHE_ERROR


# 错误码对应的默认消息（保持与旧版兼容，使用新错误码作为 key）
ERROR_MESSAGES: dict[int, str] = {
    # 通用错误
    0: "成功",
    M2ErrorCode.UNKNOWN_ERROR: "未知错误",
    M2ErrorCode.INVALID_PARAMS: "参数无效",
    M2ErrorCode.UNAUTHORIZED: "未授权",
    M2ErrorCode.FORBIDDEN: "禁止访问",
    M2ErrorCode.NOT_FOUND: "资源不存在",
    M2ErrorCode.RATE_LIMITED: "请求过于频繁",
    M2ErrorCode.SERVICE_UNAVAILABLE: "服务不可用",
    M2ErrorCode.EXECUTION_TIMEOUT: "请求超时",
    M2ErrorCode.INTERNAL_ERROR: "内部错误",
    M2ErrorCode.CONFIG_ERROR: "配置错误",

    # 技能相关错误
    M2ErrorCode.SKILL_NOT_FOUND: "技能不存在",
    M2ErrorCode.SKILL_DISABLED: "技能已禁用",
    M2ErrorCode.SKILL_LOAD_FAILED: "技能加载失败",
    M2ErrorCode.SKILL_VERSION_MISMATCH: "技能版本不匹配",
    M2ErrorCode.SKILL_DEPENDENCY_MISSING: "技能依赖缺失",
    M2ErrorCode.SKILL_ALREADY_EXISTS: "技能已存在",
    M2ErrorCode.INVALID_SKILL_MANIFEST: "技能清单无效",
    M2ErrorCode.SKILL_ACTION_NOT_FOUND: "技能动作不存在",
    M2ErrorCode.SKILL_CATEGORY_NOT_FOUND: "技能分类不存在",

    # 执行相关错误
    M2ErrorCode.EXECUTION_FAILED: "执行失败",
    M2ErrorCode.EXECUTION_TIMEOUT: "执行超时",
    M2ErrorCode.EXECUTION_CANCELLED: "执行已取消",
    M2ErrorCode.EXECUTION_RETRY_EXHAUSTED: "重试次数耗尽",
    M2ErrorCode.INVALID_EXECUTION_PARAMS: "执行参数无效",
    M2ErrorCode.EXECUTION_RESULT_INVALID: "执行结果无效",

    # 权限相关错误
    M2ErrorCode.PERMISSION_DENIED: "权限不足",
    M2ErrorCode.PERMISSION_LEVEL_INSUFFICIENT: "权限等级不足",
    M2ErrorCode.INVALID_PERMISSION_SCOPE: "权限作用域无效",
    M2ErrorCode.PERMISSION_TOKEN_INVALID: "权限令牌无效",
    M2ErrorCode.PERMISSION_ROLE_NOT_FOUND: "角色不存在",

    # MCP 相关错误
    M2ErrorCode.MCP_SERVER_NOT_FOUND: "MCP服务不存在",
    M2ErrorCode.MCP_SERVER_UNAVAILABLE: "MCP服务不可用",
    M2ErrorCode.MCP_TOOL_NOT_FOUND: "MCP工具不存在",
    M2ErrorCode.MCP_CALL_FAILED: "MCP调用失败",
    M2ErrorCode.MCP_PROTOCOL_ERROR: "MCP协议错误",
    M2ErrorCode.MCP_CONNECTION_FAILED: "MCP连接失败",

    # 代码执行相关错误
    M2ErrorCode.CODE_EXEC_FAILED: "代码执行失败",
    M2ErrorCode.INVALID_CODE_SYNTAX: "代码语法错误",
    M2ErrorCode.CODE_TIMEOUT: "代码执行超时",
    M2ErrorCode.CODE_MEMORY_LIMIT: "内存不足",
    M2ErrorCode.CODE_SECURITY_BLOCKED: "安全拦截",
    M2ErrorCode.CODE_DEPENDENCY_MISSING: "依赖缺失",
    M2ErrorCode.INVALID_LANGUAGE: "不支持的语言",
    M2ErrorCode.CODE_REPL_NOT_FOUND: "REPL会话不存在",
    M2ErrorCode.CODE_REPL_LIMIT_EXCEEDED: "REPL会话数超限",
    M2ErrorCode.CODE_INSTALL_FAILED: "包安装失败",

    # 推荐相关错误
    M2ErrorCode.RECOMMEND_NO_RESULT: "无推荐结果",
    M2ErrorCode.RECOMMEND_QUERY_EMPTY: "查询为空",
    M2ErrorCode.INVALID_RECOMMEND_SCENE: "场景无效",
    M2ErrorCode.RECOMMEND_CACHE_ERROR: "推荐缓存错误",
}


def get_error_message(code: int) -> str:
    """获取错误码对应的默认消息.

    自动规范化旧版 5 位错误码为新版 6 位编码。
    """
    normalized = m2_normalize_error_code(code)
    return ERROR_MESSAGES.get(normalized, "未知错误")


def make_error_response(
    code: int,
    message: str | None = None,
    data: Any = None,
    trace_id: str = "",
) -> dict[str, Any]:
    """构造标准错误响应（已迁移至统一错误码体系）.

    旧版 5 位错误码会自动映射为新版 6 位编码。
    """
    normalized_code = m2_normalize_error_code(code)
    return {
        "code": normalized_code,
        "message": message or get_error_message(normalized_code),
        "data": data,
        "trace_id": trace_id,
        "success": normalized_code == 0,
    }


def make_success_response(
    data: Any = None,
    message: str = "成功",
    trace_id: str = "",
) -> dict[str, Any]:
    """构造标准成功响应."""
    return {
        "code": 0,
        "message": message,
        "data": data,
        "trace_id": trace_id,
        "success": True,
    }


# 发出废弃警告（模块级别）
warnings.warn(
    "skill_cluster.error_codes 已废弃，请使用 skill_cluster.unified_errors.M2ErrorCode。"
    "旧错误码常量仍然可用但已映射为新的 6 位编码。",
    DeprecationWarning,
    stacklevel=2,
)


__all__ = [
    "ErrorCode",
    "ERROR_MESSAGES",
    "get_error_message",
    "make_error_response",
    "make_success_response",
    "M2ErrorCode",
    "M2_LEGACY_ERROR_MAP",
    "_UNIFIED_ERRORS_AVAILABLE",
]
