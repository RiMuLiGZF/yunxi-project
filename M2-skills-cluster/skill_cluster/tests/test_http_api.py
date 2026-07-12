"""Tests for HTTP API layer."""

import pytest

from skill_cluster.http_api import (
    InvokeRequest,
    SearchResponse,
    SkillInfo,
    HealthResponse,
    manifest_to_skill_info,
    result_to_dict,
    create_app,
)


class FakeManifest:
    skill_id = "skill.test"
    name = "TestSkill"
    description = "A test skill"
    category = "test"
    tags = ["test", "demo"]
    actions = ["run", "analyze"]
    complexity_score = 0.8


class FakeResult:
    skill_id = "skill.test"
    action = "run"
    status = "success"
    data = {"key": "value"}
    error = None
    latency_ms = 42.5
    trace_id = "trace_001"


def test_invoke_request_defaults():
    req = InvokeRequest(skill_id="s1")
    assert req.action == "default"
    assert req.agent_id == "default_agent"
    assert req.cache_scope == "public"


def test_manifest_to_skill_info():
    info = manifest_to_skill_info(FakeManifest())
    assert info.skill_id == "skill.test"
    assert info.name == "TestSkill"
    assert info.actions == ["run", "analyze"]
    assert info.complexity_score == 0.8


def test_result_to_dict():
    d = result_to_dict(FakeResult())
    assert d["status"] == "success"
    assert d["data"] == {"key": "value"}
    assert d["latency_ms"] == 42.5


def test_search_response():
    resp = SearchResponse(
        query="test",
        results=[manifest_to_skill_info(FakeManifest())],
        total=1,
    )
    assert resp.total == 1


def test_health_response():
    resp = HealthResponse(status="healthy", score=0.95, components=[])
    assert resp.status == "healthy"


def test_create_app_without_fastapi():
    """FastAPI 不存在时返回 None."""
    # 保存原始值
    import skill_cluster.http_api as mod
    orig = mod._fastapi_available
    mod._fastapi_available = False
    app = create_app()
    assert app is None
    mod._fastapi_available = orig


def test_create_app_with_fastapi():
    """FastAPI 存在时返回 FastAPI 实例."""
    import skill_cluster.http_api as mod
    if not mod._fastapi_available:
        pytest.skip("FastAPI not installed")
    app = create_app()
    assert app is not None
    assert app.title == "云汐 Skills 集群 API"
