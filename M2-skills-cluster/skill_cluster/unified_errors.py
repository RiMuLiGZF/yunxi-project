"""
M2 技能集群 - 模块级错误码定义（统一 6 位错误码体系）
====================================================

遵循云汐系统统一 6 位错误码规范：XX YY ZZ
  - XX = 02 (模块编号，M2 技能集群)
  - YY = 错误类别
  - ZZ = 序号

模块范围：020100 - 020999

旧错误码体系（2xxxx，5 位）通过 LEGACY_MAP 映射到新的 6 位体系，
保持向后兼容。
"""

from __future__ import annotations

import warnings
from typing import Dict

try:
    from shared.core.errors import (
        ModuleCode,
        ErrorCategory,
        build_error_code,
        ModuleErrorCode,
    )
    _UNIFIED_ERRORS_AVAILABLE = True
except ImportError:
    _UNIFIED_ERRORS_AVAILABLE = False
    ModuleCode = None  # type: ignore
    ErrorCategory = None  # type: ignore
    ModuleCode = object  # type: ignore
    ModuleErrorCode = object  # type: ignore

    def build_error_code(module, category, seq):  # type: ignore
        return int(module) * 10000 + int(category) * 100 + seq


if _UNIFIED_ERRORS_AVAILABLE:

    class M2ErrorCode(ModuleErrorCode):
        """M2 技能集群错误码常量.

        模块编号: 02
        范围: 020100 - 020999
        """
        MODULE = ModuleCode.M2

        # ---------- 参数错误 (0201xx) ----------
        INVALID_PARAMS = build_error_code(ModuleCode.M2, ErrorCategory.VALIDATION, 1)
        """参数无效"""
        INVALID_SKILL_ID = build_error_code(ModuleCode.M2, ErrorCategory.VALIDATION, 2)
        """无效的技能 ID"""
        INVALID_SKILL_MANIFEST = build_error_code(ModuleCode.M2, ErrorCategory.VALIDATION, 3)
        """技能清单无效"""
        INVALID_EXECUTION_PARAMS = build_error_code(ModuleCode.M2, ErrorCategory.VALIDATION, 4)
        """执行参数无效"""
        INVALID_PERMISSION_SCOPE = build_error_code(ModuleCode.M2, ErrorCategory.VALIDATION, 5)
        """权限作用域无效"""
        INVALID_RECOMMEND_SCENE = build_error_code(ModuleCode.M2, ErrorCategory.VALIDATION, 6)
        """推荐场景无效"""
        INVALID_LANGUAGE = build_error_code(ModuleCode.M2, ErrorCategory.VALIDATION, 7)
        """不支持的编程语言"""
        INVALID_CODE_SYNTAX = build_error_code(ModuleCode.M2, ErrorCategory.VALIDATION, 8)
        """代码语法错误"""

        # ---------- 认证错误 (0202xx) ----------
        UNAUTHORIZED = build_error_code(ModuleCode.M2, ErrorCategory.AUTHENTICATION, 1)
        """未授权"""
        PERMISSION_TOKEN_INVALID = build_error_code(ModuleCode.M2, ErrorCategory.AUTHENTICATION, 2)
        """权限令牌无效"""

        # ---------- 权限错误 (0203xx) ----------
        FORBIDDEN = build_error_code(ModuleCode.M2, ErrorCategory.AUTHORIZATION, 1)
        """禁止访问"""
        PERMISSION_DENIED = build_error_code(ModuleCode.M2, ErrorCategory.AUTHORIZATION, 2)
        """权限不足"""
        PERMISSION_LEVEL_INSUFFICIENT = build_error_code(ModuleCode.M2, ErrorCategory.AUTHORIZATION, 3)
        """权限等级不足"""
        PERMISSION_ROLE_NOT_FOUND = build_error_code(ModuleCode.M2, ErrorCategory.AUTHORIZATION, 4)
        """角色不存在"""

        # ---------- 资源不存在 (0204xx) ----------
        NOT_FOUND = build_error_code(ModuleCode.M2, ErrorCategory.NOT_FOUND, 1)
        """资源不存在"""
        SKILL_NOT_FOUND = build_error_code(ModuleCode.M2, ErrorCategory.NOT_FOUND, 2)
        """技能不存在"""
        SKILL_ACTION_NOT_FOUND = build_error_code(ModuleCode.M2, ErrorCategory.NOT_FOUND, 3)
        """技能动作不存在"""
        SKILL_CATEGORY_NOT_FOUND = build_error_code(ModuleCode.M2, ErrorCategory.NOT_FOUND, 4)
        """技能分类不存在"""
        MCP_SERVER_NOT_FOUND = build_error_code(ModuleCode.M2, ErrorCategory.NOT_FOUND, 5)
        """MCP 服务不存在"""
        MCP_TOOL_NOT_FOUND = build_error_code(ModuleCode.M2, ErrorCategory.NOT_FOUND, 6)
        """MCP 工具不存在"""
        CODE_REPL_NOT_FOUND = build_error_code(ModuleCode.M2, ErrorCategory.NOT_FOUND, 7)
        """REPL 会话不存在"""

        # ---------- 业务错误 (0205xx) ----------
        SKILL_DISABLED = build_error_code(ModuleCode.M2, ErrorCategory.BUSINESS, 1)
        """技能已禁用"""
        SKILL_LOAD_FAILED = build_error_code(ModuleCode.M2, ErrorCategory.BUSINESS, 2)
        """技能加载失败"""
        SKILL_VERSION_MISMATCH = build_error_code(ModuleCode.M2, ErrorCategory.BUSINESS, 3)
        """技能版本不匹配"""
        SKILL_DEPENDENCY_MISSING = build_error_code(ModuleCode.M2, ErrorCategory.BUSINESS, 4)
        """技能依赖缺失"""
        SKILL_ALREADY_EXISTS = build_error_code(ModuleCode.M2, ErrorCategory.BUSINESS, 5)
        """技能已存在"""
        EXECUTION_FAILED = build_error_code(ModuleCode.M2, ErrorCategory.BUSINESS, 6)
        """执行失败"""
        EXECUTION_TIMEOUT = build_error_code(ModuleCode.M2, ErrorCategory.BUSINESS, 7)
        """执行超时"""
        EXECUTION_CANCELLED = build_error_code(ModuleCode.M2, ErrorCategory.BUSINESS, 8)
        """执行已取消"""
        EXECUTION_RETRY_EXHAUSTED = build_error_code(ModuleCode.M2, ErrorCategory.BUSINESS, 9)
        """重试次数耗尽"""
        EXECUTION_RESULT_INVALID = build_error_code(ModuleCode.M2, ErrorCategory.BUSINESS, 10)
        """执行结果无效"""
        MCP_SERVER_UNAVAILABLE = build_error_code(ModuleCode.M2, ErrorCategory.BUSINESS, 11)
        """MCP 服务不可用"""
        MCP_CALL_FAILED = build_error_code(ModuleCode.M2, ErrorCategory.BUSINESS, 12)
        """MCP 调用失败"""
        MCP_PROTOCOL_ERROR = build_error_code(ModuleCode.M2, ErrorCategory.BUSINESS, 13)
        """MCP 协议错误"""
        MCP_CONNECTION_FAILED = build_error_code(ModuleCode.M2, ErrorCategory.BUSINESS, 14)
        """MCP 连接失败"""
        CODE_EXEC_FAILED = build_error_code(ModuleCode.M2, ErrorCategory.BUSINESS, 15)
        """代码执行失败"""
        CODE_TIMEOUT = build_error_code(ModuleCode.M2, ErrorCategory.BUSINESS, 16)
        """代码执行超时"""
        CODE_MEMORY_LIMIT = build_error_code(ModuleCode.M2, ErrorCategory.BUSINESS, 17)
        """内存不足"""
        CODE_SECURITY_BLOCKED = build_error_code(ModuleCode.M2, ErrorCategory.BUSINESS, 18)
        """安全拦截"""
        CODE_DEPENDENCY_MISSING = build_error_code(ModuleCode.M2, ErrorCategory.BUSINESS, 19)
        """依赖缺失"""
        CODE_REPL_LIMIT_EXCEEDED = build_error_code(ModuleCode.M2, ErrorCategory.BUSINESS, 20)
        """REPL 会话数超限"""
        CODE_INSTALL_FAILED = build_error_code(ModuleCode.M2, ErrorCategory.BUSINESS, 21)
        """包安装失败"""
        RECOMMEND_NO_RESULT = build_error_code(ModuleCode.M2, ErrorCategory.BUSINESS, 22)
        """无推荐结果"""
        RECOMMEND_QUERY_EMPTY = build_error_code(ModuleCode.M2, ErrorCategory.BUSINESS, 23)
        """查询为空"""

        # ---------- 系统错误 (0206xx) ----------
        INTERNAL_ERROR = build_error_code(ModuleCode.M2, ErrorCategory.SYSTEM, 1)
        """内部错误"""
        UNKNOWN_ERROR = build_error_code(ModuleCode.M2, ErrorCategory.SYSTEM, 2)
        """未知错误"""
        CONFIG_ERROR = build_error_code(ModuleCode.M2, ErrorCategory.SYSTEM, 3)
        """配置错误"""
        SERVICE_UNAVAILABLE = build_error_code(ModuleCode.M2, ErrorCategory.SYSTEM, 4)
        """服务不可用"""
        RECOMMEND_CACHE_ERROR = build_error_code(ModuleCode.M2, ErrorCategory.SYSTEM, 5)
        """推荐缓存错误"""

        # ---------- 限流错误 (0208xx) ----------
        RATE_LIMITED = build_error_code(ModuleCode.M2, ErrorCategory.RATE_LIMIT, 1)
        """请求过于频繁"""

    # 便捷别名
    M2_ERR = M2ErrorCode

