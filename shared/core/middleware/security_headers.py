"""
云汐系统 - 安全响应头中间件

为所有 HTTP 响应添加标准安全头，防止常见的 Web 攻击：
- X-Content-Type-Options: nosniff  （防止 MIME 类型嗅探）
- X-Frame-Options: DENY  （防止点击劫持）
- X-XSS-Protection: 1; mode=block  （启用浏览器 XSS 防护）
- Content-Security-Policy: default-src 'self'  （内容安全策略）
- Strict-Transport-Security: max-age=31536000  （强制 HTTPS）
- Referrer-Policy: strict-origin-when-cross-origin  （引用来源策略）
- Cache-Control: no-store  （敏感页面禁用缓存）
- Permissions-Policy  （浏览器权限策略）

特性：
1. 可配置：每个安全头都可以单独启用/禁用
2. 模块自定义：不同模块可以覆盖默认策略
3. 路径排除：静态资源、健康检查等路径可排除
4. 生产/开发环境自动适配：开发环境下 CSP 更宽松
5. 零外部依赖：纯标准库实现

使用方式：
    from shared.core.middleware.security_headers import (
        SecurityHeadersMiddleware,
        register_security_headers,
        SecurityHeadersConfig,
    )

    # 方式一：手动注册
    app.add_middleware(SecurityHeadersMiddleware)

    # 方式二：使用注册函数（推荐）
    register_security_headers(app)

    # 方式三：自定义配置
    config = SecurityHeadersConfig(
        hsts_enabled=True,
        csp_policy="default-src 'self'; script-src 'self' 'unsafe-inline'",
    )
    register_security_headers(app, config=config)
"""

import os
import logging
from typing import Dict, List, Optional, Set
from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


# ===========================================================================
# 安全头配置
# ===========================================================================

