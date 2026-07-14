"""M9 API 统一响应工具"""

from typing import Any, Optional, List, Dict
from ..models.errors import ErrorCode, M9Exception, http_from_error


def success_response(data: Any = None, message: str = "ok") -> Dict[str, Any]:
    """构造成功响应.

    Args:
        data: 响应数据
        message: 提示消息

    Returns:
        标准响应字典
    """
    return {"code": 0, "message": message, "data": data}


def error_response(code: ErrorCode, message: str = "", detail: str = "") -> Dict[str, Any]:
    """构造错误响应.

    Args:
        code: 错误码
        message: 错误消息
        detail: 详细信息

    Returns:
        错误响应字典
    """
    return {
        "code": code,
        "message": message or code.name,
        "detail": detail,
    }
