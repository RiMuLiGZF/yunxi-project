"""
M10 API 统一响应工具.

迁移说明：
    本模块已接入项目级统一响应标准 shared.unified_response。
    success() / error() 函数现在返回标准格式（含 trace_id 和 timestamp）。
    旧的 3 字段格式（code/message/data）已升级为 5 字段标准格式。

新代码建议直接使用：
    from shared.unified_response import ApiResponse, ok, fail
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# 确保能导入 shared 包
_project_root = Path(__file__).resolve().parents[3]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# 从权威标准导入
try:
    from shared.unified_response import ApiResponse, ok as _ok, fail as _fail

    _unified_available = True
except ImportError:
    _unified_available = False
    from ..models import make_response


def success(data=None, message: str = "ok"):
    """构造成功响应.

    Args:
        data: 响应数据
        message: 状态消息

    Returns:
        标准响应字典（code/message/data/trace_id/timestamp）
    """
    if _unified_available:
        return _ok(data=data, message=message)
    return make_response(data=data, message=message)


def error(code: int, message: str, data=None):
    """构造错误响应.

    Args:
        code: 错误码
        message: 错误消息
        data: 附加数据

    Returns:
        标准响应字典
    """
    if _unified_available:
        return _fail(code=code, message=message, data=data)
    return make_response(code=code, message=message, data=data)