else:
    # 回退模式
    class M2ErrorCode:
        """M2 错误码常量（回退模式）"""
        # 参数错误
        INVALID_PARAMS = 20101
        INVALID_SKILL_ID = 20102
        INVALID_SKILL_MANIFEST = 20103
        INVALID_EXECUTION_PARAMS = 20104
        INVALID_PERMISSION_SCOPE = 20105
        INVALID_RECOMMEND_SCENE = 20106
        INVALID_LANGUAGE = 20107
        INVALID_CODE_SYNTAX = 20108
        # 认证错误
        UNAUTHORIZED = 20201
        PERMISSION_TOKEN_INVALID = 20202
        # 权限错误
        FORBIDDEN = 20301
        PERMISSION_DENIED = 20302
        PERMISSION_LEVEL_INSUFFICIENT = 20303
        PERMISSION_ROLE_NOT_FOUND = 20304
        # 资源不存在
        NOT_FOUND = 20401
        SKILL_NOT_FOUND = 20402
        SKILL_ACTION_NOT_FOUND = 20403
        SKILL_CATEGORY_NOT_FOUND = 20404
        MCP_SERVER_NOT_FOUND = 20405
        MCP_TOOL_NOT_FOUND = 20406
        CODE_REPL_NOT_FOUND = 20407
        # 业务错误
        SKILL_DISABLED = 20501
        SKILL_LOAD_FAILED = 20502
        SKILL_VERSION_MISMATCH = 20503
        SKILL_DEPENDENCY_MISSING = 20504
        SKILL_ALREADY_EXISTS = 20505
        EXECUTION_FAILED = 20506
        EXECUTION_TIMEOUT = 20507
        EXECUTION_CANCELLED = 20508
        EXECUTION_RETRY_EXHAUSTED = 20509
        EXECUTION_RESULT_INVALID = 20510
        MCP_SERVER_UNAVAILABLE = 20511
        MCP_CALL_FAILED = 20512
        MCP_PROTOCOL_ERROR = 20513
        MCP_CONNECTION_FAILED = 20514
        CODE_EXEC_FAILED = 20515
        CODE_TIMEOUT = 20516
        CODE_MEMORY_LIMIT = 20517
        CODE_SECURITY_BLOCKED = 20518
        CODE_DEPENDENCY_MISSING = 20519
        CODE_REPL_LIMIT_EXCEEDED = 20520
        CODE_INSTALL_FAILED = 20521
        RECOMMEND_NO_RESULT = 20522
        RECOMMEND_QUERY_EMPTY = 20523
        # 系统错误
        INTERNAL_ERROR = 20601
        UNKNOWN_ERROR = 20602
        CONFIG_ERROR = 20603
        SERVICE_UNAVAILABLE = 20604
        RECOMMEND_CACHE_ERROR = 20605
        # 限流错误
        RATE_LIMITED = 20801

    M2_ERR = M2ErrorCode


