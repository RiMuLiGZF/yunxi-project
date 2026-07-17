"""
M11 MCP 总线 - 模块级错误码定义
==================================

遵循云汐系统统一 6 位错误码规范：XX YY ZZ
  - XX = 11（M11 MCP 总线）
  - YY = 错误类别
  - ZZ = 具体错误序号

模块范围：110100 - 110999

M11 原有负数错误码（JSON-RPC 风格 -32000 系列）通过
parse_error_code 的负数兼容自动转换。
"""

from shared.core.errors import (
    ModuleCode,
    ErrorCategory,
    build_error_code,
    ModuleErrorCode,
)


class M11ErrorCode(ModuleErrorCode):
    """M11 MCP 总线错误码常量.

    模块编号: 11
    范围: 110100 - 110999
    """
    MODULE = ModuleCode.M11

    # ---------- 参数错误 (1101xx) ----------
    INVALID_SERVER_ID = build_error_code(ModuleCode.M11, ErrorCategory.VALIDATION, 1)
    """无效的服务 ID"""
    INVALID_TOOL_NAME = build_error_code(ModuleCode.M11, ErrorCategory.VALIDATION, 2)
    """无效的工具名称"""
    INVALID_API_KEY_NAME = build_error_code(ModuleCode.M11, ErrorCategory.VALIDATION, 3)
    """无效的 API Key 名称"""
    INVALID_TRANSPORT_TYPE = build_error_code(ModuleCode.M11, ErrorCategory.VALIDATION, 4)
    """无效的传输类型"""
    MCP_PARSE_ERROR = build_error_code(ModuleCode.M11, ErrorCategory.VALIDATION, 5)
    """MCP 消息解析错误"""
    MCP_INVALID_REQUEST = build_error_code(ModuleCode.M11, ErrorCategory.VALIDATION, 6)
    """MCP 请求无效"""
    MCP_INVALID_PARAMS = build_error_code(ModuleCode.M11, ErrorCategory.VALIDATION, 7)
    """MCP 参数无效"""

    # ---------- 认证错误 (1102xx) ----------
    API_KEY_MISSING = build_error_code(ModuleCode.M11, ErrorCategory.AUTHENTICATION, 1)
    """缺少 API Key"""
    API_KEY_INVALID = build_error_code(ModuleCode.M11, ErrorCategory.AUTHENTICATION, 2)
    """API Key 无效"""
    API_KEY_EXPIRED = build_error_code(ModuleCode.M11, ErrorCategory.AUTHENTICATION, 3)
    """API Key 已过期"""
    MCP_AUTH_FAILED = build_error_code(ModuleCode.M11, ErrorCategory.AUTHENTICATION, 4)
    """MCP 认证失败"""

    # ---------- 权限错误 (1103xx) ----------
    ADMIN_REQUIRED = build_error_code(ModuleCode.M11, ErrorCategory.AUTHORIZATION, 1)
    """需要管理员权限"""
    TOOL_ACCESS_DENIED = build_error_code(ModuleCode.M11, ErrorCategory.AUTHORIZATION, 2)
    """工具访问被拒绝"""
    SERVER_ACCESS_DENIED = build_error_code(ModuleCode.M11, ErrorCategory.AUTHORIZATION, 3)
    """服务访问被拒绝"""

    # ---------- 资源不存在 (1104xx) ----------
    SERVER_NOT_FOUND = build_error_code(ModuleCode.M11, ErrorCategory.NOT_FOUND, 1)
    """MCP 服务不存在"""
    TOOL_NOT_FOUND = build_error_code(ModuleCode.M11, ErrorCategory.NOT_FOUND, 2)
    """MCP 工具不存在"""
    API_KEY_NOT_FOUND = build_error_code(ModuleCode.M11, ErrorCategory.NOT_FOUND, 3)
    """API Key 不存在"""
    SESSION_NOT_FOUND = build_error_code(ModuleCode.M11, ErrorCategory.NOT_FOUND, 4)
    """会话不存在"""

    # ---------- 业务错误 (1105xx) ----------
    SERVER_ALREADY_EXISTS = build_error_code(ModuleCode.M11, ErrorCategory.BUSINESS, 1)
    """服务已存在"""
    SERVER_OFFLINE = build_error_code(ModuleCode.M11, ErrorCategory.BUSINESS, 2)
    """服务离线"""
    TOOL_DISABLED = build_error_code(ModuleCode.M11, ErrorCategory.BUSINESS, 3)
    """工具已禁用"""
    SESSION_EXPIRED = build_error_code(ModuleCode.M11, ErrorCategory.BUSINESS, 4)
    """会话已过期"""
    STDIO_START_FAILED = build_error_code(ModuleCode.M11, ErrorCategory.BUSINESS, 5)
    """STDIO 进程启动失败"""
    STDIO_STOP_FAILED = build_error_code(ModuleCode.M11, ErrorCategory.BUSINESS, 6)
    """STDIO 进程停止失败"""

    # ---------- 系统错误 (1106xx) ----------
    REGISTRY_ERROR = build_error_code(ModuleCode.M11, ErrorCategory.SYSTEM, 1)
    """注册中心错误"""
    ROUTER_ERROR = build_error_code(ModuleCode.M11, ErrorCategory.SYSTEM, 2)
    """路由错误"""
    CACHE_ERROR = build_error_code(ModuleCode.M11, ErrorCategory.SYSTEM, 3)
    """缓存错误"""

    # ---------- 第三方/上游错误 (1107xx) ----------
    UPSTREAM_TIMEOUT = build_error_code(ModuleCode.M11, ErrorCategory.THIRD_PARTY, 1)
    """上游服务超时"""
    UPSTREAM_ERROR = build_error_code(ModuleCode.M11, ErrorCategory.THIRD_PARTY, 2)
    """上游服务错误"""
    MCP_METHOD_NOT_FOUND = build_error_code(ModuleCode.M11, ErrorCategory.THIRD_PARTY, 3)
    """MCP 方法不存在（上游返回）"""
    MCP_INTERNAL_ERROR = build_error_code(ModuleCode.M11, ErrorCategory.THIRD_PARTY, 4)
    """MCP 内部错误（上游返回）"""
    ADAPTER_ERROR = build_error_code(ModuleCode.M11, ErrorCategory.THIRD_PARTY, 5)
    """适配器错误"""

    # ---------- 限流错误 (1108xx) ----------
    RATE_LIMITED = build_error_code(ModuleCode.M11, ErrorCategory.RATE_LIMIT, 1)
    """请求频率超限"""
    TOOL_RATE_LIMITED = build_error_code(ModuleCode.M11, ErrorCategory.RATE_LIMIT, 2)
    """工具调用频率超限"""
    QUOTA_EXCEEDED = build_error_code(ModuleCode.M11, ErrorCategory.RATE_LIMIT, 3)
    """配额已用完"""

    # ---------- 数据错误 (1109xx) ----------
    DATABASE_ERROR = build_error_code(ModuleCode.M11, ErrorCategory.DATA, 1)
    """数据库错误"""
    DATA_CONFLICT = build_error_code(ModuleCode.M11, ErrorCategory.DATA, 2)
    """数据冲突"""


# JSON-RPC 风格负数错误码 -> 统一 6 位错误码 映射
# 用于 M11 原有 MCP 协议错误码的兼容
JSONRPC_ERROR_MAP = {
    -32700: M11ErrorCode.MCP_PARSE_ERROR,      # Parse error
    -32600: M11ErrorCode.MCP_INVALID_REQUEST,  # Invalid Request
    -32601: M11ErrorCode.MCP_METHOD_NOT_FOUND, # Method not found
    -32602: M11ErrorCode.MCP_INVALID_PARAMS,   # Invalid params
    -32603: M11ErrorCode.MCP_INTERNAL_ERROR,   # Internal error
    -32000: M11ErrorCode.REGISTRY_ERROR,         # Server error (默认)
}


# 便捷别名
M11_ERR = M11ErrorCode
