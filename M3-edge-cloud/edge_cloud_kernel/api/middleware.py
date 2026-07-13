"""API 弹性中间件.

将限流（Rate Limiter）和熔断（Circuit Breaker）接入 FastAPI 中间件层，
为所有 API 端点提供统一的弹性保护。

主要功能：
- 全局限流：基于 IP 的令牌桶限流
- 接口级熔断：按路由路径独立熔断器统计
- 降级响应：触发限流/熔断时返回标准错误响应
"""

from __future__ import annotations

import time
from typing import Any

import structlog
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from edge_cloud_kernel.gateway.circuit_breaker import CircuitBreaker, CircuitState
from edge_cloud_kernel.gateway.rate_limiter import TokenBucketRateLimiter

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 限流中间件
# ---------------------------------------------------------------------------

class RateLimitMiddleware(BaseHTTPMiddleware):
    """全局限流中间件（基于 IP 的令牌桶）.

    为每个客户端 IP 维护独立的令牌桶，超过速率限制时返回 429 响应。

    Args:
        app: FastAPI 应用实例.
        max_tokens: IP 桶最大令牌容量（每分钟请求数）.
        refill_rate: IP 桶每秒补充令牌数.
        global_max_tokens: 全局限流桶容量.
        global_refill_rate: 全局每秒补充令牌数.
        exempt_paths: 免限流路径列表.
    """

    def __init__(
        self,
        app,
        max_tokens: int = 60,
        refill_rate: float = 1.0,
        global_max_tokens: int = 500,
        global_refill_rate: float = 10.0,
        exempt_paths: list[str] | None = None,
    ):
        super().__init__(app)
        self.max_tokens = max_tokens
        self.refill_rate = refill_rate
        self.exempt_paths = exempt_paths or ["/health", "/healthz"]

        # 全局限流桶
        self._global_limiter = TokenBucketRateLimiter(
            max_tokens=global_max_tokens,
            refill_rate=global_refill_rate,
        )

        # 按 IP 分桶
        self._ip_limiters: dict[str, TokenBucketRateLimiter] = {}

    async def _get_ip_limiter(self, ip: str) -> TokenBucketRateLimiter:
        """获取或创建 IP 对应的限流器.

        Args:
            ip: 客户端 IP.

        Returns:
            TokenBucketRateLimiter 实例.
        """
        if ip not in self._ip_limiters:
            self._ip_limiters[ip] = TokenBucketRateLimiter(
                max_tokens=self.max_tokens,
                refill_rate=self.refill_rate,
            )
        return self._ip_limiters[ip]

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """执行限流检查.

        Args:
            request: 请求对象.
            call_next: 下一个处理函数.

        Returns:
            响应对象.
        """
        path = request.url.path

        # 免限流路径
        if path in self.exempt_paths:
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"

        # 全局限流检查（异步，timeout=0 表示不等待）
        global_ok = await self._global_limiter.acquire(tokens=1, timeout=0)
        if not global_ok:
            logger.warning(
                "rate_limit.global_exceeded",
                ip=client_ip,
                path=path,
            )
            return self._rate_limit_response("Global rate limit exceeded")

        # IP 级限流检查（异步，timeout=0 表示不等待）
        ip_limiter = await self._get_ip_limiter(client_ip)
        ip_ok = await ip_limiter.acquire(tokens=1, timeout=0)
        if not ip_ok:
            logger.warning(
                "rate_limit.ip_exceeded",
                ip=client_ip,
                path=path,
            )
            return self._rate_limit_response("Rate limit exceeded for your IP")

        return await call_next(request)

    def _rate_limit_response(self, message: str) -> JSONResponse:
        """构造限流响应.

        Args:
            message: 错误消息.

        Returns:
            429 JSON 响应.
        """
        return JSONResponse(
            status_code=429,
            content={
                "code": 429,
                "message": message,
                "data": None,
                "retry_after": 1,
                "timestamp": time.time(),
            },
        )


# ---------------------------------------------------------------------------
# 熔断中间件
# ---------------------------------------------------------------------------

