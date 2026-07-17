"""M9 开发者工坊 - 代码质量工具集成.

提供代码质量检查和格式化工具集成：
- 代码格式化（black/ruff format）
- 代码检查（ruff/flake8）
- 类型检查（mypy）
- 代码复杂度分析
- 统一的质量报告格式
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from typing import Any, Dict, List, Optional


class CodeQualityTool:
    """代码质量工具基类."""

    name: str = ""
    description: str = ""
    available: bool = False
    command: List[str] = []

    @classmethod
    def check_available(cls) -> bool:
        """检查工具是否可用."""
        if not cls.command:
            return False
        try:
            result = subprocess.run(
                cls.command + ["--version"], capture_output=True, text=True, timeout=5)
            cls.available = result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            cls.available = False
        return cls.available


class BlackFormatter(CodeQualityTool):
    """Black 代码格式化工具."""

    name = "black"
    description = "Python 代码格式化工具"
    command = ["python", "-m", "black"]


class RuffFormatter(CodeQualityTool):
    """Ruff 代码格式化工具."""

    name = "ruff format"
    description = "Rust 实现的 Python 代码格式化"
    command = ["python", "-m", "ruff", "format"]


class RuffLinter(CodeQualityTool):
    """Ruff 代码检查工具."""

    name = "ruff"
    description = "Rust 实现的 Python linter"
    command = ["python", "-m", "ruff"]


class Flake8Linter(CodeQualityTool):
    """Flake8 代码检查工具."""

    name = "flake8"
    description = "Python 代码风格检查工具"
    command = ["python", "-m", "flake8"]


class MypyTypeChecker(CodeQualityTool):
    """Mypy 类型检查工具."""

    name = "mypy"
    description = "Python 静态类型检查器"
    command = ["python", "-m", "mypy"]


class CodeQualityManager:
    """代码质量管理器.

    集成多种代码质量工具，提供统一的接口和报告格式。
    """

    def __init__(self) -> None:
        self._tools_cache: Dict[str, bool] = {}

    def check_tool_available(self, tool_name: str) -> bool:
        """检查指定工具是否可用."""
        if tool_name in self._tools_cache:
            return self._tools_cache[tool_name]

        tool_classes = {
            "black": BlackFormatter,
            "ruff": RuffLinter,
            "ruff_format": RuffFormatter,
            "flake8": Flake8Linter,
            "mypy": MypyTypeChecker,
        }

        tool_cls = tool_classes.get(tool_name)
        if not tool_cls:
            self._tools_cache[tool_name] = False
            return False

        available = tool_cls.check_available()
        self._tools_cache[tool_name] = available
        return available

    def get_available_tools(self) -> Dict[str, bool]:
        """获取所有可用工具的状态."""
        tools = ["black", "ruff", "ruff_format", "flake8", "mypy"]
        return {tool: self.check_tool_available(tool) for tool in tools}

    # ------------------------------------------------------------------
    # 代码格式化
    # ------------------------------------------------------------------

    def format_code(
        self,
        code: str,
        tool: str = "black",
        line_length: int = 88,
    ) -> Dict[str, Any]:
        """格式化代码.

        Args:
            code: 代码内容
            tool: 使用的工具（black/ruff_format）
            line_length: 行长度

        Returns:
            格式化结果
        """
        start_time = time.time()

        # 写入临时文件
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
            f.write(code)
            temp_file = f.name

        try:
            if tool == "black":
                cmd = ["python", "-m", "black", "--line-length", str(line_length), temp_file]
            elif tool == "ruff_format":
                cmd = ["python", "-m", "ruff", "format", "--line-length", str(line_length), temp_file]
            else:
                return {
                    "success": False,
                    "error": f"不支持的格式化工具: {tool}",
                    "formatted_code": code,
                }

            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )

                # 读取格式化后的代码
                with open(temp_file, 'r', encoding='utf-8') as f:
                    formatted_code = f.read()

                changed = formatted_code != code

                return {
                    "success": True,
                    "tool": tool,
                    "formatted_code": formatted_code,
                    "changed": changed,
                    "original_size": len(code),
                    "formatted_size": len(formatted_code),
                    "duration_ms": int((time.time() - start_time) * 1000),
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                }

            except subprocess.TimeoutExpired:
                return {
                    "success": False,
                    "error": "格式化超时",
                    "formatted_code": code,
                    "tool": tool,
                }
            except FileNotFoundError:
                return {
                    "success": False,
                    "error": f"工具 {tool} 未安装",
                    "formatted_code": code,
                    "tool": tool,
                }

        finally:
            try:
                os.unlink(temp_file)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 代码检查
    # ------------------------------------------------------------------

    def lint_code(
        self,
        code: str,
        tool: str = "ruff",
        select: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """检查代码质量.

        Args:
            code: 代码内容
            tool: 使用的工具（ruff/flake8）
            select: 选择的规则列表

        Returns:
            检查结果
        """
        start_time = time.time()

        # 写入临时文件
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
            f.write(code)
            temp_file = f.name

        try:
            if tool == "ruff":
                cmd = ["python", "-m", "ruff", "check", "--output-format=json", temp_file]
                if select:
                    cmd.extend(["--select", ",".join(select)])
            elif tool == "flake8":
                cmd = ["python", "-m", "flake8", "--format=json", temp_file]
            else:
                return {
                    "success": False,
                    "error": f"不支持的检查工具: {tool}",
                    "issues": [],
                }

            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )

                # 解析结果
                issues = self._parse_lint_output(result.stdout, tool)

                # 统计
                error_count = sum(1 for i in issues if i.get("severity") == "error")
                warning_count = sum(1 for i in issues if i.get("severity") == "warning")
                info_count = sum(1 for i in issues if i.get("severity") == "info")

                return {
                    "success": True,
                    "tool": tool,
                    "issues": issues,
                    "total_issues": len(issues),
                    "error_count": error_count,
                    "warning_count": warning_count,
                    "info_count": info_count,
                    "duration_ms": int((time.time() - start_time) * 1000),
                    "stdout": result.stdout[:2000] if result.stdout else "",
                    "stderr": result.stderr[:2000] if result.stderr else "",
                }

            except subprocess.TimeoutExpired:
                return {
                    "success": False,
                    "error": "检查超时",
                    "issues": [],
                    "tool": tool,
                }
            except FileNotFoundError:
                return {
                    "success": False,
                    "error": f"工具 {tool} 未安装",
                    "issues": [],
                    "tool": tool,
                }

        finally:
            try:
                os.unlink(temp_file)
            except Exception:
                pass

    def _parse_lint_output(self, output: str, tool: str) -> List[Dict[str, Any]]:
        """解析 linter 输出."""
        issues = []

        if not output:
            return issues

        if tool == "ruff":
            try:
                import json
                data = json.loads(output)
                if isinstance(data, list):
                    for item in data:
                        severity = "error" if item.get("type") == "error" else "warning"
                        issues.append({
                            "line": item.get("location", {}).get("row", 0),
                            "column": item.get("location", {}).get("column", 0),
                            "end_line": item.get("end_location", {}).get("row", 0),
                            "end_column": item.get("end_location", {}).get("column", 0),
                            "code": item.get("code", ""),
                            "message": item.get("message", ""),
                            "severity": severity,
                            "fixable": item.get("fix", None) is not None,
                        })
            except (json.JSONDecodeError, Exception):
                pass

        elif tool == "flake8":
            try:
                import json
                data = json.loads(output)
                if isinstance(data, dict):
                    for file_path, file_issues in data.items():
                        for item in file_issues:
                            issues.append({
                                "line": item.get("line_number", 0),
                                "column": item.get("column_number", 0),
                                "code": item.get("code", ""),
                                "message": item.get("text", ""),
                                "severity": "warning",
                                "fixable": False,
                            })
            except (json.JSONDecodeError, Exception):
                pass

        return issues

    # ------------------------------------------------------------------
    # 类型检查
    # ------------------------------------------------------------------

    def type_check(
        self,
        code: str,
        strict: bool = False,
    ) -> Dict[str, Any]:
        """类型检查.

        Args:
            code: 代码内容
            strict: 是否使用严格模式

        Returns:
            类型检查结果
        """
        start_time = time.time()

        # 写入临时文件
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
            f.write(code)
            temp_file = f.name

        try:
            cmd = ["python", "-m", "mypy", temp_file, "--output-format=json", "--no-error-summary"]
            if strict:
                cmd.append("--strict")

            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )

                # 解析结果
                issues = []
                try:
                    import json
                    for line in result.stdout.strip().split("\n"):
                        if line.strip():
                            try:
                                item = json.loads(line)
                                severity = "error" if item.get("severity") == "error" else "info"
                                issues.append({
                                    "line": item.get("line", 0),
                                    "column": item.get("column", 0),
                                    "message": item.get("message", ""),
                                    "severity": severity,
                                    "code": item.get("code", ""),
                                })
                            except json.JSONDecodeError:
                                pass
                except Exception:
                    pass

                error_count = sum(1 for i in issues if i.get("severity") == "error")

                return {
                    "success": True,
                    "tool": "mypy",
                    "issues": issues,
                    "total_issues": len(issues),
                    "error_count": error_count,
                    "duration_ms": int((time.time() - start_time) * 1000),
                    "strict_mode": strict,
                }

            except subprocess.TimeoutExpired:
                return {
                    "success": False,
                    "error": "类型检查超时",
                    "issues": [],
                }
            except FileNotFoundError:
                return {
                    "success": False,
                    "error": "mypy 未安装",
                    "issues": [],
                }

        finally:
            try:
                os.unlink(temp_file)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 代码复杂度分析
    # ------------------------------------------------------------------

    def analyze_complexity(
        self,
        code: str,
    ) -> Dict[str, Any]:
        """分析代码复杂度.

        基于 AST 进行基本的复杂度分析，不依赖外部工具。

        Args:
            code: 代码内容

        Returns:
            复杂度分析结果
        """
        import ast

        start_time = time.time()

        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return {
                "success": False,
                "error": f"语法错误: {str(e)}",
                "metrics": {},
            }

        # 统计函数和类
        functions = []
        classes = []
        lines = code.splitlines()
        total_lines = len(lines)
        code_lines = [line for line in lines if line.strip() and not line.strip().startswith("#")]

        class ComplexityVisitor(ast.NodeVisitor):
            def __init__(self):
                self.complexity = 1  # 基础复杂度
                self.function_count = 0
                self.class_count = 0
                self.max_depth = 0
                self.current_depth = 0

            def visit_FunctionDef(self, node):
                    self.function_count += 1
                    self.complexity += 1  # 函数定义
                    self.current_depth += 1
                    self.max_depth = max(self.max_depth, self.current_depth)
                    self.generic_visit(node)
                    self.current_depth -= 1

            def visit_ClassDef(self, node):
                self.class_count += 1
                self.current_depth += 1
                self.max_depth = max(self.max_depth, self.current_depth)
                self.generic_visit(node)
                self.current_depth -= 1

            def visit_If(self, node):
                self.complexity += 1
                self.generic_visit(node)

            def visit_For(self, node):
                self.complexity += 1
                self.generic_visit(node)

            def visit_While(self, node):
                self.complexity += 1
                self.generic_visit(node)

            def visit_Try(self, node):
                self.complexity += 1
                self.generic_visit(node)

            def visit_BoolOp(self, node):
                # 布尔运算符增加复杂度
                self.complexity += len(node.values) - 1
                self.generic_visit(node)

        visitor = ComplexityVisitor()
        visitor.visit(tree)

        # 收集函数列表
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                functions.append({
                    "name": node.name,
                    "line": node.lineno,
                    "args": len(node.args.args),
                })
            elif isinstance(node, ast.ClassDef):
                classes.append({
                    "name": node.name,
                    "line": node.lineno,
                    "methods": len([n for n in node.body if isinstance(n, ast.FunctionDef)]),
                })

        return {
            "success": True,
            "metrics": {
                "total_lines": len(total_lines),
                "code_lines": len(code_lines),
                "comment_lines": len(total_lines) - len(code_lines),
                "cyclomatic_complexity": visitor.complexity,
                "function_count": visitor.function_count,
                "class_count": visitor.class_count,
                "max_nesting_depth": visitor.max_depth,
                "avg_function_complexity": round(visitor.complexity / max(visitor.function_count, 1), 2),
            },
            "functions": functions,
            "classes": classes,
            "duration_ms": int((time.time() - start_time) * 1000),
        }

    # ------------------------------------------------------------------
    # 综合质量报告
    # ------------------------------------------------------------------

    def full_quality_report(
        self,
        code: str,
        tools: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """生成综合质量报告.

        Args:
            code: 代码内容
            tools: 要运行的工具列表（默认全部）

        Returns:
            综合质量报告
        """
        if tools is None:
            tools = ["format", "lint", "type_check", "complexity"]

        report = {
            "success": True,
            "total_issues": 0,
            "error_count": 0,
            "warning_count": 0,
            "tools": {},
            "overall_score": 100,
        }

        # 代码格式化检查
        if "format" in tools:
            # 尝试用 black 检查
            formatted = self.format_code(code, tool="black")
            report["tools"]["format"] = {
                "available": formatted.get("success", False),
                "needs_formatting": formatted.get("changed", False),
            }
            if formatted.get("changed"):
                report["overall_score"] -= 5

        # 代码检查
        if "lint" in tools:
            lint_result = self.lint_code(code, tool="ruff")
            report["tools"]["lint"] = lint_result
            if lint_result.get("success"):
                report["total_issues"] += lint_result.get("total_issues", 0)
                report["error_count"] += lint_result.get("error_count", 0)
                report["warning_count"] += lint_result.get("warning_count", 0)
                report["overall_score"] -= min(lint_result.get("total_issues", 0) * 2, 30)

        # 类型检查
        if "type_check" in tools:
            type_result = self.type_check(code)
            report["tools"]["type_check"] = type_result
            if type_result.get("success"):
                report["total_issues"] += type_result.get("total_issues", 0)
                report["error_count"] += type_result.get("error_count", 0)
                report["overall_score"] -= type_result.get("error_count", 0) * 3

        # 复杂度分析
        if "complexity" in tools:
            complexity_result = self.analyze_complexity(code)
            report["tools"]["complexity"] = complexity_result
            if complexity_result.get("success"):
                metrics = complexity_result.get("metrics", {})
                complexity = metrics.get("cyclomatic_complexity", 0)
                if complexity > 20:
                    report["overall_score"] -= 10
                elif complexity > 10:
                    report["overall_score"] -= 5

        report["overall_score"] = max(0, min(100, report["overall_score"]))

        # 质量等级
        score = report["overall_score"]
        if score >= 90:
            report["grade"] = "A"
        elif score >= 80:
            report["grade"] = "B"
        elif score >= 70:
            report["grade"] = "C"
        elif score >= 60:
            report["grade"] = "D"
        else:
            report["grade"] = "F"

        return report


# 全局单例
_quality_manager: Optional[CodeQualityManager] = None


def get_code_quality_manager() -> CodeQualityManager:
    """获取代码质量管理器单例."""
    global _quality_manager
    if _quality_manager is None:
        _quality_manager = CodeQualityManager()
    return _quality_manager
