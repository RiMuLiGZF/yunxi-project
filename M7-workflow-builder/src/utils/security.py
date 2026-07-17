"""M7 安全工具函数.

提供路径安全校验、输入验证、代码安全审计等安全相关工具。
"""

from __future__ import annotations

import ast
import logging
import os
import re
import tempfile
import time
from typing import Optional

logger = logging.getLogger("m7.security")

# 允许的文件扩展名白名单
ALLOWED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg"}
ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
ALLOWED_TEXT_EXTENSIONS = {".txt", ".md", ".json", ".csv", ".xml", ".yaml", ".yml"}

# 文件名最大长度
MAX_FILENAME_LENGTH = 255

# ============================================================
# 自定义积木代码安全配置
# ============================================================

# 自定义积木代码最大长度（字符），防止超大代码导致的 DoS
MAX_CUSTOM_BLOCK_CODE_SIZE = 100 * 1024  # 100KB

# 危险关键字黑名单（字符串匹配，作为第一道防线）
# 注意：黑名单不能替代 AST 级别的安全检查，仅作为快速拒绝
DANGEROUS_KEYWORDS = [
    # 代码执行相关
    "exec(", "eval(", "compile(",
    "__import__", "importlib",
    # 子进程/命令执行
    "subprocess", "os.system", "os.popen", "os.execl", "os.execle",
    "os.execlp", "os.execlpe", "os.execv", "os.execve",
    "os.execvp", "os.execvpe", "os.spawnl", "os.spawnle",
    "os.spawnlp", "os.spawnlpe", "os.spawnv", "os.spawnve",
    "os.spawnvp", "os.spawnvpe",
    "commands.", "popen2",
    # 文件系统高危操作
    "os.remove", "os.unlink", "os.rmdir", "os.removedirs",
    "shutil.rmtree", "shutil.move",
    # 网络/请求（可能用于 SSRF）
    "socket.", "http.client", "urllib.request", "requests.",
    # 环境/系统信息泄露
    "os.environ", "os.getenv", "sys.path", "sys.modules",
    # 反射/内省（可能用于沙箱逃逸）
    "getattr", "setattr", "delattr", "hasattr",
    "__class__", "__bases__", "__subclasses__", "__mro__",
    "__globals__", "__locals__", "__builtins__",
    "__dict__", "__code__", "__func__", "__self__",
    # 内存/进程操作
    "ctypes", "gc.", "threading", "multiprocessing",
    # 内置危险函数
    "open(", "input(", "__import__",
]

# 安全审计日志（内存环形缓冲，用于调试和审计）
_audit_log_buffer: list[dict] = []
AUDIT_LOG_MAX_ENTRIES = 1000


def _add_audit_log(event_type: str, severity: str, user_id: str = "",
                   block_id: str = "", details: str = "") -> None:
    """添加安全审计日志.

    Args:
        event_type: 事件类型
        severity: 严重级别 info/warning/error/critical
        user_id: 用户ID
        block_id: 积木ID
        details: 详细描述
    """
    entry = {
        "timestamp": time.time(),
        "event_type": event_type,
        "severity": severity,
        "user_id": user_id,
        "block_id": block_id,
        "details": details,
    }
    _audit_log_buffer.append(entry)
    # 保持环形缓冲大小
    if len(_audit_log_buffer) > AUDIT_LOG_MAX_ENTRIES:
        _audit_log_buffer.pop(0)

    # 同时输出到 logger
    log_level = {
        "info": logging.INFO,
        "warning": logging.WARNING,
        "error": logging.ERROR,
        "critical": logging.CRITICAL,
    }.get(severity, logging.INFO)
    logger.log(
        log_level,
        f"[AUDIT] type={event_type} severity={severity} "
        f"user={user_id} block={block_id} details={details}"
    )


def get_audit_logs(limit: int = 100) -> list[dict]:
    """获取最近的安全审计日志.

    Args:
        limit: 返回的最大条数

    Returns:
        审计日志列表（按时间倒序）
    """
    return list(reversed(_audit_log_buffer[-limit:]))


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


# ============================================================
# 自定义积木代码安全校验
# ============================================================