class CircuitBreakerMiddleware(BaseHTTPMiddleware):
    """API 熔断中间件（按路由路径独立统计）.

    为每个路由路径维护独立熔断器，当错误率超过阈值时熔断该接口，
    快速失败避免级联故障。

    Args:
        app: FastAPI 应用实例.
        error_threshold_pct: 错误率阈值（百分比，0-100）.
        volume_threshold: 触发熔断的最小请求数.
        reset_timeout_s: 熔断恢复超时（秒）.
        exempt_paths: 免熔断路径列表.
    """

    def __init__(
        self,
        app,
        error_threshold_pct: float = 50.0,
        volume_threshold: int = 20,
        reset_timeout_s: float = 30.0,
        exempt_paths: list[str] | None = None,
    ):
        super().__init__(app)
        self.error_threshold_pct = error_threshold_pct
        self.volume_threshold = volume_threshold
        self.reset_timeout_s = reset_timeout_s
        self.exempt_paths = exempt_paths or ["/health", "/healthz"]

        # 按路径存储熔断器
        self._breakers: dict[str, CircuitBreaker] = {}

    def _get_breaker(self, path: str) -> CircuitBreaker:
        """获取或创建路径对应的熔断器.

        Args:
            path: 路由路径.

        Returns:
            CircuitBreaker 实例.
        """
        if path not in self._breakers:
            self._breakers[path] = CircuitBreaker(
                name=f"api:{path}",
                error_threshold_pct=self.error_threshold_pct,
                volume_threshold=self.volume_threshold,
                reset_timeout_s=self.reset_timeout_s,
            )
        return self._breakers[path]

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """执行熔断检查.

        Args:
            request: 请求对象.
            call_next: 下一个处理函数.

        Returns:
            响应对象.
        """
        path = request.url.path

        # 免熔断路径
        if path in self.exempt_paths:
            return await call_next(request)

        breaker = self._get_breaker(path)

        # 检查熔断器是否允许请求通过
        if not breaker.allow_request():
            logger.warning(
                "circuit_breaker.open",
                path=path,
            )
            return self._circuit_break_response()

        # 正常执行
        start_time = time.time()
        try:
            response = await call_next(request)
            latency_ms = (time.time() - start_time) * 1000

            # 记录结果
            if response.status_code >= 500:
                breaker.record_failure(latency_ms=latency_ms, error_type="retryable")
            elif response.status_code >= 400:
                # 4xx 不计入熔断（客户端错误）
                breaker.record_success(latency_ms=latency_ms)
            else:
                breaker.record_success(latency_ms=latency_ms)

            return response

        except Exception:
            latency_ms = (time.time() - start_time) * 1000
            # 异常计入熔断
            breaker.record_failure(latency_ms=latency_ms, error_type="retryable")
            raise

    def _circuit_break_response(self) -> JSONResponse:
        """构造熔断响应.

        Returns:
            503 JSON 响应.
        """
        return JSONResponse(
            status_code=503,
            content={
                "code": 503,
                "message": "Service temporarily unavailable (circuit breaker open)",
                "data": None,
                "retry_after": int(self.reset_timeout_s),
                "timestamp": time.time(),
            },
        )

    def get_breaker_stats(self, path: str | None = None) -> dict[str, Any]:
        """获取熔断器统计信息.

        Args:
            path: 指定路径，为 None 则返回所有路径.

        Returns:
            统计信息字典.
        """
        if path:
            breaker = self._breakers.get(path)
            if breaker is None:
                return {}
            return {path: breaker.get_stats()}

        return {p: b.get_stats() for p, b in self._breakers.items()}


# ---------------------------------------------------------------------------
# 便捷工厂函数
# ---------------------------------------------------------------------------

def create_resilience_middleware(
    app,
    rate_limit_enabled: bool = True,
    circuit_breaker_enabled: bool = True,
    rate_limit_config: dict[str, Any] | None = None,
    circuit_breaker_config: dict[str, Any] | None = None,
) -> list[BaseHTTPMiddleware]:
    """创建弹性中间件列表（便捷函数）.

    Args:
        app: FastAPI 应用实例.
        rate_limit_enabled: 是否启用限流.
        circuit_breaker_enabled: 是否启用熔断.
        rate_limit_config: 限流配置字典.
        circuit_breaker_config: 熔断配置字典.

    Returns:
        中间件实例列表.
    """
    middlewares: list[BaseHTTPMiddleware] = []

    if rate_limit_enabled:
        rl_config = rate_limit_config or {}
        middlewares.append(RateLimitMiddleware(app, **rl_config))

    if circuit_breaker_enabled:
        cb_config = circuit_breaker_config or {}
        middlewares.append(CircuitBreakerMiddleware(app, **cb_config))

    return middlewares
