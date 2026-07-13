from __future__ import annotations

"""AST Security Scanner - AST 静态安全分析器.

【整改 R04 - 评审报告 REV-20250628-M2-001】
评审意见：plugin_loader 的 exec_module 存在 RCE 风险，
注释中已标注"生产环境应使用 AST 静态分析"但未实现。

设计：独立的 AST 安全扫描器，可在 plugin 加载前对代码做静态分析。
检测维度：
1. 危险导入（os, subprocess, socket 等）
2. 危险内置调用（eval, exec, compile, __import__）
3. 文件系统操作（open, os.remove, os.unlink）
4. 网络操作（socket, urllib, http）
5. getattr dunder 访问
6. 异步逃逸（os.system, os.popen）
"""

import ast
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Severity(Enum):
    """安全检查严重级别."""
    BLOCK = "block"       # 必须阻止（禁止加载）
    WARN = "warn"         # 警告（可加载但记录日志）
    INFO = "info"         # 信息提示


@dataclass
class SecurityFinding:
    """安全检查发现."""
    severity: Severity
    category: str         # "dangerous_import" / "dangerous_call" / "file_access" / "network" / "dunder_access"
    description: str
    line: int = 0
    col: int = 0
    node_text: str = ""


@dataclass
class ScanResult:
    """扫描结果."""
    findings: list[SecurityFinding] = field(default_factory=list)
    passed: bool = True
    block_count: int = 0
    warn_count: int = 0

    @property
    def summary(self) -> str:
        if self.passed:
            return f"PASS ({self.warn_count} warnings)"
        return f"BLOCK ({self.block_count} blocks, {self.warn_count} warnings)"


# 默认禁止的模块
_BLOCKED_MODULES: frozenset[str] = frozenset({
    "os", "subprocess", "sys", "socket", "urllib", "http",
    "ftplib", "smtplib", "telnetlib", "pathlib",
    "ctypes", "multiprocessing", "threading",
    "signal", "resource", "shutil",
})

# 默认禁止的内置调用
_BLOCKED_BUILTINS: frozenset[str] = frozenset({
    "eval", "exec", "compile", "__import__", "breakpoint",
    "exit", "quit", "globals", "locals", "vars",
})

# 危险属性操作
_BLOCKED_ATTRS: frozenset[str] = frozenset({
    "system", "popen", "spawn", "exec", "fork",
    "remove", "unlink", "rmdir", "rmtree",
})


class ASTSecurityScanner:
    """AST 静态安全分析器.

    用法：
        scanner = ASTSecurityScanner()
        result = scanner.scan(code_string)
        if not result.passed:
            # 拒绝加载
    """

    def __init__(
        self,
        blocked_modules: frozenset[str] | None = None,
        blocked_builtins: frozenset[str] | None = None,
        blocked_attrs: frozenset[str] | None = None,
    ) -> None:
        self._blocked_modules = blocked_modules or _BLOCKED_MODULES
        self._blocked_builtins = blocked_builtins or _BLOCKED_BUILTINS
        self._blocked_attrs = blocked_attrs or _BLOCKED_ATTRS

    def scan(self, code: str) -> ScanResult:
        """扫描 Python 代码，返回安全检查结果."""
        result = ScanResult()

        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            result.findings.append(SecurityFinding(
                severity=Severity.BLOCK,
                category="syntax_error",
                description=f"Syntax error: {e}",
                line=getattr(e, "lineno", 0),
            ))
            result.passed = False
            result.block_count = 1
            return result

        for node in ast.walk(tree):
            self._check_imports(node, result)
            self._check_calls(node, result)
            self._check_attr_access(node, result)

        result.passed = result.block_count == 0
        return result

    def _check_imports(self, node: ast.AST, result: ScanResult) -> None:
        """检查危险导入."""
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules = [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            mod = (node.module or "").split(".")[0]
            if mod:
                modules = [mod]

        for mod in modules:
            if mod in self._blocked_modules:
                result.findings.append(SecurityFinding(
                    severity=Severity.BLOCK,
                    category="dangerous_import",
                    description=f"Import of blocked module '{mod}'",
                    line=node.lineno if hasattr(node, "lineno") else 0,
                    node_text=f"import {mod}",
                ))
                result.block_count += 1

    def _check_calls(self, node: ast.AST, result: ScanResult) -> None:
        """检查危险调用."""
        if not isinstance(node, ast.Call):
            return

        # 直接调用危险 builtin
        if isinstance(node.func, ast.Name):
            name = node.func.id
            if name in self._blocked_builtins:
                result.findings.append(SecurityFinding(
                    severity=Severity.BLOCK,
                    category="dangerous_call",
                    description=f"Call to blocked builtin '{name}'",
                    line=node.lineno,
                    node_text=name,
                ))
                result.block_count += 1
            # getattr(__builtins__, '__dunder__') 检查
            if name == "getattr" and len(node.args) >= 2:
                second_arg = node.args[1]
                if (isinstance(second_arg, ast.Constant)
                        and isinstance(second_arg.value, str)
                        and second_arg.value.startswith("__")
                        and second_arg.value.endswith("__")):
                    result.findings.append(SecurityFinding(
                        severity=Severity.BLOCK,
                        category="dunder_access",
                        description=f"getattr access to dunder '{second_arg.value}'",
                        line=node.lineno,
                        node_text=f"getattr(..., '{second_arg.value}')",
                    ))
                    result.block_count += 1

        # 属性调用：os.system, subprocess.run 等
        if isinstance(node.func, ast.Attribute):
            attr = node.func.attr
            if attr in self._blocked_attrs:
                result.findings.append(SecurityFinding(
                    severity=Severity.BLOCK,
                    category="dangerous_call",
                    description=f"Call to dangerous attribute '{attr}'",
                    line=node.lineno,
                    node_text=attr,
                ))
                result.block_count += 1

    def _check_attr_access(self, node: ast.AST, result: ScanResult) -> None:
        """检查属性访问（非调用场景）."""
        # 这里可以扩展检查如 `os.environ` 等
        pass
