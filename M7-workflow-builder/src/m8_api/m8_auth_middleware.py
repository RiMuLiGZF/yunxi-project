"""M8 管理平台 Token 鉴权中间件.

基于 X-M8-Token 请求头的鉴权机制，与 M8 控制塔保持一致。
Token 从环境变量 M7_ADMIN_TOKEN 读取。
"""

from __future__ import annotations

import hmac
import os
import uuid
from typing import Optional

from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


# 白名单：不需要鉴权的接口路径
WHITE_LIST_PATHS = {
    "/health",
    "/api/v1/health",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/favicon.ico",
}


class M8AuthMiddleware(BaseHTTPMiddleware):
    """M8 Token 鉴权中间件.

    使用 X-M8-Token 请求头进行鉴权：
    - Token 从环境变量 M7_ADMIN_TOKEN 读取
    - 白名单路径（如 /health, /docs）跳过鉴权
    - 使用 hmac.compare_digest 安全比较，防止时序攻击

    环境变量:
        M7_ADMIN_TOKEN: 管理令牌
        M7_ENV: 运行模式（production/development），默认 development
    """

    def __init__(self, app, token_env_var: str = "M7_ADMIN_TOKEN"):
        super().__init__(app)
        self._expected_token = os.environ.get(token_env_var, "")
        self._env_mode = os.environ.get("M7_ENV", "development")
        self._token_env_var = token_env_var

        if self._env_mode == "production" and not self._expected_token:
            raise RuntimeError(
                f"[M7] 生产环境必须配置 {token_env_var} 环境变量"
            )

        if not self._expected_token:
            print(
                f"[M7] 警告: {token_env_var} 未配置，开发模式下将使用默认 token"
            )
            # 开发模式下使用默认 token
            self._expected_token = "m7-dev-token-default"

    def is_whitelisted(self, path: str) -> bool:
        """判断路径是否在白名单中.

        Args:
            path: 请求路径（不含查询参数）

        Returns:
            True 表示白名单，跳过鉴权
        """
        # 支持带查询参数的路径
        clean_path = path.split("?")[0]
        # 白名单精确匹配
        if clean_path in WHITE_LIST_PATHS:
            return True
        # 支持 /docs 下的子路径
        if clean_path.startswith("/docs/"):
            return True
        # 支持 /openapi.json 等
        return False

    def verify_token(self, token: str) -> bool:
        """验证 M8 管理令牌.

        使用 hmac.compare_digest 进行安全比较，防止时序攻击。

        Args:
            token: 请求中携带的令牌

        Returns:
            True 表示验证通过
        """
        if not self._expected_token:
            return False
        if not token:
            return False
        return hmac.compare_digest(token, self._expected_token)

    def extract_token(self, request: Request) -> str:
        """从请求中提取 Token.

        优先从 X-M8-Token 头提取，其次从 Authorization Bearer 提取。

        Args:
            request: FastAPI 请求对象

        Returns:
            提取的 Token，空字符串表示未找到
        """
        # 优先 X-M8-Token 头
        token = request.headers.get("X-M8-Token", "")
        if token:
            return token.strip()

        # 其次 Authorization Bearer
        auth_header = request.headers.get("Authorization", "")
        if auth_header:
            parts = auth_header.split(" ", 1)
            if len(parts) == 2 and parts[0].lower() == "bearer":
                return parts[1].strip()

        # 还可以从 query 参数获取（仅限开发环境）
        if self._env_mode != "production":
            token = request.query_params.get("token", "")
            if token:
                return token.strip()

        return ""

    async def dispatch(self, request: Request, call_next):
        """中间件主逻辑."""
        path = request.url.path

        # 白名单直接放行
        if self.is_whitelisted(path):
            response = await call_next(request)
            return response

        # 提取并验证 Token
        token = self.extract_token(request)
        if not token:
            request_id = uuid.uuid4().hex[:16]
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "code": 40100,
                    "message": "未提供认证令牌，请在 X-M8-Token 请求头中携带",
                    "data": None,
                    "request_id": request_id,
                },
            )

        if not self.verify_token(token):
            request_id = uuid.uuid4().hex[:16]
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "code": 40101,
                    "message": "认证令牌无效",
                    "data": None,
                    "request_id": request_id,
                },
            )

        # 鉴权通过，继续处理
        response = await call_next(request)
        return response

    @property
    def is_configured(self) -> bool:
        """Token 是否已配置."""
        return bool(self._expected_token)

    @property
    def env_mode(self) -> str:
        """运行模式."""
        return self._env_mode


def get_current_user(request: Request) -> dict:
    """获取当前用户信息（从请求上下文中）.

    简化实现：基于 Token 鉴权，返回一个虚拟的 admin 用户。
    后续可扩展为从 Token 中解析用户信息。

    Args:
        request: FastAPI 请求对象

    Returns:
        用户信息字典
    """
    token = request.headers.get("X-M8-Token", "")
    return {
        "username": "admin",
        "role": "admin",
        "authenticated": bool(token),
    }
