"""M9 沙箱安全检测单元测试"""

import pytest
from m9_programming_dev.sandbox_security import (
    detect_dangerous_code,
    is_code_allowed,
    get_safe_environ,
    validate_code_size,
)


class TestDetectDangerousCode:
    """危险代码检测测试"""

    def test_detect_os_system(self):
        """测试检测 os.system 调用"""
        findings = detect_dangerous_code("os.system('ls')", "python")
        assert len(findings) > 0
        assert any("os.system" in f["code"] for f in findings)

    def test_detect_subprocess(self):
        """测试检测 subprocess 调用"""
        findings = detect_dangerous_code("subprocess.run(['ls'])", "python")
        assert len(findings) > 0

    def test_detect_import_socket(self):
        """测试检测 socket 导入"""
        findings = detect_dangerous_code("import socket", "python")
        assert len(findings) > 0

    def test_detect_bash_rm_rf(self):
        """测试检测 bash rm -rf"""
        findings = detect_dangerous_code("rm -rf /", "bash")
        assert len(findings) > 0

    def test_detect_bash_fork_bomb(self):
        """测试检测 bash fork炸弹"""
        findings = detect_dangerous_code(":(){ :|:& };:", "bash")
        assert len(findings) > 0

    def test_safe_code_no_findings(self):
        """测试安全代码无检出"""
        findings = detect_dangerous_code("x = 1 + 2\nprint(x)", "python")
        assert len(findings) == 0

    def test_javascript_eval(self):
        """测试检测 JS eval"""
        findings = detect_dangerous_code("eval('code')", "javascript")
        assert len(findings) > 0

    def test_unknown_language_empty(self):
        """测试未知语言返回空"""
        findings = detect_dangerous_code("anything", "rust")
        assert len(findings) == 0


class TestIsCodeAllowed:
    """代码执行许可测试"""

    def test_safe_code_allowed(self):
        """测试安全代码允许执行"""
        allowed, findings = is_code_allowed("x = 1", "python", "strict")
        assert allowed is True
        assert findings == []

    def test_dangerous_code_blocked_strict(self):
        """测试严格模式阻止危险代码"""
        allowed, findings = is_code_allowed("os.system('ls')", "python", "strict")
        assert allowed is False
        assert len(findings) > 0

    def test_medium_risk_allowed_permissive(self):
        """测试宽松模式允许中等风险"""
        allowed, findings = is_code_allowed("import threading", "python", "permissive")
        assert allowed is True

    def test_high_risk_blocked_permissive(self):
        """测试宽松模式阻止高风险"""
        allowed, findings = is_code_allowed("os.remove('/file')", "python", "permissive")
        assert allowed is False


class TestGetSafeEnviron:
    """安全环境变量测试"""

    def test_removes_api_keys(self):
        """测试移除 API_KEY"""
        import os
        os.environ["TEST_M9_API_KEY"] = "secret"
        env = get_safe_environ()
        assert "TEST_M9_API_KEY" not in env
        del os.environ["TEST_M9_API_KEY"]

    def test_removes_tokens(self):
        """测试移除 TOKEN"""
        import os
        os.environ["TEST_M9_TOKEN"] = "secret"
        env = get_safe_environ()
        assert "TEST_M9_TOKEN" not in env
        del os.environ["TEST_M9_TOKEN"]

    def test_sets_sandbox_mode(self):
        """测试设置沙箱标记"""
        env = get_safe_environ()
        assert env.get("SANDBOX_MODE") == "true"


class TestValidateCodeSize:
    """代码大小验证测试"""

    def test_within_limit(self):
        """测试代码在限制内"""
        ok, msg = validate_code_size("print('hello')", max_size_kb=100)
        assert ok is True
        assert msg == ""

    def test_exceeds_limit(self):
        """测试代码超过限制"""
        big_code = "x" * (101 * 1024)
        ok, msg = validate_code_size(big_code, max_size_kb=100)
        assert ok is False
        assert "超过限制" in msg
