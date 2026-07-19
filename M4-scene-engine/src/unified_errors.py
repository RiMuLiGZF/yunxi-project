"""
M4 场景引擎 - 模块级错误码定义（统一 6 位错误码体系）
====================================================

遵循云汐系统统一 6 位错误码规范：XX YY ZZ
  - XX = 04 (模块编号，M4 场景引擎)
  - YY = 错误类别
  - ZZ = 序号

模块范围：040100 - 040999

旧错误码体系（4xxxx/5xxxx，5 位）通过 LEGACY_MAP 映射到新的 6 位体系，
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
    ModuleErrorCode = object  # type: ignore

    def build_error_code(module, category, seq):  # type: ignore
        return int(module) * 10000 + int(category) * 100 + seq


if _UNIFIED_ERRORS_AVAILABLE:

    class M4ErrorCode(ModuleErrorCode):
        """M4 场景引擎错误码常量.

        模块编号: 04
        范围: 040100 - 040999
        """
        MODULE = ModuleCode.M4

        # ---------- 参数错误 (0401xx) ----------
        INVALID_SCENE_ID = build_error_code(ModuleCode.M4, ErrorCategory.VALIDATION, 1)
        """无效的场景 ID"""
        INVALID_SCENE_CONFIG = build_error_code(ModuleCode.M4, ErrorCategory.VALIDATION, 2)
        """无效的场景配置"""
        INVALID_TRIGGER = build_error_code(ModuleCode.M4, ErrorCategory.VALIDATION, 3)
        """无效的触发器"""
        INVALID_CONDITION = build_error_code(ModuleCode.M4, ErrorCategory.VALIDATION, 4)
        """无效的条件表达式"""
        INVALID_ACTION = build_error_code(ModuleCode.M4, ErrorCategory.VALIDATION, 5)
        """无效的动作配置"""
        INVALID_SCENE_NAME = build_error_code(ModuleCode.M4, ErrorCategory.VALIDATION, 6)
        """无效的场景名称"""
        BAD_REQUEST = build_error_code(ModuleCode.M4, ErrorCategory.VALIDATION, 7)
        """请求参数错误"""
        INVALID_PARAMETER = build_error_code(ModuleCode.M4, ErrorCategory.VALIDATION, 8)
        """参数无效"""
        MISSING_PARAMETER = build_error_code(ModuleCode.M4, ErrorCategory.VALIDATION, 9)
        """缺少必需参数"""
        INVALID_CONTEXT = build_error_code(ModuleCode.M4, ErrorCategory.VALIDATION, 10)
        """上下文内容无效"""
        CONTEXT_TOO_LARGE = build_error_code(ModuleCode.M4, ErrorCategory.VALIDATION, 11)
        """上下文内容过大"""
        CONFIG_INVALID = build_error_code(ModuleCode.M4, ErrorCategory.VALIDATION, 12)
        """配置无效"""

        # ---------- 认证错误 (0402xx) ----------
        TOKEN_MISSING = build_error_code(ModuleCode.M4, ErrorCategory.AUTHENTICATION, 1)
        """未提供认证令牌"""
        TOKEN_INVALID = build_error_code(ModuleCode.M4, ErrorCategory.AUTHENTICATION, 2)
        """认证令牌无效"""

        # ---------- 权限错误 (0403xx) ----------
        PERMISSION_DENIED = build_error_code(ModuleCode.M4, ErrorCategory.AUTHORIZATION, 1)
        """权限不足"""

        # ---------- 资源不存在 (0404xx) ----------
        SCENE_NOT_FOUND = build_error_code(ModuleCode.M4, ErrorCategory.NOT_FOUND, 1)
        """场景不存在"""
        TRIGGER_NOT_FOUND = build_error_code(ModuleCode.M4, ErrorCategory.NOT_FOUND, 2)
        """触发器不存在"""
        ACTION_NOT_FOUND = build_error_code(ModuleCode.M4, ErrorCategory.NOT_FOUND, 3)
        """动作不存在"""
        SCENE_TEMPLATE_NOT_FOUND = build_error_code(ModuleCode.M4, ErrorCategory.NOT_FOUND, 4)
        """场景模板不存在"""
        RESOURCE_NOT_FOUND = build_error_code(ModuleCode.M4, ErrorCategory.NOT_FOUND, 5)
        """资源不存在"""
        CONTEXT_NOT_FOUND = build_error_code(ModuleCode.M4, ErrorCategory.NOT_FOUND, 6)
        """上下文不存在"""
        CONFIG_NOT_FOUND = build_error_code(ModuleCode.M4, ErrorCategory.NOT_FOUND, 7)
        """配置不存在"""

        # ---------- 业务错误 (0405xx) ----------
        SCENE_ALREADY_EXISTS = build_error_code(ModuleCode.M4, ErrorCategory.BUSINESS, 1)
        """场景已存在"""
        SCENE_ALREADY_ACTIVE = build_error_code(ModuleCode.M4, ErrorCategory.BUSINESS, 2)
        """场景已激活"""
        SCENE_NOT_ACTIVE = build_error_code(ModuleCode.M4, ErrorCategory.BUSINESS, 3)
        """场景未激活"""
        TRIGGER_CONFLICT = build_error_code(ModuleCode.M4, ErrorCategory.BUSINESS, 4)
        """触发器冲突"""
        ACTION_EXECUTION_FAILED = build_error_code(ModuleCode.M4, ErrorCategory.BUSINESS, 5)
        """动作执行失败"""
        CONDITION_EVALUATION_FAILED = build_error_code(ModuleCode.M4, ErrorCategory.BUSINESS, 6)
        """条件评估失败"""
        SCENE_CYCLE_DETECTED = build_error_code(ModuleCode.M4, ErrorCategory.BUSINESS, 7)
        """检测到场景循环依赖"""
        SCENE_SWITCH_FAILED = build_error_code(ModuleCode.M4, ErrorCategory.BUSINESS, 8)
        """场景切换失败"""
        METHOD_NOT_ALLOWED = build_error_code(ModuleCode.M4, ErrorCategory.BUSINESS, 9)
        """方法不允许"""
        CONTEXT_STORE_ERROR = build_error_code(ModuleCode.M4, ErrorCategory.BUSINESS, 10)
        """上下文存储错误"""
        CONFIG_READ_ONLY = build_error_code(ModuleCode.M4, ErrorCategory.BUSINESS, 11)
        """配置为只读"""

        # ---------- 系统错误 (0406xx) ----------
        ENGINE_INIT_FAILED = build_error_code(ModuleCode.M4, ErrorCategory.SYSTEM, 1)
        """场景引擎初始化失败"""
        EVENT_BUS_ERROR = build_error_code(ModuleCode.M4, ErrorCategory.SYSTEM, 2)
        """事件总线错误"""
        SCHEDULER_ERROR = build_error_code(ModuleCode.M4, ErrorCategory.SYSTEM, 3)
        """调度器错误"""
        INTERNAL_ERROR = build_error_code(ModuleCode.M4, ErrorCategory.SYSTEM, 4)
        """服务器内部错误"""
        SCENE_ENGINE_ERROR = build_error_code(ModuleCode.M4, ErrorCategory.SYSTEM, 5)
        """场景引擎内部错误"""
        SERVICE_UNAVAILABLE = build_error_code(ModuleCode.M4, ErrorCategory.SYSTEM, 6)
        """服务暂不可用"""

        # ---------- 限流错误 (0408xx) ----------
        RATE_LIMITED = build_error_code(ModuleCode.M4, ErrorCategory.RATE_LIMIT, 1)
        """请求过于频繁"""

        # ---------- 超时 (0406xx 系统错误段) ----------
        TIMEOUT = build_error_code(ModuleCode.M4, ErrorCategory.SYSTEM, 7)
        """请求超时"""

    # 便捷别名
    M4_ERR = M4ErrorCode

else:
    # 回退模式
    class M4ErrorCode:
        """M4 错误码常量（回退模式）"""
        # 参数错误
        INVALID_SCENE_ID = 40101
        INVALID_SCENE_CONFIG = 40102
        INVALID_TRIGGER = 40103
        INVALID_CONDITION = 40104
        INVALID_ACTION = 40105
        INVALID_SCENE_NAME = 40106
        BAD_REQUEST = 40107
        INVALID_PARAMETER = 40108
        MISSING_PARAMETER = 40109
        INVALID_CONTEXT = 40110
        CONTEXT_TOO_LARGE = 40111
        CONFIG_INVALID = 40112
        # 认证错误
        TOKEN_MISSING = 40201
        TOKEN_INVALID = 40202
        # 权限错误
        PERMISSION_DENIED = 40301
        # 资源不存在
        SCENE_NOT_FOUND = 40401
        TRIGGER_NOT_FOUND = 40402
        ACTION_NOT_FOUND = 40403
        SCENE_TEMPLATE_NOT_FOUND = 40404
        RESOURCE_NOT_FOUND = 40405
        CONTEXT_NOT_FOUND = 40406
        CONFIG_NOT_FOUND = 40407
        # 业务错误
        SCENE_ALREADY_EXISTS = 40501
        SCENE_ALREADY_ACTIVE = 40502
        SCENE_NOT_ACTIVE = 40503
        TRIGGER_CONFLICT = 40504
        ACTION_EXECUTION_FAILED = 40505
        CONDITION_EVALUATION_FAILED = 40506
        SCENE_CYCLE_DETECTED = 40507
        SCENE_SWITCH_FAILED = 40508
        METHOD_NOT_ALLOWED = 40509
        CONTEXT_STORE_ERROR = 40510
        CONFIG_READ_ONLY = 40511
        # 系统错误
        ENGINE_INIT_FAILED = 40601
        EVENT_BUS_ERROR = 40602
        SCHEDULER_ERROR = 40603
        INTERNAL_ERROR = 40604
        SCENE_ENGINE_ERROR = 40605
        SERVICE_UNAVAILABLE = 40606
        # 限流错误
        RATE_LIMITED = 40801
        # 超时
        TIMEOUT = 40607

    M4_ERR = M4ErrorCode


# ============================================================
# 旧错误码 -> 新 6 位错误码 映射（向后兼容）
# ============================================================
# 旧格式：4xxxx/5xxxx（5 位）
#  - 400xx: 通用错误
#  - 410xx: 场景相关
#  - 420xx: 上下文相关
#  - 430xx: 配置相关
#  - 440xx: 鉴权相关
#  - 500xx: 服务端错误

M4_LEGACY_ERROR_MAP: Dict[int, int] = {
    # 成功
    0: 0,  # SUCCESS

    # 通用错误 (400xx)
    40000: M4ErrorCode.BAD_REQUEST,
    40001: M4ErrorCode.INVALID_PARAMETER,
    40002: M4ErrorCode.MISSING_PARAMETER,
    40004: M4ErrorCode.RESOURCE_NOT_FOUND,
    40005: M4ErrorCode.METHOD_NOT_ALLOWED,
    40029: M4ErrorCode.RATE_LIMITED,

    # 场景相关 (410xx)
    41001: M4ErrorCode.SCENE_NOT_FOUND,
    41002: M4ErrorCode.SCENE_SWITCH_FAILED,
    41003: M4ErrorCode.SCENE_ALREADY_ACTIVE,
    41004: M4ErrorCode.INVALID_SCENE_CONFIG,
    41005: M4ErrorCode.SCENE_ENGINE_ERROR,

    # 上下文相关 (420xx)
    42001: M4ErrorCode.CONTEXT_NOT_FOUND,
    42002: M4ErrorCode.CONTEXT_STORE_ERROR,
    42003: M4ErrorCode.CONTEXT_TOO_LARGE,

    # 配置相关 (430xx)
    43001: M4ErrorCode.CONFIG_NOT_FOUND,
    43002: M4ErrorCode.CONFIG_INVALID,
    43003: M4ErrorCode.CONFIG_READ_ONLY,

    # 鉴权相关 (440xx)
    44001: M4ErrorCode.TOKEN_MISSING,
    44002: M4ErrorCode.TOKEN_INVALID,
    44003: M4ErrorCode.PERMISSION_DENIED,

    # 服务端错误 (500xx)
    50000: M4ErrorCode.INTERNAL_ERROR,
    50003: M4ErrorCode.SERVICE_UNAVAILABLE,
    50004: M4ErrorCode.TIMEOUT,
}


def m4_normalize_error_code(code: int) -> int:
    """将 M4 旧错误码规范化为新的 6 位错误码.

    若 code 已在新体系内（或无法识别），原样返回。
    """
    return M4_LEGACY_ERROR_MAP.get(code, code)


def m4_is_legacy_code(code: int) -> bool:
    """判断是否为旧版 5 位错误码."""
    return (40000 <= code <= 49999) or (50000 <= code <= 59999)


def warn_legacy_code(code: int, stacklevel: int = 3) -> None:
    """对使用旧错误码的代码发出 DeprecationWarning."""
    if m4_is_legacy_code(code):
        new_code = m4_normalize_error_code(code)
        warnings.warn(
            f"错误码 {code} 已废弃，请使用新的 6 位错误码 {new_code:06d}。"
            f"参考 src.unified_errors.M4ErrorCode",
            DeprecationWarning,
            stacklevel=stacklevel,
        )


__all__ = [
    "M4ErrorCode",
    "M4_ERR",
    "M4_LEGACY_ERROR_MAP",
    "m4_normalize_error_code",
    "m4_is_legacy_code",
    "warn_legacy_code",
    "_UNIFIED_ERRORS_AVAILABLE",
]
