"""
M10 系统卫士 - M8 接口 Token 鉴权安全测试

P0 级安全修复验证：确保 M8 标准接口（/m8/health, /m8/metrics, /m8/config）
在 Token 未配置时默认拒绝访问，而非直接放行。

测试覆盖：
1. 未配置 token 时访问 /m8/health 返回 401
2. 错误 token 时返回 401
3. 正确 token 时正常访问
4. 未配置 token 时访问 /m8/metrics 返回 401
5. 未配置 token 时访问 /m8/config 返回 401
6. M10_DEV_MODE=true 时空 token 可访问
7. 业务接口空 token 仍然拒绝（确保不影响业务鉴权逻辑）
"""

from __future__ import annotations

import os
import sys
import pytest
from unittest.mock import patch


# ============================================================
# 测试配置：确保沙盒模式启用
# ============================================================

def _enable_sandbox_mode():
    """启用沙盒模式，避免真实系统调用导致测试缓慢."""
    from m10_system_guard.config import get_config
    config = get_config()
    config.sandbox.enabled = True

    # 重置可能已初始化的单例
    import m10_system_guard.system_monitor as sm_mod
    import m10_system_guard.process_manager as pm_mod

    sm_mod._system_monitor_instance = None
    pm_mod._process_manager_instance = None


