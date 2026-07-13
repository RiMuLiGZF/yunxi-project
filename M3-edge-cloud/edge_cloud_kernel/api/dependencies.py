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

from fastapi import Header, HTTPException, Request

from edge_cloud_kernel.core.kernel_manager import KernelManager


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


def verify_m8_token(x_m8_token: str = Header(default="")) -> bool:
    """验证 M8 标准接口的 Token.

    Args:
        x_m8_token: 请求头中的 M8 Token.

    Returns:
        验证是否通过.

    Raises:
        HTTPException: Token 无效时抛出 401.
    """
    expected = os.environ.get("M3_ADMIN_TOKEN", "")
    if not expected:
        # 未配置 token 时放行
        return True
    if not hmac.compare_digest(x_m8_token, expected):
        raise HTTPException(status_code=401, detail="Invalid M8 token")
    return True
