"""
云汐 M9 开发者工坊 - 代码执行沙箱安全增强

提供危险代码检测、AST静态分析、RestrictedPython隔离、环境清理等多层安全防护。

防护层级（由外到内）：
1. 正则危险模式检测（快速预检）
2. AST 静态分析（Python 深度语法检查）
3. RestrictedPython 编译（受限字节码）
4. 安全执行环境（受限 builtins + 资源限制）
5. 超时 + 内存限制（最后防线）
"""

import os
import re
import ast
import sys
from typing import List, Tuple, Dict, Any, Optional, Set


# 各语言的危险模式（第一层：快速预检）
DANGEROUS_PATTERNS = {
    "python": [
        # 文件系统操作
        (r"os\.system\s*\(", "执行系统命令"),
        (r"subprocess\.", "创建子进程"),
        (r"os\.popen\s*\(", "执行系统命令"),
        # 文件删除
        (r"os\.remove\s*\(", "删除文件"),
        (r"os\.rmdir\s*\(", "删除目录"),
        (r"shutil\.rmtree\s*\(", "递归删除目录"),
        # 网络
        (r"import\s+socket", "网络连接"),
        (r"urllib\.", "网络请求"),
        (r"requests\.", "网络请求"),
        # 环境变量读取
        (r"os\.environ", "读取环境变量"),
        # 进程操作
        (r"multiprocessing\.", "多进程"),
        (r"threading\.", "多线程"),
        # 反射/元编程
        (r"__import__\s*\(", "动态导入"),
        (r"getattr\s*\(", "动态属性访问"),
        (r"setattr\s*\(", "动态属性设置"),
        (r"delattr\s*\(", "动态属性删除"),
        # eval/exec
        (r"eval\s*\(", "动态代码执行"),
        (r"exec\s*\(", "动态代码执行"),
        (r"compile\s*\(", "动态编译"),
    ],
    "javascript": [
        (r"require\s*\(\s*['\"]child_process['\"]", "执行系统命令"),
        (r"exec\s*\(", "执行命令"),
        (r"eval\s*\(", "动态代码执行"),
        (r"fs\.unlink", "删除文件"),
        (r"fs\.rmdir", "删除目录"),
        (r"process\.env", "读取环境变量"),
        (r"globalThis\.", "全局对象访问"),
    ],
    "bash": [
        (r"rm\s+-rf", "递归删除"),
        (r">\s*/dev/", "写入系统设备"),
        (r"mkfs\.", "格式化磁盘"),
        (r":\(\)\{\s*:\|:&\s*\};:", "fork炸弹"),
        (r"wget\s+", "网络下载"),
        (r"curl\s+", "网络请求"),
    ],
}

# Python AST 黑名单（第二层：深度语法检查）
# 禁止的 AST 节点类型
FORBIDDEN_AST_NODES: Dict[str, str] = {
    # 动态执行
    "Exec": "exec 语句",
    # 直接访问受保护属性
    # 注：ast.Attribute 需额外检查属性名，不在此列表
}

# Python 危险属性名前缀（AST 属性访问检查）
DANGEROUS_ATTR_PREFIXES: List[str] = [
    "__",           # 所有双下划线属性（__import__, __builtins__, __class__等）
    "func_",        # 函数内部属性
    "im_",          # 方法内部属性
    "gi_",          # 生成器内部属性
    "cr_",          # 协程内部属性
]

# Python 危险内置函数（执行环境层禁用）
FORBIDDEN_BUILTINS: Set[str] = {
    "eval", "exec", "compile", "open", "input",
    "__import__", "getattr", "setattr", "delattr", "hasattr",
    "globals", "locals", "vars", "dir",
    "breakpoint", "help", "memoryview",
}

