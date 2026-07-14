"""
M10 API 统一响应工具."""

from ..models import make_response


def success(data=None, message: str = "ok"):
    """构造成功响应."""
    return make_response(data=data, message=message)


def error(code: int, message: str, data=None):
    """构造错误响应."""
    return make_response(code=code, message=message, data=data)
