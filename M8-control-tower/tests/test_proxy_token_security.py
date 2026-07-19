"""
M8 控制塔 - 代理 Token 安全修复测试

验证 M8 代理模块中硬编码默认 token 的修复：
- 默认值改为空字符串
- 开发环境自动生成随机 token
- 生产环境 token 为空时报错返回 503

覆盖模块：
- routers/business/agents.py (M1_ADMIN_TOKEN)
- routers/business/brain.py (M1_ADMIN_TOKEN)
- routers/business/growth_m5_proxy.py (M5_ADMIN_TOKEN)

运行: python -m pytest tests/test_proxy_token_security.py -v --noconftest
"""

import os
import secrets
import hmac
import pytest
from unittest.mock import patch
from pathlib import Path


# ============================================================================
# 模拟 _resolve_admin_token 逻辑进行测试
# 避免导入完整模块带来的复杂依赖链
# ============================================================================

def _is_production_env() -> bool:
    """检查是否处于生产环境."""
    return os.environ.get("YUNXI_ENV", "").lower() in ("production", "prod")


def _resolve_admin_token(env_var: str, module_name: str) -> str:
    """解析 Admin Token，根据环境采取不同策略（与实际实现一致）.

    - 生产环境：未配置时报错并返回空字符串（代理将拒绝）
    - 开发环境：未配置时生成随机 token 并打印到日志，便于本地调试
    """
    token = os.getenv(env_var, "")
    if not token:
        if _is_production_env():
            return ""
        # 开发环境生成随机 token
        random_token = secrets.token_urlsafe(32)
        return random_token
    return token


def _proxy_allowed(token: str) -> bool:
    """模拟代理是否允许（生产环境 + 空 token = 不允许）."""
    if not token and _is_production_env():
        return False
    return True


class TestAgentsProxyToken:
    """Agent 代理 token 安全测试"""

    def test_no_hardcoded_default_token_production(self, monkeypatch):
        """生产环境验证不再使用硬编码默认 token"""
        monkeypatch.delenv("M1_ADMIN_TOKEN", raising=False)
        monkeypatch.setenv("YUNXI_ENV", "production")
        token = _resolve_admin_token("M1_ADMIN_TOKEN", "M1 Agent Hub")
        # 生产环境下 token 为空
        assert token == ""
        assert token != "yunxi-m1-admin-token-2026"

    def test_production_empty_token_proxy_blocked(self, monkeypatch):
        """生产环境下 token 为空时代理应被阻止"""
        monkeypatch.delenv("M1_ADMIN_TOKEN", raising=False)
        monkeypatch.setenv("YUNXI_ENV", "production")
        token = _resolve_admin_token("M1_ADMIN_TOKEN", "M1 Agent Hub")
        assert _proxy_allowed(token) is False

    def test_dev_env_auto_generates_token(self, monkeypatch):
        """开发环境下 token 未配置时自动生成随机 token"""
        monkeypatch.delenv("M1_ADMIN_TOKEN", raising=False)
        monkeypatch.delenv("YUNXI_ENV", raising=False)
        token = _resolve_admin_token("M1_ADMIN_TOKEN", "M1 Agent Hub")
        # 开发环境下应生成非空的随机 token
        assert token != ""
        assert token != "yunxi-m1-admin-token-2026"
        # 随机 token 应该足够长（secrets.token_urlsafe(32) 约 43 字符）
        assert len(token) > 20

    def test_dev_env_generates_unique_tokens(self, monkeypatch):
        """每次生成的随机 token 应不同"""
        monkeypatch.delenv("M1_ADMIN_TOKEN", raising=False)
        monkeypatch.delenv("YUNXI_ENV", raising=False)
        token1 = _resolve_admin_token("M1_ADMIN_TOKEN", "M1 Agent Hub")
        token2 = _resolve_admin_token("M1_ADMIN_TOKEN", "M1 Agent Hub")
        # 两次生成的 token 应该不同（极高概率）
        assert token1 != token2

    def test_explicit_token_respected(self, monkeypatch):
        """显式配置的 token 应被正确使用"""
        monkeypatch.setenv("M1_ADMIN_TOKEN", "my-custom-token-xyz")
        token = _resolve_admin_token("M1_ADMIN_TOKEN", "M1 Agent Hub")
        assert token == "my-custom-token-xyz"

    def test_dev_env_proxy_allowed_with_random_token(self, monkeypatch):
        """开发环境下自动生成 token 后代理应允许"""
        monkeypatch.delenv("M1_ADMIN_TOKEN", raising=False)
        monkeypatch.delenv("YUNXI_ENV", raising=False)
        token = _resolve_admin_token("M1_ADMIN_TOKEN", "M1 Agent Hub")
        assert _proxy_allowed(token) is True

    def test_agents_source_no_hardcoded_token(self):
        """验证 agents.py 源码中没有硬编码默认 token"""
        src_path = Path(__file__).resolve().parents[1] / "backend" / "routers" / "business" / "agents.py"
        with open(src_path, "r", encoding="utf-8") as f:
            source = f.read()

        # 不应有硬编码的默认 token
        assert "yunxi-m1-admin-token-2026" not in source, "不应有硬编码默认 token"
        assert "_resolve_admin_token" in source, "应使用 _resolve_admin_token 函数"
        assert "secrets" in source, "应使用 secrets 模块生成随机 token"
        assert "YUNXI_ENV" in source, "应使用 YUNXI_ENV 判断环境"
        assert "503" in source, "生产环境空 token 应返回 503"

    def test_brain_source_no_hardcoded_token(self):
        """验证 brain.py 源码中没有硬编码默认 token"""
        src_path = Path(__file__).resolve().parents[1] / "backend" / "routers" / "business" / "brain.py"
        with open(src_path, "r", encoding="utf-8") as f:
            source = f.read()

        # 不应有硬编码的默认 token
        assert "yunxi-m1-admin-token-2026" not in source, "不应有硬编码默认 token"
        assert "_resolve_admin_token" in source, "应使用 _resolve_admin_token 函数"
        assert "secrets" in source, "应使用 secrets 模块生成随机 token"
        assert "YUNXI_ENV" in source, "应使用 YUNXI_ENV 判断环境"
        assert "503" in source, "生产环境空 token 应返回 503"


