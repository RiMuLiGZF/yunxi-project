"""
P2-23: 代码执行沙箱安全增强

提供危险代码检测、环境隔离、资源限制等安全功能。
"""

import os
import re
from typing import List, Tuple, Dict, Any


# 各语言的危险模式
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
    ],
    "javascript": [
        (r"require\s*\(\s*['\"]child_process['\"]", "执行系统命令"),
        (r"exec\s*\(", "执行命令"),
        (r"eval\s*\(", "动态代码执行"),
        (r"fs\.unlink", "删除文件"),
        (r"fs\.rmdir", "删除目录"),
    ],
    "bash": [
        (r"rm\s+-rf", "递归删除"),
        (r">\s*/dev/", "写入系统设备"),
        (r"mkfs\.", "格式化磁盘"),
        (r":\(\)\{\s*:\|:&\s*\};:", "fork炸弹"),
    ],
}

def detect_dangerous_code(code: str, language: str) -> List[Dict[str, Any]]:
    """检测代码中的危险模式.

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
        for pattern, desc in patterns:
            if re.search(pattern, line):
                findings.append({
                    "line": line_num,
                    "code": line.strip()[:100],
                    "pattern": pattern,
                    "description": desc,
                    "severity": "high" if any(
                        kw in desc for kw in ["删除", "执行系统命令", "格式化"]
                    ) else "medium",
                })

    return findings


def is_code_allowed(code: str, language: str, sandbox_level: str = "strict") -> Tuple[bool, List[Dict[str, Any]]]:
    """判断代码是否允许执行.

    Args:
        code: 代码内容
        language: 编程语言
        sandbox_level: 沙箱级别 - "strict" 禁止所有危险操作, "permissive" 仅禁止高危操作

    Returns:
        (是否允许, 检测到的危险项列表)
    """
    findings = detect_dangerous_code(code, language)

    if not findings:
        return True, []

    if sandbox_level == "permissive":
        # 宽松模式：只阻止高危操作
        high_risk = [f for f in findings if f["severity"] == "high"]
        if not high_risk:
            return True, findings
        return False, findings

    # 严格模式：任何危险操作都阻止
    return False, findings


def get_safe_environ() -> Dict[str, str]:
    """获取安全的环境变量（移除敏感信息）.

    Returns:
        过滤后的环境变量字典
    """
    env = os.environ.copy()

    # 移除敏感的环境变量
    sensitive_keys = [
        "API_KEY", "SECRET", "TOKEN", "PASSWORD", "PASSWD",
        "PRIVATE_KEY", "ACCESS_KEY", "AUTH", "COOKIE",
        "GIT_TOKEN", "GITHUB_TOKEN", "NPM_TOKEN",
        "AWS_ACCESS_KEY", "AWS_SECRET", "AZURE_KEY",
        "YUNXI_TOKEN", "M8_API_KEY", "ADMIN_TOKEN",
    ]

    keys_to_remove = []
    for key in env:
        upper_key = key.upper()
        for sensitive in sensitive_keys:
            if sensitive in upper_key:
                keys_to_remove.append(key)
                break

    for key in keys_to_remove:
        del env[key]

    # 设置沙箱标记
    env["SANDBOX_MODE"] = "true"
    env["PYTHONSAFEPATH"] = "1"

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
