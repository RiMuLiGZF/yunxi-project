"""M8 管理平台 Token 鉴权中间件.

提供统一的 M8 管理接口鉴权机制，与 M2 实现保持一致。
Token 从环境变量 M3_ADMIN_TOKEN 读取。
"""

from __future__ import annotations

import hmac
import os
from typing import Any

import structlog

from edge_cloud_kernel.m8_api.error_codes import ERR_AUTH_TOKEN_INVALID, ERR_AUTH_REQUIRED

logger = structlog.get_logger(__name__)

# 白名单：不需要鉴权的接口路径
WHITE_LIST_PATHS = {
    "/api/v3/health",
}

# 错误码 30500 对应鉴权错误（复用 ERR_AUTH_REQUIRED）
AUTH_ERROR_CODE = ERR_AUTH_REQUIRED.code
AUTH_ERROR_MSG = ERR_AUTH_REQUIRED.message


class M8TokenAuthMiddleware:
    """M8 管理平台 Token 鉴权中间件.

    实现基于 Bearer Token 的鉴权机制：
    - Token 从环境变量 M3_ADMIN_TOKEN 读取
    - 白名单路径（如 /health）跳过鉴权
    - 使用 hmac.compare_digest 安全比较，防止时序攻击
    - 生产环境未配置 Token 则拒绝启动

    Attributes:
        _expected_token: 预期的管理令牌.
        _env_mode: 运行模式（production/development）.
    """

    def __init__(
        self,
        token_env_var: str = "M3_ADMIN_TOKEN",
        env: str = "production",
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
                f"[M3] 生产环境必须配置 {token_env_var} 环境变量"
            )

        if not self._expected_token:
            logger.warning(
                "m8_auth.token_not_configured",
                env=env,
                message=f"{token_env_var} not set, auth will reject all requests",
            )
        else:
            logger.info(
                "m8_auth.initialized",
                env=env,
                whitelist_count=len(WHITE_LIST_PATHS),
            )

    def is_whitelisted(self, path: str) -> bool:
        """判断路径是否在白名单中.

        Args:
            path: 请求路径，如 /api/v3/health.

        Returns:
            True 表示白名单，跳过鉴权.
        """
        # 支持带查询参数的路径
        clean_path = path.split("?")[0]
        return clean_path in WHITE_LIST_PATHS

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
        """从 HTTP 请求头中提取 Bearer Token.

        Args:
            headers: 请求头字典.

        Returns:
            提取的 Token，空字符串表示未找到.
        """
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
            logger.debug("m8_auth.whitelisted", path=path)
            return True, 0, "success"

        # 提取 Token
        token = self.extract_token_from_headers(headers)
        if not token:
            logger.warning("m8_auth.missing_token", path=path)
            return False, ERR_AUTH_REQUIRED.code, ERR_AUTH_REQUIRED.message

        # 验证 Token
        if self.verify_token(token):
            logger.debug("m8_auth.success", path=path)
            return True, 0, "success"
        else:
            logger.warning("m8_auth.invalid_token", path=path)
            return False, ERR_AUTH_TOKEN_INVALID.code, ERR_AUTH_TOKEN_INVALID.message

    @property
    def is_configured(self) -> bool:
        """Token 是否已配置."""
        return bool(self._expected_token)

    @property
    def env_mode(self) -> str:
        """运行模式."""
        return self._env_mode