def validate_custom_block_code(code: str, user_id: str = "",
                               block_id: str = "") -> tuple[bool, str]:
    """校验自定义积木代码的安全性.

    多层防御策略：
    1. 大小限制：防止超大代码导致的 DoS
    2. 关键字黑名单：快速拒绝明显危险的代码
    3. AST 语法检查：确保代码语法正确且不包含危险节点类型
    4. Import 白名单：仅允许安全的标准库模块

    注意：
    - 当前自定义积木的 code 字段仅作存储，不会被执行
    - 本函数作为防御性安全措施，防止未来代码执行功能上线时的安全风险
    - 黑名单 + AST 检查不能替代真正的沙箱隔离（如 Docker/seccomp）

    Args:
        code: 待校验的代码字符串
        user_id: 用户ID（用于审计日志）
        block_id: 积木ID（用于审计日志）

    Returns:
        (是否安全, 原因描述) 元组
    """
    if code is None:
        return True, ""

    code_str = str(code)

    # 第1层：大小限制
    if len(code_str) > MAX_CUSTOM_BLOCK_CODE_SIZE:
        reason = f"代码长度超过限制：{len(code_str)} > {MAX_CUSTOM_BLOCK_CODE_SIZE}"
        _add_audit_log(
            event_type="custom_block_code_rejected",
            severity="warning",
            user_id=user_id,
            block_id=block_id,
            details=reason,
        )
        return False, reason

    if not code_str.strip():
        return True, "空代码"

    # 第2层：关键字黑名单快速扫描
    dangerous_found = _scan_dangerous_keywords(code_str)
    if dangerous_found:
        reason = f"代码包含危险关键字：{', '.join(dangerous_found[:5])}"
        _add_audit_log(
            event_type="custom_block_code_rejected",
            severity="warning",
            user_id=user_id,
            block_id=block_id,
            details=reason,
        )
        return False, reason

    # 第3层：AST 语法与节点类型检查
    try:
        tree = ast.parse(code_str, mode="exec")
    except SyntaxError as e:
        # 语法错误不记录为安全事件，只是普通错误
        return False, f"代码语法错误：{e}"

    ast_issues = _scan_ast_unsafe_nodes(tree)
    if ast_issues:
        reason = f"代码包含不安全的语法结构：{', '.join(ast_issues[:5])}"
        _add_audit_log(
            event_type="custom_block_code_rejected",
            severity="warning",
            user_id=user_id,
            block_id=block_id,
            details=reason,
        )
        return False, reason

    # 校验通过
    _add_audit_log(
        event_type="custom_block_code_validated",
        severity="info",
        user_id=user_id,
        block_id=block_id,
        details=f"代码校验通过，长度：{len(code_str)}",
    )
    return True, "安全检查通过"


def _scan_dangerous_keywords(code: str) -> list[str]:
    """扫描代码中的危险关键字.

    Args:
        code: 代码字符串

    Returns:
        发现的危险关键字列表（去重）
    """
    found = []
    code_lower = code.lower()
    for keyword in DANGEROUS_KEYWORDS:
        if keyword.lower() in code_lower:
            found.append(keyword)
    # 去重保序
    seen = set()
    result = []
    for k in found:
        if k not in seen:
            seen.add(k)
            result.append(k)
    return result


def _scan_ast_unsafe_nodes(tree: ast.AST) -> list[str]:
    """扫描 AST 中的不安全节点类型.

    检查项：
    - Import / ImportFrom：检查导入的模块是否在白名单内
    - Call：检查是否调用了危险的内置函数
    - Attribute：检查危险属性访问（如 __class__, __bases__）

    Args:
        tree: AST 根节点

    Returns:
        发现的不安全问题列表
    """
    issues: list[str] = []

    # 允许导入的安全模块白名单
    SAFE_IMPORTS = {
        "math", "random", "statistics",
        "json", "re", "datetime", "time",
        "collections", "itertools", "functools",
        "string", "textwrap",
        "copy", "hashlib",
        "decimal", "fractions",
    }

    # 危险的内置函数调用黑名单
    UNSAFE_BUILTIN_CALLS = {
        "eval", "exec", "compile",
        "open", "input", "breakpoint",
        "__import__", "globals", "locals", "vars",
        "getattr", "setattr", "delattr", "hasattr",
    }

    for node in ast.walk(tree):
        # 检查 import 语句
        if isinstance(node, ast.Import):
            for alias in node.names:
                module_name = alias.name.split(".")[0]
                if module_name not in SAFE_IMPORTS:
                    issues.append(f"import {alias.name}")

        elif isinstance(node, ast.ImportFrom):
            module_name = (node.module or "").split(".")[0]
            if module_name not in SAFE_IMPORTS:
                issues.append(f"from {node.module} import ...")

        # 检查函数调用
        elif isinstance(node, ast.Call):
            # 直接的名称调用，如 eval("...")
            if isinstance(node.func, ast.Name):
                if node.func.id in UNSAFE_BUILTIN_CALLS:
                    issues.append(f"调用危险函数：{node.func.id}")

            # 方法调用，如 os.system(...)
            elif isinstance(node.func, ast.Attribute):
                # 检查危险的方法名
                if node.func.attr in {"system", "popen", "exec", "eval",
                                      "remove", "unlink", "rmdir"}:
                    issues.append(f"调用危险方法：{node.func.attr}")

        # 检查危险属性访问（沙箱逃逸常用）
        elif isinstance(node, ast.Attribute):
            dangerous_attrs = {
                "__class__", "__bases__", "__subclasses__", "__mro__",
                "__globals__", "__builtins__", "__code__", "__func__",
                "__self__", "__dict__", "__import__",
            }
            if node.attr in dangerous_attrs:
                issues.append(f"访问危险属性：{node.attr}")

    # 去重
    seen = set()
    unique_issues = []
    for issue in issues:
        if issue not in seen:
            seen.add(issue)
            unique_issues.append(issue)
    return unique_issues


def sanitize_custom_block_name(name: str, max_length: int = 200) -> str:
    """清洗自定义积木名称，移除危险字符.

    Args:
        name: 原始名称
        max_length: 最大长度

    Returns:
        清洗后的安全名称
    """
    if not name:
        return ""

    # 移除控制字符和危险字符
    safe_name = re.sub(r'[\x00-\x1f\x7f<>:"/\\|?*]', '', name)
    safe_name = safe_name.strip()

    # 限制长度
    if len(safe_name) > max_length:
        safe_name = safe_name[:max_length]

    return safe_name
