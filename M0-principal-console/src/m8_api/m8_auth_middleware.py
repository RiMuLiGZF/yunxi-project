"""
M0 主理人管控台 - M8 认证中间件

提供与 M8 兼容的认证中间件，
确保来自 M8 的内部调用可以正确鉴权。
"""

from __future__ import annotations

from typing import Optional

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from ..config import settings
from ..auth import decode_token


class M8AuthMiddleware(BaseHTTPMiddleware):
    """
    M8 认证中间件

    用于验证来自 M8 控制塔的内部调用请求。
    支持两种认证方式：
    1. Bearer Token（JWT，与 M8 同一套密钥）
    2. X-M8-Internal-Token（内部服务间调用）
    """

    def __init__(self, app, require_auth: bool = False) -> None:
        """
        初始化中间件

        Args:
            app: ASGI 应用
            require_auth: 是否强制要求认证（默认 False，由各路由自己控制）
        """
        super().__init__(app)
        self.require_auth = require_auth

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """
        中间件分发逻辑

        Args:
            request: 请求对象
            call_next: 下一个处理函数

        Returns:
            Response: 响应对象
        """
        # 健康检查和静态文件跳过认证
        path = request.url.path
        if path in ("/health", "/healthz", "/ready") or path.startswith("/static/") or path.startswith("/frontend/"):
            return await call_next(request)

        # 尝试从请求中提取用户信息
        user_info = self._extract_user_info(request)

        # 将用户信息存入 request state，供后续路由使用
        if user_info:
            request.state.user = user_info
        else:
            request.state.user = None

        # 如果强制认证且未获取到用户信息，返回 401
        if self.require_auth and user_info is None:
            return JSONResponse(
                status_code=401,
                content={
                    "code": 40100,
                    "message": "认证失败",
                    "data": None,
                },
            )

        response = await call_next(request)
        return response

    def _extract_user_info(self, request: Request) -> Optional[dict]:
        """
        从请求中提取用户信息

        Args:
            request: 请求对象

        Returns:
            Optional[dict]: 用户信息字典，提取失败返回 None
        """
        # 方式 1: Bearer Token (JWT)
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            try:
                payload = decode_token(token)
                username = payload.get("sub")
                role = payload.get("role", "viewer")
                if username:
                    return {"username": username, "role": role, "auth_type": "jwt"}
            except Exception:
                pass

        # 方式 2: 内部 Token（M8 -> M0 调用）
        internal_token = request.headers.get("X-M8-Internal-Token", "")
        if internal_token and internal_token == settings.jwt_secret:
            return {
                "username": "m8-internal",
                "role": "admin",
                "auth_type": "internal",
            }

        return None


def get_request_user(request: Request) -> Optional[dict]:
    """
    从 request state 中获取用户信息（由中间件注入）

    Args:
        request: FastAPI 请求对象

    Returns:
        Optional[dict]: 用户信息字典
    """
    return getattr(request.state, "user", None)
