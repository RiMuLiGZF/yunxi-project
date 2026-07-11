"""M2 错误码定义.

错误码段：20000 - 29999（M2 模块专属）

错误码分段：
- 20000 - 20999: 通用错误
- 21000 - 21999: 技能相关错误
- 22000 - 22999: 执行相关错误
- 23000 - 23999: 权限相关错误
- 24000 - 24999: MCP 相关错误
- 25000 - 25999: 代码执行相关错误
- 26000 - 26999: 推荐相关错误
"""

from __future__ import annotations

from typing import Any


class ErrorCode:
    """错误码常量."""

    # === 通用错误 20000-20999 ===
    SUCCESS = 20000
    UNKNOWN_ERROR = 20001
    INVALID_PARAMS = 20002
    UNAUTHORIZED = 20003
    FORBIDDEN = 20004
    NOT_FOUND = 20005
    RATE_LIMITED = 20006
    SERVICE_UNAVAILABLE = 20007
    TIMEOUT = 20008
    INTERNAL_ERROR = 20009
    CONFIG_ERROR = 20010

    # === 技能相关错误 21000-21999 ===
    SKILL_NOT_FOUND = 21001
    SKILL_DISABLED = 21002
    SKILL_LOAD_FAILED = 21003
    SKILL_VERSION_MISMATCH = 21004
    SKILL_DEPENDENCY_MISSING = 21005
    SKILL_ALREADY_EXISTS = 21006
    SKILL_INVALID_MANIFEST = 21007
    SKILL_ACTION_NOT_FOUND = 21008
    SKILL_CATEGORY_NOT_FOUND = 21009

    # === 执行相关错误 22000-22999 ===
    EXECUTION_FAILED = 22001
    EXECUTION_TIMEOUT = 22002
    EXECUTION_CANCELLED = 22003
    EXECUTION_RETRY_EXHAUSTED = 22004
    EXECUTION_PARAMS_INVALID = 22005
    EXECUTION_RESULT_INVALID = 22006

    # === 权限相关错误 23000-23999 ===
    PERMISSION_DENIED = 23001
    PERMISSION_LEVEL_INSUFFICIENT = 23002
    PERMISSION_SCOPE_INVALID = 23003
    PERMISSION_TOKEN_INVALID = 23004
    PERMISSION_ROLE_NOT_FOUND = 23005

    # === MCP 相关错误 24000-24999 ===
    MCP_SERVER_NOT_FOUND = 24001
    MCP_SERVER_UNAVAILABLE = 24002
    MCP_TOOL_NOT_FOUND = 24003
    MCP_CALL_FAILED = 24004
    MCP_PROTOCOL_ERROR = 24005
    MCP_CONNECTION_FAILED = 24006

    # === 代码执行相关错误 25000-25999 ===
    CODE_EXEC_FAILED = 25001
    CODE_SYNTAX_ERROR = 25002
    CODE_TIMEOUT = 25003
    CODE_MEMORY_LIMIT = 25004
    CODE_SECURITY_BLOCKED = 25005
    CODE_DEPENDENCY_MISSING = 25006
    CODE_LANGUAGE_UNSUPPORTED = 25007
    CODE_REPL_NOT_FOUND = 25008
    CODE_REPL_LIMIT_EXCEEDED = 25009
    CODE_INSTALL_FAILED = 25010

    # === 推荐相关错误 26000-26999 ===
    RECOMMEND_NO_RESULT = 26001
    RECOMMEND_QUERY_EMPTY = 26002
    RECOMMEND_SCENE_INVALID = 26003
    RECOMMEND_CACHE_ERROR = 26004


