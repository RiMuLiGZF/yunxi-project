"""用户上下文管理模块.

基于 contextvars 实现请求级别的用户 ID 上下文传递，
解决用户 ID 硬编码为 "default" 的系统性问题。

使用方式：
    from src.common.user_context import get_current_user_id, set_current_user_id

    # 在请求入口设置
    set_current_user_id("user_123")

    # 在业务代码中获取（无需层层传递 user_id 参数）
    user_id = get_current_user_id()

向后兼容：
    - 未设置时 get_current_user_id() 返回 "default"
    - 所有现有代码无需修改即可继续工作
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Optional

from src.common.constants import DEFAULT_USER_ID

# ---------------------------------------------------------------------------
# 上下文变量
# ---------------------------------------------------------------------------

#: 当前请求的用户 ID（contextvars 保证线程/协程安全）
_current_user_id: ContextVar[Optional[str]] = ContextVar(
    "current_user_id",
    default=None,
)

# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------


def get_current_user_id() -> str:
    """获取当前用户 ID.

    未设置时返回 DEFAULT_USER_ID（即 "default"），保持向后兼容。

    Returns:
        当前用户 ID 字符串
    """
    user_id = _current_user_id.get()
    return user_id or DEFAULT_USER_ID


def set_current_user_id(user_id: str) -> None:
    """设置当前用户 ID.

    Args:
        user_id: 要设置的用户 ID
    """
    _current_user_id.set(user_id)


def clear_current_user_id() -> None:
    """清除当前用户 ID.

    请求结束时调用，避免上下文泄漏。
    """
    _current_user_id.set(None)


def has_user_context() -> bool:
    """检查当前是否有设置用户上下文.

    Returns:
        True 表示已显式设置用户 ID，False 表示使用默认值
    """
    return _current_user_id.get() is not None


__all__ = [
    "get_current_user_id",
    "set_current_user_id",
    "clear_current_user_id",
    "has_user_context",
]
