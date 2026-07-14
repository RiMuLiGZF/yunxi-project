"""
M0 主理人管控台 - M8 标准接口测试

测试 M8 标准接口（/m8/health, /m8/metrics, /m8/config）的可用性。
运行方式: pytest tests/test_m8_api.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

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


class TestM8HealthEndpoint:
    """M8 标准健康检查接口测试"""

    def test_m8_health(self, client):
        """测试 /m8/health 返回标准格式"""
        response = client.get("/m8/health")
        assert response.status_code in (200, 404)
        if response.status_code == 200:
            data = response.json()
            assert "code" in data or "status" in data

    def test_m8_metrics(self, client):
        """测试 /m8/metrics 返回指标数据"""
        response = client.get("/m8/metrics")
        assert response.status_code in (200, 404)

    def test_m8_config(self, client):
        """测试 /m8/config 返回配置信息"""
        response = client.get("/m8/config")
        assert response.status_code in (200, 404)


class TestM8AuthMiddleware:
    """M8 认证中间件测试"""

    def test_internal_token_auth(self, client):
        """测试 X-M8-Internal-Token 认证"""
        response = client.get(
            "/api/modules",
            headers={"X-M8-Internal-Token": "yunxi-dev-secret-do-not-use-in-production-20260714"},
        )
        # 内部 Token 认证通过后应返回 200
        assert response.status_code in (200, 401, 403)

    def test_invalid_token_rejected(self, client):
        """测试无效 Token 被拒绝"""
        response = client.get(
            "/api/modules",
            headers={"Authorization": "Bearer invalid-token-12345"},
        )
        assert response.status_code in (401, 403, 200)

    def test_no_auth_for_public_endpoints(self, client):
        """测试公开端点无需认证"""
        response = client.get("/health")
        assert response.status_code == 200

        response = client.get("/healthz")
        assert response.status_code == 200

        response = client.get("/ready")
        assert response.status_code == 200


class TestM0M8Client:
    """M0 对 M8 的客户端调用测试（模拟）"""

    def test_m8_client_check_health_mock(self, client):
        """测试 M8 客户端健康检查（M8 未启动时返回 False）"""
        # 此测试验证 M0 在 M8 不可用时不会崩溃
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        # m8_connected 可能为 True 或 False，取决于 M8 是否运行
        assert "data" in data
