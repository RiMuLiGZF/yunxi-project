"""
M10 系统卫士 - 模块级错误码定义（统一 6 位错误码体系）
======================================================

遵循云汐系统统一 6 位错误码规范：XX YY ZZ
  - XX = 10 (模块编号，M10 系统卫士)
  - YY = 错误类别
  - ZZ = 序号

模块范围：100100 - 100999

旧错误码体系（10xxxx 6 位但格式为 M10+子模块+序号）通过 LEGACY_MAP
映射到新的统一 6 位体系，保持向后兼容。
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
    ModuleErrorCode = object  # type: ignore

    def build_error_code(module, category, seq):  # type: ignore
        return int(module) * 10000 + int(category) * 100 + seq


if _UNIFIED_ERRORS_AVAILABLE:

    class M10ErrorCode(ModuleErrorCode):
        """M10 系统卫士错误码常量.

        模块编号: 10
        范围: 100100 - 100999
        """
        MODULE = ModuleCode.M10

        # ---------- 参数错误 (1001xx) ----------
        INVALID_PARAMETER = build_error_code(ModuleCode.M10, ErrorCategory.VALIDATION, 1)
        """参数无效"""
        METRIC_TYPE_INVALID = build_error_code(ModuleCode.M10, ErrorCategory.VALIDATION, 2)
        """指标类型无效"""
        REPORT_FORMAT_INVALID = build_error_code(ModuleCode.M10, ErrorCategory.VALIDATION, 3)
        """报告格式无效"""

        # ---------- 认证错误 (1002xx) ----------
        AUTH_FAILED = build_error_code(ModuleCode.M10, ErrorCategory.AUTHENTICATION, 1)
        """认证失败"""
        TOKEN_MISSING = build_error_code(ModuleCode.M10, ErrorCategory.AUTHENTICATION, 2)
        """Token 缺失"""

        # ---------- 资源不存在 (1004xx) ----------
        NOT_FOUND = build_error_code(ModuleCode.M10, ErrorCategory.NOT_FOUND, 1)
        """资源不存在"""
        PROCESS_NOT_FOUND = build_error_code(ModuleCode.M10, ErrorCategory.NOT_FOUND, 2)
        """进程不存在"""
        POLICY_NOT_FOUND = build_error_code(ModuleCode.M10, ErrorCategory.NOT_FOUND, 3)
        """策略不存在"""
        ALERT_NOT_FOUND = build_error_code(ModuleCode.M10, ErrorCategory.NOT_FOUND, 4)
        """告警不存在"""
        MISSION_NOT_FOUND = build_error_code(ModuleCode.M10, ErrorCategory.NOT_FOUND, 5)
        """任务不存在"""
        AUDIT_LOG_NOT_FOUND = build_error_code(ModuleCode.M10, ErrorCategory.NOT_FOUND, 6)
        """审计日志不存在"""
        REPORT_NOT_FOUND = build_error_code(ModuleCode.M10, ErrorCategory.NOT_FOUND, 7)
        """报告不存在"""

        # ---------- 业务错误 (1005xx) ----------
        MONITOR_NOT_STARTED = build_error_code(ModuleCode.M10, ErrorCategory.BUSINESS, 1)
        """监控未启动"""
        MONITOR_COLLECTION_FAILED = build_error_code(ModuleCode.M10, ErrorCategory.BUSINESS, 2)
        """监控采集失败"""
        GPU_NOT_AVAILABLE = build_error_code(ModuleCode.M10, ErrorCategory.BUSINESS, 3)
        """GPU 不可用"""
        PROCESS_KILL_FAILED = build_error_code(ModuleCode.M10, ErrorCategory.BUSINESS, 4)
        """进程终止失败"""
        PROCESS_TREE_ERROR = build_error_code(ModuleCode.M10, ErrorCategory.BUSINESS, 5)
        """进程树操作错误"""
        GUARD_CHECK_FAILED = build_error_code(ModuleCode.M10, ErrorCategory.BUSINESS, 6)
        """防护检查失败"""
        POLICY_UPDATE_FAILED = build_error_code(ModuleCode.M10, ErrorCategory.BUSINESS, 7)
        """策略更新失败"""
        THROTTLING_ACTIVE = build_error_code(ModuleCode.M10, ErrorCategory.BUSINESS, 8)
        """限流已激活"""
        TIDE_NOT_INITIALIZED = build_error_code(ModuleCode.M10, ErrorCategory.BUSINESS, 9)
        """潮汐引擎未初始化"""
        MISSION_SUBMIT_FAILED = build_error_code(ModuleCode.M10, ErrorCategory.BUSINESS, 10)
        """任务提交失败"""
        GPU_ORCHESTRATION_FAILED = build_error_code(ModuleCode.M10, ErrorCategory.BUSINESS, 11)
        """GPU 调度失败"""
        AUDIT_EXPORT_FAILED = build_error_code(ModuleCode.M10, ErrorCategory.BUSINESS, 12)
        """审计导出失败"""
        AUDIT_CLEAR_FAILED = build_error_code(ModuleCode.M10, ErrorCategory.BUSINESS, 13)
        """审计清理失败"""
        REPORT_GENERATE_FAILED = build_error_code(ModuleCode.M10, ErrorCategory.BUSINESS, 14)
        """报告生成失败"""

        # ---------- 系统错误 (1006xx) ----------
        INTERNAL_ERROR = build_error_code(ModuleCode.M10, ErrorCategory.SYSTEM, 1)
        """内部错误"""
        UNKNOWN_ERROR = build_error_code(ModuleCode.M10, ErrorCategory.SYSTEM, 2)
        """未知错误"""
        SERVICE_UNAVAILABLE = build_error_code(ModuleCode.M10, ErrorCategory.SYSTEM, 3)
        """服务不可用"""

        # ---------- 限流错误 (1008xx) ----------
        RATE_LIMITED = build_error_code(ModuleCode.M10, ErrorCategory.RATE_LIMIT, 1)
        """请求频率超限"""

    # 便捷别名
    M10_ERR = M10ErrorCode

else:
    # 回退模式
    class M10ErrorCode:
        """M10 错误码常量（回退模式）"""
        # 参数错误
        INVALID_PARAMETER = 100101
        METRIC_TYPE_INVALID = 100102
        REPORT_FORMAT_INVALID = 100103
        # 认证错误
        AUTH_FAILED = 100201
        TOKEN_MISSING = 100202
        # 资源不存在
        NOT_FOUND = 100401
        PROCESS_NOT_FOUND = 100402
        POLICY_NOT_FOUND = 100403
        ALERT_NOT_FOUND = 100404
        MISSION_NOT_FOUND = 100405
        AUDIT_LOG_NOT_FOUND = 100406
        REPORT_NOT_FOUND = 100407
        # 业务错误
        MONITOR_NOT_STARTED = 100501
        MONITOR_COLLECTION_FAILED = 100502
        GPU_NOT_AVAILABLE = 100503
        PROCESS_KILL_FAILED = 100504
        PROCESS_TREE_ERROR = 100505
        GUARD_CHECK_FAILED = 100506
        POLICY_UPDATE_FAILED = 100507
        THROTTLING_ACTIVE = 100508
        TIDE_NOT_INITIALIZED = 100509
        MISSION_SUBMIT_FAILED = 100510
        GPU_ORCHESTRATION_FAILED = 100511
        AUDIT_EXPORT_FAILED = 100512
        AUDIT_CLEAR_FAILED = 100513
        REPORT_GENERATE_FAILED = 100514
        # 系统错误
        INTERNAL_ERROR = 100601
        UNKNOWN_ERROR = 100602
        SERVICE_UNAVAILABLE = 100603
        # 限流错误
        RATE_LIMITED = 100801

    M10_ERR = M10ErrorCode


# ============================================================
# 旧错误码 -> 新 6 位错误码 映射（向后兼容）
# ============================================================
# 旧格式：10xxxx（6 位，M10+子模块+序号）
#  - 1000xx: 通用错误
#  - 1010xx: 系统监控相关
#  - 1020xx: 进程管理相关
#  - 1030xx: 防护引擎相关
#  - 1040xx: 潮汐引擎相关
#  - 1050xx: 审计日志相关
#  - 1060xx: 报告生成相关

M10_LEGACY_ERROR_MAP: Dict[int, int] = {
    # 通用错误 (1000xx)
    100000: 0,  # SUCCESS
    100001: M10ErrorCode.UNKNOWN_ERROR,
    100002: M10ErrorCode.INVALID_PARAMETER,
    100003: M10ErrorCode.AUTH_FAILED,
    100004: M10ErrorCode.TOKEN_MISSING,
    100005: M10ErrorCode.RATE_LIMITED,
    100006: M10ErrorCode.NOT_FOUND,
    100007: M10ErrorCode.INTERNAL_ERROR,
    100008: M10ErrorCode.SERVICE_UNAVAILABLE,

    # 系统监控 (1010xx)
    101001: M10ErrorCode.MONITOR_NOT_STARTED,
    101002: M10ErrorCode.MONITOR_COLLECTION_FAILED,
    101003: M10ErrorCode.METRIC_TYPE_INVALID,
    101004: M10ErrorCode.GPU_NOT_AVAILABLE,

    # 进程管理 (1020xx)
    102001: M10ErrorCode.PROCESS_NOT_FOUND,
    102002: M10ErrorCode.PROCESS_KILL_FAILED,
    102003: M10ErrorCode.PROCESS_TREE_ERROR,

    # 防护引擎 (1030xx)
    103001: M10ErrorCode.GUARD_CHECK_FAILED,
    103002: M10ErrorCode.POLICY_NOT_FOUND,
    103003: M10ErrorCode.POLICY_UPDATE_FAILED,
    103004: M10ErrorCode.ALERT_NOT_FOUND,
    103005: M10ErrorCode.THROTTLING_ACTIVE,

    # 潮汐引擎 (1040xx)
    104001: M10ErrorCode.TIDE_NOT_INITIALIZED,
    104002: M10ErrorCode.MISSION_NOT_FOUND,
    104003: M10ErrorCode.MISSION_SUBMIT_FAILED,
    104004: M10ErrorCode.GPU_ORCHESTRATION_FAILED,

    # 审计日志 (1050xx)
    105001: M10ErrorCode.AUDIT_LOG_NOT_FOUND,
    105002: M10ErrorCode.AUDIT_EXPORT_FAILED,
    105003: M10ErrorCode.AUDIT_CLEAR_FAILED,

    # 报告生成 (1060xx)
    106001: M10ErrorCode.REPORT_NOT_FOUND,
    106002: M10ErrorCode.REPORT_GENERATE_FAILED,
    106003: M10ErrorCode.REPORT_FORMAT_INVALID,
}


def m10_normalize_error_code(code: int) -> int:
    """将 M10 旧错误码规范化为新的统一 6 位错误码.

    若 code 已在新体系内（或无法识别），原样返回。
    """
    return M10_LEGACY_ERROR_MAP.get(code, code)


def m10_is_legacy_code(code: int) -> bool:
    """判断是否为旧版错误码.

    旧版格式：10xxxx 但第3-4位是子模块号（00/10/20/30/40/50/60），
    新版格式：10 YY ZZ 其中 YY 是 01-09（错误类别）。
    通过判断中间两位是否 >= 10 来区分旧版。
    """
    if not (100000 <= code <= 109999):
        return False
    # 旧版：中间两位是子模块号（00, 10, 20, 30, 40, 50, 60）
    # 新版：中间两位是错误类别（01-09）
    middle = (code // 100) % 100
    return middle in (0, 10, 20, 30, 40, 50, 60)


def warn_legacy_code(code: int, stacklevel: int = 3) -> None:
    """对使用旧错误码的代码发出 DeprecationWarning."""
    if m10_is_legacy_code(code):
        new_code = m10_normalize_error_code(code)
        warnings.warn(
            f"错误码 {code} 已废弃，请使用新的统一 6 位错误码 {new_code:06d}。"
            f"参考 m10_system_guard.unified_errors.M10ErrorCode",
            DeprecationWarning,
            stacklevel=stacklevel,
        )


__all__ = [
    "M10ErrorCode",
    "M10_ERR",
    "M10_LEGACY_ERROR_MAP",
    "m10_normalize_error_code",
    "m10_is_legacy_code",
    "warn_legacy_code",
    "_UNIFIED_ERRORS_AVAILABLE",
]
