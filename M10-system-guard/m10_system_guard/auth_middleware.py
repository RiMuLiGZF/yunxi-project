"""
M10 系统卫士 - API 认证中间件

**已升级到统一认证体系**：本模块内部使用 shared.core.auth 提供的
统一认证中间件，保留原有接口以保证向后兼容。

保护 /api/v1/* 所有业务接口，使用 M10_ADMIN_TOKEN 验证。
支持多种认证方式：X-M10-Token / X-M8-Token / Authorization: Bearer
"""

import os
import hmac
import structlog
from typing import Optional, Dict, Any, List

logger = structlog.get_logger("m10.auth")

# ===========================================================================
# 从统一认证模块导入（优先使用，不可用时回退）
# ===========================================================================

try:
    from shared.core.auth import (
        UnifiedAuthMiddleware as _UnifiedAuthMiddleware,
        ApiKeyValidator as _ApiKeyValidator,
        InMemoryApiKeyStore as _InMemoryApiKeyStore,
        ApiKeyInfo as _ApiKeyInfo,
        hash_api_key_sha256 as _hash_api_key_sha256,
    )
    _unified_auth_available = True
except ImportError:
    _unified_auth_available = False
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import JSONResponse


def get_admin_token() -> str:
    """获取管理员 Token."""
    return os.environ.get("M10_ADMIN_TOKEN", "")


def verify_token(token: str) -> bool:
    """安全验证 Token，使用 hmac.compare_digest 防止时序攻击.

    Args:
        token: 请求中携带的令牌.

    Returns:
        True 表示验证通过.
    """
    expected = get_admin_token()
    if not expected:
        logger.warning(
            "m10.auth.token_not_configured",
            message="M10_ADMIN_TOKEN 未配置，所有业务接口鉴权将被拒绝",
        )
        return False
    # 拒绝空 Token，防止空值绕过
    if not token:
        return False
    return hmac.compare_digest(token, expected)


# ===========================================================================
# 认证中间件（保留旧 API，内部使用统一认证）
# ===========================================================================

def _build_m10_auth_middleware_class():
    """构建 M10AuthMiddleware 类（优先使用统一认证）"""

    if _unified_auth_available:
        # 使用统一认证体系
        _store = _InMemoryApiKeyStore()
        _token = get_admin_token()
        if _token:
            _store.add_key(_ApiKeyInfo(
                key_hash=_hash_api_key_sha256(_token),
                key_name="m10-admin",
                roles=["admin"],
                scopes=["*"],
            ))
        _validator = _ApiKeyValidator(_store, use_bcrypt=False)

        class M10AuthMiddleware(_UnifiedAuthMiddleware):
            """M10 API 认证中间件（基于统一认证体系）

            保护所有 /api/v1/* 接口，支持多种认证方式。
            以下路径豁免：
            - /health
            - /m8/* （M8 标准接口有自己的认证）
            - /docs, /openapi.json, /redoc
            """

            EXEMPT_PREFIXES = (
                "/health",
                "/m8/",
                "/docs",
                "/openapi.json",
                "/redoc",
                "/favicon.ico",
            )

            def __init__(self, app):
                # 动态获取当前 Token（支持运行时配置变更）
                token = get_admin_token()
                if token:
                    key_hash = _hash_api_key_sha256(token)
                    existing = _store.find_by_hash(key_hash)
                    if not existing:
                        _store.add_key(_ApiKeyInfo(
                            key_hash=key_hash,
                            key_name="m10-admin",
                            roles=["admin"],
                            scopes=["*"],
                        ))

                super().__init__(
                    app,
                    api_key_validator=_validator,
                    api_key_header_names=[
                        "X-M10-Token",
                        "X-M8-Token",
                        "X-API-Key",
                    ],
                    public_paths=list(self.EXEMPT_PREFIXES) + ["/m8/*"],
                    enabled=True,
                    require_auth=False,  # 非 /api/v1/* 路径不强制认证
                    fallback_mode="strict",
                )

            async def dispatch(self, request, call_next):
                path = request.url.path

                # 公开路径直接放行（交给父类处理，会设置匿名用户信息）
                # 非 /api/v1/* 路径：不强制认证，可选认证
                if not path.startswith("/api/v1/"):
                    # 非 API 路径：先尝试认证（设置 user 信息），失败也放行
                    original_require = self.require_auth
                    self.require_auth = False
                    try:
                        return await super().dispatch(request, call_next)
                    finally:
                        self.require_auth = original_require

                # /api/v1/* 路径：强制认证
                original_require = self.require_auth
                self.require_auth = True
                try:
                    return await super().dispatch(request, call_next)
                finally:
                    self.require_auth = original_require

        return M10AuthMiddleware

    else:
        # 旧实现（兜底）
        class M10AuthMiddlewareFallback(BaseHTTPMiddleware):
            """M10 API 认证中间件（回退实现）

            保护所有 /api/v1/* 接口，要求 X-M10-Token 或 Authorization: Bearer header。
            """

            EXEMPT_PREFIXES = (
                "/health",
                "/m8/",
                "/docs",
                "/openapi.json",
                "/redoc",
                "/favicon.ico",
            )

            async def dispatch(self, request: Request, call_next):
                path = request.url.path

                for prefix in self.EXEMPT_PREFIXES:
                    if path.startswith(prefix):
                        return await call_next(request)

                if not path.startswith("/api/v1/"):
                    return await call_next(request)

                token = ""

                m10_token = request.headers.get("x-m10-token", "")
                if m10_token:
                    token = m10_token

                auth_header = request.headers.get("authorization", "")
                if auth_header.startswith("Bearer "):
                    token = auth_header[7:]

                if not token:
                    m8_token = request.headers.get("x-m8-token", "")
                    if m8_token:
                        token = m8_token

                if not token:
                    logger.warning("m10.auth.no_token_provided", path=path)
                    return JSONResponse(
                        status_code=401,
                        content={
                            "code": 401,
                            "message": "未提供认证 Token",
                            "data": None,
                        },
                    )

                if not verify_token(token):
                    logger.warning("m10.auth.token_invalid", path=path)
                    return JSONResponse(
                        status_code=401,
                        content={
                            "code": 401,
                            "message": "Token 无效",
                            "data": None,
                        },
                    )

                return await call_next(request)

        return M10AuthMiddlewareFallback


M10AuthMiddleware = _build_m10_auth_middleware_class()


# ===========================================================================
# Depends 风格认证依赖（保留旧 API）
# ===========================================================================

async def require_m10_token(x_m10_token: str = ""):
    """FastAPI Depends 风格的认证依赖.

    注意：这是兼容层，新代码建议使用 shared.core.auth 中的
    create_auth_dependency 或 create_token_header_dependency。
    """
    from fastapi import Header, HTTPException

    if not verify_token(x_m10_token):
        raise HTTPException(status_code=401, detail="Token 无效")
    return True
