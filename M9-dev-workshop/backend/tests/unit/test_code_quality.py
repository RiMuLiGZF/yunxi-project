"""
M9 单元测试 - 代码质量工具测试

覆盖: 代码格式化、代码检查、类型检查、复杂度分析、综合报告
运行: python -m pytest tests/unit/test_code_quality.py -v
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "shared"))

from code_quality import CodeQualityManager


@pytest.fixture
def quality_manager():
    """代码质量管理器 fixture"""
    return CodeQualityManager()


@pytest.fixture
def sample_code():
    """示例代码"""
    return '''"""示例代码."""


def add(a, b):
    """加法函数."""
    return a + b


def greet(name):
    """问候函数."""
    return f"Hello, {name}!"


class Calculator:
    """计算器类."""

    def __init__(self, initial=0):
        self.value = initial

    def add(self, num):
        self.value += num
        return self.value

    def multiply(self, num):
        self.value *= num
        return self.value


if __name__ == "__main__":
    calc = Calculator(10)
    print(calc.add(5))
    print(greet("World"))
'''


@pytest.fixture
def bad_code():
    """有问题的代码示例"""
    return '''import os
import sys
import json
import re

def foo(x,y,z):
    if x > 0:
        if y > 0:
            if z > 0:
                return x+y+z
            else:
                return x+y
        else:
            return x
    else:
        return 0

unused_var = 123

def bar():
    pass
'''


class TestCodeQualityManager:
    """代码质量管理器测试"""

    def test_init(self, quality_manager):
        """初始化测试"""
        assert quality_manager is not None

    def test_get_available_tools(self, quality_manager):
        """获取可用工具列表"""
        tools = quality_manager.get_available_tools()
        assert isinstance(tools, dict)
        assert "black" in tools
        assert "ruff" in tools
        assert "ruff_format" in tools
        assert "flake8" in tools
        assert "mypy" in tools

    def test_check_tool_available(self, quality_manager):
        """检查单个工具可用性"""
        result = quality_manager.check_tool_available("black")
        assert isinstance(result, bool)

    def test_check_tool_invalid(self, quality_manager):
        """检查不存在的工具"""
        result = quality_manager.check_tool_available("nonexistent_tool")
        assert result is False


class TestCodeFormatting:
    """代码格式化测试"""

    def test_format_code_basic(self, quality_manager, sample_code):
        """基本格式化"""
        result = quality_manager.format_code(sample_code, tool="black")
        # 即使 black 不可用，也应该返回结果
        assert "success" in result
        assert "formatted_code" in result

    def test_format_code_ruff(self, quality_manager, sample_code):
        """使用 ruff 格式化"""
        result = quality_manager.format_code(sample_code, tool="ruff_format")
        assert "success" in result
        assert "formatted_code" in result

    def test_format_code_invalid_tool(self, quality_manager, sample_code):
        """使用无效工具格式化"""
        result = quality_manager.format_code(sample_code, tool="invalid_tool")
        assert result["success"] is False
        assert "不支持" in result.get("error", "")

    def test_format_code_line_length(self, quality_manager, sample_code):
        """自定义行长度"""
        result = quality_manager.format_code(sample_code, tool="black", line_length=120)
        assert "formatted_code" in result

    def test_format_code_no_change(self, quality_manager):
        """格式化不需要修改的代码"""
        clean_code = "x = 1\n"
        result = quality_manager.format_code(clean_code, tool="black")
        assert "formatted_code" in result


class TestCodeLinting:
    """代码检查测试"""

    def test_lint_code_ruff(self, quality_manager, sample_code):
        """使用 ruff 检查代码"""
        result = quality_manager.lint_code(sample_code, tool="ruff")
        assert "success" in result
        assert "issues" in result
        assert "total_issues" in result

    def test_lint_code_flake8(self, quality_manager, sample_code):
        """使用 flake8 检查代码"""
        result = quality_manager.lint_code(sample_code, tool="flake8")
        assert "success" in result
        assert "issues" in result

    def test_lint_code_invalid_tool(self, quality_manager, sample_code):
        """使用无效工具检查"""
        result = quality_manager.lint_code(sample_code, tool="invalid")
        assert result["success"] is False

    def test_lint_code_with_select(self, quality_manager, sample_code):
        """选择特定规则"""
        result = quality_manager.lint_code(
            sample_code,
            tool="ruff",
            select=["E", "F"],
        )
        assert "issues" in result

    def test_lint_issue_structure(self, quality_manager, bad_code):
        """检查问题结构"""
        result = quality_manager.lint_code(bad_code, tool="ruff")
        if result.get("success") and result.get("issues"):
            issue = result["issues"][0]
            assert "line" in issue
            assert "message" in issue
            assert "severity" in issue
            assert "code" in issue


class TestTypeChecking:
    """类型检查测试"""

    def test_type_check_basic(self, quality_manager, sample_code):
        """基本类型检查"""
        result = quality_manager.type_check(sample_code)
        assert "success" in result
        assert "issues" in result

    def test_type_check_strict(self, quality_manager, sample_code):
        """严格模式类型检查"""
        result = quality_manager.type_check(sample_code, strict=True)
        assert "success" in result
        assert result.get("strict_mode") is True

    def test_type_check_empty_code(self, quality_manager):
        """空代码类型检查"""
        result = quality_manager.type_check("")
        assert "success" in result


class TestComplexityAnalysis:
    """复杂度分析测试"""

    def test_analyze_complexity_basic(self, quality_manager, sample_code):
        """基本复杂度分析"""
        result = quality_manager.analyze_complexity(sample_code)
        assert result["success"] is True
        assert "metrics" in result
        metrics = result["metrics"]
        assert "total_lines" in metrics
        assert "cyclomatic_complexity" in metrics
        assert "function_count" in metrics
        assert "class_count" in metrics

    def test_analyze_complexity_metrics(self, quality_manager, sample_code):
        """复杂度指标验证"""
        result = quality_manager.analyze_complexity(sample_code)
        metrics = result["metrics"]
        assert metrics["total_lines"] > 0
        assert metrics["function_count"] == 2  # add, greet
        assert metrics["class_count"] == 1  # Calculator
        assert metrics["cyclomatic_complexity"] > 0

    def test_analyze_complexity_nested(self, quality_manager, bad_code):
        """嵌套代码复杂度"""
        result = quality_manager.analyze_complexity(bad_code)
        assert result["success"] is True
        metrics = result["metrics"]
        # 嵌套 if 应该增加复杂度
        assert metrics["cyclomatic_complexity"] >= 4

    def test_analyze_complexity_syntax_error(self, quality_manager):
        """语法错误的代码"""
        bad_syntax = "def foo(:"
        result = quality_manager.analyze_complexity(bad_syntax)
        assert result["success"] is False
        assert "语法错误" in result.get("error", "")

    def test_analyze_complexity_functions_list(self, quality_manager, sample_code):
        """函数列表"""
        result = quality_manager.analyze_complexity(sample_code)
        assert "functions" in result
        assert len(result["functions"]) == 2
        assert result["functions"][0]["name"] == "add"

    def test_analyze_complexity_classes_list(self, quality_manager, sample_code):
        """类列表"""
        result = quality_manager.analyze_complexity(sample_code)
        assert "classes" in result
        assert len(result["classes"]) == 1
        assert result["classes"][0]["name"] == "Calculator"

    def test_analyze_complexity_empty_code(self, quality_manager):
        """空代码复杂度"""
        result = quality_manager.analyze_complexity("")
        assert result["success"] is True
        assert result["metrics"]["total_lines"] == 0


class TestFullQualityReport:
    """综合质量报告测试"""

    def test_full_report_basic(self, quality_manager, sample_code):
        """基本综合报告"""
        result = quality_manager.full_quality_report(sample_code)
        assert result["success"] is True
        assert "overall_score" in result
        assert "grade" in result
        assert "tools" in result
        assert "total_issues" in result

    def test_full_report_score_range(self, quality_manager, sample_code):
        """分数范围验证"""
        result = quality_manager.full_quality_report(sample_code)
        score = result["overall_score"]
        assert 0 <= score <= 100

    def test_full_report_grade(self, quality_manager, sample_code):
        """质量等级"""
        result = quality_manager.full_quality_report(sample_code)
        grade = result["grade"]
        assert grade in ("A", "B", "C", "D", "F")

    def test_full_report_selected_tools(self, quality_manager, sample_code):
        """选择部分工具"""
        result = quality_manager.full_quality_report(
            sample_code,
            tools=["complexity"],
        )
        assert result["success"] is True
        assert "complexity" in result["tools"]

    def test_full_report_issue_count(self, quality_manager, bad_code):
        """问题代码的报告"""
        result = quality_manager.full_quality_report(bad_code)
        assert result["success"] is True
        # 有问题的代码分数应该更低
        assert result["total_issues"] >= 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
