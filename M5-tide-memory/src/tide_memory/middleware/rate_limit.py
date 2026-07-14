"""
限流中间件

基于令牌桶算法的 IP 级别限流中间件，保护 M5 潮汐记忆系统免受请求洪泛攻击。

环境变量：
- M5_RATE_LIMIT_ENABLED: 是否启限流，默认 true
- M5_RATE_LIMIT_PER_MINUTE: 每分钟允许的请求数，默认 100
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from typing import Dict, Optional

import structlog
from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from tide_memory.common.errors import ErrorCode, error_response

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 免限流路径
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
    """判断路径是否豁免限流"""
    return path in _EXEMPT_PATHS


# ---------------------------------------------------------------------------
# TokenBucket 令牌桶
# ---------------------------------------------------------------------------


class TokenBucket:
    """
    令牌桶限流器

    以固定速率向桶中添加令牌，每个请求消耗一个令牌，
    桶满时多余令牌丢弃，桶空时拒绝请求。

    Args:
        rate: 令牌生成速率（每秒令牌数）
        capacity: 桶容量（最大令牌数）
    """

    def __init__(self, rate: float, capacity: float) -> None:
        if rate <= 0:
            raise ValueError("rate must be > 0")
        if capacity <= 0:
            raise ValueError("capacity must be > 0")

        self._rate = rate  # 令牌/秒
        self._capacity = capacity
        self._tokens = float(capacity)  # 当前令牌数
        self._last_refill = time.time()
        self._lock = threading.Lock()

    @property
    def rate(self) -> float:
        """令牌生成速率（每秒）"""
        return self._rate

    @property
    def capacity(self) -> float:
        """桶容量"""
        return self._capacity

    @property
    def tokens(self) -> float:
        """当前令牌数（线程安全读取）"""
        with self._lock:
            self._refill()
            return self._tokens

    def _refill(self) -> None:
        """补充令牌（调用者应持有 _lock）"""
        now = time.time()
        elapsed = now - self._last_refill
        if elapsed > 0:
            new_tokens = elapsed * self._rate
            self._tokens = min(self._capacity, self._tokens + new_tokens)
            self._last_refill = now

    def try_consume(self, tokens: float = 1.0) -> bool:
        """
        尝试消耗指定数量的令牌

        Args:
            tokens: 需要消耗的令牌数，默认 1

        Returns:
            True 表示消耗成功（允许请求），False 表示令牌不足（限流）
        """
        with self._lock:
            self._refill()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    def reset(self) -> None:
        """重置令牌桶到满状态"""
        with self._lock:
            self._tokens = float(self._capacity)
            self._last_refill = time.time()

    def __repr__(self) -> str:
        return f"TokenBucket(rate={self._rate}, capacity={self._capacity})"


# ---------------------------------------------------------------------------
# RateLimitMiddleware 限流中间件
# ---------------------------------------------------------------------------


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    令牌桶限流中间件（按 IP 限流）

    为每个客户端 IP 维护独立的令牌桶，超出速率限制时返回 429 Too Many Requests。

    环境变量：
    - M5_RATE_LIMIT_ENABLED: 是否启用限流，默认 true
    - M5_RATE_LIMIT_PER_MINUTE: 每分钟允许的请求数，默认 100
    - M5_RATE_LIMIT_BURST: 突发请求上限（桶容量倍数），默认 2.0
    """

    def __init__(self, app) -> None:
        super().__init__(app)

        # 读取环境变量配置
        self._enabled = self._read_bool_env("M5_RATE_LIMIT_ENABLED", default=True)

        env_per_minute = os.environ.get("M5_RATE_LIMIT_PER_MINUTE")
        self._per_minute = int(env_per_minute) if env_per_minute else 100
        if self._per_minute <= 0:
            self._per_minute = 100

        env_burst = os.environ.get("M5_RATE_LIMIT_BURST")
        self._burst_factor = float(env_burst) if env_burst else 2.0
        if self._burst_factor < 1.0:
            self._burst_factor = 1.0

        # 每个 IP 对应的令牌桶
        self._buckets: Dict[str, TokenBucket] = {}
        self._buckets_lock = threading.Lock()

        # 令牌桶参数
        self._rate = self._per_minute / 60.0  # 每秒令牌数
        self._capacity = self._per_minute * self._burst_factor

        # 清理过期桶的阈值
        self._max_buckets = 10000
        self._last_cleanup = time.time()
        self._cleanup_interval = 300  # 5 分钟清理一次

        logger.info(
            "rate_limit_middleware.initialized",
            enabled=self._enabled,
            per_minute=self._per_minute,
            burst_factor=self._burst_factor,
            rate_per_second=round(self._rate, 2),
            capacity=round(self._capacity, 2),
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
        """限流是否启用"""
        return self._enabled

    @property
    def per_minute(self) -> int:
        """每分钟请求数限制"""
        return self._per_minute

    def _get_client_ip(self, request: Request) -> str:
        """
        获取客户端真实 IP

        优先从 X-Forwarded-For / X-Real-IP 头中提取，
        否则使用连接对端地址。
        """
        # X-Forwarded-For: client, proxy1, proxy2, ...
        xff = request.headers.get("x-forwarded-for")
        if xff:
            # 取第一个（最左侧）为客户端 IP
            client_ip = xff.split(",")[0].strip()
            if client_ip:
                return client_ip

        # X-Real-IP
        xri = request.headers.get("x-real-ip")
        if xri:
            return xri.strip()

        # 连接对端地址
        client_host = getattr(request.client, "host", None) if request.client else None
        return client_host or "unknown"

    def _get_or_create_bucket(self, ip: str) -> TokenBucket:
        """
        获取或创建 IP 对应的令牌桶

        同时执行周期性清理，移除过期的桶。
        """
        with self._buckets_lock:
            # 周期性清理
            now = time.time()
            if now - self._last_cleanup > self._cleanup_interval:
                self._cleanup_expired_buckets(now)
                self._last_cleanup = now

            if ip not in self._buckets:
                # 超过最大桶数时，先清理一轮
                if len(self._buckets) >= self._max_buckets:
                    self._cleanup_expired_buckets(now)
                self._buckets[ip] = TokenBucket(rate=self._rate, capacity=self._capacity)

            return self._buckets[ip]

    def _cleanup_expired_buckets(self, now: float) -> None:
        """
        清理长时间未使用的令牌桶
        注意：调用者应持有 _buckets_lock
        """
        # 移除超过 1 小时未使用的桶
        # 由于 TokenBucket 没有暴露最后使用时间，这里简单按数量清理
        # 如果桶数量超过上限的 80%，清理掉一半（基于 Python dict 插入顺序）
        if len(self._buckets) > self._max_buckets * 0.8:
            remove_count = len(self._buckets) // 2
            keys = list(self._buckets.keys())[:remove_count]
            for key in keys:
                del self._buckets[key]
            logger.debug(
                "rate_limit.cleanup_buckets",
                removed=remove_count,
                remaining=len(self._buckets),
            )

    def _build_rate_limit_response(self, request: Request, ip: str) -> JSONResponse:
        """构造 429 限流响应"""
        request_id = getattr(request.state, "request_id", None)
        if not request_id:
            request_id = request.headers.get("x-request-id", f"m5-{uuid.uuid4().hex[:12]}")

        resp = error_response(
            code=ErrorCode.RATE_LIMITED,
            message=f"请求过于频繁，请稍后再试（限制：{self._per_minute} 次/分钟）",
            data={
                "limit": self._per_minute,
                "period": "minute",
                "client_ip": ip,
            },
            request_id=request_id,
        )

        response = JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content=resp,
        )

        # 添加标准限流响应头
        response.headers["X-RateLimit-Limit"] = str(self._per_minute)
        response.headers["X-RateLimit-Remaining"] = "0"
        response.headers["Retry-After"] = str(
            max(1, int(60.0 / self._rate))
        )

        return response

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ):
        """
        中间件核心分发逻辑

        1. 限流关闭 → 直接放行
        2. 豁免路径 → 直接放行
        3. 令牌桶检查 → 通过则放行，失败返回 429
        """
        # 未启用时直接放行
        if not self._enabled:
            return await call_next(request)

        path = request.url.path

        # 豁免路径跳过限流
        if _is_exempt_path(path):
            return await call_next(request)

        # 获取客户端 IP
        client_ip = self._get_client_ip(request)

        # 获取令牌桶并尝试消耗令牌
        bucket = self._get_or_create_bucket(client_ip)

        if not bucket.try_consume(1.0):
            # 令牌不足，限流
            remaining_tokens = bucket.tokens
            logger.warning(
                "rate_limit.blocked",
                client_ip=client_ip,
                path=path,
                method=request.method,
                limit_per_minute=self._per_minute,
                remaining=remaining_tokens,
            )
            return self._build_rate_limit_response(request, client_ip)

        # 放行请求
        response = await call_next(request)

        # 添加限流信息头
        try:
            remaining = int(bucket.tokens)
            response.headers["X-RateLimit-Limit"] = str(self._per_minute)
            response.headers["X-RateLimit-Remaining"] = str(remaining)
        except Exception:
            pass

        return response

    def get_stats(self) -> dict:
        """获取限流中间件统计信息"""
        with self._buckets_lock:
            return {
                "enabled": self._enabled,
                "per_minute": self._per_minute,
                "burst_factor": self._burst_factor,
                "rate_per_second": round(self._rate, 2),
                "capacity": round(self._capacity, 2),
                "tracked_ips": len(self._buckets),
                "max_buckets": self._max_buckets,
            }


__all__ = ["TokenBucket", "RateLimitMiddleware"]
# vim: set et ts=4 sw=4:
