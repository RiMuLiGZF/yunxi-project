"""
云汐 M9 开发者工坊 - API 认证中间件

**已升级到统一认证体系**：本模块内部使用 shared.core.auth 提供的
统一认证中间件和速率限制器，保留原有接口以保证向后兼容。

使用 Token 认证保护 M9 的 API 接口。
Token 从配置或环境变量读取，通过 Header X-M9-Token 传递。
"""

import os
import time
import hmac
import hashlib
from typing import Optional, Dict, Any, Tuple, List

# ===========================================================================
# 从统一认证模块导入（优先使用，不可用时回退）
# ===========================================================================
try:
    from shared.core.auth import (
        UnifiedAuthMiddleware as _UnifiedAuthMiddleware,
        SimpleMemoryRateLimiter as _SimpleRateLimiter,
        ApiKeyValidator as _ApiKeyValidator,
        InMemoryApiKeyStore as _InMemoryApiKeyStore,
        ApiKeyInfo as _ApiKeyInfo,
        hash_api_key_sha256 as _hash_api_key_sha256,
        is_public_path as _is_public_path,
    )
    _unified_auth_available = True
except ImportError:
    _unified_auth_available = False
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import JSONResponse


# 免认证的路径（白名单）
PUBLIC_PATHS = {
    "/health",
    "/api/info",
    "/",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/m8/health",
    "/m8/metrics",
    "/m8/config",
    "/m8/*",
}


# ===========================================================================
# Token 获取与验证（保留旧 API）
# ===========================================================================

def get_admin_token() -> str:
    """获取管理员 Token.

    从 config 模块的 get_settings() 获取 admin_token 配置。
    优先级：环境变量 > 配置文件 > 默认值（开发环境）
    """
    # 从环境变量获取
    env_token = os.environ.get("M9_ADMIN_TOKEN", "")
    if env_token:
        return env_token

    # 从配置获取
    try:
        from config import get_settings
        settings = get_settings()
        if hasattr(settings, "admin_token") and settings.admin_token:
            return settings.admin_token
    except Exception:
        pass

    # 未配置 token 时返回空（认证失败）
    return ""


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


# ===========================================================================
# 速率限制器（保留旧 API，内部使用统一认证的实现）
# ===========================================================================

class RateLimiter:
    """简单的速率限制器（令牌桶算法）.

    **已升级**：内部使用统一认证体系的 SimpleMemoryRateLimiter。
    保留原有 API 以保证向后兼容。

    限制每个 IP 或 Token 的请求频率。
    """

    def __init__(self, max_requests: int = 100, window_seconds: int = 60):
        if _unified_auth_available:
            self._limiter = _SimpleRateLimiter(
                default_limit=max_requests,
                window_seconds=window_seconds,
            )
        else:
            self.max_requests = max_requests
            self.window_seconds = window_seconds
            self._buckets: Dict[str, Dict[str, Any]] = {}

        self.max_requests = max_requests
        self.window_seconds = window_seconds

    def check(self, key: str) -> Tuple[bool, Dict[str, Any]]:
        """检查是否超过速率限制.

        Args:
            key: 限制键（如 IP 地址或 Token）

        Returns:
            (是否允许, 限流信息)
        """
        if _unified_auth_available:
            allowed, remaining, window = self._limiter.check(key)
            return allowed, {
                "remaining": remaining,
                "limit": self.max_requests,
            }

        # 旧实现（兜底）
        now = time.time()
        bucket = self._buckets.get(key)

        if not bucket:
            self._buckets[key] = {
                "tokens": self.max_requests - 1,
                "last_refill": now,
            }
            return True, {"remaining": self.max_requests - 1, "limit": self.max_requests}

        elapsed = now - bucket["last_refill"]
        tokens_to_add = int(elapsed / self.window_seconds * self.max_requests)
        if tokens_to_add > 0:
            bucket["tokens"] = min(self.max_requests, bucket["tokens"] + tokens_to_add)
            bucket["last_refill"] = now

        if bucket["tokens"] <= 0:
            return False, {"remaining": 0, "limit": self.max_requests}

        bucket["tokens"] -= 1
        return True, {"remaining": bucket["tokens"], "limit": self.max_requests}


# 全局速率限制器
rate_limiter = RateLimiter(max_requests=100, window_seconds=60)


# ===========================================================================
# 认证中间件（保留旧 API，内部使用统一认证）
# ===========================================================================

def _build_auth_middleware_class():
    """构建 AuthMiddleware 类（优先使用统一认证）"""

    if _unified_auth_available:
        # 使用统一认证体系
        _store = _InMemoryApiKeyStore()
        _token = get_admin_token()
        if _token:
            _store.add_key(_ApiKeyInfo(
                key_hash=_hash_api_key_sha256(_token),
                key_name="m9-admin",
                roles=["admin"],
                scopes=["*"],
            ))
        _validator = _ApiKeyValidator(_store, use_bcrypt=False)

        class AuthMiddleware(_UnifiedAuthMiddleware):
            """认证中间件（基于统一认证体系）

            对除白名单外的所有请求进行 Token 验证。
            Token 通过 X-M9-Token 请求头传递。
            """

            def __init__(self, app, exempt_paths: Optional[set] = None):
                paths = exempt_paths or PUBLIC_PATHS
                # 刷新存储中的密钥（支持动态配置）
                token = get_admin_token()
                if token:
                    key_hash = _hash_api_key_sha256(token)
                    existing = _store.find_by_hash(key_hash)
                    if not existing:
                        _store.add_key(_ApiKeyInfo(
                            key_hash=key_hash,
                            key_name="m9-admin",
                            roles=["admin"],
                            scopes=["*"],
                        ))

                super().__init__(
                    app,
                    api_key_validator=_validator,
                    api_key_header_names=["X-M9-Token", "X-API-Key"],
                    public_paths=list(paths),
                    enabled=True,
                    require_auth=True,
                    fallback_mode="strict",
                )

            async def dispatch(self, request, call_next):
                # 统一认证中间件已处理白名单、认证等
                return await super().dispatch(request, call_next)

        return AuthMiddleware

    else:
        # 旧实现（兜底）
        class AuthMiddlewareFallback(BaseHTTPMiddleware):
            """认证中间件（回退实现）

            对除白名单外的所有请求进行 Token 验证。
            """

            def __init__(self, app, exempt_paths: Optional[set] = None):
                super().__init__(app)
                self.exempt_paths = exempt_paths or PUBLIC_PATHS

            async def dispatch(self, request: Request, call_next):
                path = request.url.path
                if path in self.exempt_paths:
                    return await call_next(request)

                for exempt in ["/docs", "/openapi.json", "/redoc", "/m8/"]:
                    if path.startswith(exempt):
                        return await call_next(request)

                token = request.headers.get("X-M9-Token", "")
                if not token:
                    auth_header = request.headers.get("Authorization", "")
                    if auth_header.startswith("Bearer "):
                        token = auth_header[7:]

                if not token or not validate_token(token):
                    return JSONResponse(
                        status_code=401,
                        content={
                            "code": 40101,
                            "message": "Unauthorized: Invalid or missing token",
                            "data": None,
                        },
                    )

                return await call_next(request)

        return AuthMiddlewareFallback


AuthMiddleware = _build_auth_middleware_class()


# ===========================================================================
# 速率限制中间件（保留旧 API）
# ===========================================================================

def _build_rate_limit_middleware_class():
    """构建 RateLimitMiddleware 类"""

    if _unified_auth_available:
        class RateLimitMiddleware(_UnifiedAuthMiddleware):
            """速率限制中间件（基于统一认证体系）

            仅启用速率限制功能，不做认证检查。
            """

            def __init__(self, app):
                super().__init__(
                    app,
                    rate_limiter=rate_limiter._limiter if hasattr(rate_limiter, '_limiter') else None,
                    rate_limit_by="ip",
                    enabled=True,
                    require_auth=False,  # 不强制认证，仅限流
                    public_paths=[],  # 所有路径都限流
                )

            async def dispatch(self, request, call_next):
                # 仅做速率限制，不做认证
                client_ip = request.client.host if request.client else "unknown"
                rate_key = f"ip:{client_ip}"

                if hasattr(rate_limiter, '_limiter'):
                    allowed, remaining, window = rate_limiter._limiter.check(rate_key)
                    if not allowed:
                        return JSONResponse(
                            status_code=429,
                            content={
                                "code": 42901,
                                "message": "Too Many Requests",
                                "data": {"retry_after": 60},
                            },
                            headers={
                                "X-RateLimit-Limit": str(rate_limiter.max_requests),
                                "X-RateLimit-Remaining": "0",
                                "Retry-After": "60",
                            },
                        )

                    response = await call_next(request)
                    response.headers["X-RateLimit-Limit"] = str(rate_limiter.max_requests)
                    response.headers["X-RateLimit-Remaining"] = str(remaining)
                    return response

                # 兜底：直接放行
                return await call_next(request)

        return RateLimitMiddleware

    else:
        class RateLimitMiddlewareFallback(BaseHTTPMiddleware):
            """速率限制中间件（回退实现）"""

            async def dispatch(self, request: Request, call_next):
                client_ip = request.client.host if request.client else "unknown"
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

        return RateLimitMiddlewareFallback


RateLimitMiddleware = _build_rate_limit_middleware_class()