class SecurityHeadersConfig:
    """安全头配置类

    所有安全头都可以通过配置启用/禁用或自定义值。
    支持通过环境变量或代码配置。

    环境变量：
    - SEC_HEADERS_ENABLED: 是否启用安全头（默认 true）
    - SEC_HEADERS_HSTS: 是否启用 HSTS（默认生产环境 true）
    - SEC_HEADERS_CSP: 自定义 CSP 策略
    - SEC_HEADERS_FRAME_OPTIONS: X-Frame-Options 值（默认 DENY）
    """

    def __init__(
        self,
        enabled: bool = True,
        # X-Content-Type-Options
        content_type_options: bool = True,
        # X-Frame-Options
        frame_options: bool = True,
        frame_options_value: str = "DENY",
        # X-XSS-Protection
        xss_protection: bool = True,
        # Content-Security-Policy
        csp_enabled: bool = True,
        csp_policy: Optional[str] = None,
        csp_report_only: bool = False,
        # Strict-Transport-Security
        hsts_enabled: Optional[bool] = None,
        hsts_max_age: int = 31536000,
        hsts_include_subdomains: bool = True,
        hsts_preload: bool = False,
        # Referrer-Policy
        referrer_policy: bool = True,
        referrer_policy_value: str = "strict-origin-when-cross-origin",
        # Cache-Control (敏感页面)
        cache_control: bool = True,
        cache_control_value: str = "no-store, no-cache, must-revalidate, max-age=0",
        # Permissions-Policy
        permissions_policy: bool = True,
        permissions_policy_value: str = (
            "geolocation=(), microphone=(), camera=(), "
            "payment=(), usb=(), bluetooth=(), gyroscope=(), accelerometer=()"
        ),
        # 排除路径
        exclude_paths: Optional[Set[str]] = None,
        exclude_static: bool = True,
        # 环境
        env: Optional[str] = None,
    ):
        self.enabled = enabled

        # X-Content-Type-Options
        self.content_type_options = content_type_options

        # X-Frame-Options
        self.frame_options = frame_options
        self.frame_options_value = frame_options_value.upper()
        if self.frame_options_value not in ("DENY", "SAMEORIGIN"):
            self.frame_options_value = "DENY"

        # X-XSS-Protection
        self.xss_protection = xss_protection

        # Content-Security-Policy
        self.csp_enabled = csp_enabled
        self.csp_policy = csp_policy
        self.csp_report_only = csp_report_only

        # HSTS
        self.hsts_enabled = hsts_enabled
        self.hsts_max_age = hsts_max_age
        self.hsts_include_subdomains = hsts_include_subdomains
        self.hsts_preload = hsts_preload

        # Referrer-Policy
        self.referrer_policy = referrer_policy
        self.referrer_policy_value = referrer_policy_value

        # Cache-Control
        self.cache_control = cache_control
        self.cache_control_value = cache_control_value

        # Permissions-Policy
        self.permissions_policy = permissions_policy
        self.permissions_policy_value = permissions_policy_value

        # 排除路径
        self.exclude_paths = exclude_paths or set()
        self.exclude_static = exclude_static

        # 环境检测
        if env is None:
            env = os.getenv("YUNXI_ENV", os.getenv("ENV", "development"))
        self.env = env.lower()
        self.is_production = self.env in ("production", "prod", "release")

        # HSTS 默认值：生产环境启用，开发环境禁用
        if self.hsts_enabled is None:
            self.hsts_enabled = self.is_production

        # 默认 CSP 策略
        if self.csp_policy is None:
            if self.is_production:
                self.csp_policy = (
                    "default-src 'self'; "
                    "script-src 'self'; "
                    "style-src 'self' 'unsafe-inline'; "
                    "img-src 'self' data:; "
                    "font-src 'self'; "
                    "connect-src 'self'; "
                    "frame-ancestors 'none'; "
                    "base-uri 'self'; "
                    "form-action 'self'"
                )
            else:
                # 开发环境更宽松，便于调试
                self.csp_policy = (
                    "default-src 'self'; "
                    "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
                    "style-src 'self' 'unsafe-inline'; "
                    "img-src 'self' data:; "
                    "font-src 'self'; "
                    "connect-src 'self' ws: wss:; "
                    "frame-ancestors 'self'; "
                    "base-uri 'self'; "
                    "form-action 'self'"
                )

    def _build_hsts_value(self) -> str:
        """构建 HSTS 头值"""
        parts = [f"max-age={self.hsts_max_age}"]
        if self.hsts_include_subdomains:
            parts.append("includeSubDomains")
        if self.hsts_preload:
            parts.append("preload")
        return "; ".join(parts)

    def get_headers(self, request_path: str = "") -> Dict[str, str]:
        """获取要添加的安全头字典

        Args:
            request_path: 请求路径（用于判断是否为静态资源）

        Returns:
            安全头字典 {header_name: header_value}
        """
        if not self.enabled:
            return {}

        headers: Dict[str, str] = {}

        # 1. X-Content-Type-Options
        if self.content_type_options:
            headers["X-Content-Type-Options"] = "nosniff"

        # 2. X-Frame-Options
        if self.frame_options:
            headers["X-Frame-Options"] = self.frame_options_value

        # 3. X-XSS-Protection
        if self.xss_protection:
            headers["X-XSS-Protection"] = "1; mode=block"

        # 4. Content-Security-Policy
        if self.csp_enabled and self.csp_policy:
            if self.csp_report_only:
                headers["Content-Security-Policy-Report-Only"] = self.csp_policy
            else:
                headers["Content-Security-Policy"] = self.csp_policy

        # 5. Strict-Transport-Security (仅 HTTPS / 生产环境)
        if self.hsts_enabled:
            headers["Strict-Transport-Security"] = self._build_hsts_value()

        # 6. Referrer-Policy
        if self.referrer_policy:
            headers["Referrer-Policy"] = self.referrer_policy_value

        # 7. Cache-Control (敏感页面，不包含静态资源)
        if self.cache_control and not self._is_static_path(request_path):
            headers["Cache-Control"] = self.cache_control_value
            headers["Pragma"] = "no-cache"
            headers["Expires"] = "0"

        # 8. Permissions-Policy
        if self.permissions_policy:
            headers["Permissions-Policy"] = self.permissions_policy_value

        return headers

    def _is_static_path(self, path: str) -> bool:
        """判断路径是否为静态资源"""
        if not self.exclude_static:
            return False
        static_extensions = (
            ".js", ".css", ".png", ".jpg", ".jpeg", ".gif",
            ".svg", ".ico", ".woff", ".woff2", ".ttf", ".eot",
            ".mp4", ".webm", ".mp3", ".wav", ".flac",
            ".map", ".txt",
        )
        return path.lower().endswith(static_extensions)

    def is_excluded(self, path: str) -> bool:
        """判断路径是否在排除列表中"""
        if path in self.exclude_paths:
            return True
        # 健康检查路径默认排除
        health_paths = {
            "/health", "/healthz", "/ready", "/status",
            "/m8/health", "/m8/metrics",
            "/api/waf/health",
        }
        if path in health_paths:
            return True
        return False