# 错误码对应的默认消息
ERROR_MESSAGES: dict[int, str] = {
    ErrorCode.SUCCESS: "成功",
    ErrorCode.UNKNOWN_ERROR: "未知错误",
    ErrorCode.INVALID_PARAMS: "参数无效",
    ErrorCode.UNAUTHORIZED: "未授权",
    ErrorCode.FORBIDDEN: "禁止访问",
    ErrorCode.NOT_FOUND: "资源不存在",
    ErrorCode.RATE_LIMITED: "请求过于频繁",
    ErrorCode.SERVICE_UNAVAILABLE: "服务不可用",
    ErrorCode.TIMEOUT: "请求超时",
    ErrorCode.INTERNAL_ERROR: "内部错误",
    ErrorCode.CONFIG_ERROR: "配置错误",

    ErrorCode.SKILL_NOT_FOUND: "技能不存在",
    ErrorCode.SKILL_DISABLED: "技能已禁用",
    ErrorCode.SKILL_LOAD_FAILED: "技能加载失败",
    ErrorCode.SKILL_VERSION_MISMATCH: "技能版本不匹配",
    ErrorCode.SKILL_DEPENDENCY_MISSING: "技能依赖缺失",
    ErrorCode.SKILL_ALREADY_EXISTS: "技能已存在",
    ErrorCode.SKILL_INVALID_MANIFEST: "技能清单无效",
    ErrorCode.SKILL_ACTION_NOT_FOUND: "技能动作不存在",
    ErrorCode.SKILL_CATEGORY_NOT_FOUND: "技能分类不存在",

    ErrorCode.EXECUTION_FAILED: "执行失败",
    ErrorCode.EXECUTION_TIMEOUT: "执行超时",
    ErrorCode.EXECUTION_CANCELLED: "执行已取消",
    ErrorCode.EXECUTION_RETRY_EXHAUSTED: "重试次数耗尽",
    ErrorCode.EXECUTION_PARAMS_INVALID: "执行参数无效",
    ErrorCode.EXECUTION_RESULT_INVALID: "执行结果无效",

    ErrorCode.PERMISSION_DENIED: "权限不足",
    ErrorCode.PERMISSION_LEVEL_INSUFFICIENT: "权限等级不足",
    ErrorCode.PERMISSION_SCOPE_INVALID: "权限作用域无效",
    ErrorCode.PERMISSION_TOKEN_INVALID: "权限令牌无效",
    ErrorCode.PERMISSION_ROLE_NOT_FOUND: "角色不存在",

    ErrorCode.MCP_SERVER_NOT_FOUND: "MCP服务不存在",
    ErrorCode.MCP_SERVER_UNAVAILABLE: "MCP服务不可用",
    ErrorCode.MCP_TOOL_NOT_FOUND: "MCP工具不存在",
    ErrorCode.MCP_CALL_FAILED: "MCP调用失败",
    ErrorCode.MCP_PROTOCOL_ERROR: "MCP协议错误",
    ErrorCode.MCP_CONNECTION_FAILED: "MCP连接失败",

    ErrorCode.CODE_EXEC_FAILED: "代码执行失败",
    ErrorCode.CODE_SYNTAX_ERROR: "代码语法错误",
    ErrorCode.CODE_TIMEOUT: "代码执行超时",
    ErrorCode.CODE_MEMORY_LIMIT: "内存不足",
    ErrorCode.CODE_SECURITY_BLOCKED: "安全拦截",
    ErrorCode.CODE_DEPENDENCY_MISSING: "依赖缺失",
    ErrorCode.CODE_LANGUAGE_UNSUPPORTED: "不支持的语言",
    ErrorCode.CODE_REPL_NOT_FOUND: "REPL会话不存在",
    ErrorCode.CODE_REPL_LIMIT_EXCEEDED: "REPL会话数超限",
    ErrorCode.CODE_INSTALL_FAILED: "包安装失败",

    ErrorCode.RECOMMEND_NO_RESULT: "无推荐结果",
    ErrorCode.RECOMMEND_QUERY_EMPTY: "查询为空",
    ErrorCode.RECOMMEND_SCENE_INVALID: "场景无效",
    ErrorCode.RECOMMEND_CACHE_ERROR: "推荐缓存错误",
}


def get_error_message(code: int) -> str:
    """获取错误码对应的默认消息."""
    return ERROR_MESSAGES.get(code, "未知错误")


def make_error_response(
    code: int,
    message: str | None = None,
    data: Any = None,
    trace_id: str = "",
) -> dict[str, Any]:
    """构造标准错误响应.

    Args:
        code: 错误码
        message: 错误消息（不传则用默认）
        data: 附加数据
        trace_id: 追踪ID

    Returns:
        标准错误响应字典
    """
    return {
        "code": code,
        "message": message or get_error_message(code),
        "data": data,
        "trace_id": trace_id,
        "success": code == ErrorCode.SUCCESS,
    }


def make_success_response(
    data: Any = None,
    message: str = "成功",
    trace_id: str = "",
) -> dict[str, Any]:
    """构造标准成功响应."""
    return {
        "code": ErrorCode.SUCCESS,
        "message": message,
        "data": data,
        "trace_id": trace_id,
        "success": True,
    }