_enable_sandbox_mode()


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def client_no_token(monkeypatch):
    """未配置 M10_ADMIN_TOKEN 的 TestClient（模拟生产环境缺配置）."""
    monkeypatch.delenv("M10_ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("M10_DEV_MODE", raising=False)

    # 重新导入 server 以应用环境变量
    import importlib
    import server as server_mod
    importlib.reload(server_mod)

    from fastapi.testclient import TestClient
    with TestClient(server_mod.app) as c:
        yield c


@pytest.fixture
def client_with_token(monkeypatch):
    """配置了正确 M10_ADMIN_TOKEN 的 TestClient."""
    test_token = "test-m10-admin-token-12345"
    monkeypatch.setenv("M10_ADMIN_TOKEN", test_token)
    monkeypatch.delenv("M10_DEV_MODE", raising=False)

    import importlib
    import server as server_mod
    importlib.reload(server_mod)

    from fastapi.testclient import TestClient
    with TestClient(server_mod.app) as c:
        c.test_token = test_token
        yield c


@pytest.fixture
def client_dev_mode_no_token(monkeypatch):
    """开发模式（M10_DEV_MODE=true）且未配置 token 的 TestClient."""
    monkeypatch.delenv("M10_ADMIN_TOKEN", raising=False)
    monkeypatch.setenv("M10_DEV_MODE", "true")

    import importlib
    import server as server_mod
    importlib.reload(server_mod)

    from fastapi.testclient import TestClient
    with TestClient(server_mod.app) as c:
        yield c


# ============================================================
# 测试：M8 接口鉴权 - 未配置 Token 时默认拒绝
# ============================================================

class TestM8AuthNoToken:
    """M8 接口在未配置 M10_ADMIN_TOKEN 时的行为（生产环境默认拒绝）."""

    def test_m8_health_without_token_rejected(self, client_no_token):
        """未配置 token 时访问 /m8/health 返回 401（安全默认：拒绝）."""
        resp = client_no_token.get("/m8/health")
        assert resp.status_code == 401, (
            f"P0 漏洞：未配置 token 时 /m8/health 应返回 401，实际返回 {resp.status_code}"
        )
        assert "Invalid M8 token" in resp.text or "401" in resp.text

    def test_m8_metrics_without_token_rejected(self, client_no_token):
        """未配置 token 时访问 /m8/metrics 返回 401（安全默认：拒绝）."""
        resp = client_no_token.get("/m8/metrics")
        assert resp.status_code == 401, (
            f"P0 漏洞：未配置 token 时 /m8/metrics 应返回 401，实际返回 {resp.status_code}"
        )

    def test_m8_config_without_token_rejected(self, client_no_token):
        """未配置 token 时访问 /m8/config 返回 401（安全默认：拒绝）."""
        resp = client_no_token.get("/m8/config")
        assert resp.status_code == 401, (
            f"P0 漏洞：未配置 token 时 /m8/config 应返回 401，实际返回 {resp.status_code}"
        )


# ============================================================
# 测试：M8 接口鉴权 - Token 验证正确性
# ============================================================

class TestM8AuthWithToken:
    """M8 接口在配置了 M10_ADMIN_TOKEN 时的验证行为."""

    def test_m8_health_with_wrong_token_rejected(self, client_with_token):
        """错误 token 时访问 /m8/health 返回 401."""
        resp = client_with_token.get(
            "/m8/health",
            headers={"x-m8-token": "wrong-token-value"},
        )
        assert resp.status_code == 401

    def test_m8_health_with_correct_token_ok(self, client_with_token):
        """正确 token 时访问 /m8/health 返回 200."""
        resp = client_with_token.get(
            "/m8/health",
            headers={"x-m8-token": client_with_token.test_token},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["status"] == "healthy"
        assert data["data"]["module"] == "m10"

    def test_m8_metrics_with_correct_token_ok(self, client_with_token):
        """正确 token 时访问 /m8/metrics 返回 200."""
        resp = client_with_token.get(
            "/m8/metrics",
            headers={"x-m8-token": client_with_token.test_token},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert "cpu_usage" in data["data"]
        assert "memory_usage" in data["data"]

    def test_m8_config_with_correct_token_ok(self, client_with_token):
        """正确 token 时访问 /m8/config 返回 200."""
        resp = client_with_token.get(
            "/m8/config",
            headers={"x-m8-token": client_with_token.test_token},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["module"] == "m10"

    def test_m8_health_empty_token_rejected(self, client_with_token):
        """配置了 token 但请求中未携带 token 时返回 401."""
        resp = client_with_token.get("/m8/health")
        assert resp.status_code == 401


# ============================================================
# 测试：开发模式兼容
# ============================================================

class TestM8AuthDevMode:
    """开发模式（M10_DEV_MODE=true）下的 M8 接口行为."""

    def test_dev_mode_allows_no_token(self, client_dev_mode_no_token):
        """M10_DEV_MODE=true 且未配置 token 时，空 token 可访问 /m8/health."""
        resp = client_dev_mode_no_token.get("/m8/health")
        assert resp.status_code == 200, (
            f"开发模式下 /m8/health 应返回 200，实际返回 {resp.status_code}"
        )
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["status"] == "healthy"

    def test_dev_mode_metrics_allows_no_token(self, client_dev_mode_no_token):
        """开发模式下 /m8/metrics 空 token 可访问."""
        resp = client_dev_mode_no_token.get("/m8/metrics")
        assert resp.status_code == 200

    def test_dev_mode_config_allows_no_token(self, client_dev_mode_no_token):
        """开发模式下 /m8/config 空 token 可访问."""
        resp = client_dev_mode_no_token.get("/m8/config")
        assert resp.status_code == 200

    def test_dev_mode_false_still_rejects(self, monkeypatch):
        """M10_DEV_MODE=false 时仍应拒绝（与未设置行为一致）."""
        monkeypatch.delenv("M10_ADMIN_TOKEN", raising=False)
        monkeypatch.setenv("M10_DEV_MODE", "false")

        import importlib
        import server as server_mod
        importlib.reload(server_mod)

        from fastapi.testclient import TestClient
        with TestClient(server_mod.app) as client:
            resp = client.get("/m8/health")
            assert resp.status_code == 401, (
                "M10_DEV_MODE=false 时应拒绝空 token 访问"
            )


# ============================================================
# 测试：业务接口鉴权不受影响（向后兼容）
# ============================================================

class TestBusinessInterfaceAuthUnaffected:
    """验证业务接口（/api/v1/*）的鉴权逻辑不受 M8 接口修复影响."""

    def test_business_interface_token_empty_rejected(self, client_no_token):
        """业务接口空 token 仍然拒绝（确保不影响业务鉴权逻辑）."""
        resp = client_no_token.get("/api/v1/status")
        # 业务接口在无 token 时应返回 401
        assert resp.status_code == 401, (
            f"业务接口空 token 应返回 401，实际返回 {resp.status_code}"
        )

    def test_business_interface_with_token_ok(self, client_with_token):
        """业务接口携带正确 token 时正常访问."""
        resp = client_with_token.get(
            "/api/v1/status",
            headers={"x-m8-token": client_with_token.test_token},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0


# ============================================================
# 测试：_verify_m8_token 单元测试
# ============================================================

class TestVerifyM8TokenUnit:
    """_verify_m8_token 函数的单元级测试."""

    def test_no_token_prod_rejects(self, monkeypatch):
        """生产环境（无 M10_DEV_MODE）未配置 token 时返回 False."""
        monkeypatch.delenv("M10_ADMIN_TOKEN", raising=False)
        monkeypatch.delenv("M10_DEV_MODE", raising=False)

        import importlib
        import server as server_mod
        importlib.reload(server_mod)

        assert server_mod._verify_m8_token("") is False
        assert server_mod._verify_m8_token("any-token") is False

    def test_no_token_dev_mode_allows(self, monkeypatch):
        """开发模式未配置 token 时返回 True."""
        monkeypatch.delenv("M10_ADMIN_TOKEN", raising=False)
        monkeypatch.setenv("M10_DEV_MODE", "true")

        import importlib
        import server as server_mod
        importlib.reload(server_mod)

        assert server_mod._verify_m8_token("") is True
        assert server_mod._verify_m8_token("anything") is True

    def test_with_token_correct(self, monkeypatch):
        """配置 token 且匹配时返回 True."""
        monkeypatch.setenv("M10_ADMIN_TOKEN", "secret-123")
        monkeypatch.delenv("M10_DEV_MODE", raising=False)

        import importlib
        import server as server_mod
        importlib.reload(server_mod)

        assert server_mod._verify_m8_token("secret-123") is True

    def test_with_token_wrong(self, monkeypatch):
        """配置 token 但不匹配时返回 False."""
        monkeypatch.setenv("M10_ADMIN_TOKEN", "secret-123")
        monkeypatch.delenv("M10_DEV_MODE", raising=False)

        import importlib
        import server as server_mod
        importlib.reload(server_mod)

        assert server_mod._verify_m8_token("wrong-token") is False

    def test_with_token_empty_request(self, monkeypatch):
        """配置 token 但请求 token 为空时返回 False."""
        monkeypatch.setenv("M10_ADMIN_TOKEN", "secret-123")
        monkeypatch.delenv("M10_DEV_MODE", raising=False)

        import importlib
        import server as server_mod
        importlib.reload(server_mod)

        assert server_mod._verify_m8_token("") is False

    def test_dev_mode_case_insensitive(self, monkeypatch):
        """M10_DEV_MODE 值大小写不敏感（TRUE/True/true 均有效）."""
        monkeypatch.delenv("M10_ADMIN_TOKEN", raising=False)

        import importlib
        import server as server_mod

        for val in ("true", "TRUE", "True"):
            monkeypatch.setenv("M10_DEV_MODE", val)
            importlib.reload(server_mod)
            assert server_mod._verify_m8_token("") is True, (
                f"M10_DEV_MODE={val} 应视为开发模式"
            )

    def test_is_dev_mode_false_values(self, monkeypatch):
        """非 true 值的 M10_DEV_MODE 不视为开发模式."""
        monkeypatch.delenv("M10_ADMIN_TOKEN", raising=False)

        import importlib
        import server as server_mod

        for val in ("false", "0", "1", "", "prod", "production"):
            monkeypatch.setenv("M10_DEV_MODE", val)
            importlib.reload(server_mod)
            assert server_mod._verify_m8_token("") is False, (
                f"M10_DEV_MODE={val} 不应视为开发模式"
            )