# ============================================================
# 旧错误码 -> 新 6 位错误码 映射（向后兼容）
# ============================================================
# 旧格式：2xxxx（5 位）
#  - 20000-20999: 通用错误
#  - 21000-21999: 技能相关错误
#  - 22000-22999: 执行相关错误
#  - 23000-23999: 权限相关错误
#  - 24000-24999: MCP 相关错误
#  - 25000-25999: 代码执行相关错误
#  - 26000-26999: 推荐相关错误

M2_LEGACY_ERROR_MAP: Dict[int, int] = {
    # 通用错误 (20000-20999)
    20000: 0,  # SUCCESS -> 0
    20001: M2ErrorCode.UNKNOWN_ERROR,
    20002: M2ErrorCode.INVALID_PARAMS,
    20003: M2ErrorCode.UNAUTHORIZED,
    20004: M2ErrorCode.FORBIDDEN,
    20005: M2ErrorCode.NOT_FOUND,
    20006: M2ErrorCode.RATE_LIMITED,
    20007: M2ErrorCode.SERVICE_UNAVAILABLE,
    20008: M2ErrorCode.EXECUTION_TIMEOUT,  # TIMEOUT -> 执行超时
    20009: M2ErrorCode.INTERNAL_ERROR,
    20010: M2ErrorCode.CONFIG_ERROR,

    # 技能相关错误 (21000-21999)
    21001: M2ErrorCode.SKILL_NOT_FOUND,
    21002: M2ErrorCode.SKILL_DISABLED,
    21003: M2ErrorCode.SKILL_LOAD_FAILED,
    21004: M2ErrorCode.SKILL_VERSION_MISMATCH,
    21005: M2ErrorCode.SKILL_DEPENDENCY_MISSING,
    21006: M2ErrorCode.SKILL_ALREADY_EXISTS,
    21007: M2ErrorCode.INVALID_SKILL_MANIFEST,
    21008: M2ErrorCode.SKILL_ACTION_NOT_FOUND,
    21009: M2ErrorCode.SKILL_CATEGORY_NOT_FOUND,

    # 执行相关错误 (22000-22999)
    22001: M2ErrorCode.EXECUTION_FAILED,
    22002: M2ErrorCode.EXECUTION_TIMEOUT,
    22003: M2ErrorCode.EXECUTION_CANCELLED,
    22004: M2ErrorCode.EXECUTION_RETRY_EXHAUSTED,
    22005: M2ErrorCode.INVALID_EXECUTION_PARAMS,
    22006: M2ErrorCode.EXECUTION_RESULT_INVALID,

    # 权限相关错误 (23000-23999)
    23001: M2ErrorCode.PERMISSION_DENIED,
    23002: M2ErrorCode.PERMISSION_LEVEL_INSUFFICIENT,
    23003: M2ErrorCode.INVALID_PERMISSION_SCOPE,
    23004: M2ErrorCode.PERMISSION_TOKEN_INVALID,
    23005: M2ErrorCode.PERMISSION_ROLE_NOT_FOUND,

    # MCP 相关错误 (24000-24999)
    24001: M2ErrorCode.MCP_SERVER_NOT_FOUND,
    24002: M2ErrorCode.MCP_SERVER_UNAVAILABLE,
    24003: M2ErrorCode.MCP_TOOL_NOT_FOUND,
    24004: M2ErrorCode.MCP_CALL_FAILED,
    24005: M2ErrorCode.MCP_PROTOCOL_ERROR,
    24006: M2ErrorCode.MCP_CONNECTION_FAILED,

    # 代码执行相关错误 (25000-25999)
    25001: M2ErrorCode.CODE_EXEC_FAILED,
    25002: M2ErrorCode.INVALID_CODE_SYNTAX,
    25003: M2ErrorCode.CODE_TIMEOUT,
    25004: M2ErrorCode.CODE_MEMORY_LIMIT,
    25005: M2ErrorCode.CODE_SECURITY_BLOCKED,
    25006: M2ErrorCode.CODE_DEPENDENCY_MISSING,
    25007: M2ErrorCode.INVALID_LANGUAGE,
    25008: M2ErrorCode.CODE_REPL_NOT_FOUND,
    25009: M2ErrorCode.CODE_REPL_LIMIT_EXCEEDED,
    25010: M2ErrorCode.CODE_INSTALL_FAILED,

    # 推荐相关错误 (26000-26999)
    26001: M2ErrorCode.RECOMMEND_NO_RESULT,
    26002: M2ErrorCode.RECOMMEND_QUERY_EMPTY,
    26003: M2ErrorCode.INVALID_RECOMMEND_SCENE,
    26004: M2ErrorCode.RECOMMEND_CACHE_ERROR,
}


def m2_normalize_error_code(code: int) -> int:
    """将 M2 旧错误码规范化为新的 6 位错误码.

    若 code 已在新体系内（或无法识别），原样返回。
    """
    return M2_LEGACY_ERROR_MAP.get(code, code)


def m2_is_legacy_code(code: int) -> bool:
    """判断是否为旧版 5 位错误码."""
    return 20000 <= code <= 29999


def warn_legacy_code(code: int, stacklevel: int = 3) -> None:
    """对使用旧错误码的代码发出 DeprecationWarning."""
    if m2_is_legacy_code(code):
        new_code = m2_normalize_error_code(code)
        warnings.warn(
            f"错误码 {code} 已废弃，请使用新的 6 位错误码 {new_code:06d}。"
            f"参考 skill_cluster.unified_errors.M2ErrorCode",
            DeprecationWarning,
            stacklevel=stacklevel,
        )


__all__ = [
    "M2ErrorCode",
    "M2_ERR",
    "M2_LEGACY_ERROR_MAP",
    "m2_normalize_error_code",
    "m2_is_legacy_code",
    "warn_legacy_code",
    "_UNIFIED_ERRORS_AVAILABLE",
]
