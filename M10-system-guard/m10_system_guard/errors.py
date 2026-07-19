"""
M10 系统卫士 - 统一错误码与异常定义

错误码规则：M10 + 3位序号
- M100xx: 通用错误（参数、认证、系统）
- M101xx: 系统监控相关
- M102xx: 进程管理相关
- M103xx: 防护引擎相关
- M104xx: 潮汐引擎相关
- M105xx: 审计日志相关
- M106xx: 报告生成相关
"""

from __future__ import annotations

from fastapi import HTTPException


# ============================================================
# 错误码常量
# ============================================================

class M10ErrorCode:
    """M10 错误码定义."""

    # 通用错误 M100xx
    SUCCESS = 0
    UNKNOWN_ERROR = 100001
    INVALID_PARAMETER = 100002
    AUTH_FAILED = 100003
    TOKEN_MISSING = 100004
    RATE_LIMITED = 100005
    NOT_FOUND = 100006
    INTERNAL_ERROR = 100007
    SERVICE_UNAVAILABLE = 100008

    # 系统监控 M101xx
    MONITOR_NOT_STARTED = 101001
    MONITOR_COLLECTION_FAILED = 101002
    METRIC_TYPE_INVALID = 101003
    GPU_NOT_AVAILABLE = 101004

    # 进程管理 M102xx
    PROCESS_NOT_FOUND = 102001
    PROCESS_KILL_FAILED = 102002
    PROCESS_TREE_ERROR = 102003

    # 防护引擎 M103xx
    GUARD_CHECK_FAILED = 103001
    POLICY_NOT_FOUND = 103002
    POLICY_UPDATE_FAILED = 103003
    ALERT_NOT_FOUND = 103004
    THROTTLING_ACTIVE = 103005

    # 潮汐引擎 M104xx
    TIDE_NOT_INITIALIZED = 104001
    MISSION_NOT_FOUND = 104002
    MISSION_SUBMIT_FAILED = 104003
    GPU_ORCHESTRATION_FAILED = 104004

    # 审计日志 M105xx
    AUDIT_LOG_NOT_FOUND = 105001
    AUDIT_EXPORT_FAILED = 105002
    AUDIT_CLEAR_FAILED = 105003

    # 报告生成 M106xx
    REPORT_NOT_FOUND = 106001
    REPORT_GENERATE_FAILED = 106002
    REPORT_FORMAT_INVALID = 106003


# 错误码到翻译 key 的映射
_ERROR_MESSAGE_KEYS: dict[int, str] = {
    M10ErrorCode.SUCCESS: "success",
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

    Args:
        code: 错误码

    Returns:
        翻译后的错误消息
    """
    from .i18n import t

    key = _ERROR_MESSAGE_KEYS.get(code)
    if key:
        return t(f"m10_errors.{key}")
    return t("m10_errors.unknown_error")


# ============================================================
# 自定义异常
# ============================================================

class M10Error(Exception):
    """M10 基础异常类."""

    def __init__(self, code: int, message: str = "", details: dict | None = None):
        self.code = code
        self.message = message or get_error_message(code)
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
