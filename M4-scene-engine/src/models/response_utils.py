"""通用响应工具模块.

提供统一的 API 响应格式构造函数。

迁移说明：
    已升级为 5 字段标准格式（code/message/data/trace_id/timestamp）。
    新代码建议直接使用 shared.unified_response.ok / fail。
"""

from __future__ import annotations

import time
from typing import Any


def make_response(
    data: Any = None,
    code: int = 0,
    message: str = "success",
) -> dict[str, Any]:
    """构造统一响应格式（5 字段标准格式）.

    Args:
        data: 响应数据
        code: 状态码（0 表示成功）
        message: 状态消息

    Returns:
        标准格式的响应字典
    """
    return {
        "code": code,
        "message": message,
        "data": data if data is not None else {},
        "trace_id": None,
        "timestamp": time.time(),
    }
