"""
API 接口测试套件（按功能模块重组）

来源版本：
- test_api_v10.py (v10.0 FastAPI HTTP API 封装层)
- test_v11_1_m8_integration.py (M8 标准接口)

说明：
本文件从各版本测试中提取 API 接口相关测试，按端点分类组织。
原始版本文件已移入 tests/_legacy/ 目录保存。
"""

from __future__ import annotations

import sys
import os

import pytest
from unittest.mock import AsyncMock, MagicMock

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================================
# 1. 主 API Server 测试（来源：test_api_v10.py）
# ============================================================================

class TestMainAPIServer:
    """主 API Server 接口测试"""

    @pytest.fixture
    def mock_deps(self):
        orch = MagicMock()
        registry = MagicMock()
        ledger = MagicMock()
        bus = MagicMock()
        health = MagicMock()

        async def mock_process(*args, **kwargs):
            return {"status": "success", "reply": "hello", "task_id": kwargs.get("task_id", "t1")}

        orch.process = mock_process
        orch.process_stream = AsyncMock()
        orch.diagnose.return_value = {"status": "ok"}

        registry.list_all.return_value = []
        registry.unregister = AsyncMock()

        async def mock_get_status(agent_id):
            if agent_id == "agent.dev":
                return {"agent_id": agent_id, "registered": True, "version": "1.0", "capabilities": ["code"], "health": {"status": "healthy"}}
            return None
        registry.get_status = mock_get_status

        def mock_query_task(task_id):
            if task_id == "task.1":
                return {"task_id": task_id, "goal": "test", "status": "in_progress", "completion_rate": 0.5, "plans": [], "agents": [], "active": True}
            return None
        ledger.query_task = mock_query_task

        bus.publish = AsyncMock()

        async def mock_liveness():
            from health_monitor import HealthStatus
            return HealthStatus(status="up")
        health.liveness = mock_liveness

        async def mock_overall():
            return {"status": "up", "liveness": {}, "readiness": {}}
        health.overall_status = mock_overall

        async def mock_prom():
            return "# metrics\n"
        health.to_prometheus = mock_prom

        return {"orchestrator": orch, "registry": registry, "ledger": ledger, "message_bus": bus, "health_monitor": health}

    @pytest.fixture
    def client(self, mock_deps):
        from api.server import create_server
        from fastapi.testclient import TestClient
        app = create_server(**mock_deps)
        return TestClient(app)

    def test_submit_task(self, client):
        resp = client.post("/api/v1/tasks/submit", json={"user_input": "hello", "task_id": "t1"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["task_id"] == "t1"

    def test_delete_agent(self, client):
        resp = client.delete("/api/v1/agents/agent.dev")
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "unregistered"

    def test_get_agent_status_found(self, client):
        resp = client.get("/api/v1/agents/agent.dev/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_id"] == "agent.dev"
        assert data["registered"] is True

    def test_get_agent_status_not_found(self, client):
        resp = client.get("/api/v1/agents/agent.unknown/status")
        assert resp.status_code == 404

    def test_get_task_status_found(self, client):
        resp = client.get("/api/v1/tasks/task.1/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["task_id"] == "task.1"
        assert data["status"] == "in_progress"

    def test_get_task_status_not_found(self, client):
        resp = client.get("/api/v1/tasks/task.unknown/status")
        assert resp.status_code == 404

    def test_bus_publish(self, client, mock_deps):
        resp = client.post("/api/v1/bus/publish", json={"topic": "test.topic", "payload": {"msg": "hi"}})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "published"
        assert "msg_id" in data
        mock_deps["message_bus"].publish.assert_called_once()

    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "up"

    def test_agents_list(self, client):
        resp = client.get("/agents")
        assert resp.status_code == 200
        assert "agents" in resp.json()


# ============================================================================
# 2. M8 标准接口测试（来源：test_v11_1_m8_integration.py）
# ============================================================================

class TestM8StandardInterface:
    """M8 标准接口测试"""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from api.m8_interface import register_m8_routes
        from config_manager import ConfigManager

        class MockOrchestrator:
            def get_stats(self):
                return {
                    "active_tasks": 5,
                    "queue_size": 10,
                    "total_requests": 100,
                    "rps": 2.5,
                    "avg_latency_ms": 50.0,
                    "error_rate": 0.01,
                }

        app = FastAPI(title="M8 Test App")
        register_m8_routes(
            app,
            config_manager=ConfigManager(),
            health_monitor=None,
            metrics_collector=None,
            orchestrator=MockOrchestrator(),
        )
        return TestClient(app)

    def test_health_returns_m8_standard_format(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "version" in data
        assert "uptime_seconds" in data
        assert "module" in data
        assert data["status"] in ("healthy", "degraded", "unhealthy")
        assert isinstance(data["uptime_seconds"], int)
        assert data["module"] == "m1"

    def test_metrics_returns_m8_standard_format(self, client):
        response = client.get("/metrics")
        assert response.status_code == 200
        data = response.json()
        assert "cpu_percent" in data
        assert "memory_mb" in data
        assert "requests_total" in data
        assert "requests_per_second" in data
        assert "avg_response_ms" in data
        assert "error_rate" in data
        assert "active_tasks" in data
        assert "queue_size" in data

    def test_config_requires_m8_token(self, client):
        original_token = os.environ.get("M1_ADMIN_TOKEN", "")
        os.environ["M1_ADMIN_TOKEN"] = "test-m8-token-secret"
        try:
            response_no_token = client.get("/config")
            assert response_no_token.status_code == 401
            response_wrong_token = client.get(
                "/config", headers={"X-M8-Token": "wrong-token"}
            )
            assert response_wrong_token.status_code == 401
            response_valid = client.get(
                "/config", headers={"X-M8-Token": "test-m8-token-secret"}
            )
            assert response_valid.status_code == 200
            data = response_valid.json()
            assert "success" in data
            assert "config" in data
        finally:
            if original_token:
                os.environ["M1_ADMIN_TOKEN"] = original_token
            else:
                os.environ.pop("M1_ADMIN_TOKEN", None)

    def test_code_snapshot_returns_info(self, client):
        response = client.get("/code/snapshot")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "snapshot_id" in data
        assert "module" in data
        assert "version" in data
        assert "file_count" in data
        assert isinstance(data["file_count"], int)
        assert data["file_count"] > 0

    def test_upgrade_preview_returns_compatibility(self, client):
        response = client.post(
            "/upgrade/preview",
            json={
                "target_version": "12.0.0",
                "package_url": "http://example.com/package.tar.gz",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "compatible" in data
        assert "can_upgrade" in data
        assert isinstance(data["changes"], list)

    def test_upgrade_apply_returns_upgrade_task(self, client):
        response = client.post(
            "/upgrade/apply",
            json={"target_version": "12.0.0"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "upgrade_id" in data
        assert data["status"] == "pending"

    def test_test_run_creates_task(self, client):
        response = client.post(
            "/test/run",
            json={
                "type": "smoke",
                "scope": "core",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "test_id" in data
        assert data["test_type"] == "smoke"

    def test_test_result_gets_result(self, client):
        run_response = client.post(
            "/test/run",
            json={"type": "unit", "scope": "all"},
        )
        test_id = run_response.json()["test_id"]
        response = client.get(f"/test/result/{test_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["test_id"] == test_id
        assert "total_tests" in data
        not_found_response = client.get("/test/result/nonexistent_test_id")
        assert not_found_response.status_code == 404


# ============================================================================
# 测试入口
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
