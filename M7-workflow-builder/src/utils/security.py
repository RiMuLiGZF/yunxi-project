"""M7 安全工具函数.

提供路径安全校验、输入验证等安全相关工具。
"""

from __future__ import annotations

import os
import re
import tempfile
from typing import Optional


# 允许的文件扩展名白名单
ALLOWED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg"}
ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
ALLOWED_TEXT_EXTENSIONS = {".txt", ".md", ".json", ".csv", ".xml", ".yaml", ".yml"}

# 文件名最大长度
MAX_FILENAME_LENGTH = 255


def get_temp_dir() -> str:
    """获取 M7 临时文件目录.

    优先级：
    1. 环境变量 M7_TEMP_DIR
    2. ~/.yunxi/m7_temp/
    3. 系统临时目录下的 m7 子目录

    Returns:
        临时目录绝对路径
    """
    env_dir = os.environ.get("M7_TEMP_DIR")
    if env_dir:
        temp_dir = os.path.expanduser(env_dir)
    else:
        home = os.path.expanduser("~")
        temp_dir = os.path.join(home, ".yunxi", "m7_temp")

    os.makedirs(temp_dir, exist_ok=True)
    return os.path.abspath(temp_dir)


def get_data_dir() -> str:
    """获取 M7 数据目录.

    Returns:
        数据目录绝对路径
    """
    env_path = os.environ.get("M7_DATA_PATH", "~/.yunxi/m7_workflows.json")
    data_path = os.path.expanduser(env_path)
    data_dir = os.path.dirname(data_path)
    if data_dir:
        os.makedirs(data_dir, exist_ok=True)
    return os.path.abspath(data_dir or ".")


def safe_join_path(base_dir: str, user_path: str) -> str:
    """安全地拼接路径，防止路径遍历攻击.

    确保 user_path 被限制在 base_dir 目录内，
    阻止 ../../../etc/passwd 等路径遍历攻击。

    Args:
        base_dir: 基础目录（白名单目录）
        user_path: 用户输入的相对路径

    Returns:
        安全的绝对路径

    Raises:
        ValueError: 路径超出允许范围或格式非法
    """
    if not user_path:
        raise ValueError("路径不能为空")

    base_dir = os.path.abspath(base_dir)

    # 规范化用户路径
    user_path = os.path.normpath(user_path)

    # 拒绝绝对路径
    if os.path.isabs(user_path):
        raise ValueError("不允许使用绝对路径")

    # 去掉开头的路径分隔符
    user_path = user_path.lstrip(os.sep + "/")

    # 拒绝包含 .. 的路径（双重保险）
    if ".." + os.sep in user_path or user_path == "..":
        raise ValueError("路径中不允许包含 '..'")

    # 拼接并规范化
    full_path = os.path.abspath(os.path.join(base_dir, user_path))

    # 最终校验：必须在 base_dir 内
    if not (full_path == base_dir or full_path.startswith(base_dir + os.sep)):
        raise ValueError("路径超出允许的目录范围")

    return full_path


def safe_filename(filename: str, max_length: int = MAX_FILENAME_LENGTH) -> str:
    """清洗文件名，移除危险字符.

    Args:
        filename: 原始文件名
        max_length: 最大长度

    Returns:
        安全的文件名

    Raises:
        ValueError: 文件名为空或清洗后为空
    """
    if not filename:
        raise ValueError("文件名不能为空")

    # 只保留安全字符：字母、数字、下划线、点、横线、中文
    # 移除路径分隔符、控制字符等
    safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', filename)

    # 去掉开头的点（隐藏文件）
    safe_name = safe_name.lstrip('.')

    # 限制长度
    if len(safe_name) > max_length:
        # 保留扩展名
        name, ext = os.path.splitext(safe_name)
        if len(ext) + 10 > max_length:
            ext = ""
        safe_name = name[:max_length - len(ext)] + ext

    if not safe_name or safe_name in {'.', '..'}:
        raise ValueError("无效的文件名")

    return safe_name


def validate_file_extension(file_path: str, allowed_extensions: set[str]) -> bool:
    """校验文件扩展名是否在白名单内.

    Args:
        file_path: 文件路径
        allowed_extensions: 允许的扩展名集合（包含点号，如 {'.wav', '.mp3'}）

    Returns:
        是否允许
    """
    _, ext = os.path.splitext(file_path.lower())
    return ext in allowed_extensions


def safe_audio_path(user_path: str) -> str:
    """校验并返回安全的音频文件路径.

    Args:
        user_path: 用户输入的音频文件路径

    Returns:
        安全的绝对路径

    Raises:
        ValueError: 路径不安全或扩展名不允许
    """
    # 扩展名校验
    if not validate_file_extension(user_path, ALLOWED_AUDIO_EXTENSIONS):
        raise ValueError(
            f"不支持的音频文件格式，支持: {', '.join(sorted(ALLOWED_AUDIO_EXTENSIONS))}"
        )

    # 如果是绝对路径且存在，直接返回（只读场景）
    if os.path.isabs(user_path) and os.path.isfile(user_path):
        # 仍做基本安全检查
        if not validate_file_extension(user_path, ALLOWED_AUDIO_EXTENSIONS):
            raise ValueError("不支持的音频文件格式")
        return os.path.abspath(user_path)

    # 相对路径：限制在数据目录内
    data_dir = get_data_dir()
    return safe_join_path(data_dir, user_path)


def safe_output_path(user_path: Optional[str], suffix: str = ".tmp") -> str:
    """生成安全的输出文件路径.

    如果用户提供了路径，做安全校验；
    如果没有提供，生成临时文件路径。

    Args:
        user_path: 用户指定的输出路径（可为空）
        suffix: 临时文件后缀

    Returns:
        安全的绝对路径
    """
    if user_path:
        # 用户指定路径：限制在数据目录内
        data_dir = get_data_dir()
        return safe_join_path(data_dir, user_path)

    # 生成临时文件
    temp_dir = get_temp_dir()
    fd, path = tempfile.mkstemp(suffix=suffix, dir=temp_dir)
    os.close(fd)
    return path


def is_safe_path_for_read(path: str, base_dir: Optional[str] = None) -> bool:
    """检查路径是否可安全读取（快速判断）.

    Args:
        path: 待检查的路径
        base_dir: 可选的基础目录限制

    Returns:
        是否安全
    """
    try:
        # 检查路径遍历
        norm = os.path.normpath(path)
        if '..' + os.sep in norm or norm.startswith('..'):
            return False

        # 如果指定了基础目录，检查是否在范围内
        if base_dir:
            abs_path = os.path.abspath(path)
            abs_base = os.path.abspath(base_dir)
            if not (abs_path == abs_base or abs_path.startswith(abs_base + os.sep)):
                return False

        return True
    except Exception:
        return False
