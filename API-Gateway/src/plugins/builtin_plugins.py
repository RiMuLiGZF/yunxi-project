"""
云汐 API 网关 - 内置插件

包含：
- LoggingPlugin: 日志增强插件（详细请求/响应日志）
- MetricsPlugin: 指标采集插件（Prometheus 格式指标）
- RequestIdPlugin: 请求 ID 插件（生成和传递 request_id）
- CorsPlugin: CORS 插件（跨域处理）
- SecurityHeadersPlugin: 安全头插件（安全响应头）
"""
import uuid
import time
import logging
from typing import Dict, Any, Optional

from .plugin_base import BasePlugin, PluginContext


logger = logging.getLogger("yunxi-gateway.plugins")


# ===================================================================
# 日志增强插件
# ===================================================================

class LoggingPlugin(BasePlugin):
    """日志增强插件

    记录详细的请求/响应日志，包括：
    - 请求方法、路径、状态码、延迟
    - 请求头/响应头（可配置）
    - 请求体大小、响应体大小
    - 用户信息
    """

    name = "logging"
    description = "详细请求/响应日志插件"
    version = "1.0.0"
    priority = 10

    def __init__(self, log_headers: bool = False, log_body: bool = False,
                 slow_request_threshold_ms: float = 1000.0):
        super().__init__()
        self.log_headers = log_headers
        self.log_body = log_body
        self.slow_request_threshold_ms = slow_request_threshold_ms
        self._slow_request_count = 0

    async def pre_request(self, ctx: PluginContext) -> Optional[PluginContext]:
        await super().pre_request(ctx)
        # 记录请求开始
        logger.info(
            f"[REQ] {ctx.request_method} {ctx.request_path} "
            f"ip={ctx.client_ip} request_id={ctx.request_id}"
        )
        if self.log_headers:
            logger.debug(f"[REQ-HEADERS] {ctx.request_headers}")
        return ctx

    async def post_response(self, ctx: PluginContext) -> PluginContext:
        await super().post_response(ctx)

        body_size = len(ctx.response_body) if ctx.response_body else 0
        is_slow = ctx.latency_ms > self.slow_request_threshold_ms

        if is_slow:
            self._slow_request_count += 1
            logger.warning(
                f"[SLOW-RESP] {ctx.request_method} {ctx.request_path} "
                f"status={ctx.response_status} latency={ctx.latency_ms:.2f}ms "
                f"size={body_size}B request_id={ctx.request_id}"
            )
        else:
            logger.info(
                f"[RESP] {ctx.request_method} {ctx.request_path} "
                f"status={ctx.response_status} latency={ctx.latency_ms:.2f}ms "
                f"size={body_size}B request_id={ctx.request_id}"
            )

        if self.log_headers:
            logger.debug(f"[RESP-HEADERS] {ctx.response_headers}")

        return ctx

    async def on_error(self, ctx: PluginContext) -> PluginContext:
        await super().on_error(ctx)
        logger.error(
            f"[ERROR] {ctx.request_method} {ctx.request_path} "
            f"error={ctx.error_message} request_id={ctx.request_id}",
            exc_info=ctx.error,
        )
        return ctx

    def get_stats(self) -> Dict[str, Any]:
        stats = super().get_stats()
        stats["slow_request_count"] = self._slow_request_count
        return stats


# ===================================================================
# 指标采集插件
# ===================================================================

