"""M8 管理平台 Token 鉴权中间件.

提供统一的 M8 管理接口鉴权机制。
Token 从环境变量 M4_ADMIN_TOKEN 读取。
Header: X-M8-Token
"""

from __future__ import annotations

import hmac
import os
from typing import Any

# 白名单：不需要鉴权的接口路径
WHITE_LIST_PATHS = {
    "/health",
    "/api/v1/admin/health",
    "/docs",
    "/openapi.json",
    "/",
    "/redoc",
}

# 鉴权错误码
AUTH_ERROR_CODE = 40101
AUTH_ERROR_MSG = "未授权：缺少或无效的访问令牌"
AUTH_REQUIRED_MSG = "未授权：请在请求头中提供 X-M8-Token"


class M8TokenAuthMiddleware:
    """M8 管理平台 Token 鉴权中间件.

    实现基于 Header Token 的鉴权机制：
    - Token 从环境变量 M4_ADMIN_TOKEN 读取
    - 白名单路径跳过鉴权
    - 使用 hmac.compare_digest 安全比较，防止时序攻击
    - 生产环境未配置 Token 则拒绝启动

    Attributes:
        _expected_token: 预期的管理令牌.
        _env_mode: 运行模式（production/development）.
    """

    def __init__(
        self,
        token_env_var: str = "M4_ADMIN_TOKEN",
        env: str = "development",
    ) -> None:
        """初始化鉴权中间件.

        Args:
            token_env_var: Token 环境变量名.
            env: 运行模式，production 未配置 Token 则报错.

        Raises:
            RuntimeError: 生产环境未配置 Token.
        """
        self._expected_token = os.environ.get(token_env_var, "")
        self._env_mode = env
        self._token_env_var = token_env_var

        if env == "production" and not self._expected_token:
            raise RuntimeError(
                f"[M4] 生产环境必须配置 {token_env_var} 环境变量"
            )

        if not self._expected_token:
            # 开发环境默认 Token
            self._expected_token = os.environ.get(token_env_var, "m4-dev-token")
            self._env_mode = env

    def is_whitelisted(self, path: str) -> bool:
        """判断路径是否在白名单中.

        Args:
            path: 请求路径，如 /health.

        Returns:
            True 表示白名单，跳过鉴权.
        """
        # 支持带查询参数的路径
        clean_path = path.split("?")[0]

        # 精确匹配
        if clean_path in WHITE_LIST_PATHS:
            return True

        # 前缀匹配（/docs 开头的都放行，包括 /docs/oauth2-redirect 等）
        for wp in WHITE_LIST_PATHS:
            if wp.endswith("/") and clean_path.startswith(wp):
                return True

        return False

    def verify_token(self, token: str) -> bool:
        """验证 M8 管理令牌.

        使用 hmac.compare_digest 进行安全比较，防止时序攻击。

        Args:
            token: 请求中携带的令牌.

        Returns:
            True 表示验证通过.
        """
        if not self._expected_token:
            return False
        if not token:
            return False
        return hmac.compare_digest(token, self._expected_token)

    def extract_token_from_headers(self, headers: dict[str, Any]) -> str:
        """从 HTTP 请求头中提取 Token.

        支持的 Header：
        - X-M8-Token: <token>
        - Authorization: Bearer <token>

        Args:
            headers: 请求头字典.

        Returns:
            提取的 Token，空字符串表示未找到.
        """
        # 优先检查 X-M8-Token
        for key in ("X-M8-Token", "x-m8-token", "X-M8-token", "x-M8-Token"):
            if key in headers:
                token = headers[key]
                if isinstance(token, str):
                    return token.strip()

        # 其次检查 Authorization: Bearer
        auth_header = ""
        for key in ("Authorization", "authorization"):
            if key in headers:
                auth_header = headers[key]
                break

        if not auth_header:
            return ""

        parts = auth_header.split(" ", 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1].strip()

        return ""

    def check_auth(self, path: str, headers: dict[str, Any]) -> tuple[bool, int, str]:
        """完整的鉴权检查.

        Args:
            path: 请求路径.
            headers: 请求头.

        Returns:
            (是否通过, 错误码, 错误信息). 通过时错误码为 0.
        """
        # 白名单直接放行
        if self.is_whitelisted(path):
            return True, 0, "success"

        # 提取 Token
        token = self.extract_token_from_headers(headers)
        if not token:
            return False, AUTH_ERROR_CODE, AUTH_REQUIRED_MSG

        # 验证 Token
        if self.verify_token(token):
            return True, 0, "success"
        else:
            return False, AUTH_ERROR_CODE, AUTH_ERROR_MSG

    @property
    def is_configured(self) -> bool:
        """Token 是否已配置."""
        return bool(self._expected_token)

    @property
    def env_mode(self) -> str:
        """运行模式."""
        return self._env_mode