# Python 安全内置函数白名单（严格模式）
SAFE_BUILTINS_STRICT: Set[str] = {
    # 基础类型
    "int", "float", "complex", "bool", "str", "bytes",
    "list", "tuple", "dict", "set", "frozenset",
    "range", "slice", "enumerate", "zip", "map", "filter",
    # 工具
    "len", "abs", "min", "max", "sum", "round",
    "sorted", "reversed", "all", "any",
    "type", "isinstance", "issubclass", "id", "hash",
    # 数学
    "pow", "divmod", "ord", "chr", "bin", "hex", "oct",
    # 迭代
    "iter", "next",
    # 其他安全
    "print", "repr", "str", "format",
    "Exception", "ValueError", "TypeError", "KeyError", "IndexError",
    "StopIteration", "RuntimeError", "AttributeError",
}


def detect_dangerous_code(code: str, language: str) -> List[Dict[str, Any]]:
    """检测代码中的危险模式（第一层：正则快速预检）.

    Args:
        code: 代码内容
        language: 编程语言

    Returns:
        危险检测结果列表，每项包含 pattern、description、line
    """
    patterns = DANGEROUS_PATTERNS.get(language, [])
    if not patterns:
        return []

    findings = []
    lines = code.split("\n")

    for line_num, line in enumerate(lines, 1):
        # 跳过纯注释行
        stripped = line.strip()
        if language == "python" and stripped.startswith("#"):
            continue
        if language == "javascript" and (stripped.startswith("//") or stripped.startswith("/*")):
            continue
        if language == "bash" and stripped.startswith("#"):
            continue

        for pattern, desc in patterns:
            if re.search(pattern, line):
                findings.append({
                    "line": line_num,
                    "code": line.strip()[:100],
                    "pattern": pattern,
                    "description": desc,
                    "severity": "high" if any(
                        kw in desc for kw in ["删除", "执行系统命令", "格式化", "动态代码执行", "动态导入"]
                    ) else "medium",
                    "layer": "pattern",
                })

    return findings


def ast_analyze_python(code: str) -> List[Dict[str, Any]]:
    """Python AST 静态分析（第二层：深度语法检查）.

    检查内容：
    1. 禁止的 AST 节点类型
    2. 危险属性访问（__xxx__ 双下划线）
    3. 危险函数调用
    4. 动态导入

    Args:
        code: Python 源代码

    Returns:
        检测到的问题列表
    """
    findings = []

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        findings.append({
            "line": e.lineno,
            "code": f"语法错误: {e.msg}",
            "pattern": "syntax_error",
            "description": "代码无法解析",
            "severity": "high",
            "layer": "ast",
        })
        return findings

    # 遍历 AST
    for node in ast.walk(tree):
        line_num = getattr(node, "lineno", 0)

        # 1. 检查禁止的节点类型
        node_type = type(node).__name__
        if node_type in FORBIDDEN_AST_NODES:
            findings.append({
                "line": line_num,
                "code": f"<{node_type}>",
                "pattern": f"ast_node:{node_type}",
                "description": FORBIDDEN_AST_NODES[node_type],
                "severity": "high",
                "layer": "ast",
            })

        # 2. 检查危险属性访问（双下划线属性）
        if isinstance(node, ast.Attribute):
            attr_name = node.attr
            for prefix in DANGEROUS_ATTR_PREFIXES:
                if attr_name.startswith(prefix):
                    findings.append({
                        "line": line_num,
                        "code": f".{attr_name}",
                        "pattern": f"dangerous_attr:{attr_name}",
                        "description": f"访问内部属性: {attr_name}",
                        "severity": "high",
                        "layer": "ast",
                    })
                    break

        # 3. 检查危险函数调用（名称级）
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
                if func_name in FORBIDDEN_BUILTINS:
                    findings.append({
                        "line": line_num,
                        "code": f"{func_name}()",
                        "pattern": f"forbidden_call:{func_name}",
                        "description": f"调用禁止的内置函数: {func_name}",
                        "severity": "high",
                        "layer": "ast",
                    })
            # 检查 __import__ 调用
            if isinstance(node.func, ast.Name) and node.func.id == "__import__":
                findings.append({
                    "line": line_num,
                    "code": "__import__()",
                    "pattern": "dynamic_import",
                    "description": "动态导入模块",
                    "severity": "high",
                    "layer": "ast",
                })

        # 4. 检查 import / from import 中的危险模块
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_dangerous_module(alias.name):
                    findings.append({
                        "line": line_num,
                        "code": f"import {alias.name}",
                        "pattern": f"dangerous_import:{alias.name}",
                        "description": f"导入危险模块: {alias.name}",
                        "severity": "high",
                        "layer": "ast",
                    })

        if isinstance(node, ast.ImportFrom):
            if node.module and _is_dangerous_module(node.module):
                findings.append({
                    "line": line_num,
                    "code": f"from {node.module} import ...",
                    "pattern": f"dangerous_import:{node.module}",
                    "description": f"从危险模块导入: {node.module}",
                    "severity": "high",
                    "layer": "ast",
                })

    return findings