class MetricsPlugin(BasePlugin):
    """指标采集插件

    采集 Prometheus 格式的指标：
    - 请求总数（按方法、路径、状态码）
    - 请求延迟（直方图）
    - 活跃请求数
    - 错误率
    """

    name = "metrics"
    description = "Prometheus 格式指标采集插件"
    version = "1.0.0"
    priority = 20

    def __init__(self):
        super().__init__()
        self._total_requests = 0
        self._active_requests = 0
        self._status_counts: Dict[str, int] = {}
        self._method_counts: Dict[str, int] = {}
        self._path_counts: Dict[str, int] = {}
        self._total_latency_ms = 0.0
        self._max_latency_ms = 0.0
        self._min_latency_ms = float('inf')
        self._error_count = 0
        self._bucket_boundaries = [5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000]
        self._latency_buckets: Dict[float, int] = {b: 0 for b in self._bucket_boundaries}
        self._latency_buckets[float('inf')] = 0

    async def pre_request(self, ctx: PluginContext) -> Optional[PluginContext]:
        await super().pre_request(ctx)
        self._active_requests += 1
        return ctx

    async def post_response(self, ctx: PluginContext) -> PluginContext:
        await super().post_response(ctx)

        self._total_requests += 1
        self._active_requests = max(0, self._active_requests - 1)

        # 状态码统计
        status_key = str(ctx.response_status)
        self._status_counts[status_key] = self._status_counts.get(status_key, 0) + 1

        # 方法统计
        method_key = ctx.request_method.upper()
        self._method_counts[method_key] = self._method_counts.get(method_key, 0) + 1

        # 路径统计（按路由分组）
        path_key = ctx.route_key or "unknown"
        self._path_counts[path_key] = self._path_counts.get(path_key, 0) + 1

        # 延迟统计
        latency = ctx.latency_ms
        self._total_latency_ms += latency
        self._max_latency_ms = max(self._max_latency_ms, latency)
        self._min_latency_ms = min(self._min_latency_ms, latency)

        # 延迟直方图
        for bound in self._bucket_boundaries:
            if latency <= bound:
                self._latency_buckets[bound] += 1
        self._latency_buckets[float('inf')] += 1

        # 错误统计（4xx, 5xx）
        if ctx.response_status >= 400:
            self._error_count += 1

        return ctx

    async def on_error(self, ctx: PluginContext) -> PluginContext:
        await super().on_error(ctx)
        self._active_requests = max(0, self._active_requests - 1)
        self._error_count += 1
        return ctx

    def get_stats(self) -> Dict[str, Any]:
        stats = super().get_stats()
        avg_latency = (
            self._total_latency_ms / self._total_requests
            if self._total_requests > 0 else 0
        )
        error_rate = (
            self._error_count / self._total_requests * 100
            if self._total_requests > 0 else 0
        )
        stats.update({
            "total_requests": self._total_requests,
            "active_requests": self._active_requests,
            "error_count": self._error_count,
            "error_rate_percent": round(error_rate, 2),
            "avg_latency_ms": round(avg_latency, 2),
            "min_latency_ms": round(self._min_latency_ms if self._min_latency_ms != float('inf') else 0, 2),
            "max_latency_ms": round(self._max_latency_ms, 2),
            "status_counts": self._status_counts,
            "method_counts": self._method_counts,
            "path_counts": self._path_counts,
        })
        return stats

    def get_prometheus_metrics(self) -> str:
        """生成 Prometheus 格式的指标"""
        lines = []

        # 请求总数
        lines.append("# HELP gateway_requests_total Total number of requests")
        lines.append("# TYPE gateway_requests_total counter")
        lines.append(f"gateway_requests_total {self._total_requests}")

        # 活跃请求数
        lines.append("# HELP gateway_active_requests Number of active requests")
        lines.append("# TYPE gateway_active_requests gauge")
        lines.append(f"gateway_active_requests {self._active_requests}")

        # 错误率
        lines.append("# HELP gateway_errors_total Total number of errors")
        lines.append("# TYPE gateway_errors_total counter")
        lines.append(f"gateway_errors_total {self._error_count}")

        # 按状态码
        for status, count in sorted(self._status_counts.items()):
            lines.append(
                f'gateway_requests_by_status{{status="{status}"}} {count}'
            )

        # 按方法
        for method, count in sorted(self._method_counts.items()):
            lines.append(
                f'gateway_requests_by_method{{method="{method}"}} {count}'
            )

        # 延迟直方图
        lines.append("# HELP gateway_request_duration_seconds Request duration in seconds")
        lines.append("# TYPE gateway_request_duration_seconds histogram")
        cumulative = 0
        for bound in self._bucket_boundaries:
            cumulative += self._latency_buckets[bound]
            le = bound / 1000.0  # ms -> s
            lines.append(
                f'gateway_request_duration_seconds{{le="{le}"}} {cumulative}'
            )
        cumulative += self._latency_buckets[float('inf')]
        lines.append(f'gateway_request_duration_seconds{{le="+Inf"}} {cumulative}')
        lines.append(f"gateway_request_duration_seconds_sum {self._total_latency_ms / 1000.0}")
        lines.append(f"gateway_request_duration_seconds_count {self._total_requests}")

        return "\n".join(lines) + "\n"


