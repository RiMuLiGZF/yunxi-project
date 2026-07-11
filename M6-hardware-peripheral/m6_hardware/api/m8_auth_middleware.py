"""
M8 统一鉴权中间件
- 白名单路径直接放行
- 其余路径校验 X-M8-Token 或 Authorization: Bearer <token>
- 使用 hmac.compare_digest 防时序攻击
- 生产环境强制要求配置 token
"""

import os
import hmac
import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


# 白名单路径（无需鉴权即可访问）
WHITELIST_PATHS = [
    "/health",
    "/api/v1/health",
    "/m8/health",
    "/docs",
    "/docs/",
    "/openapi.json",
    "/redoc",
    "/favicon.ico",
    "/sse/stream",  # SSE 流暂不鉴权（需客户端支持 header）
]

# 白名单前缀（以这些前缀开头的路径放行）
WHITELIST_PREFIXES = [
    "/docs/",
    "/static/",
]


def is_whitelisted(path: str) -> bool:
    """检查路径是否在白名单中"""
    if path in WHITELIST_PATHS:
        return True
    for prefix in WHITELIST_PREFIXES:
        if path.startswith(prefix):
            return True
    # SSE 特殊处理
    if path.startswith("/api/v1/sse/"):
        return True
    return False


def _get_expected_token() -> str:
    """获取预期的管理员 Token"""
    # 优先从环境变量读取
    token = os.environ.get("M6_ADMIN_TOKEN", "")
    if token:
        return token
    # 开发环境默认 token（打印警告）
    env = os.environ.get("M6_ENV", os.environ.get("YUNXI_ENV", "development"))
    if env == "production":
        raise RuntimeError("生产环境必须配置 M6_ADMIN_TOKEN 环境变量")
    default_token = "yunxi-m6-dev-token"
    print(f"[WARNING] 未配置 M6_ADMIN_TOKEN，开发环境使用默认 token: {default_token}")
    return default_token


def _verify_token(token: str) -> bool:
    """安全验证 token（防时序攻击）"""
    expected = _get_expected_token()
    if not expected or not token:
        return False
    return hmac.compare_digest(token, expected)


def _extract_token(request: Request) -> str:
    """从请求中提取 token

    优先级：
    1. X-M8-Token 请求头
    2. Authorization: Bearer <token>
    3. query 参数 token=（仅开发环境）
    """
    # 1. X-M8-Token header
    token = request.headers.get("x-m8-token", "")
    if token:
        return token

    # 2. Authorization: Bearer <token>
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]

    # 3. query 参数（仅开发环境）
    env = os.environ.get("M6_ENV", os.environ.get("YUNXI_ENV", "development"))
    if env != "production":
        token = request.query_params.get("token", "")
        if token:
            return token

    return ""


class M8AuthMiddleware(BaseHTTPMiddleware):
    """M8 统一鉴权中间件"""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # 白名单直接放行
        if is_whitelisted(path):
            return await call_next(request)

        # 提取并验证 token
        token = _extract_token(request)
        if not token:
            request_id = uuid.uuid4().hex[:16]
            return JSONResponse(
                status_code=401,
                content={
                    "code": 40100,
                    "message": "未提供认证令牌",
                    "data": None,
                    "request_id": request_id,
                },
            )

        if not _verify_token(token):
            request_id = uuid.uuid4().hex[:16]
            return JSONResponse(
                status_code=401,
                content={
                    "code": 40101,
                    "message": "认证令牌无效",
                    "data": None,
                    "request_id": request_id,
                },
            )

        # Token 验证通过，继续处理
        response = await call_next(request)
        return response


# 便捷函数：获取当前用户（简化版，后续可扩展）
def get_current_user(request: Request) -> dict:
    """获取当前认证用户信息"""
    return {
        "id": 1,
        "username": "admin",
        "role": "admin",
        "authenticated": True,
    }
