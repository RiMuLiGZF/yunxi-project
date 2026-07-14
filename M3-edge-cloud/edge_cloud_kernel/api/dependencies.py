"""API 依赖注入.

提供 FastAPI 路由中使用的依赖项，包括：
- 获取 KernelManager 实例
- 获取 trace_id
- M8 Token 鉴权
"""

from __future__ import annotations

import os
import hmac
from typing import Any

import structlog
from fastapi import Header, HTTPException, Request

from edge_cloud_kernel.core.kernel_manager import KernelManager

logger = structlog.get_logger(__name__)


def get_kernel_manager(request: Request) -> KernelManager:
    """从 request state 中获取 KernelManager 实例.

    Args:
        request: FastAPI 请求对象.

    Returns:
        KernelManager 实例.

    Raises:
        RuntimeError: KernelManager 未初始化.
    """
    kernel: KernelManager | None = getattr(request.state, "kernel_manager", None)
    if kernel is None:
        raise RuntimeError("KernelManager not initialized in request state")
    return kernel


def get_trace_id(request: Request) -> str:
    """从 request state 中获取 trace_id.

    Args:
        request: FastAPI 请求对象.

    Returns:
        trace_id 字符串.
    """
    return getattr(request.state, "trace_id", "")


def _get_m8_expected_token() -> str:
    """从环境变量读取 M8 标准接口的预期 Token.

    优先级：M3_M8_TOKEN > M8_TOKEN > M3_ADMIN_TOKEN（向后兼容）.

    Returns:
        预期的 Token 字符串，未配置则返回空字符串.
    """
    return (
        os.environ.get("M3_M8_TOKEN", "")
        or os.environ.get("M8_TOKEN", "")
        or os.environ.get("M3_ADMIN_TOKEN", "")
    )


def verify_m8_token(
    x_m8_token: str = Header(default="", alias="X-M8-Token"),
    authorization: str = Header(default=""),
) -> bool:
    """验证 M8 标准接口的 Token.

    支持两种 Token 传递方式：
    1. 请求头 X-M8-Token（M8 标准方式）
    2. 请求头 Authorization: Bearer <token>（通用方式）

    Token 从环境变量 M3_M8_TOKEN 或 M8_TOKEN 读取，
    向后兼容 M3_ADMIN_TOKEN。使用 hmac.compare_digest 进行安全比较，
    防止时序攻击。

    Args:
        x_m8_token: 请求头 X-M8-Token 中的 Token.
        authorization: 请求头 Authorization 中的 Bearer Token.

    Returns:
        验证是否通过.

    Raises:
        HTTPException: Token 无效时抛出 401.
    """
    expected = _get_m8_expected_token()
    if not expected:
        # 未配置 token 时放行（开发/测试模式）
        logger.debug("m8_token.not_configured_pass_through")
        return True

    # 提取 Token：优先 X-M8-Token，其次 Authorization Bearer
    provided = x_m8_token
    if not provided and authorization:
        parts = authorization.split(" ", 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            provided = parts[1].strip()

    if not provided:
        logger.warning("m8_token.missing", path="m8_endpoint")
        raise HTTPException(status_code=401, detail="M8 token required")

    if not hmac.compare_digest(provided, expected):
        logger.warning("m8_token.invalid", path="m8_endpoint")
        raise HTTPException(status_code=401, detail="Invalid M8 token")

    logger.debug("m8_token.verified")
    return True
