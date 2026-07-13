"""
云汐 M9 开发者工坊 - 路径安全工具

防止路径遍历攻击，确保所有文件操作都限制在允许的根目录内。
"""

import os
from pathlib import Path
from typing import Optional


def safe_join(root_dir: str, *paths: str) -> Optional[str]:
    """安全拼接路径，确保结果在 root_dir 内.

    Args:
        root_dir: 允许的根目录（绝对路径）
        *paths: 要拼接的路径段

    Returns:
        安全的绝对路径，如果路径越界返回 None

    示例:
        >>> safe_join("/home/user/projects", "myproject", "src/main.py")
        "/home/user/projects/myproject/src/main.py"
        >>> safe_join("/home/user/projects", "../../etc/passwd")
        None
    """
    # 规范化根目录
    root = os.path.realpath(root_dir)

    # 拼接路径
    target = os.path.realpath(os.path.join(root, *paths))

    # 确保目标路径在根目录内
    if not target.startswith(root + os.sep) and target != root:
        return None

    return target


def is_path_safe(root_dir: str, target_path: str) -> bool:
    """检查目标路径是否在根目录内.

    Args:
        root_dir: 允许的根目录
        target_path: 要检查的路径

    Returns:
        True 表示安全，False 表示越界
    """
    root = os.path.realpath(root_dir)
    target = os.path.realpath(target_path)
    return target.startswith(root + os.sep) or target == root


def sanitize_filename(filename: str) -> str:
    """清理文件名，移除危险字符.

    Args:
        filename: 原始文件名

    Returns:
        清理后的安全文件名
    """
    # 移除路径分隔符
    filename = filename.replace("/", "_").replace("\\", "_")
    # 移除开头的点（隐藏文件）
    filename = filename.lstrip(".")
    # 限制长度
    if len(filename) > 255:
        name, ext = os.path.splitext(filename)
        filename = name[:255 - len(ext)] + ext
    # 如果为空，给个默认名
    if not filename:
        filename = "unnamed"
    return filename


class PathSecurityError(Exception):
    """路径安全异常"""
    pass


def assert_path_safe(root_dir: str, target_path: str, operation: str = "operation"):
    """断言路径安全，不安全则抛出异常.

    Args:
        root_dir: 允许的根目录
        target_path: 要检查的路径
        operation: 操作名称（用于错误消息）

    Raises:
        PathSecurityError: 路径越界时抛出
    """
    if not is_path_safe(root_dir, target_path):
        raise PathSecurityError(
            f"Path traversal detected: {operation} on '{target_path}' "
            f"is outside allowed root '{root_dir}'"
        )