# ===========================================================================
# 默认配置（从环境变量加载）
# ===========================================================================

def _load_default_config() -> SecurityHeadersConfig:
    """从环境变量加载默认配置"""
    enabled = os.getenv("SEC_HEADERS_ENABLED", "true").lower() not in ("false", "0", "no", "off")

    hsts_env = os.getenv("SEC_HEADERS_HSTS")
    hsts_enabled = None
    if hsts_env:
        hsts_enabled = hsts_env.lower() in ("true", "1", "yes", "on")

    csp_policy = os.getenv("SEC_HEADERS_CSP") or None

    frame_options_value = os.getenv("SEC_HEADERS_FRAME_OPTIONS", "DENY")

    referrer_value = os.getenv(
        "SEC_HEADERS_REFERRER_POLICY",
        "strict-origin-when-cross-origin"
    )

    exclude_raw = os.getenv("SEC_HEADERS_EXCLUDE_PATHS", "")
    exclude_paths = set(p.strip() for p in exclude_raw.split(",") if p.strip())

    return SecurityHeadersConfig(
        enabled=enabled,
        hsts_enabled=hsts_enabled,
        csp_policy=csp_policy,
        frame_options_value=frame_options_value,
        referrer_policy_value=referrer_value,
        exclude_paths=exclude_paths,
    )


DEFAULT_CONFIG = _load_default_config()


# ===========================================================================
# 安全头中间件
# ===========================================================================

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """安全响应头中间件

    为所有 HTTP 响应添加标准安全头，防止常见的 Web 攻击。

    使用方式：
        app.add_middleware(SecurityHeadersMiddleware, config=my_config)
    """

    def __init__(self, app, config: Optional[SecurityHeadersConfig] = None, **kwargs):
        """初始化安全头中间件

        Args:
            app: ASGI 应用
            config: 安全头配置，为 None 时使用默认配置
            **kwargs: 额外配置参数，传递给 SecurityHeadersConfig
        """
        super().__init__(app)
        if config is not None:
            self.config = config
        elif kwargs:
            self.config = SecurityHeadersConfig(**kwargs)
        else:
            self.config = DEFAULT_CONFIG

        if self.config.enabled:
            headers_count = len(self.config.get_headers("/api/test"))
            logger.info(
                "[SecurityHeaders] 安全头中间件已初始化 - "
                "环境: %s, 启用头: %d 个",
                self.config.env,
                headers_count,
            )
        else:
            logger.info("[SecurityHeaders] 安全头中间件已禁用")

    async def dispatch(self, request: Request, call_next):
        """处理请求，添加安全头到响应"""
        # 检查是否排除
        path = request.url.path
        if self.config.is_excluded(path):
            return await call_next(request)

        # 处理请求
        response = await call_next(request)

        # 添加安全头
        security_headers = self.config.get_headers(path)
        for header_name, header_value in security_headers.items():
            # 不覆盖已有的头（除非是强制安全头）
            if header_name not in response.headers:
                response.headers[header_name] = header_value

        return response


