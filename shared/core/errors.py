"""
云汐系统统一错误码体系
====================

6 位错误码规范：XX YY ZZ
  - 前 2 位（XX）：模块编号
      00 = 系统通用
      01 = M1 智能体集群 / 02 = M2 技能集群 / 03 = M3 边端云协同
      04 = M4 场景引擎   / 05 = M5 潮汐记忆 / 06 = M6 硬件外设
      07 = M7 积木平台   / 08 = M8 控制塔  / 09 = M9 开发工坊
      10 = M10 系统卫士  / 11 = M11 MCP总线 / 12 = M12 安全盾

  - 中间 2 位（YY）：错误类别
      00 = 成功
      01 = 参数错误 (Validation / Bad Request)
      02 = 认证错误 (Authentication)
      03 = 权限错误 (Authorization / Forbidden)
      04 = 资源不存在 (Not Found)
      05 = 业务错误 (Business Logic)
      06 = 系统错误 (Internal Server Error)
      07 = 第三方错误 (Third-party / Upstream)
      08 = 限流错误 (Rate Limit)
      09 = 数据错误 (Data Integrity / Conflict)

  - 后 2 位（ZZ）：具体错误序号（00-99）

示例：
  000101 = 系统通用-参数错误-缺少必填字段
  080501 = M8 控制塔-业务错误-模块启动失败
  110701 = M11 MCP总线-第三方错误-MCP 服务调用超时

向后兼容：
  - 保留旧版 YunxiError 基类及其子类（deprecated 别名）
  - 旧错误码（如 40001、40101）通过 ERROR_CODE_LEGACY_MAP 映射到新码
  - 过渡期内同时支持新旧两种错误码
"""

from __future__ import annotations

from enum import IntEnum
from typing import Any, Dict, Optional, Type


# ============================================================
# 错误码分段定义
# ============================================================

class ErrorCategory(IntEnum):
    """错误类别枚举（中间 2 位）"""
    SUCCESS = 0       # 成功
    VALIDATION = 1    # 参数错误
    AUTHENTICATION = 2  # 认证错误
    AUTHORIZATION = 3   # 权限错误
    NOT_FOUND = 4     # 资源不存在
    BUSINESS = 5      # 业务错误
    SYSTEM = 6        # 系统错误
    THIRD_PARTY = 7   # 第三方错误
    RATE_LIMIT = 8    # 限流错误
    DATA = 9          # 数据错误


class ModuleCode(IntEnum):
    """模块编号枚举（前 2 位）"""
    SYSTEM = 0      # 系统通用
    M1 = 1          # M1 智能体集群
    M2 = 2          # M2 技能集群
    M3 = 3          # M3 边端云协同
    M4 = 4          # M4 场景引擎
    M5 = 5          # M5 潮汐记忆
    M6 = 6          # M6 硬件外设
    M7 = 7          # M7 积木平台
    M8 = 8          # M8 控制塔
    M9 = 9          # M9 开发工坊
    M10 = 10        # M10 系统卫士
    M11 = 11        # M11 MCP 总线
    M12 = 12        # M12 安全盾


# ============================================================
# HTTP 状态码映射（错误类别 -> 默认 HTTP 状态码）
# ============================================================

CATEGORY_HTTP_STATUS: Dict[ErrorCategory, int] = {
    ErrorCategory.SUCCESS: 200,
    ErrorCategory.VALIDATION: 400,
    ErrorCategory.AUTHENTICATION: 401,
    ErrorCategory.AUTHORIZATION: 403,
    ErrorCategory.NOT_FOUND: 404,
    ErrorCategory.BUSINESS: 409,
    ErrorCategory.SYSTEM: 500,
    ErrorCategory.THIRD_PARTY: 502,
    ErrorCategory.RATE_LIMIT: 429,
    ErrorCategory.DATA: 409,
}


# ============================================================
# 错误码构建工具
# ============================================================