def _is_dangerous_module(module_name: str) -> bool:
    """判断模块名是否为危险模块."""
    dangerous_modules = {
        "os", "sys", "subprocess", "multiprocessing",
        "socket", "http", "urllib", "requests",
        "shutil", "pathlib", "importlib", "ctypes",
        "pickle", "marshal", "shelve",
        "threading", "asyncio", "concurrent",
        "builtins", "__builtin__", "types",
        "gc", "inspect", "dis",
        "crypt", "ssl", "hashlib",  # 加密模块可能被滥用
        "pty", "termios", "tty",
    }
    top_level = module_name.split(".")[0].lower()
    return top_level in dangerous_modules


def is_code_allowed(code: str, language: str, sandbox_level: str = "strict") -> Tuple[bool, List[Dict[str, Any]]]:
    """判断代码是否允许执行（综合所有检测层）.

    Args:
        code: 代码内容
        language: 编程语言
        sandbox_level: 沙箱级别 - "strict" 禁止所有危险操作, "permissive" 仅禁止高危操作

    Returns:
        (是否允许, 检测到的危险项列表)
    """
    all_findings = []

    # 第一层：正则模式检测
    pattern_findings = detect_dangerous_code(code, language)
    all_findings.extend(pattern_findings)

    # 第二层：Python AST 深度分析
    if language == "python":
        ast_findings = ast_analyze_python(code)
        all_findings.extend(ast_findings)

    if not all_findings:
        return True, []

    if sandbox_level == "permissive":
        # 宽松模式：只阻止高危操作
        high_risk = [f for f in all_findings if f["severity"] == "high"]
        if not high_risk:
            return True, all_findings
        return False, all_findings

    # 严格模式：任何危险操作都阻止
    return False, all_findings


def compile_restricted_python(code: str) -> Tuple[bool, Any, str]:
    """使用 RestrictedPython 编译 Python 代码（第三层沙箱防护）.

    Args:
        code: Python 源代码

    Returns:
        (编译成功, 编译后代码对象或错误消息, 额外信息)
    """
    try:
        from RestrictedPython import compile_restricted
        from RestrictedPython.Guards import safe_builtins
        from RestrictedPython import Eval

        # 编译受限代码（严格模式）
        result = compile_restricted(code, filename='<sandbox>', mode='exec')

        # 检查编译结果
        if result.errors:
            error_list = "; ".join(str(e) for e in result.errors)
            return False, f"RestrictedPython 编译错误: {error_list}", ""

        if result.code is None:
            return False, "RestrictedPython 编译失败: 代码对象为空", ""

        return True, result.code, ""

    except ImportError:
        # RestrictedPython 未安装，跳过此层检测，但返回警告
        return True, "", "WARNING: RestrictedPython 未安装，跳过第三层沙箱编译检测"
    except Exception as e:
        return False, f"RestrictedPython 异常: {str(e)}", ""


