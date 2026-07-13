"""
熔断中间件

监控 API 整体错误率，当错误率超过阈值时自动熔断，
返回 503 Service Unavailable，保护后端服务免受过载影响。

环境变量：
- M5_CIRCUIT_BREAKER_ENABLED: 是否启用熔断中间件，默认 true
- M5_CIRCUIT_BREAKER_FAILURE_THRESHOLD: 失败次数阈值，默认 20
- M5_CIRCUIT_BREAKER_RECOVERY_TIMEOUT: 恢复超时（秒），默认 30
- M5_CIRCUIT_BREAKER_WINDOW_SIZE: 滑动窗口大小（秒），默认 60
- M5_CIRCUIT_BREAKER_HALF_OPEN_CALLS: 半开状态探测请求数，默认 3
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Optional

import structlog
from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from tide_memory.common.retry import CircuitBreaker, CircuitState
from tide_memory.errors import ErrorCode, error_response

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 免熔断路径
# ---------------------------------------------------------------------------

_EXEMPT_PATHS = (
    "/health",
    "/healthz",
    "/api/v1/health",
    "/m8/health",
    "/m8/metrics",
    "/m8/config",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/favicon.ico",
)


def _is_exempt_path(path: str) -> bool:
    """判断路径是否豁免熔断统计"""
    return path in _EXEMPT_PATHS


def _is_server_error(status_code: int) -> bool:
    """判断状态码是否为服务端错误（5xx）"""
    return 500 <= status_code < 600


# ---------------------------------------------------------------------------
# CircuitBreakerMiddleware 熔断中间件
# ---------------------------------------------------------------------------


class CircuitBreakerMiddleware(BaseHTTPMiddleware):
    """
    API 熔断中间件

    监控全局 API 请求的错误率（5xx 响应），当滑动窗口内的失败次数
    达到阈值时自动熔断，后续请求直接返回 503 Service Unavailable。

    熔断状态：
    - CLOSED: 正常状态，请求通过，统计失败数
    - OPEN: 熔断状态，请求直接返回 503
    - HALF_OPEN: 半开状态，放行少量探测请求，成功则闭合，失败则重新熔断

    环境变量：
    - M5_CIRCUIT_BREAKER_ENABLED: 是否启用，默认 true
    - M5_CIRCUIT_BREAKER_FAILURE_THRESHOLD: 失败次数阈值，默认 20
    - M5_CIRCUIT_BREAKER_RECOVERY_TIMEOUT: 恢复超时秒数，默认 30
    - M5_CIRCUIT_BREAKER_WINDOW_SIZE: 滑动窗口秒数，默认 60
    - M5_CIRCUIT_BREAKER_HALF_OPEN_CALLS: 半开探测请求数，默认 3
    """

    def __init__(self, app):
        super().__init__(app)

        # 读取环境变量配置
        self._enabled = self._read_bool_env("M5_CIRCUIT_BREAKER_ENABLED", default=True)

        env_threshold = os.environ.get("M5_CIRCUIT_BREAKER_FAILURE_THRESHOLD")
        failure_threshold = int(env_threshold) if env_threshold else 20
        if failure_threshold < 1:
            failure_threshold = 20

        env_recovery = os.environ.get("M5_CIRCUIT_BREAKER_RECOVERY_TIMEOUT")
        recovery_timeout = float(env_recovery) if env_recovery else 30.0
        if recovery_timeout < 1:
            recovery_timeout = 30.0

        env_window = os.environ.get("M5_CIRCUIT_BREAKER_WINDOW_SIZE")
        window_size = float(env_window) if env_window else 60.0
        if window_size < 1:
            window_size = 60.0

        env_half_open = os.environ.get("M5_CIRCUIT_BREAKER_HALF_OPEN_CALLS")
        half_open_calls = int(env_half_open) if env_half_open else 3
        if half_open_calls < 1:
            half_open_calls = 3

        # 全局熔断器
        self._circuit_breaker = CircuitBreaker(
            name="m5-api-global",
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
            half_open_max_calls=half_open_calls,
            window_size=window_size,
        )

        logger.info(
            "circuit_breaker_middleware.initialized",
            enabled=self._enabled,
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
            window_size=window_size,
            half_open_calls=half_open_calls,
            exempt_paths=list(_EXEMPT_PATHS),
        )

    @staticmethod
    def _read_bool_env(name: str, default: bool = False) -> bool:
        """读取布尔型环境变量"""
        val = os.environ.get(name, "").strip().lower()
        if val in ("true", "1", "yes", "on"):
            return True
        if val in ("false", "0", "no", "off"):
            return False
        return default

    @property
    def enabled(self) -> bool:
        """熔断中间件是否启用"""
        return self._enabled

    @property
    def circuit_state(self) -> CircuitState:
        """当前熔断器状态"""
        return self._circuit_breaker.state

    def _build_503_response(self, request: Request) -> JSONResponse:
        """构造 503 熔断响应"""
        request_id = getattr(request.state, "request_id", None)
        if not request_id:
            request_id = request.headers.get("x-request-id", f"m5-{uuid.uuid4().hex[:12]}")

        stats = self._circuit_breaker.get_stats()
        recovery_timeout = stats.get("recovery_timeout", 30)

        resp = error_response(
            code=ErrorCode.SERVICE_UNAVAILABLE,
            message="服务暂不可用，请稍后重试（熔断器已打开）",
            data={
                "reason": "circuit_breaker_open",
                "failure_count": stats.get("failure_count", 0),
                "failure_threshold": stats.get("failure_threshold", 0),
                "recovery_timeout": recovery_timeout,
                "state": stats.get("state", "open"),
            },
            request_id=request_id,
        )

        response = JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=resp,
        )

        # Retry-After 头，提示客户端何时重试
        response.headers["Retry-After"] = str(int(recovery_timeout))
        response.headers["X-Circuit-Breaker"] = "open"

        return response

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ):
        """
        中间件核心分发逻辑

        1. 熔断关闭 → 直接放行
        2. 豁免路径 → 直接放行（不参与熔断统计）
        3. 熔断器 OPEN → 返回 503
        4. 熔断器 HALF_OPEN → 放行探测请求
        5. 请求完成后根据响应状态码更新熔断器
        """
        # 未启用时直接放行
        if not self._enabled:
            return await call_next(request)

        path = request.url.path

        # 豁免路径跳过熔断（健康检查、文档等）
        if _is_exempt_path(path):
            return await call_next(request)

        # 检查熔断器是否允许请求通过
        if not self._circuit_breaker.allow_request():
            logger.warning(
                "circuit_breaker.rejected",
                path=path,
                method=request.method,
                state=self._circuit_breaker.state.value,
            )
            return self._build_503_response(request)

        # 执行请求
        response = await call_next(request)

        # 根据响应状态码更新熔断器
        if _is_server_error(response.status_code):
            self._circuit_breaker.record_failure()
            logger.debug(
                "circuit_breaker.failure_recorded",
                path=path,
                status_code=response.status_code,
                failure_count=self._circuit_breaker.failure_count,
                state=self._circuit_breaker.state.value,
            )
        else:
            self._circuit_breaker.record_success()

        # 添加熔断状态响应头
        try:
            response.headers["X-Circuit-Breaker"] = self._circuit_breaker.state.value
        except Exception:
            pass

        return response

    def get_stats(self) -> dict:
        """获取熔断中间件统计信息"""
        stats = self._circuit_breaker.get_stats()
        stats["enabled"] = self._enabled
        return stats

    def reset(self) -> None:
        """手动重置熔断器"""
        self._circuit_breaker.reset()
        logger.info("circuit_breaker_middleware.reset")


__all__ = ["CircuitBreakerMiddleware"]
# vim: set et ts=4 sw=4:
