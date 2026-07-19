"""
M10 系统卫士 - 统一错误码与异常定义（已迁移至统一 6 位错误码体系）
==================================================================

.. deprecated::
    新代码请使用 ``m10_system_guard.unified_errors.M10ErrorCode``。

错误码已从旧版体系（10xxxx 子模块格式）迁移至统一 6 位体系（10YYZZ）。
所有旧错误码常量仍然可用，但其底层值已映射为新的 6 位编码。
"""

from __future__ import annotations

import warnings

from fastapi import HTTPException

from .unified_errors import (
    M10ErrorCode,
    M10_LEGACY_ERROR_MAP,
    m10_normalize_error_code,
    m10_is_legacy_code,
    _UNIFIED_ERRORS_AVAILABLE,
)


# ============================================================
# 兼容层：旧版 M10ErrorCode 类
# ============================================================
# 保持旧的常量名不变，但其值已映射为新的 6 位错误码

class _LegacyM10ErrorCode:
    """M10 错误码定义（已迁移至统一 6 位体系）.

    .. deprecated::
        请使用 ``M10ErrorCode`` 替代。

    所有旧常量名仍然可用，其值已自动映射为新的 6 位错误码。
    """

    # 通用错误 M100xx
    SUCCESS = 0
    UNKNOWN_ERROR = M10ErrorCode.UNKNOWN_ERROR
    INVALID_PARAMETER = M10ErrorCode.INVALID_PARAMETER
    AUTH_FAILED = M10ErrorCode.AUTH_FAILED
    TOKEN_MISSING = M10ErrorCode.TOKEN_MISSING
    RATE_LIMITED = M10ErrorCode.RATE_LIMITED
    NOT_FOUND = M10ErrorCode.NOT_FOUND
    INTERNAL_ERROR = M10ErrorCode.INTERNAL_ERROR
    SERVICE_UNAVAILABLE = M10ErrorCode.SERVICE_UNAVAILABLE

    # 系统监控 M101xx
    MONITOR_NOT_STARTED = M10ErrorCode.MONITOR_NOT_STARTED
    MONITOR_COLLECTION_FAILED = M10ErrorCode.MONITOR_COLLECTION_FAILED
    METRIC_TYPE_INVALID = M10ErrorCode.METRIC_TYPE_INVALID
    GPU_NOT_AVAILABLE = M10ErrorCode.GPU_NOT_AVAILABLE

    # 进程管理 M102xx
    PROCESS_NOT_FOUND = M10ErrorCode.PROCESS_NOT_FOUND
    PROCESS_KILL_FAILED = M10ErrorCode.PROCESS_KILL_FAILED
    PROCESS_TREE_ERROR = M10ErrorCode.PROCESS_TREE_ERROR

    # 防护引擎 M103xx
    GUARD_CHECK_FAILED = M10ErrorCode.GUARD_CHECK_FAILED
    POLICY_NOT_FOUND = M10ErrorCode.POLICY_NOT_FOUND
    POLICY_UPDATE_FAILED = M10ErrorCode.POLICY_UPDATE_FAILED
    ALERT_NOT_FOUND = M10ErrorCode.ALERT_NOT_FOUND
    THROTTLING_ACTIVE = M10ErrorCode.THROTTLING_ACTIVE

    # 潮汐引擎 M104xx
    TIDE_NOT_INITIALIZED = M10ErrorCode.TIDE_NOT_INITIALIZED
    MISSION_NOT_FOUND = M10ErrorCode.MISSION_NOT_FOUND
    MISSION_SUBMIT_FAILED = M10ErrorCode.MISSION_SUBMIT_FAILED
    GPU_ORCHESTRATION_FAILED = M10ErrorCode.GPU_ORCHESTRATION_FAILED

    # 审计日志 M105xx
    AUDIT_LOG_NOT_FOUND = M10ErrorCode.AUDIT_LOG_NOT_FOUND
    AUDIT_EXPORT_FAILED = M10ErrorCode.AUDIT_EXPORT_FAILED
    AUDIT_CLEAR_FAILED = M10ErrorCode.AUDIT_CLEAR_FAILED

    # 报告生成 M106xx
    REPORT_NOT_FOUND = M10ErrorCode.REPORT_NOT_FOUND
    REPORT_GENERATE_FAILED = M10ErrorCode.REPORT_GENERATE_FAILED
    REPORT_FORMAT_INVALID = M10ErrorCode.REPORT_FORMAT_INVALID


# 旧版名称保持可用
M10ErrorCodeLegacy = _LegacyM10ErrorCode


