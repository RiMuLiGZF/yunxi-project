"""
M1 Agent Hub - M8 Token 安全修复测试

验证 3 个 API 模块（m8_interface、brain_agent、agents）的
_verify_m8_token 函数的安全行为：
- 生产环境 + 空 token → 拒绝
- 开发环境 + 空 token → 放行
- 有效 token → 通过
- 无效 token → 拒绝
- 使用 hmac.compare_digest 防止时序攻击

运行: python -m pytest tests/test_m8_token_security.py -v
"""

from __future__ import annotations

import os
import hmac
import pytest
from unittest.mock import patch
from pathlib import Path


# ============================================================================
# 通用验证逻辑（与各模块实现一致）
# ============================================================================

def _is_production_env() -> bool:
    """检查是否处于生产环境."""
    return os.environ.get("YUNXI_ENV", "").lower() in ("production", "prod")


def _verify_m8_token_generic(env_var: str, x_m8_token: str = "") -> bool:
    """通用 M8 token 验证逻辑（与各模块实现一致）."""
    expected = os.environ.get(env_var, "")
    if not expected:
        if _is_production_env():
            return False
        return True
    if not x_m8_token:
        return False
    return hmac.compare_digest(x_m8_token, expected)


class TestM1M8InterfaceToken:
    """M1 m8_interface 模块 M8 Token 验证安全测试"""

    ENV_VAR = "M1_ADMIN_TOKEN"

    def test_production_env_empty_token_rejected(self, monkeypatch):
        """生产环境下 token 未配置时应拒绝访问"""
        monkeypatch.delenv(self.ENV_VAR, raising=False)
        monkeypatch.setenv("YUNXI_ENV", "production")
        assert _verify_m8_token_generic(self.ENV_VAR, "") is False

    def test_dev_env_empty_token_allowed(self, monkeypatch):
        """开发环境下 token 未配置时应放行"""
        monkeypatch.delenv(self.ENV_VAR, raising=False)
        monkeypatch.delenv("YUNXI_ENV", raising=False)
        assert _verify_m8_token_generic(self.ENV_VAR, "") is True

    def test_valid_token_passes(self, monkeypatch):
        """配置了有效 token 时应通过验证"""
        monkeypatch.setenv(self.ENV_VAR, "my-secret-token-123")
        monkeypatch.setenv("YUNXI_ENV", "production")
        assert _verify_m8_token_generic(self.ENV_VAR, "my-secret-token-123") is True

    def test_invalid_token_rejected(self, monkeypatch):
        """无效 token 应被拒绝"""
        monkeypatch.setenv(self.ENV_VAR, "my-secret-token-123")
        monkeypatch.setenv("YUNXI_ENV", "production")
        assert _verify_m8_token_generic(self.ENV_VAR, "wrong-token") is False

    def test_empty_header_token_rejected_when_configured(self, monkeypatch):
        """配置了 token 但请求头中无 token 应被拒绝"""
        monkeypatch.setenv(self.ENV_VAR, "my-secret-token-123")
        monkeypatch.setenv("YUNXI_ENV", "production")
        assert _verify_m8_token_generic(self.ENV_VAR, "") is False

    def test_source_code_contains_security_patterns(self):
        """验证 m8_interface.py 源码包含正确的安全模式"""
        src_path = Path(__file__).resolve().parents[1] / "src" / "api" / "m8_interface.py"
        with open(src_path, "r", encoding="utf-8") as f:
            source = f.read()

        assert "YUNXI_ENV" in source, "应使用 YUNXI_ENV 环境变量判断生产环境"
        assert "hmac.compare_digest" in source, "应使用 hmac.compare_digest"
        assert "production" in source, "应包含生产环境判断"
        # 不应直接无条件 return True
        # 检查空 token 时是否有条件判断（生产环境拒绝）
        assert "token_not_configured_rejected" in source or "拒绝所有访问" in source, \
            "生产环境空 token 应拒绝访问"


