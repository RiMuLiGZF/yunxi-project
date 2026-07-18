"""M11 MCP Bus - 安全中间件.

提供 HTTP 层面的安全防护：
- 请求 ID 注入
- 安全响应头（CSP, X-Frame-Options, X-Content-Type-Options 等）
- 请求大小限制
- 方法白名单
- IP 黑白名单

作为 FastAPI 中间件（Middleware）使用，在请求进入路由前
和响应返回客户端前进行安全处理。
"""

from __future__ import annotations

import secrets
import time
from fnmatch import fnmatch
from typing import List, Optional, Set

import structlog
from fastapi import Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = structlog.get_logger(__name__)


# ============================================================
# 默认配置
# ============================================================

# 默认安全响应头
DEFAULT_SECURITY_HEADERS: dict = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "font-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    ),
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Permissions-Policy": (
        "camera=(), microphone=(), geolocation=(), "
        "interest-cohort=()"
    ),
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
}

# 允许的 HTTP 方法
DEFAULT_ALLOWED_METHODS: Set[str] = {
    "GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"
}

# 默认请求大小限制（10MB）
DEFAULT_MAX_REQUEST_SIZE: int = 10 * 1024 * 1024


# ============================================================
# 安全中间件配置
# ============================================================

class SecurityMiddlewareConfig:
    """安全中间件配置."""

    def __init__(
        self,
        security_headers_enabled: bool = True,
        security_headers: Optional[dict] = None,
        max_request_size: int = DEFAULT_MAX_REQUEST_SIZE,
        allowed_methods: Optional[Set[str]] = None,
        ip_whitelist: Optional[List[str]] = None,
        ip_blacklist: Optional[List[str]] = None,
        request_id_header: str = "X-Request-ID",
        request_id_enabled: bool = True,
    ) -> None:
        """初始化安全中间件配置.

        Args:
            security_headers_enabled: 是否启用安全响应头
            security_headers: 自定义安全响应头
            max_request_size: 最大请求体大小（字节）
            allowed_methods: 允许的 HTTP 方法集合
            ip_whitelist: IP 白名单（支持通配符 *）
            ip_blacklist: IP 黑名单（支持通配符 *）
            request_id_header: 请求 ID 头名称
            request_id_enabled: 是否注入请求 ID
        """
        self.security_headers_enabled = security_headers_enabled
        self.security_headers = security_headers or dict(DEFAULT_SECURITY_HEADERS)
        self.max_request_size = max_request_size
        self.allowed_methods = allowed_methods or set(DEFAULT_ALLOWED_METHODS)
        self.ip_whitelist = ip_whitelist or []
        self.ip_blacklist = ip_blacklist or []
        self.request_id_header = request_id_header
        self.request_id_enabled = request_id_enabled


# ============================================================
# 安全中间件
# ============================================================

