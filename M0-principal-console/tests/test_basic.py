"""
M0 主理人管控台 - 基础测试

测试 API 基本功能是否正常。
运行方式: pytest tests/test_basic.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 添加项目路径
BASE_DIR = Path(__file__).parent.parent
SRC_DIR = BASE_DIR / "src"
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(SRC_DIR))

from fastapi.testclient import TestClient

from src.main import create_app


@pytest.fixture
def client():
    """创建测试客户端"""
    app = create_app()
    return TestClient(app)


class TestHealthEndpoints:
    """健康检查端点测试"""

    def test_health_check(self, client):
        """测试健康检查接口"""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["status"] == "healthy"
        assert "version" in data["data"]

    def test_healthz(self, client):
        """测试 liveness probe"""
        response = client.get("/healthz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    def test_readiness(self, client):
        """测试 readiness probe"""
        response = client.get("/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert "ready" in data["data"]


class TestAuthEndpoints:
    """认证端点测试"""

    def test_login_success(self, client):
        """测试登录成功"""
        response = client.post(
            "/api/auth/login",
            json={"username": "owner", "password": "owner123456"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["role"] == "owner"
        assert "access_token" in data["data"]

    def test_login_failure(self, client):
        """测试登录失败"""
        response = client.post(
            "/api/auth/login",
            json={"username": "wrong", "password": "wrong"},
        )
        assert response.status_code == 401
        data = response.json()
        assert data["code"] != 0

    def test_me_unauthorized(self, client):
        """测试未认证访问 /me"""
        response = client.get("/api/auth/me")
        assert response.status_code == 401


class TestDashboardEndpoints:
    """仪表盘端点测试"""

    def _get_token(self, client) -> str:
        """获取测试用 Token"""
        response = client.post(
            "/api/auth/login",
            json={"username": "owner", "password": "owner123456"},
        )
        return response.json()["data"]["access_token"]

    def test_dashboard_summary(self, client):
        """测试仪表盘总览"""
        token = self._get_token(client)
        response = client.get(
            "/api/dashboard/summary",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert "module_count" in data["data"]

    def test_quick_stats(self, client):
        """测试快速统计"""
        token = self._get_token(client)
        response = client.get(
            "/api/dashboard/quick-stats",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert len(data["data"]) == 6  # 6 个状态卡片

    def test_dashboard_unauthorized(self, client):
        """测试未认证访问仪表盘"""
        response = client.get("/api/dashboard/summary")
        assert response.status_code == 401


class TestModulesEndpoints:
    """模块管理端点测试"""

    def _get_token(self, client) -> str:
        response = client.post(
            "/api/auth/login",
            json={"username": "owner", "password": "owner123456"},
        )
        return response.json()["data"]["access_token"]

    def test_list_modules(self, client):
        """测试获取模块列表"""
        token = self._get_token(client)
        response = client.get(
            "/api/modules",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert isinstance(data["data"], list)
        assert len(data["data"]) > 0

    def test_get_module_detail(self, client):
        """测试获取模块详情"""
        token = self._get_token(client)
        response = client.get(
            "/api/modules/m8",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["key"] == "m8"


class TestConfigEndpoints:
    """配置中心端点测试"""

    def _get_token(self, client) -> str:
        response = client.post(
            "/api/auth/login",
            json={"username": "owner", "password": "owner123456"},
        )
        return response.json()["data"]["access_token"]

    def test_get_config(self, client):
        """测试获取全局配置"""
        token = self._get_token(client)
        response = client.get(
            "/api/config",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert "configs" in data["data"]

    def test_get_categories(self, client):
        """测试获取配置分类"""
        token = self._get_token(client)
        response = client.get(
            "/api/config/categories",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert isinstance(data["data"], list)

    def test_update_config(self, client):
        """测试更新配置"""
        token = self._get_token(client)
        response = client.put(
            "/api/config?category=system",
            json={"key": "log_level", "value": "debug"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
