"""
测试：APIServer HTTP API 服务网关

使用 httpx 对 FastAPI 应用进行测试。
"""

import pytest
import sys
import asyncio
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, "/workspace/agent_cluster")

from fastapi.testclient import TestClient

from api_server import APIServer
from streaming_engine import StreamChunk, StreamChunkType


@pytest.fixture
def mock_orchestrator():
    orch = MagicMock()
    orch._config = MagicMock()
    orch._config.to_dict.return_value = {"llm": {"model": "test"}}

    async def mock_process(*args, **kwargs):
        return {"reply": "test reply", "status": "success", "trace_id": "t1"}

    async def mock_stream(*args, **kwargs):
        yield StreamChunk(chunk_type=StreamChunkType.TEXT, content="Hello", trace_id="t1")
        yield StreamChunk(chunk_type=StreamChunkType.DONE, trace_id="t1")

    orch.process = mock_process
    orch.process_stream = mock_stream
    orch.submit_feedback = MagicMock()
    orch.discover_agents.return_value = []
    orch.diagnose.return_value = {"status": "ok"}
    return orch


@pytest.fixture
def client(mock_orchestrator):
    health = MagicMock()

    async def mock_liveness():
        from health_monitor import HealthStatus
        return HealthStatus(status="up")

    async def mock_overall():
        return {"status": "up", "liveness": {}, "readiness": {}}

    async def mock_prom():
        return "# metrics\n"

    health.liveness = mock_liveness
    health.overall_status = mock_overall
    health.to_prometheus = mock_prom

    server = APIServer(orchestrator=mock_orchestrator, health_monitor=health)
    return TestClient(server._app)


def test_chat(client):
    resp = client.post("/api/v1/chat", json={"user_input": "hello"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["reply"] == "test reply"


def test_chat_stream(client):
    resp = client.post("/api/v1/chat/stream", json={"user_input": "hello"})
    assert resp.status_code == 200
    text = resp.text
    assert "data:" in text
    assert "[DONE]" in text


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "up"


def test_ready(client):
    resp = client.get("/ready")
    assert resp.status_code == 200
    assert resp.json()["status"] == "up"


def test_metrics(client):
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "metrics" in resp.text


def test_diagnose(client):
    resp = client.get("/diagnose")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_feedback(client):
    resp = client.post("/feedback", json={
        "trace_id": "t1",
        "agent_id": "agent.test",
        "intent": "test",
        "rating": 5,
        "comment": "good",
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "feedback_received"


def test_agents(client):
    resp = client.get("/agents")
    assert resp.status_code == 200
    assert "agents" in resp.json()


def test_config(client):
    resp = client.get("/config")
    assert resp.status_code == 200
    assert resp.json()["llm"]["model"] == "test"
