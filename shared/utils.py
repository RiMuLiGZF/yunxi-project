"""
云汐系统通用工具函数模块
提供常用的工具函数，供各模块复用
"""

import os
import secrets
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def generate_id(length: int = 16) -> str:
    """生成随机十六进制 ID

    使用加密安全的随机数生成器，生成指定长度的十六进制字符串。

    Args:
        length: ID 长度（字符数），默认 16

    Returns:
        随机十六进制字符串

    Examples:
        >>> generate_id(8)
        'a1b2c3d4'
        >>> generate_id()
        'a1b2c3d4e5f6a7b8'
    """
    if length <= 0:
        raise ValueError("length 必须为正整数")
    # token_hex(n) 生成 2*n 个字符的十六进制字符串
    num_bytes = (length + 1) // 2
    return secrets.token_hex(num_bytes)[:length]


def now_timestamp() -> int:
    """获取当前 Unix 时间戳（秒）

    Returns:
        当前时间戳（整数秒）

    Examples:
        >>> now_timestamp()
        1720000000
    """
    return int(time.time())


def now_iso() -> str:
    """获取当前 ISO 格式时间字符串（UTC）

    Returns:
        ISO 8601 格式的时间字符串，带时区信息

    Examples:
        >>> now_iso()
        '2026-07-12T10:30:00+00:00'
    """
    return datetime.now(timezone.utc).isoformat()


def safe_get(
    dict_obj: Optional[Dict[str, Any]],
    key: str,
    default: Any = None,
) -> Any:
    """安全获取字典值

    当字典为 None 或键不存在时，返回默认值，避免抛出异常。

    Args:
        dict_obj: 字典对象，允许为 None
        key: 要获取的键名
        default: 默认值，键不存在时返回

    Returns:
        字典中键对应的值，或默认值

    Examples:
        >>> safe_get({"a": 1}, "a")
        1
        >>> safe_get({"a": 1}, "b", 0)
        0
        >>> safe_get(None, "a")
        None
    """
    if dict_obj is None:
        return default
    return dict_obj.get(key, default)


def truncate_text(text: str, max_length: int = 100) -> str:
    """截断文本，超出部分用省略号表示

    Args:
        text: 原始文本
        max_length: 最大长度（含省略号），默认 100

    Returns:
        截断后的文本。如果原文本长度不超过 max_length，原样返回。

    Examples:
        >>> truncate_text("hello", 10)
        'hello'
        >>> truncate_text("hello world", 8)
        'hello...'
    """
    if text is None:
        return ""
    if max_length <= 3:
        raise ValueError("max_length 必须大于 3（需容纳省略号）")
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def format_file_size(bytes_size: int) -> str:
    """格式化文件大小为可读字符串

    自动选择合适的单位（B / KB / MB / GB / TB），保留两位小数。

    Args:
        bytes_size: 文件大小（字节数）

    Returns:
        带单位的可读大小字符串

    Examples:
        >>> format_file_size(0)
        '0 B'
        >>> format_file_size(1024)
        '1.00 KB'
        >>> format_file_size(1048576)
        '1.00 MB'
        >>> format_file_size(1073741824)
        '1.00 GB'
    """
    if bytes_size < 0:
        return "0 B"
    if bytes_size == 0:
        return "0 B"

    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(bytes_size)
    unit_index = 0

    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1

    if unit_index == 0:
        return f"{int(size)} {units[unit_index]}"
    return f"{size:.2f} {units[unit_index]}"
