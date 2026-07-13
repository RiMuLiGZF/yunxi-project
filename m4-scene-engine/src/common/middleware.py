"""API 弹性中间件.

限流（Rate Limiter）和熔断（Circuit Breaker）接入 FastAPI 中间件层，
为所有 API 端点提供统一的弹性保护。

主要功能：
- 全局限流：基于 IP 的令牌桶限流
- 接口级熔断：按路由路径独立熔断器统计
- 降级响应：触发限流/熔断时返回标准错误响应
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 令牌桶限流器（轻量版，不依赖外部包）
# ---------------------------------------------------------------------------

class TokenBucketRateLimiter:
    """轻量级令牌桶限流器.

    纯异步实现，无需额外依赖。
    """

    def __init__(self, max_tokens: int = 60, refill_rate: float = 1.0):
        self.max_tokens = max_tokens
        self.refill_rate = refill_rate  # tokens per second
        self._tokens = float(max_tokens)
        self._last_refill = time.time()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = time.time()
        elapsed = now - self._last_refill
        if elapsed > 0:
            new_tokens = elapsed * self.refill_rate
            self._tokens = min(self.max_tokens, self._tokens + new_tokens)
            self._last_refill = now

    async def acquire(self, tokens: int = 1, timeout: float = 0) -> bool:
        """尝试获取令牌.

        Args:
            tokens: 需要的令牌数.
            timeout: 等待超时时间（秒），0 表示不等待立即返回.

        Returns:
            是否成功获取令牌.
        """
        async with self._lock:
            self._refill()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True

            if timeout <= 0:
                return False

            # 等待足够的令牌补充
            needed = tokens - self._tokens
            wait_time = needed / self.refill_rate
            if wait_time > timeout:
                return False

            await asyncio.sleep(wait_time)
            self._refill()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False


# ---------------------------------------------------------------------------
# 熔断器（轻量版）
# ---------------------------------------------------------------------------

class CircuitState:
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """轻量级熔断器.

    三态：CLOSED（正常）→ OPEN（熔断）→ HALF_OPEN（半开探测）→ CLOSED
    """

    def __init__(
        self,
        name: str = "default",
        error_threshold_pct: float = 50.0,
        volume_threshold: int = 10,
        reset_timeout_s: float = 30.0,
        half_open_max_requests: int = 3,
    ):
        self.name = name
        self.error_threshold_pct = error_threshold_pct
        self.volume_threshold = volume_threshold
        self.reset_timeout_s = reset_timeout_s
        self.half_open_max_requests = half_open_max_requests

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._open_at = 0.0
        self._half_open_count = 0
        self._lock = asyncio.Lock()

    def allow_request(self) -> bool:
        """检查是否允许请求通过.

        Returns:
            是否允许请求.
        """
        if self._state == CircuitState.CLOSED:
            return True

        if self._state == CircuitState.OPEN:
            if time.time() - self._open_at >= self.reset_timeout_s:
                self._state = CircuitState.HALF_OPEN
                self._half_open_count = 0
                return True
            return False

        if self._state == CircuitState.HALF_OPEN:
            return self._half_open_count < self.half_open_max_requests

        return True

    async def record_success(self, latency_ms: float = 0) -> None:
        """记录成功请求."""
        async with self._lock:
            self._success_count += 1
            if self._state == CircuitState.HALF_OPEN:
                self._half_open_count += 1
                # 半开状态下成功足够次数则关闭熔断
                if self._half_open_count >= self.half_open_max_requests:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._success_count = 0

    async def record_failure(self, latency_ms: float = 0, error_type: str = "retryable") -> None:
        """记录失败请求."""
        async with self._lock:
            self._failure_count += 1
            total = self._failure_count + self._success_count

            if self._state == CircuitState.HALF_OPEN:
                # 半开状态下失败立即重新熔断
                self._state = CircuitState.OPEN
                self._open_at = time.time()
                return

            if total >= self.volume_threshold:
                error_pct = (self._failure_count / total) * 100
                if error_pct >= self.error_threshold_pct:
                    self._state = CircuitState.OPEN
                    self._open_at = time.time()

    def get_state(self) -> str:
        """获取当前状态."""
        # 检查是否需要从 OPEN 转到 HALF_OPEN
        if self._state == CircuitState.OPEN:
            if time.time() - self._open_at >= self.reset_timeout_s:
                self._state = CircuitState.HALF_OPEN
                self._half_open_count = 0
        return self._state

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息."""
        total = self._failure_count + self._success_count
        error_pct = (self._failure_count / total * 100) if total > 0 else 0
        return {
            "state": self.get_state(),
            "total_requests": total,
            "success_count": self._success_count,
            "failure_count": self._failure_count,
            "error_pct": round(error_pct, 2),
        }


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
        self.exempt_paths = exempt_paths or ["/health", "/healthz", "/m8/health"]

        # 全局限流桶
        self._global_limiter = TokenBucketRateLimiter(
            max_tokens=global_max_tokens,
            refill_rate=global_refill_rate,
        )

        # 按 IP 分桶
        self._ip_limiters: dict[str, TokenBucketRateLimiter] = {}

    def _get_ip_limiter(self, ip: str) -> TokenBucketRateLimiter:
        if ip not in self._ip_limiters:
            self._ip_limiters[ip] = TokenBucketRateLimiter(
                max_tokens=self.max_tokens,
                refill_rate=self.refill_rate,
            )
        return self._ip_limiters[ip]

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        path = request.url.path

        # 免限流路径
        if path in self.exempt_paths:
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"

        # 全局限流检查
        global_ok = await self._global_limiter.acquire(tokens=1, timeout=0)
        if not global_ok:
            logger.warning("rate_limit.global_exceeded", ip=client_ip, path=path)
            return self._rate_limit_response("Global rate limit exceeded")

        # IP 级限流检查
        ip_limiter = self._get_ip_limiter(client_ip)
        ip_ok = await ip_limiter.acquire(tokens=1, timeout=0)
        if not ip_ok:
            logger.warning("rate_limit.ip_exceeded", ip=client_ip, path=path)
            return self._rate_limit_response("Rate limit exceeded for your IP")

        return await call_next(request)

    def _rate_limit_response(self, message: str) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content={
                "code": 40029,
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

    为每个路由路径维护独立熔断器，当错误率超过阈值时熔断该接口。

    Args:
        app: FastAPI 应用实例.
        error_threshold_pct: 错误率阈值（百分比）.
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
        self.exempt_paths = exempt_paths or ["/health", "/healthz", "/m8/health"]

        self._breakers: dict[str, CircuitBreaker] = {}

    def _get_breaker(self, path: str) -> CircuitBreaker:
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
        path = request.url.path

        if path in self.exempt_paths:
            return await call_next(request)

        breaker = self._get_breaker(path)

        if not breaker.allow_request():
            logger.warning("circuit_breaker.open", path=path)
            return self._circuit_break_response()

        start_time = time.time()
        try:
            response = await call_next(request)
            latency_ms = (time.time() - start_time) * 1000

            if response.status_code >= 500:
                await breaker.record_failure(latency_ms=latency_ms, error_type="retryable")
            elif response.status_code >= 400:
                await breaker.record_success(latency_ms=latency_ms)
            else:
                await breaker.record_success(latency_ms=latency_ms)

            return response

        except Exception:
            latency_ms = (time.time() - start_time) * 1000
            await breaker.record_failure(latency_ms=latency_ms, error_type="retryable")
            raise

    def _circuit_break_response(self) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "code": 50003,
                "message": "Service temporarily unavailable (circuit breaker open)",
                "data": None,
                "retry_after": int(self.reset_timeout_s),
                "timestamp": time.time(),
            },
        )