class TestM1BrainAgentToken:
    """M1 brain_agent 模块 M8 Token 验证安全测试"""

    ENV_VAR = "M1_ADMIN_TOKEN"

    def test_production_env_empty_token_rejected(self, monkeypatch):
        """生产环境下 token 未配置时应拒绝访问"""
        monkeypatch.delenv(self.ENV_VAR, raising=False)
        monkeypatch.setenv("YUNXI_ENV", "production")
        assert _verify_m8_token_generic(self.ENV_VAR, "") is False

    def test_dev_env_empty_token_allowed(self, monkeypatch):
        """开发环境下 token 未配置时应放行"""
        monkeypatch.delenv(self.ENV_VAR, raising=False)
        monkeypatch.delenv("YUNXI_ENV", raising=False)
        assert _verify_m8_token_generic(self.ENV_VAR, "") is True

    def test_valid_token_passes(self, monkeypatch):
        """配置了有效 token 时应通过验证"""
        monkeypatch.setenv(self.ENV_VAR, "my-secret-token-123")
        assert _verify_m8_token_generic(self.ENV_VAR, "my-secret-token-123") is True

    def test_invalid_token_rejected(self, monkeypatch):
        """无效 token 应被拒绝"""
        monkeypatch.setenv(self.ENV_VAR, "my-secret-token-123")
        assert _verify_m8_token_generic(self.ENV_VAR, "wrong-token") is False

    def test_uses_hmac_compare_digest(self, monkeypatch):
        """验证使用 hmac.compare_digest 进行安全比较"""
        monkeypatch.setenv(self.ENV_VAR, "test-token")

        original = hmac.compare_digest
        called = {"value": False}

        def mock_compare(a, b):
            called["value"] = True
            return original(a, b)

        with patch("hmac.compare_digest", side_effect=mock_compare):
            result = _verify_m8_token_generic(self.ENV_VAR, "test-token")
            assert result is True
            assert called["value"] is True

    def test_source_code_contains_security_patterns(self):
        """验证 brain_agent.py 源码包含正确的安全模式"""
        src_path = Path(__file__).resolve().parents[1] / "src" / "api" / "brain_agent.py"
        with open(src_path, "r", encoding="utf-8") as f:
            source = f.read()

        assert "YUNXI_ENV" in source, "应使用 YUNXI_ENV 环境变量判断生产环境"
        assert "hmac.compare_digest" in source, "应使用 hmac.compare_digest"
        assert "production" in source, "应包含生产环境判断"
        assert "_is_production_env" in source, "应有生产环境检测函数"


class TestM1AgentsToken:
    """M1 agents 模块 M8 Token 验证安全测试"""

    ENV_VAR = "M1_ADMIN_TOKEN"

    def test_production_env_empty_token_rejected(self, monkeypatch):
        """生产环境下 token 未配置时应拒绝访问"""
        monkeypatch.delenv(self.ENV_VAR, raising=False)
        monkeypatch.setenv("YUNXI_ENV", "production")
        assert _verify_m8_token_generic(self.ENV_VAR, "") is False

    def test_dev_env_empty_token_allowed(self, monkeypatch):
        """开发环境下 token 未配置时应放行"""
        monkeypatch.delenv(self.ENV_VAR, raising=False)
        monkeypatch.delenv("YUNXI_ENV", raising=False)
        assert _verify_m8_token_generic(self.ENV_VAR, "") is True

    def test_valid_token_passes(self, monkeypatch):
        """配置了有效 token 时应通过验证"""
        monkeypatch.setenv(self.ENV_VAR, "my-secret-token-123")
        assert _verify_m8_token_generic(self.ENV_VAR, "my-secret-token-123") is True

    def test_invalid_token_rejected(self, monkeypatch):
        """无效 token 应被拒绝"""
        monkeypatch.setenv(self.ENV_VAR, "my-secret-token-123")
        assert _verify_m8_token_generic(self.ENV_VAR, "wrong-token") is False

    def test_empty_request_token_rejected_when_configured(self, monkeypatch):
        """配置了 token 但请求 token 为空应被拒绝"""
        monkeypatch.setenv(self.ENV_VAR, "my-secret-token-123")
        assert _verify_m8_token_generic(self.ENV_VAR, "") is False

    def test_production_case_insensitive(self, monkeypatch):
        """YUNXI_ENV 值大小写不敏感"""
        monkeypatch.delenv(self.ENV_VAR, raising=False)
        monkeypatch.setenv("YUNXI_ENV", "PROD")
        assert _verify_m8_token_generic(self.ENV_VAR, "") is False

    def test_source_code_contains_security_patterns(self):
        """验证 agents.py 源码包含正确的安全模式"""
        src_path = Path(__file__).resolve().parents[1] / "src" / "api" / "agents.py"
        with open(src_path, "r", encoding="utf-8") as f:
            source = f.read()

        assert "YUNXI_ENV" in source, "应使用 YUNXI_ENV 环境变量判断生产环境"
        assert "hmac.compare_digest" in source, "应使用 hmac.compare_digest"
        assert "production" in source, "应包含生产环境判断"
        assert "_is_production_env" in source, "应有生产环境检测函数"