def build_error_code(module: int | ModuleCode, category: int | ErrorCategory, seq: int) -> int:
    """构建 6 位错误码.

    Args:
        module: 模块编号（0-12）
        category: 错误类别（0-9）
        seq: 具体错误序号（0-99）

    Returns:
        6 位整数错误码

    Examples:
        >>> build_error_code(ModuleCode.SYSTEM, ErrorCategory.VALIDATION, 1)
        101  # 即 000101
        >>> build_error_code(ModuleCode.M8, ErrorCategory.BUSINESS, 1)
        80501  # 即 080501
    """
    m = int(module)
    c = int(category)
    if not (0 <= m <= 12):
        raise ValueError(f"模块编号必须在 0-12 之间，当前: {m}")
    if not (0 <= c <= 9):
        raise ValueError(f"错误类别必须在 0-9 之间，当前: {c}")
    if not (0 <= seq <= 99):
        raise ValueError(f"错误序号必须在 0-99 之间，当前: {seq}")
    return m * 10000 + c * 100 + seq


def parse_error_code(code: int) -> Dict[str, int]:
    """解析 6 位错误码，返回模块、类别、序号.

    Args:
        code: 6 位错误码

    Returns:
        包含 module, category, seq 的字典
    """
    if code < 0:
        # 兼容 M11 负数错误码（JSON-RPC 风格），转为正数解析
        code = abs(code)
    module = code // 10000
    category = (code // 100) % 100
    seq = code % 100
    return {
        "module": module,
        "category": category,
        "seq": seq,
    }


# ============================================================
# 通用错误码定义（00 前缀，系统级）
# ============================================================

class ErrorCode:
    """系统通用错误码常量（00 模块）.

    所有模块共享的基础错误码，格式为 00 YY ZZ。
    模块特有错误码应在各模块内自行定义（如 M8ErrorCode）。
    """

    # ---------- 成功 (0000xx) ----------
    SUCCESS = build_error_code(ModuleCode.SYSTEM, ErrorCategory.SUCCESS, 0)

    # ---------- 参数错误 (0001xx) ----------
    VALIDATION_ERROR = build_error_code(ModuleCode.SYSTEM, ErrorCategory.VALIDATION, 1)
    """通用参数验证失败"""
    PARAM_MISSING = build_error_code(ModuleCode.SYSTEM, ErrorCategory.VALIDATION, 2)
    """缺少必填参数"""
    PARAM_INVALID = build_error_code(ModuleCode.SYSTEM, ErrorCategory.VALIDATION, 3)
    """参数格式无效"""
    PARAM_OUT_OF_RANGE = build_error_code(ModuleCode.SYSTEM, ErrorCategory.VALIDATION, 4)
    """参数超出范围"""
    PARAM_TYPE_ERROR = build_error_code(ModuleCode.SYSTEM, ErrorCategory.VALIDATION, 5)
    """参数类型错误"""

    # ---------- 认证错误 (0002xx) ----------
    AUTH_FAILED = build_error_code(ModuleCode.SYSTEM, ErrorCategory.AUTHENTICATION, 1)
    """认证失败"""
    TOKEN_MISSING = build_error_code(ModuleCode.SYSTEM, ErrorCategory.AUTHENTICATION, 2)
    """Token 缺失"""
    TOKEN_INVALID = build_error_code(ModuleCode.SYSTEM, ErrorCategory.AUTHENTICATION, 3)
    """Token 无效"""
    TOKEN_EXPIRED = build_error_code(ModuleCode.SYSTEM, ErrorCategory.AUTHENTICATION, 4)
    """Token 已过期"""
    API_KEY_INVALID = build_error_code(ModuleCode.SYSTEM, ErrorCategory.AUTHENTICATION, 5)
    """API Key 无效"""

    # ---------- 权限错误 (0003xx) ----------
    PERMISSION_DENIED = build_error_code(ModuleCode.SYSTEM, ErrorCategory.AUTHORIZATION, 1)
    """无访问权限"""
    ROLE_REQUIRED = build_error_code(ModuleCode.SYSTEM, ErrorCategory.AUTHORIZATION, 2)
    """需要特定角色"""
    RESOURCE_FORBIDDEN = build_error_code(ModuleCode.SYSTEM, ErrorCategory.AUTHORIZATION, 3)
    """资源访问被禁止"""

    # ---------- 资源不存在 (0004xx) ----------
    NOT_FOUND = build_error_code(ModuleCode.SYSTEM, ErrorCategory.NOT_FOUND, 1)
    """资源不存在"""
    ENDPOINT_NOT_FOUND = build_error_code(ModuleCode.SYSTEM, ErrorCategory.NOT_FOUND, 2)
    """接口不存在"""
    MODULE_NOT_FOUND = build_error_code(ModuleCode.SYSTEM, ErrorCategory.NOT_FOUND, 3)
    """模块不存在"""

    # ---------- 业务错误 (0005xx) ----------
    BUSINESS_ERROR = build_error_code(ModuleCode.SYSTEM, ErrorCategory.BUSINESS, 1)
    """通用业务错误"""
    OPERATION_NOT_ALLOWED = build_error_code(ModuleCode.SYSTEM, ErrorCategory.BUSINESS, 2)
    """操作不允许"""
    ALREADY_EXISTS = build_error_code(ModuleCode.SYSTEM, ErrorCategory.BUSINESS, 3)
    """资源已存在"""

    # ---------- 系统错误 (0006xx) ----------
    INTERNAL_ERROR = build_error_code(ModuleCode.SYSTEM, ErrorCategory.SYSTEM, 1)
    """服务器内部错误"""
    SERVICE_UNAVAILABLE = build_error_code(ModuleCode.SYSTEM, ErrorCategory.SYSTEM, 2)
    """服务暂不可用"""
    TIMEOUT = build_error_code(ModuleCode.SYSTEM, ErrorCategory.SYSTEM, 3)
    """请求超时"""
    CONFIG_ERROR = build_error_code(ModuleCode.SYSTEM, ErrorCategory.SYSTEM, 4)
    """配置错误"""

    # ---------- 第三方错误 (0007xx) ----------
    THIRD_PARTY_ERROR = build_error_code(ModuleCode.SYSTEM, ErrorCategory.THIRD_PARTY, 1)
    """第三方服务错误"""
    UPSTREAM_TIMEOUT = build_error_code(ModuleCode.SYSTEM, ErrorCategory.THIRD_PARTY, 2)
    """上游服务超时"""
    UPSTREAM_ERROR = build_error_code(ModuleCode.SYSTEM, ErrorCategory.THIRD_PARTY, 3)
    """上游服务错误"""
    MODULE_CALL_FAILED = build_error_code(ModuleCode.SYSTEM, ErrorCategory.THIRD_PARTY, 4)
    """模块调用失败"""

    # ---------- 限流错误 (0008xx) ----------
    RATE_LIMITED = build_error_code(ModuleCode.SYSTEM, ErrorCategory.RATE_LIMIT, 1)
    """请求频率超限"""
    QUOTA_EXCEEDED = build_error_code(ModuleCode.SYSTEM, ErrorCategory.RATE_LIMIT, 2)
    """配额已用完"""

    # ---------- 数据错误 (0009xx) ----------
    DATA_ERROR = build_error_code(ModuleCode.SYSTEM, ErrorCategory.DATA, 1)
    """数据错误"""
    DATA_CONFLICT = build_error_code(ModuleCode.SYSTEM, ErrorCategory.DATA, 2)
    """数据冲突"""
    DATA_INTEGRITY_ERROR = build_error_code(ModuleCode.SYSTEM, ErrorCategory.DATA, 3)
    """数据完整性错误"""
    DATABASE_ERROR = build_error_code(ModuleCode.SYSTEM, ErrorCategory.DATA, 4)
    """数据库错误"""

    # ---------- 依赖错误 (0006xx 系统错误段，补充序号) ----------
    DEPENDENCY_ERROR = build_error_code(ModuleCode.SYSTEM, ErrorCategory.SYSTEM, 5)
    """依赖服务不可用"""


# ============================================================
# 模块级错误码范围定义
# ============================================================

def module_error_range(module_code: int | ModuleCode) -> Dict[str, int]:
    """获取指定模块的错误码范围.

    Args:
        module_code: 模块编号

    Returns:
        包含 start, end 的字典，表示该模块可用的错误码范围
    """
    m = int(module_code)
    return {
        "start": m * 10000 + 100,   # xx0100 起（跳过成功段）
        "end": m * 10000 + 999,     # 到 xx0999
    }


# ============================================================
# 旧错误码 -> 新错误码 映射（向后兼容）
# ============================================================

ERROR_CODE_LEGACY_MAP: Dict[int, int] = {
    # 旧版 5 位错误码 -> 新版 6 位错误码
    40001: ErrorCode.VALIDATION_ERROR,   # 参数验证失败
    40002: ErrorCode.CONFIG_ERROR,       # 配置错误（原 ConfigError）
    40101: ErrorCode.AUTH_FAILED,        # 认证失败
    40301: ErrorCode.PERMISSION_DENIED,  # 无权限
    40401: ErrorCode.NOT_FOUND,          # 资源不存在
    40402: ErrorCode.MODULE_NOT_FOUND,   # 模块不存在
    50000: ErrorCode.INTERNAL_ERROR,     # 内部错误
    50001: ErrorCode.INTERNAL_ERROR,     # 服务器内部错误
    50301: ErrorCode.SERVICE_UNAVAILABLE,  # 模块不可用
    50302: ErrorCode.MODULE_CALL_FAILED,   # 模块调用失败
}


def normalize_error_code(code: int) -> int:
    """将旧错误码规范化为新的 6 位错误码.

    若 code 已在新体系内（或无法识别），原样返回。
    """
    return ERROR_CODE_LEGACY_MAP.get(code, code)


# ============================================================
# 错误消息默认映射
# ============================================================

ERROR_MESSAGES: Dict[int, str] = {
    ErrorCode.SUCCESS: "操作成功",
    ErrorCode.VALIDATION_ERROR: "参数验证失败",
    ErrorCode.PARAM_MISSING: "缺少必填参数",
    ErrorCode.PARAM_INVALID: "参数格式无效",
    ErrorCode.PARAM_OUT_OF_RANGE: "参数超出范围",
    ErrorCode.PARAM_TYPE_ERROR: "参数类型错误",
    ErrorCode.AUTH_FAILED: "认证失败",
    ErrorCode.TOKEN_MISSING: "缺少认证令牌",
    ErrorCode.TOKEN_INVALID: "认证令牌无效",
    ErrorCode.TOKEN_EXPIRED: "认证令牌已过期",
    ErrorCode.API_KEY_INVALID: "API Key 无效",
    ErrorCode.PERMISSION_DENIED: "无访问权限",
    ErrorCode.ROLE_REQUIRED: "需要特定角色权限",
    ErrorCode.RESOURCE_FORBIDDEN: "资源访问被禁止",
    ErrorCode.NOT_FOUND: "资源不存在",
    ErrorCode.ENDPOINT_NOT_FOUND: "接口不存在",
    ErrorCode.MODULE_NOT_FOUND: "模块不存在",
    ErrorCode.BUSINESS_ERROR: "业务处理失败",
    ErrorCode.OPERATION_NOT_ALLOWED: "操作不允许",
    ErrorCode.ALREADY_EXISTS: "资源已存在",
    ErrorCode.INTERNAL_ERROR: "服务器内部错误",
    ErrorCode.SERVICE_UNAVAILABLE: "服务暂不可用",
    ErrorCode.TIMEOUT: "请求超时",
    ErrorCode.CONFIG_ERROR: "配置错误",
    ErrorCode.THIRD_PARTY_ERROR: "第三方服务错误",
    ErrorCode.UPSTREAM_TIMEOUT: "上游服务超时",
    ErrorCode.UPSTREAM_ERROR: "上游服务错误",
    ErrorCode.MODULE_CALL_FAILED: "模块调用失败",
    ErrorCode.RATE_LIMITED: "请求频率超限，请稍后再试",
    ErrorCode.QUOTA_EXCEEDED: "配额已用完",
    ErrorCode.DATA_ERROR: "数据错误",
    ErrorCode.DATA_CONFLICT: "数据冲突",
    ErrorCode.DATA_INTEGRITY_ERROR: "数据完整性错误",
    ErrorCode.DATABASE_ERROR: "数据库操作失败",
    ErrorCode.DEPENDENCY_ERROR: "依赖服务不可用",
}


def get_default_message(code: int) -> str:
    """获取错误码对应的默认消息."""
    return ERROR_MESSAGES.get(code, "未知错误")


def get_http_status(code: int) -> int:
    """根据错误码推断默认 HTTP 状态码."""
    if code == 0:
        return 200
    parsed = parse_error_code(code)
    cat = parsed["category"]
    try:
        return CATEGORY_HTTP_STATUS[ErrorCategory(cat)]
    except (ValueError, KeyError):
        return 500


# ============================================================
# 自定义异常基类（新版）
# ============================================================

class YunxiError(Exception):
    """云汐系统自定义异常基类（新版 6 位错误码体系）.

    所有业务层自定义异常都应继承此类，便于统一捕获和处理。

    Attributes:
        code: 6 位错误码
        message: 错误描述信息（面向用户的友好信息）
        details: 错误详情，可包含额外的上下文数据（面向开发者）
        http_status: 建议的 HTTP 响应状态码
    """

    def __init__(
        self,
        message: str | None = None,
        code: int = ErrorCode.INTERNAL_ERROR,
        details: Optional[Dict[str, Any]] = None,
        http_status: int | None = None,
    ):
        # 规范化错误码（旧码转新码）
        normalized_code = normalize_error_code(code)
        # 默认消息
        final_message = message or get_default_message(normalized_code)
        # 默认 HTTP 状态码
        final_http_status = http_status if http_status is not None else get_http_status(normalized_code)

        super().__init__(final_message)
        self.code = normalized_code
        self.message = final_message
        self.details = details or {}
        self.http_status = final_http_status

    def __str__(self) -> str:
        return f"[{self.code:06d}] {self.message}"

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(code={self.code:06d}, "
            f"message={self.message!r}, http_status={self.http_status}, "
            f"details={self.details!r})"
        )

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式（用于 API 响应）."""
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


# ============================================================
# 常用异常子类
# ============================================================

class ValidationError(YunxiError):
    """参数验证错误.

    当输入参数格式不正确、缺少必填字段、或数据校验失败时抛出。
    """

    def __init__(
        self,
        message: str | None = None,
        code: int = ErrorCode.VALIDATION_ERROR,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message=message, code=code, details=details, http_status=400)


class AuthenticationError(YunxiError):
    """认证错误.

    当用户未认证、Token 无效或已过期时抛出。
    """

    def __init__(
        self,
        message: str | None = None,
        code: int = ErrorCode.AUTH_FAILED,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message=message, code=code, details=details, http_status=401)


class AuthorizationError(YunxiError):
    """授权错误.

    当用户已认证但无权访问请求的资源时抛出。
    """

    def __init__(
        self,
        message: str | None = None,
        code: int = ErrorCode.PERMISSION_DENIED,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message=message, code=code, details=details, http_status=403)


class NotFoundError(YunxiError):
    """资源不存在错误.

    当请求的资源不存在时抛出。
    """

    def __init__(
        self,
        message: str | None = None,
        code: int = ErrorCode.NOT_FOUND,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message=message, code=code, details=details, http_status=404)


class BusinessError(YunxiError):
    """业务逻辑错误.

    业务规则校验失败时抛出。
    """

    def __init__(
        self,
        message: str | None = None,
        code: int = ErrorCode.BUSINESS_ERROR,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message=message, code=code, details=details, http_status=409)


class SystemError(YunxiError):
    """系统内部错误.

    服务器内部异常、依赖故障等不可预期的错误。
    """

    def __init__(
        self,
        message: str | None = None,
        code: int = ErrorCode.INTERNAL_ERROR,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message=message, code=code, details=details, http_status=500)


class ConfigError(YunxiError):
    """配置错误.

    当配置项缺失、格式不正确或加载失败时抛出。
    """

    def __init__(
        self,
        message: str | None = None,
        code: int = ErrorCode.CONFIG_ERROR,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message=message, code=code, details=details, http_status=500)


class ModuleNotFoundError(YunxiError):
    """模块不存在错误.

    当请求的模块未在注册中心注册、或模块标识无效时抛出。
    """

    def __init__(
        self,
        message: str | None = None,
        code: int = ErrorCode.MODULE_NOT_FOUND,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message=message, code=code, details=details, http_status=404)


class ModuleCallError(YunxiError):
    """模块调用失败错误.

    当跨模块 HTTP 调用失败、超时、或返回非预期结果时抛出。
    """

    def __init__(
        self,
        message: str | None = None,
        code: int = ErrorCode.MODULE_CALL_FAILED,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message=message, code=code, details=details, http_status=502)


class RateLimitError(YunxiError):
    """限流错误.

    请求频率超限或配额不足时抛出。
    """

    def __init__(
        self,
        message: str | None = None,
        code: int = ErrorCode.RATE_LIMITED,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message=message, code=code, details=details, http_status=429)


class ThirdPartyError(YunxiError):
    """第三方服务错误.

    第三方或上游服务异常时抛出。
    """

    def __init__(
        self,
        message: str | None = None,
        code: int = ErrorCode.THIRD_PARTY_ERROR,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message=message, code=code, details=details, http_status=502)


class DataError(YunxiError):
    """数据错误.

    数据冲突、完整性校验失败、数据库操作异常等。
    """

    def __init__(
        self,
        message: str | None = None,
        code: int = ErrorCode.DATA_ERROR,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message=message, code=code, details=details, http_status=409)


class ServiceUnavailableError(YunxiError):
    """服务不可用错误.

    当目标服务暂时不可用、过载、或正在维护时抛出。
    通常对应 HTTP 503 状态码，调用方可以稍后重试。
    """

    def __init__(
        self,
        message: str | None = None,
        code: int = ErrorCode.SERVICE_UNAVAILABLE,
        details: Optional[Dict[str, Any]] = None,
        retry_after: int | None = None,
    ):
        super().__init__(message=message, code=code, details=details, http_status=503)
        if retry_after is not None:
            self.details["retry_after"] = retry_after


class TimeoutError(YunxiError):
    """超时错误（自定义，区别于内置 TimeoutError）.

    当操作超过预设时间限制时抛出，包括网络请求超时、
    数据库查询超时、任务执行超时等。

    注意：为避免与 Python 内置 TimeoutError 混淆，
    建议通过 `from shared.core.errors import TimeoutError as YunxiTimeoutError` 导入，
    或使用别名 `YunxiTimeoutError`。
    """

    def __init__(
        self,
        message: str | None = None,
        code: int = ErrorCode.TIMEOUT,
        details: Optional[Dict[str, Any]] = None,
        timeout_seconds: float | None = None,
    ):
        super().__init__(message=message, code=code, details=details, http_status=504)
        if timeout_seconds is not None:
            self.details["timeout_seconds"] = timeout_seconds


# 兼容别名（避免与内置 TimeoutError 混淆时使用）
YunxiTimeoutError = TimeoutError


class DependencyError(YunxiError):
    """依赖服务错误.

    当外部依赖服务（数据库、缓存、消息队列、第三方 API 等）
    出现故障、不可达、或返回异常结果时抛出。

    与 ThirdPartyError 的区别：
    - DependencyError 侧重内部基础设施依赖（DB、Redis、MQ 等）
    - ThirdPartyError 侧重外部业务服务（上游模块、第三方 API 等）
    """

    def __init__(
        self,
        message: str | None = None,
        code: int = ErrorCode.DEPENDENCY_ERROR,
        details: Optional[Dict[str, Any]] = None,
        dependency: str | None = None,
    ):
        super().__init__(message=message, code=code, details=details, http_status=502)
        if dependency is not None:
            self.details["dependency"] = dependency


# ============================================================
# 异常转换工具
# ============================================================

def error_to_dict(error: Exception) -> Dict[str, Any]:
    """将异常转换为字典格式，用于 API 响应.

    对于 YunxiError 及其子类，会返回完整的 code、message、details 信息。
    对于普通 Exception，会返回通用内部错误格式。

    Args:
        error: 异常实例

    Returns:
        包含错误信息的字典
    """
    if isinstance(error, YunxiError):
        return {
            "code": error.code,
            "message": error.message,
            "details": error.details,
        }
    # 兼容旧版错误码（5 位）
    code = getattr(error, "code", None)
    if isinstance(code, int):
        normalized = normalize_error_code(code)
        message = getattr(error, "message", str(error)) or get_default_message(normalized)
        details = getattr(error, "details", {}) or {}
        return {
            "code": normalized,
            "message": message,
            "details": details,
        }
    return {
        "code": ErrorCode.INTERNAL_ERROR,
        "message": "服务器内部错误",
        "details": {"error_type": type(error).__name__},
    }


def from_exception(exc: Exception, default_code: int = ErrorCode.INTERNAL_ERROR) -> YunxiError:
    """将任意异常转换为 YunxiError.

    如果已经是 YunxiError 则原样返回，否则包装为 SystemError。
    """
    if isinstance(exc, YunxiError):
        return exc
    return SystemError(message=str(exc), code=default_code, details={
        "original_type": type(exc).__name__,
    })


# ============================================================
# 模块级错误码基类（供各模块继承使用）
# ============================================================

class ModuleErrorCode:
    """模块错误码基类.

    各模块应继承此类并定义自己的错误码常量。

    Examples:
        >>> class M8ErrorCode(ModuleErrorCode):
        ...     MODULE = ModuleCode.M8
        ...     MODULE_START_FAILED = build_error_code(ModuleCode.M8, ErrorCategory.BUSINESS, 1)
        ...     MODULE_STOP_FAILED = build_error_code(ModuleCode.M8, ErrorCategory.BUSINESS, 2)
    """
    MODULE: ModuleCode = ModuleCode.SYSTEM

    @classmethod
    def range(cls) -> Dict[str, int]:
        """获取该模块的错误码范围."""
        return module_error_range(cls.MODULE)


# ============================================================
# 快捷工厂函数
# ============================================================

def raise_validation(message: str | None = None, field: str | None = None, **kwargs: Any) -> None:
    """抛出参数验证错误的便捷函数."""
    details = dict(**kwargs)
    if field:
        details["field"] = field
    raise ValidationError(message=message, details=details)


def raise_not_found(resource: str, resource_id: str | None = None, **kwargs: Any) -> None:
    """抛出资源不存在错误的便捷函数."""
    details = {"resource": resource, **kwargs}
    if resource_id:
        details["id"] = resource_id
    message = f"{resource} 不存在"
    raise NotFoundError(message=message, details=details)


def raise_auth(message: str | None = None, **kwargs: Any) -> None:
    """抛出认证错误的便捷函数."""
    raise AuthenticationError(message=message, details=kwargs)


def raise_permission(message: str | None = None, **kwargs: Any) -> None:
    """抛出权限错误的便捷函数."""
    raise AuthorizationError(message=message, details=kwargs)
