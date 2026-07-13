"""通用响应工具模块.

提供统一的 API 响应格式构造函数。
"""

from __future__ import annotations

from typing import Any


def make_response(
    data: Any = None,
    code: int = 0,
    message: str = "success",
) -> dict[str, Any]:
    """构造统一响应格式.

    Args:
        data: 响应数据
        code: 状态码（0 表示成功）
        message: 状态消息

    Returns:
        统一格式的响应字典
    """
    return {
        "code": code,
        "message": message,
        "data": data if data is not None else {},
    }
