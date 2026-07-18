"""用户上下文中间件.

从 HTTP 请求中提取用户 ID 并设置到上下文变量中，
使业务代码可以通过 get_current_user_id() 获取当前用户 ID。

提取优先级（从高到低）：
1. X-User-ID 请求头
2. Authorization Bearer token（预留解析，当前简化实现）
3. 不设置（get_current_user_id() 自动降级为 "default"）

使用方式：
    from src.middleware.user_context import UserContextMiddleware
    app.add_middleware(UserContextMiddleware)
"""

from __future__ import annotations

import base64
import json
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from src.common.user_context import clear_current_user_id, set_current_user_id

import structlog

logger = structlog.get_logger(__name__)

#: 用户 ID 请求头名称
USER_ID_HEADER = "X-User-ID"


class UserContextMiddleware(BaseHTTPMiddleware):
    """用户上下文中间件.

    从请求中提取用户 ID 并设置到 contextvars 上下文，
    请求结束时清理上下文，防止上下文泄漏。
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        """中间件核心逻辑.

        Args:
            request: 请求对象
            call_next: 下一个处理函数

        Returns:
            响应对象
        """
        user_id = self._extract_user_id(request)

        if user_id:
            set_current_user_id(user_id)

        try:
            response = await call_next(request)
            return response
        finally:
            # 确保上下文被清理，防止泄漏
            clear_current_user_id()

    def _extract_user_id(self, request: Request) -> Optional[str]:
        """从请求中提取用户 ID.

        提取顺序：
        1. X-User-ID 请求头（优先级最高）
        2. Authorization Bearer token 中的 sub 字段（预留）

        Args:
            request: 请求对象

        Returns:
            用户 ID 字符串，提取不到返回 None
        """
        # 1. 从 X-User-ID 头提取
        user_id = request.headers.get(USER_ID_HEADER)
        if user_id and user_id.strip():
            return user_id.strip()

        # 2. 从 Authorization Bearer token 中解析（预留实现）
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[len("Bearer "):].strip()
            user_id = self._parse_user_id_from_token(token)
            if user_id:
                return user_id

        return None

    @staticmethod
    def _parse_user_id_from_token(token: str) -> Optional[str]:
        """从 JWT token 中解析用户 ID（简化版）.

        当前实现：尝试解析 JWT payload 中的 sub 字段。
        解析失败时静默返回 None，不影响请求处理。

        Args:
            token: JWT token 字符串

        Returns:
            用户 ID，解析失败返回 None
        """
        try:
            # JWT 格式: header.payload.signature
            parts = token.split(".")
            if len(parts) != 3:
                return None

            # 解析 payload（base64url 解码）
            payload_b64 = parts[1]
            # 补齐 padding
            padding = 4 - len(payload_b64) % 4
            if padding != 4:
                payload_b64 += "=" * padding

            payload_bytes = base64.urlsafe_b64decode(payload_b64)
            payload = json.loads(payload_bytes)

            # 优先使用 sub（subject），其次使用 user_id / uid
            user_id = (
                payload.get("sub")
                or payload.get("user_id")
                or payload.get("uid")
            )

            return str(user_id) if user_id else None

        except Exception:
            # 解析失败不影响主流程
            return None


__all__ = ["UserContextMiddleware"]
