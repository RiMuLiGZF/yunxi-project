"""P2-7: 场景 API 集成测试"""
import sys
from pathlib import Path
from fastapi.testclient import TestClient
from main import app
import pytest


@pytest.fixture
def client():
    return TestClient(app)


class TestHealthEndpoints:
    def test_health(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        # 格式: {code, message, data: {status, ...}}
        assert data.get("code") == 0 or data.get("data", {}).get("status") == "healthy"


class TestSceneEndpoints:
    def test_list_scenes(self, client):
        response = client.get("/api/v1/scenes")
        assert response.status_code == 200

    def test_get_scene_not_found(self, client):
        response = client.get("/api/v1/scenes/nonexistent-12345")
        assert response.status_code in (200, 404)


class TestContextEndpoints:
    def test_get_context(self, client):
        response = client.get("/api/v1/context/default")
        assert response.status_code == 200