def get_safe_exec_globals() -> Dict[str, Any]:
    """获取安全的执行环境 globals（第四层：受限执行环境）.

    严格模式下的安全 builtins 集合。

    Returns:
        安全的 globals 字典
    """
    # 构建安全 builtins
    safe_builtins = {
        name: getattr(__builtins__, name)
        for name in SAFE_BUILTINS_STRICT
        if hasattr(__builtins__, name)
    }

    # 额外安全设置
    globals_dict = {
        "__builtins__": safe_builtins,
        "__name__": "__sandbox__",
        "__file__": "<sandbox>",
    }

    return globals_dict


def get_safe_environ() -> Dict[str, str]:
    """获取安全的环境变量（移除敏感信息）.

    Returns:
        过滤后的环境变量字典
    """
    env = os.environ.copy()

    # 移除敏感的环境变量（更全面的列表）
    sensitive_keywords = [
        "API_KEY", "SECRET", "TOKEN", "PASSWORD", "PASSWD",
        "PRIVATE_KEY", "ACCESS_KEY", "AUTH", "COOKIE",
        "GIT_TOKEN", "GITHUB_TOKEN", "NPM_TOKEN", "PIP_TOKEN",
        "AWS_ACCESS_KEY", "AWS_SECRET", "AZURE_KEY", "AZURE_SECRET",
        "YUNXI_TOKEN", "M8_API_KEY", "ADMIN_TOKEN",
        "DATABASE_URL", "DB_PASSWORD", "DB_PASS",
        "REDIS_PASSWORD", "MONGO_PASSWORD",
        "SMTP_PASSWORD", "MAIL_PASSWORD",
        "SLACK_TOKEN", "DISCORD_TOKEN", "TELEGRAM_TOKEN",
        "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
        "SSH_KEY", "PRIVATE_KEY", "PUBLIC_KEY",
        "SIGNING_KEY", "ENCRYPTION_KEY",
    ]

    keys_to_remove = []
    for key in env:
        upper_key = key.upper()
        for sensitive in sensitive_keywords:
            if sensitive in upper_key:
                keys_to_remove.append(key)
                break

    for key in keys_to_remove:
        del env[key]

    # 设置沙箱标记
    env["SANDBOX_MODE"] = "true"
    env["PYTHONSAFEPATH"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    # 移除 PATH 中可能的危险路径？保留基础路径即可
    # 实际执行时会进一步限制

    return env


def validate_code_size(code: str, max_size_kb: int = 100) -> Tuple[bool, str]:
    """验证代码大小是否在限制内.

    Args:
        code: 代码内容
        max_size_kb: 最大大小（KB）

    Returns:
        (是否通过, 错误消息)
    """
    size_bytes = len(code.encode("utf-8"))
    if size_bytes > max_size_kb * 1024:
        return False, f"代码大小超过限制: {size_bytes / 1024:.1f}KB > {max_size_kb}KB"
    return True, ""


def get_security_report(code: str, language: str, sandbox_level: str = "strict") -> Dict[str, Any]:
    """生成完整的安全检测报告.

    Args:
        code: 代码内容
        language: 编程语言
        sandbox_level: 沙箱级别

    Returns:
        安全报告字典
    """
    # 各层检测
    pattern_findings = detect_dangerous_code(code, language)
    ast_findings = ast_analyze_python(code) if language == "python" else []

    # 综合判定
    all_findings = pattern_findings + ast_findings
    high_risk = [f for f in all_findings if f["severity"] == "high"]
    medium_risk = [f for f in all_findings if f["severity"] == "medium"]

    if sandbox_level == "strict":
        allowed = len(all_findings) == 0
    else:
        allowed = len(high_risk) == 0

    return {
        "allowed": allowed,
        "language": language,
        "sandbox_level": sandbox_level,
        "summary": {
            "total_issues": len(all_findings),
            "high_risk": len(high_risk),
            "medium_risk": len(medium_risk),
            "pattern_findings": len(pattern_findings),
            "ast_findings": len(ast_findings),
        },
        "findings": all_findings,
        "layers": {
            "pattern": len(pattern_findings),
            "ast": len(ast_findings),
            "restricted_python": "N/A" if language != "python" else "available",
            "safe_environment": "available",
        },
    }
