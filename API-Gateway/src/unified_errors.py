"""
API 网关 - 模块级错误码定义（统一 6 位错误码体系）

遵循云汐系统统一 6 位错误码规范：XX YY ZZ
  - XX = 00 (模块编号，系统通用/网关复用 00 前缀)
  - YY = 错误类别
  - ZZ = 序号

网关特有错误码使用 00 前缀的扩展段（0010-0099 业务段），
或按模块编号约定：网关作为系统接入层，使用 00 模块编号。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

# 尝试从 shared.core.errors 导入统一错误框架
try:
    _current = Path(__file__).resolve()
    for _ in range(10):
        _current = _current.parent
        if (_current / "shared" / "core" / "errors.py").exists():
            if str(_current) not in sys.path:
                sys.path.insert(0, str(_current))
            break
    from shared.core.errors import (
        ModuleCode,
        ErrorCategory,
        build_error_code,
        ModuleErrorCode,
        YunxiError,
        ValidationError,
        AuthenticationError,
        AuthorizationError,
        NotFoundError,
        BusinessError,
        SystemError,
        ConfigError,
        RateLimitError,
        ThirdPartyError,
        ErrorCode,
    )
    _UNIFIED_ERRORS_AVAILABLE = True
except ImportError:
    _UNIFIED_ERRORS_AVAILABLE = False
    ModuleCode = None  # type: ignore
    ErrorCategory = None  # type: ignore
    ModuleErrorCode = object  # type: ignore
    YunxiError = Exception  # type: ignore
    ValidationError = ValueError  # type: ignore
    AuthenticationError = Exception  # type: ignore
    AuthorizationError = PermissionError  # type: ignore
    NotFoundError = Exception  # type: ignore
    BusinessError = Exception  # type: ignore
    SystemError = Exception  # type: ignore
    ConfigError = Exception  # type: ignore
    RateLimitError = Exception  # type: ignore
    ThirdPartyError = Exception  # type: ignore
    ErrorCode = None  # type: ignore

    def build_error_code(module, category, seq):  # type: ignore
        return int(module) * 10000 + int(category) * 100 + seq


if _UNIFIED_ERRORS_AVAILABLE:

    class GatewayErrorCode(ModuleErrorCode):
        """API 网关错误码常量.

        模块编号: 00 (系统通用/网关层)
        网关特有错误码范围: 001000 - 001099 (扩展段)

        注：通用错误码使用 shared.core.errors.ErrorCode，
        网关特有错误码在此处定义。
        """
        MODULE = ModuleCode.SYSTEM

        # ---------- 网关特有参数错误 (000110-000119) ----------
        INVALID_ROUTE_KEY = build_error_code(ModuleCode.SYSTEM, ErrorCategory.VALIDATION, 10)
        """无效的路由标识"""
        INVALID_UPSTREAM_URL = build_error_code(ModuleCode.SYSTEM, ErrorCategory.VALIDATION, 11)
        """无效的上游服务地址"""
        INVALID_RATE_LIMIT_CONFIG = build_error_code(ModuleCode.SYSTEM, ErrorCategory.VALIDATION, 12)
        """无效的限流配置"""

        # ---------- 网关特有认证错误 (000210-000219) ----------
        GATEWAY_AUTH_FAILED = build_error_code(ModuleCode.SYSTEM, ErrorCategory.AUTHENTICATION, 10)
        """网关认证失败"""
        API_KEY_MISSING = build_error_code(ModuleCode.SYSTEM, ErrorCategory.AUTHENTICATION, 11)
        """缺少 API Key"""
        API_KEY_INVALID = build_error_code(ModuleCode.SYSTEM, ErrorCategory.AUTHENTICATION, 12)
        """API Key 无效"""

        # ---------- 网关特有业务错误 (000510-000529) ----------
        ROUTE_DISABLED = build_error_code(ModuleCode.SYSTEM, ErrorCategory.BUSINESS, 10)
        """路由已禁用"""
        UPSTREAM_UNAVAILABLE = build_error_code(ModuleCode.SYSTEM, ErrorCategory.BUSINESS, 11)
        """上游服务不可用"""
        CIRCUIT_BREAKER_OPEN = build_error_code(ModuleCode.SYSTEM, ErrorCategory.BUSINESS, 12)
        """熔断器已打开"""
        PROXY_TIMEOUT = build_error_code(ModuleCode.SYSTEM, ErrorCategory.BUSINESS, 13)
        """代理请求超时"""
        ROUTE_RELOAD_FAILED = build_error_code(ModuleCode.SYSTEM, ErrorCategory.BUSINESS, 14)
        """路由配置重载失败"""

        # ---------- 网关特有限流错误 (000810-000819) ----------
        GATEWAY_RATE_LIMITED = build_error_code(ModuleCode.SYSTEM, ErrorCategory.RATE_LIMIT, 10)
        """网关级限流触发"""
        MODULE_RATE_LIMITED = build_error_code(ModuleCode.SYSTEM, ErrorCategory.RATE_LIMIT, 11)
        """模块级限流触发"""
        IP_RATE_LIMITED = build_error_code(ModuleCode.SYSTEM, ErrorCategory.RATE_LIMIT, 12)
        """IP 级限流触发"""

    # 便捷别名
    GW_ERR = GatewayErrorCode

    # ---------- 网关特有异常类 ----------

    class GatewayError(YunxiError):
        """网关通用错误."""
        pass

    class RouteDisabledError(GatewayError):
        """路由已禁用错误."""

        def __init__(self, route_key: str = "", message: str | None = None):
            details = {"route_key": route_key} if route_key else {}
            super().__init__(
                message=message or f"路由 '{route_key}' 已禁用",
                code=GatewayErrorCode.ROUTE_DISABLED,
                details=details,
                http_status=503,
            )

    class CircuitBreakerOpenError(GatewayError):
        """熔断器打开错误."""

        def __init__(self, route_key: str = "", message: str | None = None):
            details = {"route_key": route_key} if route_key else {}
            super().__init__(
                message=message or f"模块 '{route_key}' 熔断器已打开，请求被拒绝",
                code=GatewayErrorCode.CIRCUIT_BREAKER_OPEN,
                details=details,
                http_status=503,
            )

    class ProxyTimeoutError(GatewayError):
        """代理超时错误."""

        def __init__(self, route_key: str = "", message: str | None = None):
            details = {"route_key": route_key} if route_key else {}
            super().__init__(
                message=message or f"上游服务 '{route_key}' 请求超时",
                code=GatewayErrorCode.PROXY_TIMEOUT,
                details=details,
                http_status=504,
            )

    class UpstreamUnavailableError(GatewayError):
        """上游服务不可用错误."""

        def __init__(self, route_key: str = "", message: str | None = None):
            details = {"route_key": route_key} if route_key else {}
            super().__init__(
                message=message or f"上游服务 '{route_key}' 不可用",
                code=GatewayErrorCode.UPSTREAM_UNAVAILABLE,
                details=details,
                http_status=502,
            )

    class GatewayRateLimitError(GatewayError):
        """网关限流错误."""

        def __init__(self, limit_type: str = "gateway", message: str | None = None):
            details = {"limit_type": limit_type}
            super().__init__(
                message=message or "请求频率超限，请稍后再试",
                code=GatewayErrorCode.GATEWAY_RATE_LIMITED,
                details=details,
                http_status=429,
            )

else:
    # 回退模式
    class GatewayErrorCode:
        """网关错误码常量（回退模式）"""
        INVALID_ROUTE_KEY = 110
        INVALID_UPSTREAM_URL = 111
        INVALID_RATE_LIMIT_CONFIG = 112
        GATEWAY_AUTH_FAILED = 210
        API_KEY_MISSING = 211
        API_KEY_INVALID = 212
        ROUTE_DISABLED = 510
        UPSTREAM_UNAVAILABLE = 511
        CIRCUIT_BREAKER_OPEN = 512
        PROXY_TIMEOUT = 513
        ROUTE_RELOAD_FAILED = 514
        GATEWAY_RATE_LIMITED = 810
        MODULE_RATE_LIMITED = 811
        IP_RATE_LIMITED = 812

    GW_ERR = GatewayErrorCode
    GatewayError = Exception
    RouteDisabledError = Exception
    CircuitBreakerOpenError = Exception
    ProxyTimeoutError = Exception
    UpstreamUnavailableError = Exception
    GatewayRateLimitError = Exception


__all__ = [
    "GatewayErrorCode",
    "GW_ERR",
    "GatewayError",
    "RouteDisabledError",
    "CircuitBreakerOpenError",
    "ProxyTimeoutError",
    "UpstreamUnavailableError",
    "GatewayRateLimitError",
    "_UNIFIED_ERRORS_AVAILABLE",
    # 同时导出基类，方便网关模块直接使用
    "YunxiError",
    "ValidationError",
    "AuthenticationError",
    "AuthorizationError",
    "NotFoundError",
    "BusinessError",
    "SystemError",
    "ConfigError",
    "RateLimitError",
    "ThirdPartyError",
    "ErrorCode",
]