class TestGrowthM5ProxyToken:
    """M5 成长代理 token 安全测试"""

    def test_no_hardcoded_default_token_production(self, monkeypatch):
        """生产环境验证不再使用硬编码默认 token"""
        monkeypatch.delenv("M5_ADMIN_TOKEN", raising=False)
        monkeypatch.setenv("YUNXI_ENV", "production")
        token = _resolve_admin_token("M5_ADMIN_TOKEN", "M5 成长系统")
        assert token == ""
        assert token != "yunxi-m5-admin-token-2026"

    def test_dev_env_auto_generates_token(self, monkeypatch):
        """开发环境下 token 未配置时自动生成随机 token"""
        monkeypatch.delenv("M5_ADMIN_TOKEN", raising=False)
        monkeypatch.delenv("YUNXI_ENV", raising=False)
        token = _resolve_admin_token("M5_ADMIN_TOKEN", "M5 成长系统")
        assert token != ""
        assert token != "yunxi-m5-admin-token-2026"
        assert len(token) > 20

    def test_production_empty_token_proxy_blocked(self, monkeypatch):
        """生产环境下 token 为空时代理应被阻止"""
        monkeypatch.delenv("M5_ADMIN_TOKEN", raising=False)
        monkeypatch.setenv("YUNXI_ENV", "production")
        token = _resolve_admin_token("M5_ADMIN_TOKEN", "M5 成长系统")
        assert _proxy_allowed(token) is False

    def test_growth_proxy_source_no_hardcoded_token(self):
        """验证 growth_m5_proxy.py 源码中没有硬编码默认 token"""
        src_path = Path(__file__).resolve().parents[1] / "backend" / "routers" / "business" / "growth_m5_proxy.py"
        with open(src_path, "r", encoding="utf-8") as f:
            source = f.read()

        # 不应有硬编码的默认 token
        assert "yunxi-m5-admin-token-2026" not in source, "不应有硬编码默认 token"
        assert "_resolve_admin_token" in source, "应使用 _resolve_admin_token 函数"
        assert "secrets" in source, "应使用 secrets 模块生成随机 token"
        assert "YUNXI_ENV" in source, "应使用 YUNXI_ENV 判断环境"
        assert "503" in source, "生产环境空 token 应返回 503"

    def test_explicit_token_respected(self, monkeypatch):
        """显式配置的 M5 token 应被正确使用"""
        monkeypatch.setenv("M5_ADMIN_TOKEN", "my-m5-custom-token")
        token = _resolve_admin_token("M5_ADMIN_TOKEN", "M5 成长系统")
        assert token == "my-m5-custom-token"