class SecurityMiddleware(BaseHTTPMiddleware):
    """安全中间件.

    提供以下安全功能：
    1. 请求 ID 注入 - 为每个请求生成唯一 ID，便于追踪
    2. 安全响应头 - 设置 CSP、X-Frame-Options 等安全头
    3. 请求大小限制 - 防止大请求攻击
    4. 方法白名单 - 只允许指定的 HTTP 方法
    5. IP 黑白名单 - 基于 IP 地址的访问控制

    使用方式（FastAPI）：
        from src.middleware.security_middleware import SecurityMiddleware
        app.add_middleware(SecurityMiddleware, config=SecurityMiddlewareConfig())
    """

    def __init__(
        self,
        app: ASGIApp,
        config: Optional[SecurityMiddlewareConfig] = None,
    ) -> None:
        """初始化安全中间件.

        Args:
            app: ASGI 应用
            config: 中间件配置
        """
        super().__init__(app)
        self._config = config or SecurityMiddlewareConfig()

    async def dispatch(self, request: Request, call_next) -> Response:
        """处理请求的中间件方法.

        Args:
            request: 请求对象
            call_next: 下一个处理函数

        Returns:
            响应对象
        """
        start_time = time.time()

        # 1. 请求 ID 注入
        request_id = self._inject_request_id(request)

        # 2. IP 地址检查
        client_ip = self._get_client_ip(request)
        ip_check = self._check_ip_whitelist(client_ip)
        if not ip_check:
            logger.warning(
                "security.ip_whitelist_blocked",
                ip=client_ip,
                path=request.url.path,
                request_id=request_id,
            )
            return Response(
                content="Forbidden: IP not in whitelist",
                status_code=status.HTTP_403_FORBIDDEN,
                headers=self._get_security_headers(request_id),
            )

        ip_check_black = self._check_ip_blacklist(client_ip)
        if not ip_check_black:
            logger.warning(
                "security.ip_blacklist_blocked",
                ip=client_ip,
                path=request.url.path,
                request_id=request_id,
            )
            return Response(
                content="Forbidden: IP is blacklisted",
                status_code=status.HTTP_403_FORBIDDEN,
                headers=self._get_security_headers(request_id),
            )

        # 3. HTTP 方法检查
        if request.method not in self._config.allowed_methods:
            logger.warning(
                "security.method_not_allowed",
                method=request.method,
                path=request.url.path,
                ip=client_ip,
                request_id=request_id,
            )
            return Response(
                content="Method Not Allowed",
                status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
                headers=self._get_security_headers(request_id),
            )

        # 4. 请求大小检查（Content-Length 方式）
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                size = int(content_length)
                if size > self._config.max_request_size:
                    logger.warning(
                        "security.request_too_large",
                        size=size,
                        max_size=self._config.max_request_size,
                        path=request.url.path,
                        ip=client_ip,
                        request_id=request_id,
                    )
                    return Response(
                        content="Payload Too Large",
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        headers=self._get_security_headers(request_id),
                    )
            except (ValueError, TypeError):
                pass  # 无效的 Content-Length，忽略

        # 5. 处理请求
        try:
            response = await call_next(request)
        except Exception as e:
            logger.error(
                "security.request_error",
                error=str(e),
                path=request.url.path,
                request_id=request_id,
                exc_info=True,
            )
            response = Response(
                content="Internal Server Error",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                headers=self._get_security_headers(request_id),
            )

        # 6. 添加安全响应头
        if self._config.security_headers_enabled:
            security_headers = self._get_security_headers(request_id)
            for key, value in security_headers.items():
                if key.lower() not in [h.lower() for h in response.headers]:
                    response.headers[key] = value

        # 7. 添加请求耗时头
        duration_ms = int((time.time() - start_time) * 1000)
        response.headers["X-Response-Time"] = str(duration_ms)

        return response

    # --------------------------------------------------------
    # 内部方法
    # --------------------------------------------------------

    def _inject_request_id(self, request: Request) -> str:
        """注入请求 ID.

        如果请求中已有请求 ID 则使用，否则生成新的。

        Args:
            request: 请求对象

        Returns:
            请求 ID 字符串
        """
        if not self._config.request_id_enabled:
            return ""

        # 从请求头获取（如果有）
        header_name = self._config.request_id_header
        existing_id = request.headers.get(header_name)
        if existing_id and len(existing_id) <= 128:
            return existing_id

        # 生成新的请求 ID
        return secrets.token_hex(16)

    def _get_security_headers(self, request_id: str = "") -> dict:
        """获取安全响应头.

        Args:
            request_id: 请求 ID

        Returns:
            安全响应头字典
        """
        headers = dict(self._config.security_headers)

        if request_id and self._config.request_id_enabled:
            headers[self._config.request_id_header] = request_id

        return headers

    @staticmethod
    def _get_client_ip(request: Request) -> str:
        """获取客户端真实 IP.

        优先从 X-Forwarded-For 获取，其次从 X-Real-IP 获取，
        最后使用连接地址。

        Args:
            request: 请求对象

        Returns:
            客户端 IP 地址
        """
        # X-Forwarded-For: client, proxy1, proxy2, ...
        xff = request.headers.get("x-forwarded-for")
        if xff:
            # 取第一个 IP（最原始的客户端 IP）
            first_ip = xff.split(",")[0].strip()
            if first_ip:
                return first_ip

        # X-Real-IP
        xri = request.headers.get("x-real-ip")
        if xri:
            return xri.strip()

        # 连接地址
        if request.client:
            return request.client.host

        return "unknown"

    def _check_ip_whitelist(self, ip: str) -> bool:
        """检查 IP 是否在白名单中.

        如果白名单为空，则所有 IP 都允许。

        Args:
            ip: IP 地址

        Returns:
            True 表示允许
        """
        if not self._config.ip_whitelist:
            return True  # 白名单为空，不限制

        for pattern in self._config.ip_whitelist:
            if fnmatch(ip, pattern):
                return True

        return False

    def _check_ip_blacklist(self, ip: str) -> bool:
        """检查 IP 是否在黑名单中.

        Args:
            ip: IP 地址

        Returns:
            True 表示允许（不在黑名单中），False 表示被拦截
        """
        if not self._config.ip_blacklist:
            return True  # 黑名单为空，不限制

        for pattern in self._config.ip_blacklist:
            if fnmatch(ip, pattern):
                return False  # 在黑名单中，拒绝

        return True


# ============================================================
# 便捷函数：从沙箱配置创建中间件配置
# ============================================================

def create_security_middleware_config_from_sandbox(
    sandbox_config,
) -> SecurityMiddlewareConfig:
    """从沙箱配置创建安全中间件配置.

    Args:
        sandbox_config: SandboxConfig 实例

    Returns:
        SecurityMiddlewareConfig 实例
    """
    return SecurityMiddlewareConfig(
        security_headers_enabled=getattr(
            sandbox_config, "security_headers_enabled", True
        ),
        ip_whitelist=getattr(sandbox_config, "ip_whitelist", []),
        ip_blacklist=getattr(sandbox_config, "ip_blacklist", []),
    )


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "SecurityMiddleware",
    "SecurityMiddlewareConfig",
    "DEFAULT_SECURITY_HEADERS",
    "DEFAULT_ALLOWED_METHODS",
    "DEFAULT_MAX_REQUEST_SIZE",
    "create_security_middleware_config_from_sandbox",
]
