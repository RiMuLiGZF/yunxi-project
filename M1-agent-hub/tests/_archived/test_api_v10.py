"""
测试：V10.0 FastAPI HTTP API 封装层

验证R04+R05：补全4个缺失标准接口+解决M3命名冲突。
"""

import pytest
import sys
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient

from api.server import create_server


@pytest.fixture
def mock_deps():
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
def client(mock_deps):
    app = create_server(**mock_deps)
    return TestClient(app)


def test_submit_task(client):
    resp = client.post("/api/v1/tasks/submit", json={"user_input": "hello", "task_id": "t1"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["task_id"] == "t1"


def test_delete_agent(client):
    resp = client.delete("/api/v1/agents/agent.dev")
    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "unregistered"


def test_get_agent_status_found(client):
    resp = client.get("/api/v1/agents/agent.dev/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["agent_id"] == "agent.dev"
    assert data["registered"] is True


def test_get_agent_status_not_found(client):
    resp = client.get("/api/v1/agents/agent.unknown/status")
    assert resp.status_code == 404


def test_get_task_status_found(client):
    resp = client.get("/api/v1/tasks/task.1/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["task_id"] == "task.1"
    assert data["status"] == "in_progress"


def test_get_task_status_not_found(client):
    resp = client.get("/api/v1/tasks/task.unknown/status")
    assert resp.status_code == 404


def test_bus_publish(client, mock_deps):
    resp = client.post("/api/v1/bus/publish", json={"topic": "test.topic", "payload": {"msg": "hi"}})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "published"
    assert "msg_id" in data
    mock_deps["message_bus"].publish.assert_called_once()


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "up"


def test_agents_list(client):
    resp = client.get("/agents")
    assert resp.status_code == 200
    assert "agents" in resp.json()