# ===========================================================================
# 注册函数
# ===========================================================================

_security_middleware_instance: Optional[SecurityHeadersMiddleware] = None


def register_security_headers(
    app,
    config: Optional[SecurityHeadersConfig] = None,
    **kwargs,
) -> SecurityHeadersMiddleware:
    """注册安全头中间件到 FastAPI 应用

    这是推荐的注册方式，会返回中间件实例以便后续查询状态。

    Args:
        app: FastAPI 应用实例
        config: 安全头配置，为 None 时使用默认配置
        **kwargs: 额外配置参数

    Returns:
        SecurityHeadersMiddleware 实例
    """
    global _security_middleware_instance

    middleware = SecurityHeadersMiddleware(app, config=config, **kwargs)
    app.add_middleware(SecurityHeadersMiddleware, config=config, **kwargs)
    _security_middleware_instance = middleware

    return middleware


def get_security_headers_middleware() -> Optional[SecurityHeadersMiddleware]:
    """获取安全头中间件单例实例"""
    return _security_middleware_instance


# ===========================================================================
# 便捷函数：CSP 策略构建器
# ===========================================================================

class CSPBuilder:
    """CSP 策略构建器

    用于安全地构建 Content-Security-Policy 头的值。

    使用方式：
        builder = CSPBuilder()
        builder.default_src("'self'")
        builder.script_src("'self'", "https://cdn.example.com")
        builder.img_src("'self'", "data:")
        policy = builder.build()
    """

    def __init__(self):
        self._directives: Dict[str, List[str]] = {}

    def _add_directive(self, directive: str, *sources: str):
        """添加指令源"""
        if directive not in self._directives:
            self._directives[directive] = []
        for src in sources:
            if src not in self._directives[directive]:
                self._directives[directive].append(src)

    def default_src(self, *sources: str) -> "CSPBuilder":
        self._add_directive("default-src", *sources)
        return self

    def script_src(self, *sources: str) -> "CSPBuilder":
        self._add_directive("script-src", *sources)
        return self

    def style_src(self, *sources: str) -> "CSPBuilder":
        self._add_directive("style-src", *sources)
        return self

    def img_src(self, *sources: str) -> "CSPBuilder":
        self._add_directive("img-src", *sources)
        return self

    def font_src(self, *sources: str) -> "CSPBuilder":
        self._add_directive("font-src", *sources)
        return self

    def connect_src(self, *sources: str) -> "CSPBuilder":
        self._add_directive("connect-src", *sources)
        return self

    def frame_src(self, *sources: str) -> "CSPBuilder":
        self._add_directive("frame-src", *sources)
        return self

    def frame_ancestors(self, *sources: str) -> "CSPBuilder":
        self._add_directive("frame-ancestors", *sources)
        return self

    def object_src(self, *sources: str) -> "CSPBuilder":
        self._add_directive("object-src", *sources)
        return self

    def base_uri(self, *sources: str) -> "CSPBuilder":
        self._add_directive("base-uri", *sources)
        return self

    def form_action(self, *sources: str) -> "CSPBuilder":
        self._add_directive("form-action", *sources)
        return self

    def upgrade_insecure_requests(self) -> "CSPBuilder":
        self._add_directive("upgrade-insecure-requests")
        return self

    def report_uri(self, uri: str) -> "CSPBuilder":
        self._add_directive("report-uri", uri)
        return self

    def build(self) -> str:
        """构建 CSP 策略字符串"""
        parts = []
        for directive, sources in self._directives.items():
            if sources:
                parts.append(f"{directive} {' '.join(sources)}")
            else:
                parts.append(directive)
        return "; ".join(parts)


# ===========================================================================
# 模块导出
# ===========================================================================

__all__ = [
    "SecurityHeadersConfig",
    "SecurityHeadersMiddleware",
    "register_security_headers",
    "get_security_headers_middleware",
    "CSPBuilder",
    "DEFAULT_CONFIG",
]
