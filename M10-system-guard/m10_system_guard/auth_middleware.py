"""
M10 系统卫士 - API 认证中间件

保护 /api/v1/* 所有业务接口，使用 M10_ADMIN_TOKEN 验证。
使用 hmac.compare_digest 进行安全比较，防止时序攻击。
"""

import os
import hmac
import structlog
from fastapi import Request, HTTPException, Header
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = structlog.get_logger("m10.auth")


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


class M10AuthMiddleware(BaseHTTPMiddleware):
    """M10 API 认证中间件

    保护所有 /api/v1/* 接口，要求 X-M10-Token 或 Authorization: Bearer header。
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


async def require_m10_token(x_m10_token: str = Header(default="")):
    """FastAPI Depends 风格的认证依赖."""
    if not verify_token(x_m10_token):
        raise HTTPException(status_code=401, detail="Token 无效")
    return True