# ===================================================================
# 请求 ID 插件
# ===================================================================

class RequestIdPlugin(BasePlugin):
    """请求 ID 插件

    生成唯一的请求 ID，并在请求头和响应头中传递。
    支持：
    - 从 X-Request-Id / X-Trace-Id 头中读取已有 ID
    - 生成新的 UUID
    - 在响应头中返回请求 ID
    """

    name = "request_id"
    description = "请求 ID 生成和传递插件"
    version = "1.0.0"
    priority = 5  # 最高优先级，最先执行

    def __init__(self, header_name: str = "X-Request-Id",
                 alt_header_names: Optional[list] = None):
        super().__init__()
        self.header_name = header_name
        self.alt_header_names = alt_header_names or ["X-Trace-Id"]
        self._generated_count = 0
        self._inherited_count = 0

    async def pre_request(self, ctx: PluginContext) -> Optional[PluginContext]:
        await super().pre_request(ctx)

        request_id = ""

        # 尝试从请求头中获取
        headers_lower = {k.lower(): v for k, v in ctx.request_headers.items()}

        for h_name in [self.header_name] + self.alt_header_names:
            val = headers_lower.get(h_name.lower())
            if val:
                request_id = val
                self._inherited_count += 1
                break

        # 如果没有，生成新的
        if not request_id:
            request_id = uuid.uuid4().hex
            self._generated_count += 1

        ctx.request_id = request_id
        ctx.extra["request_id"] = request_id

        # 确保请求头中有 request_id
        ctx.request_headers[self.header_name] = request_id

        return ctx

    async def post_response(self, ctx: PluginContext) -> PluginContext:
        await super().post_response(ctx)

        # 在响应头中添加请求 ID
        if ctx.request_id:
            ctx.response_headers[self.header_name] = ctx.request_id
            # 也添加 X-Trace-Id 以兼容
            ctx.response_headers.setdefault("X-Trace-Id", ctx.request_id)

        return ctx

    def get_stats(self) -> Dict[str, Any]:
        stats = super().get_stats()
        stats.update({
            "generated_count": self._generated_count,
            "inherited_count": self._inherited_count,
        })
        return stats


# ===================================================================
# CORS 插件
# ===================================================================

