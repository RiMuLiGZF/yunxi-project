"""熔断中间件.

按路由路径独立统计的熔断器，三态：CLOSED → OPEN → HALF_OPEN → CLOSED。
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
