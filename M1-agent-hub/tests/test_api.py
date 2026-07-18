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
# 3. Agent Card 发现端点测试（GAP-002 补全）
# ============================================================================

class TestAgentCardDiscovery:
    """[GAP-002] Agent Card .well-known 发现端点测试"""

    @pytest.fixture
    def mock_deps(self):
        orch = MagicMock()
        registry = MagicMock()
        ledger = MagicMock()
        bus = MagicMock()
        health = MagicMock()

        orch.process = AsyncMock(return_value={"status": "success"})
        orch.process_stream = AsyncMock()
        orch.diagnose.return_value = {"status": "ok"}

        # 模拟几个 Agent
        class MockAgent:
            def __init__(self, agent_id, name, version, capabilities, description=""):
                self.agent_id = agent_id
                self.name = name
                self.version = version
                self.capabilities = capabilities
                self.description = description
                self.skills = ["general"]
                self.tags = ["test"]

        registry.list_all.return_value = [
            MockAgent("agent.note", "笔记助手", "1.2.0",
                      ["note.create", "note.search"], "管理学习笔记"),
            MockAgent("agent.dev", "开发助手", "2.0.0",
                      ["dev.code", "dev.qa", "dev.debug"], "代码开发辅助"),
        ]
        registry.unregister = AsyncMock()
        registry.get_status = AsyncMock(return_value=None)

        ledger.query_task.return_value = None
        bus.publish = AsyncMock()

        async def mock_liveness():
            class H:
                status = "up"
            return H()
        health.liveness = mock_liveness
        health.overall_status = AsyncMock(return_value={"status": "up"})
        health.to_prometheus = AsyncMock(return_value="# metrics\n")

        return {"orchestrator": orch, "registry": registry, "ledger": ledger,
                "message_bus": bus, "health_monitor": health}

    @pytest.fixture
    def client(self, mock_deps):
        from api.server import create_server
        from fastapi.testclient import TestClient
        app = create_server(**mock_deps)
        return TestClient(app)

    def test_well_known_agent_card_endpoint_exists(self, client):
        """测试 .well-known/agent-card.json 端点可访问"""
        resp = client.get("/.well-known/agent-card.json")
        assert resp.status_code == 200

    def test_well_known_response_structure(self, client):
        """测试响应包含标准字段"""
        resp = client.get("/.well-known/agent-card.json")
        data = resp.json()
        # 顶层字段
        assert "hub" in data
        assert "agent_cards" in data
        assert "endpoints" in data
        assert "protocol_version" in data
        assert "total_agents" in data
        assert data["protocol_version"] == "1.0"

    def test_hub_info_complete(self, client):
        """测试 Hub 信息完整"""
        resp = client.get("/.well-known/agent-card.json")
        data = resp.json()
        hub = data["hub"]
        assert "name" in hub
        assert "version" in hub
        assert "protocol_version" in hub
        assert "description" in hub
        assert hub["name"] == "yunxi-m1-agent-hub"

    def test_agent_cards_have_complete_fields(self, client):
        """测试每个 AgentCard 包含完整字段"""
        resp = client.get("/.well-known/agent-card.json")
        data = resp.json()
        cards = data["agent_cards"]
        assert len(cards) == 2

        for card in cards:
            assert "agent_id" in card
            assert "agent_name" in card
            assert "version" in card
            assert "description" in card
            assert "capabilities" in card
            assert "endpoints" in card
            assert "skills" in card
            assert "tags" in card

    def test_capabilities_are_objects(self, client):
        """测试能力字段为对象格式（而非纯字符串）"""
        resp = client.get("/.well-known/agent-card.json")
        data = resp.json()
        cards = data["agent_cards"]

        note_card = next(c for c in cards if c["agent_id"] == "agent.note")
        for cap in note_card["capabilities"]:
            assert isinstance(cap, dict)
            assert "id" in cap
            assert "name" in cap
            assert "description" in cap

    def test_endpoints_have_protocol_and_url(self, client):
        """测试端点包含协议和 URL"""
        resp = client.get("/.well-known/agent-card.json")
        data = resp.json()
        cards = data["agent_cards"]

        for card in cards:
            for ep in card["endpoints"]:
                assert "protocol" in ep
                assert "url" in ep
                assert "auth_type" in ep

    def test_hub_endpoints_listed(self, client):
        """测试 Hub 级别端点正确列出"""
        resp = client.get("/.well-known/agent-card.json")
        data = resp.json()
        endpoints = data["endpoints"]
        assert len(endpoints) >= 3

        urls = [ep["url"] for ep in endpoints]
        assert "/api/v1/tasks/submit" in urls
        assert "/api/v1/chat" in urls
        assert "/api/v1/chat/stream" in urls

    def test_total_agents_matches(self, client):
        """测试 total_agents 计数正确"""
        resp = client.get("/.well-known/agent-card.json")
        data = resp.json()
        assert data["total_agents"] == len(data["agent_cards"])

    def test_empty_agents_still_returns_valid(self, mock_deps):
        """测试无 Agent 时仍返回有效响应"""
        mock_deps["registry"].list_all.return_value = []
        from api.server import create_server
        from fastapi.testclient import TestClient
        app = create_server(**mock_deps)
        client = TestClient(app)

        resp = client.get("/.well-known/agent-card.json")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_agents"] == 0
        assert data["agent_cards"] == []
        assert "hub" in data


# ============================================================================
# 测试入口
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