class CorsPlugin(BasePlugin):
    """CORS 跨域插件

    处理跨域请求，支持：
    - 配置允许的来源
    - 配置允许的方法和头
    - 支持预检请求（OPTIONS）
    - 支持凭证
    """

    name = "cors"
    description = "CORS 跨域处理插件"
    version = "1.0.0"
    priority = 15

    def __init__(
        self,
        allow_origins: Optional[list] = None,
        allow_methods: Optional[list] = None,
        allow_headers: Optional[list] = None,
        allow_credentials: bool = True,
        max_age: int = 86400,
    ):
        super().__init__()
        self.allow_origins = allow_origins or ["*"]
        self.allow_methods = allow_methods or [
            "GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"
        ]
        self.allow_headers = allow_headers or [
            "Content-Type", "Authorization", "X-API-Key",
            "X-Request-Id", "X-Trace-Id",
        ]
        self.allow_credentials = allow_credentials
        self.max_age = max_age
        self._preflight_count = 0

    def _get_allow_origin(self, origin: str) -> str:
        """获取允许的 Origin"""
        if "*" in self.allow_origins:
            return "*" if not self.allow_credentials else origin
        if origin in self.allow_origins:
            return origin
        return ""

    async def pre_request(self, ctx: PluginContext) -> Optional[PluginContext]:
        await super().pre_request(ctx)

        # 处理预检请求
        if ctx.request_method.upper() == "OPTIONS":
            origin = ctx.request_headers.get("Origin", "")
            allow_origin = self._get_allow_origin(origin)

            if allow_origin:
                self._preflight_count += 1
                ctx.response_status = 204
                ctx.response_headers = {
                    "Access-Control-Allow-Origin": allow_origin,
                    "Access-Control-Allow-Methods": ", ".join(self.allow_methods),
                    "Access-Control-Allow-Headers": ", ".join(self.allow_headers),
                    "Access-Control-Max-Age": str(self.max_age),
                }
                if self.allow_credentials and allow_origin != "*":
                    ctx.response_headers["Access-Control-Allow-Credentials"] = "true"
                # 返回 None 表示终止请求，直接返回响应
                # 这里通过设置 ctx.extra 标记预检已处理
                ctx.extra["cors_preflight_handled"] = True
                return ctx

        return ctx

    async def post_response(self, ctx: PluginContext) -> PluginContext:
        await super().post_response(ctx)

        # 添加 CORS 响应头
        origin = ctx.request_headers.get("Origin", "")
        if origin:
            allow_origin = self._get_allow_origin(origin)
            if allow_origin:
                ctx.response_headers["Access-Control-Allow-Origin"] = allow_origin
                if self.allow_credentials and allow_origin != "*":
                    ctx.response_headers["Access-Control-Allow-Credentials"] = "true"
                ctx.response_headers["Access-Control-Expose-Headers"] = (
                    "X-Request-Id, X-Trace-Id, X-Gateway-Latency"
                )

        return ctx

    def get_stats(self) -> Dict[str, Any]:
        stats = super().get_stats()
        stats["preflight_count"] = self._preflight_count
        return stats


# ===================================================================
# 安全头插件
# ===================================================================

class SecurityHeadersPlugin(BasePlugin):
    """安全响应头插件

    添加安全相关的响应头：
    - X-Content-Type-Options
    - X-Frame-Options
    - X-XSS-Protection
    - Content-Security-Policy
    - Strict-Transport-Security
    - Referrer-Policy
    - Permissions-Policy
    """

    name = "security_headers"
    description = "安全响应头插件"
    version = "1.0.0"
    priority = 30

    DEFAULT_HEADERS = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "X-XSS-Protection": "1; mode=block",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    }

    def __init__(
        self,
        env: str = "development",
        csp_policy: Optional[str] = None,
        hsts_max_age: int = 31536000,
        custom_headers: Optional[Dict[str, str]] = None,
    ):
        super().__init__()
        self.env = env
        self.csp_policy = csp_policy or (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self' data:; "
            "connect-src 'self';"
        )
        self.hsts_max_age = hsts_max_age
        self.custom_headers = custom_headers or {}

    async def post_response(self, ctx: PluginContext) -> PluginContext:
        await super().post_response(ctx)

        headers = dict(self.DEFAULT_HEADERS)
        headers.update(self.custom_headers)

        # CSP
        headers["Content-Security-Policy"] = self.csp_policy

        # HSTS（仅生产环境）
        if self.env.lower() in ("production", "prod", "release"):
            headers["Strict-Transport-Security"] = (
                f"max-age={self.hsts_max_age}; includeSubDomains"
            )

        # 添加到响应头（不覆盖已有的）
        for key, value in headers.items():
            key_lower = key.lower()
            if not any(k.lower() == key_lower for k in ctx.response_headers):
                ctx.response_headers[key] = value

        return ctx

    def get_stats(self) -> Dict[str, Any]:
        stats = super().get_stats()
        stats["env"] = self.env
        stats["headers_count"] = len(self.DEFAULT_HEADERS) + len(self.custom_headers) + 2  # +2 for CSP and optional HSTS
        return stats
