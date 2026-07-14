"""
M9 API 认证中间件

使用 Token 认证保护 M9 的 API 接口。
Token 从配置或环境变量读取，通过 Header X-M9-Token 传递。
"""

import os
import secrets
import logging
import time
import hmac
import hashlib

logger = logging.getLogger("m9.auth")

from typing import Optional, Dict, Any, Tuple, List
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


# 免认证的路径（白名单）
PUBLIC_PATHS = {
    "/health",
    "/",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/m8/health",
    "/m8/metrics",
    "/m8/config",
}


_dev_token: str = ""


def get_admin_token() -> str:
    """获取管理员 Token.

    优先级：环境变量 > 配置文件 > 默认值（开发环境）
    """
    # 从环境变量获取
    env_token = os.environ.get("M9_ADMIN_TOKEN", "")
    if env_token:
        return env_token

    # 从配置获取
    try:
        from .config import settings
        if settings.admin_token:
            return settings.admin_token
    except Exception:
        pass

    # 开发环境生成随机Token
    env = os.environ.get("YUNXI_ENV", "development")
    if env == "production":
        return ""  # 生产环境不设默认值，强制认证

    global _dev_token
    if not _dev_token:
        _dev_token = secrets.token_urlsafe(32)
        logger.warning("开发环境使用随机Token: %s", _dev_token)
    return _dev_token


def validate_token(token: str) -> bool:
    """验证 Token 是否有效.

    Args:
        token: 待验证的 Token

    Returns:
        True 表示有效
    """
    expected = get_admin_token()
    if not expected:
        return False  # 没有配置 token 时不允许访问

    # 使用安全的字符串比较（防时序攻击）
    return hmac.compare_digest(token, expected)


class AuthMiddleware(BaseHTTPMiddleware):
    """认证中间件

    对除白名单外的所有请求进行 Token 验证。
    Token 通过 X-M9-Token 请求头传递。
    """

    def __init__(self, app, exempt_paths: Optional[set] = None):
        super().__init__(app)
        self.exempt_paths = exempt_paths or PUBLIC_PATHS

    async def dispatch(self, request: Request, call_next):
        # 检查是否在白名单中
        path = request.url.path
        if path in self.exempt_paths:
            return await call_next(request)

        # 白名单路径前缀匹配（如 /docs/xxx）
        for exempt in ["/docs", "/openapi.json", "/redoc"]:
            if path.startswith(exempt):
                return await call_next(request)

        # 获取 Token
        token = request.headers.get("X-M9-Token", "")

        # 也支持 Authorization: Bearer <token> 格式
        if not token:
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]

        # 验证 Token
        if not token or not validate_token(token):
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "code": 40101,
                    "message": "Unauthorized: Invalid or missing token",
                    "data": None,
                },
            )

        return await call_next(request)


class RateLimiter:
    """简单的速率限制器（令牌桶算法）.

    限制每个 IP 或 Token 的请求频率。
    """

    def __init__(self, max_requests: int = 100, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._buckets: Dict[str, Dict[str, Any]] = {}

    def check(self, key: str) -> Tuple[bool, Dict[str, Any]]:
        """检查是否超过速率限制.

        Args:
            key: 限制键（如 IP 地址或 Token）

        Returns:
            (是否允许, 限流信息)
        """
        now = time.time()
        bucket = self._buckets.get(key)

        if not bucket:
            # 新用户
            self._buckets[key] = {
                "tokens": self.max_requests - 1,
                "last_refill": now,
            }
            return True, {"remaining": self.max_requests - 1, "limit": self.max_requests}

        # 补充令牌
        elapsed = now - bucket["last_refill"]
        tokens_to_add = int(elapsed / self.window_seconds * self.max_requests)
        if tokens_to_add > 0:
            bucket["tokens"] = min(self.max_requests, bucket["tokens"] + tokens_to_add)
            bucket["last_refill"] = now

        if bucket["tokens"] <= 0:
            return False, {"remaining": 0, "limit": self.max_requests}

        bucket["tokens"] -= 1

        # 清理超过2倍窗口时间的过期桶（最多100个）
        if len(self._buckets) > 500:
            cutoff = now - self.window_seconds * 2
            expired = [k for k, v in self._buckets.items() if v["last_refill"] < cutoff]
            for k in expired[:100]:
                del self._buckets[k]

        return True, {"remaining": bucket["tokens"], "limit": self.max_requests}


# 全局速率限制器
rate_limiter = RateLimiter(max_requests=100, window_seconds=60)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """速率限制中间件"""

    async def dispatch(self, request: Request, call_next):
        # 获取客户端 IP
        client_ip = request.client.host if request.client else "unknown"

        # 检查速率限制
        allowed, info = rate_limiter.check(client_ip)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "code": 42901,
                    "message": "Too Many Requests",
                    "data": {"retry_after": 60},
                },
                headers={
                    "X-RateLimit-Limit": str(info["limit"]),
                    "X-RateLimit-Remaining": "0",
                    "Retry-After": "60",
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(info["limit"])
        response.headers["X-RateLimit-Remaining"] = str(info["remaining"])
        return response
