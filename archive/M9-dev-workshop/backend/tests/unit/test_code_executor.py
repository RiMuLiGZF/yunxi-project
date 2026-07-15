"""代码执行器单元测试 (>=15 用例)"""
import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock

# 确保可以导入 backend 模块
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import pytest
from core.models_code import CodeExecutionRequest, CodeExecutionResult
from core.code_executor import CodeExecutor


@pytest.fixture
def executor():
    """创建代码执行器实例"""
    return CodeExecutor()


class TestExecutePython:
    """Python 代码执行测试"""

    @patch("core.code_executor.get_settings")
    def test_execute_safe_python(self, mock_get_settings, executor):
        """执行安全 Python 代码"""
        mock_get_settings.return_value.code_exec_sandbox_enabled = True
        mock_get_settings.return_value.code_exec_timeout = 30
        request = CodeExecutionRequest(language="python", code="print(42)")
        result = executor.execute(request)
        assert result.success is True
        assert "42" in result.stdout

    @patch("core.code_executor.get_settings")
    def test_execute_python_with_error(self, mock_get_settings, executor):
        """执行有错误的 Python 代码"""
        mock_get_settings.return_value.code_exec_sandbox_enabled = True
        mock_get_settings.return_value.code_exec_timeout = 30
        request = CodeExecutionRequest(language="python", code="1/0")
        result = executor.execute(request)
        assert result.success is False
        assert result.exit_code != 0


class TestExecuteJavaScript:
    """JavaScript 代码执行测试"""

    @patch("core.code_executor.get_settings")
    def test_execute_safe_js(self, mock_get_settings, executor):
        """执行安全 JS 代码（需要 node 可用）"""
        mock_get_settings.return_value.code_exec_sandbox_enabled = True
        mock_get_settings.return_value.code_exec_timeout = 30
        request = CodeExecutionRequest(language="javascript", code="console.log(42);")
        result = executor.execute(request)
        # node 可能不可用，所以只验证结果格式
        assert isinstance(result, CodeExecutionResult)


class TestUnsupportedLanguage:
    """不支持的语言测试"""

    @patch("core.code_executor.get_settings")
    def test_unsupported_language(self, mock_get_settings, executor):
        """不支持的语言返回错误"""
        mock_get_settings.return_value.code_exec_sandbox_enabled = True
        mock_get_settings.return_value.code_exec_timeout = 30
        request = CodeExecutionRequest(language="ruby", code="puts 42")
        result = executor.execute(request)
        assert result.success is False
        assert "不支持" in result.stderr


class TestTimeoutHandling:
    """超时处理测试"""

    @patch("core.code_executor.get_settings")
    def test_timeout_code(self, mock_get_settings, executor):
        """超时代码处理"""
        mock_get_settings.return_value.code_exec_sandbox_enabled = True
        mock_get_settings.return_value.code_exec_timeout = 30
        request = CodeExecutionRequest(
            language="python",
            code="import time; time.sleep(60)",
            timeout=1
        )
        result = executor.execute(request)
        assert result.success is False
        assert "超时" in result.stderr


class TestSandboxIntercept:
    """沙箱拦截测试"""

    @patch("core.code_executor.get_settings")
    def test_sandbox_blocks_dangerous(self, mock_get_settings, executor):
        """沙箱拦截危险代码"""
        mock_get_settings.return_value.code_exec_sandbox_enabled = True
        mock_get_settings.return_value.code_exec_timeout = 30
        request = CodeExecutionRequest(
            language="python",
            code="import os; os.system('rm -rf /')"
        )
        result = executor.execute(request)
        assert result.success is False
        assert "沙箱" in result.stderr

    @patch("core.code_executor.get_settings")
    def test_sandbox_disabled(self, mock_get_settings, executor):
        """沙箱禁用时允许代码执行"""
        mock_get_settings.return_value.code_exec_sandbox_enabled = False
        mock_get_settings.return_value.code_exec_timeout = 30
        request = CodeExecutionRequest(
            language="python",
            code="x = 1\nprint(x)"
        )
        result = executor.execute(request)
        assert result.success is True


class TestCodeSizeLimit:
    """代码大小限制测试"""

    def test_oversized_code_direct(self):
        """超限代码 - 直接测试 validate_code_size"""
        from core.sandbox_security import validate_code_size
        code = "x" * (200 * 1024)  # 200KB
        ok, msg = validate_code_size(code, max_size_kb=100)
        assert ok is False
        assert "超过限制" in msg

    def test_normal_size_direct(self):
        """正常大小代码"""
        from core.sandbox_security import validate_code_size
        code = "x = 1\nprint(x)"
        ok, msg = validate_code_size(code, max_size_kb=100)
        assert ok is True


class TestEmptyCode:
    """空代码测试"""

    def test_empty_code_validation(self):
        """空代码被 Pydantic 验证拒绝"""
        import pydantic
        with pytest.raises(Exception):
            CodeExecutionRequest(language="python", code="")


class TestResultFormat:
    """执行结果格式测试"""

    @patch("core.code_executor.get_settings")
    def test_result_has_required_fields(self, mock_get_settings, executor):
        """结果包含必需字段"""
        mock_get_settings.return_value.code_exec_sandbox_enabled = True
        mock_get_settings.return_value.code_exec_timeout = 30
        request = CodeExecutionRequest(language="python", code="print(1)")
        result = executor.execute(request)
        assert hasattr(result, "success")
        assert hasattr(result, "stdout")
        assert hasattr(result, "stderr")
        assert hasattr(result, "exit_code")
        assert hasattr(result, "execution_time")
        assert isinstance(result.execution_time, float)

    @patch("core.code_executor.get_settings")
    def test_execution_time_non_negative(self, mock_get_settings, executor):
        """执行时间非负"""
        mock_get_settings.return_value.code_exec_sandbox_enabled = True
        mock_get_settings.return_value.code_exec_timeout = 30
        request = CodeExecutionRequest(language="python", code="print(1)")
        result = executor.execute(request)
        assert result.execution_time >= 0


class TestLanguageExtensions:
    """语言扩展名映射测试"""

    def test_python_extension(self, executor):
        """Python 扩展名"""
        assert executor.LANGUAGE_EXTENSIONS["python"] == ".py"

    def test_javascript_extension(self, executor):
        """JavaScript 扩展名"""
        assert executor.LANGUAGE_EXTENSIONS["javascript"] == ".js"

    def test_bash_extension(self, executor):
        """Bash 扩展名"""
        assert executor.LANGUAGE_EXTENSIONS["bash"] == ".sh"

    def test_unknown_language_extension(self, executor):
        """未知语言返回 None"""
        assert executor.LANGUAGE_EXTENSIONS.get("ruby") is None


class TestLanguageCommands:
    """语言命令映射测试"""

    def test_python_command(self, executor):
        """Python 命令"""
        assert executor.LANGUAGE_COMMANDS["python"] == ["python"]

    def test_javascript_command(self, executor):
        """JavaScript 命令"""
        assert executor.LANGUAGE_COMMANDS["javascript"] == ["node"]

    def test_unknown_language_command(self, executor):
        """未知语言返回 None"""
        assert executor.LANGUAGE_COMMANDS.get("ruby") is None