# 错误码到翻译 key 的映射（使用新错误码作为 key）
_ERROR_MESSAGE_KEYS: dict[int, str] = {
    0: "success",
    M10ErrorCode.UNKNOWN_ERROR: "unknown_error",
    M10ErrorCode.INVALID_PARAMETER: "invalid_parameter",
    M10ErrorCode.AUTH_FAILED: "auth_failed",
    M10ErrorCode.TOKEN_MISSING: "token_missing",
    M10ErrorCode.RATE_LIMITED: "rate_limited",
    M10ErrorCode.NOT_FOUND: "not_found",
    M10ErrorCode.INTERNAL_ERROR: "internal_error",
    M10ErrorCode.SERVICE_UNAVAILABLE: "service_unavailable",
    M10ErrorCode.MONITOR_NOT_STARTED: "monitor_not_started",
    M10ErrorCode.MONITOR_COLLECTION_FAILED: "monitor_collection_failed",
    M10ErrorCode.METRIC_TYPE_INVALID: "metric_type_invalid",
    M10ErrorCode.GPU_NOT_AVAILABLE: "gpu_not_available",
    M10ErrorCode.PROCESS_NOT_FOUND: "process_not_found",
    M10ErrorCode.PROCESS_KILL_FAILED: "process_kill_failed",
    M10ErrorCode.PROCESS_TREE_ERROR: "process_tree_error",
    M10ErrorCode.GUARD_CHECK_FAILED: "guard_check_failed",
    M10ErrorCode.POLICY_NOT_FOUND: "policy_not_found",
    M10ErrorCode.POLICY_UPDATE_FAILED: "policy_update_failed",
    M10ErrorCode.ALERT_NOT_FOUND: "alert_not_found",
    M10ErrorCode.THROTTLING_ACTIVE: "throttling_active",
    M10ErrorCode.TIDE_NOT_INITIALIZED: "tide_not_initialized",
    M10ErrorCode.MISSION_NOT_FOUND: "mission_not_found",
    M10ErrorCode.MISSION_SUBMIT_FAILED: "mission_submit_failed",
    M10ErrorCode.GPU_ORCHESTRATION_FAILED: "gpu_orchestration_failed",
    M10ErrorCode.AUDIT_LOG_NOT_FOUND: "audit_log_not_found",
    M10ErrorCode.AUDIT_EXPORT_FAILED: "audit_export_failed",
    M10ErrorCode.AUDIT_CLEAR_FAILED: "audit_clear_failed",
    M10ErrorCode.REPORT_NOT_FOUND: "report_not_found",
    M10ErrorCode.REPORT_GENERATE_FAILED: "report_generate_failed",
    M10ErrorCode.REPORT_FORMAT_INVALID: "report_format_invalid",
}


def get_error_message(code: int) -> str:
    """
    获取错误码对应的消息（使用 i18n 翻译）.

    自动规范化旧版错误码为新版统一 6 位编码。

    Args:
        code: 错误码

    Returns:
        翻译后的错误消息
    """
    from .i18n import t

    normalized_code = m10_normalize_error_code(code)
    key = _ERROR_MESSAGE_KEYS.get(normalized_code)
    if key:
        return t(f"m10_errors.{key}")
    return t("m10_errors.unknown_error")


# ============================================================
# 自定义异常
# ============================================================

class M10Error(Exception):
    """M10 基础异常类（已迁移至统一错误码体系）.

    旧版错误码会自动规范化为新版 6 位编码。
    """

    def __init__(self, code: int, message: str = "", details: dict | None = None):
        # 自动规范化旧错误码
        normalized_code = m10_normalize_error_code(code)
        self.code = normalized_code
        self.message = message or get_error_message(normalized_code)
        self.details = details or {}
        super().__init__(self.message)

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


class M10AuthError(M10Error):
    """认证异常."""
    def __init__(self, message: str = ""):
        if not message:
            from .i18n import t
            message = t("m10_errors.auth_failed")
        super().__init__(code=M10ErrorCode.AUTH_FAILED, message=message)


class M10ParamError(M10Error):
    """参数异常."""
    def __init__(self, message: str = "", details: dict | None = None):
        if not message:
            from .i18n import t
            message = t("m10_errors.invalid_parameter")
        super().__init__(code=M10ErrorCode.INVALID_PARAMETER, message=message, details=details)


class M10NotFoundError(M10Error):
    """资源不存在异常."""
    def __init__(self, message: str = ""):
        if not message:
            from .i18n import t
            message = t("m10_errors.not_found")
        super().__init__(code=M10ErrorCode.NOT_FOUND, message=message)


class M10MonitorError(M10Error):
    """监控异常."""
    def __init__(self, message: str = ""):
        if not message:
            from .i18n import t
            message = t("m10_errors.monitor_collection_failed")
        super().__init__(code=M10ErrorCode.MONITOR_COLLECTION_FAILED, message=message)


# ============================================================
# FastAPI 异常处理器
# ============================================================

def register_exception_handlers(app) -> None:
    """为 FastAPI 应用注册全局异常处理器."""
    from fastapi import Request
    from fastapi.responses import JSONResponse
    import traceback

    @app.exception_handler(M10Error)
    async def m10_error_handler(request: Request, exc: M10Error):
        """处理 M10 自定义异常."""
        return JSONResponse(
            status_code=400,
            content={
                "code": exc.code,
                "message": exc.message,
                "data": exc.details,
            },
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        """处理 FastAPI HTTPException."""
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": M10ErrorCode.INTERNAL_ERROR if exc.status_code >= 500 else M10ErrorCode.UNKNOWN_ERROR,
                "message": exc.detail,
                "data": {},
            },
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        """处理未捕获的异常."""
        import os
        from .i18n import t

        env = os.getenv("M10_ENV", "development")
        error_detail = traceback.format_exc() if env == "development" else "Internal Server Error"

        return JSONResponse(
            status_code=500,
            content={
                "code": M10ErrorCode.INTERNAL_ERROR,
                "message": t("m10_errors.internal_error"),
                "data": {"detail": error_detail} if env == "development" else {},
            },
        )


# 发出废弃警告（模块级别）
warnings.warn(
    "m10_system_guard.errors 已迁移至统一错误码体系。"
    "新代码请使用 m10_system_guard.unified_errors.M10ErrorCode。"
    "旧错误码常量仍然可用但已映射为新的 6 位编码。",
    DeprecationWarning,
    stacklevel=2,
)


__all__ = [
    "M10ErrorCode",
    "M10ErrorCodeLegacy",
    "M10Error",
    "M10AuthError",
    "M10ParamError",
    "M10NotFoundError",
    "M10MonitorError",
    "get_error_message",
    "register_exception_handlers",
    "M10_LEGACY_ERROR_MAP",
    "_UNIFIED_ERRORS_AVAILABLE",
]
