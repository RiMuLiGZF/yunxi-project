"""数据模型单元测试 (>=10 用例)"""
import sys
from pathlib import Path

# 确保可以导入 backend 模块
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import pytest
from core.models_code import CodeExecutionRequest, CodeExecutionResult


class TestCodeExecutionRequest:
    """CodeExecutionRequest 测试"""

    def test_create_request(self):
        """创建请求"""
        req = CodeExecutionRequest(language="python", code="print(1)")
        assert req.language == "python"
        assert req.code == "print(1)"

    def test_default_timeout(self):
        """默认超时"""
        req = CodeExecutionRequest(language="python", code="x=1")
        assert req.timeout == 30

    def test_custom_timeout(self):
        """自定义超时"""
        req = CodeExecutionRequest(language="python", code="x=1", timeout=60)
        assert req.timeout == 60

    def test_default_args_none(self):
        """默认 args 为 None"""
        req = CodeExecutionRequest(language="python", code="x=1")
        assert req.args is None

    def test_default_env_none(self):
        """默认 env 为 None"""
        req = CodeExecutionRequest(language="python", code="x=1")
        assert req.env is None

    def test_with_env(self):
        """带环境变量"""
        req = CodeExecutionRequest(
            language="python",
            code="x=1",
            env={"KEY": "value"}
        )
        assert req.env == {"KEY": "value"}

    def test_with_args(self):
        """带参数"""
        req = CodeExecutionRequest(
            language="python",
            code="import sys; print(sys.argv)",
            args=["--flag"]
        )
        assert req.args == ["--flag"]

    def test_missing_language_raises(self):
        """缺少 language 抛出验证错误"""
        with pytest.raises(Exception):
            CodeExecutionRequest(code="x=1")

    def test_missing_code_raises(self):
        """缺少 code 抛出验证错误"""
        with pytest.raises(Exception):
            CodeExecutionRequest(language="python")

    def test_serialization(self):
        """序列化"""
        req = CodeExecutionRequest(language="python", code="print(1)", timeout=10)
        d = req.model_dump()
        assert d["language"] == "python"
        assert d["code"] == "print(1)"
        assert d["timeout"] == 10


class TestCodeExecutionResult:
    """CodeExecutionResult 测试"""

    def test_default_values(self):
        """默认值"""
        result = CodeExecutionResult(success=True)
        assert result.stdout == ""
        assert result.stderr == ""
        assert result.exit_code is None
        assert result.execution_time == 0.0

    def test_success_result(self):
        """成功结果"""
        result = CodeExecutionResult(
            success=True,
            stdout="42",
            exit_code=0,
            execution_time=0.5
        )
        assert result.success is True
        assert result.stdout == "42"
        assert result.exit_code == 0

    def test_failure_result(self):
        """失败结果"""
        result = CodeExecutionResult(
            success=False,
            stderr="Error occurred",
            exit_code=1,
            execution_time=0.1
        )
        assert result.success is False
        assert result.stderr == "Error occurred"

    def test_serialization(self):
        """序列化"""
        result = CodeExecutionResult(
            success=True,
            stdout="hello",
            exit_code=0,
            execution_time=0.3
        )
        d = result.model_dump()
        assert d["success"] is True
        assert d["stdout"] == "hello"

    def test_json_serialization(self):
        """JSON 序列化"""
        import json
        result = CodeExecutionResult(
            success=True,
            stdout="output",
            exit_code=0,
            execution_time=0.1
        )
        json_str = result.model_dump_json()
        parsed = json.loads(json_str)
        assert parsed["success"] is True
        assert parsed["stdout"] == "output"
