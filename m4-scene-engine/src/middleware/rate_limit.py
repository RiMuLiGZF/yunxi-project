"""限流中间件.

基于令牌桶算法的全局限流 + IP 级限流。
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
