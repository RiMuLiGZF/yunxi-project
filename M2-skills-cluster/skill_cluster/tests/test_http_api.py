"""Tests for HTTP API layer."""

import sys
import pytest
from unittest.mock import patch, MagicMock

from skill_cluster.api.http import (
    InvokeRequest,
    SearchResponse,
    SkillInfo,
    HealthResponse,
    manifest_to_skill_info,
    result_to_dict,
    create_http_app as create_app,
    _fastapi_available,
)



class FakeAction:
    """模拟 SkillAction 对象."""
    def __init__(self, name):
        self.name = name


class FakeManifest:
    skill_id = "skill.test"
    name = "TestSkill"
    description = "A test skill"
    category = "test"
    tags = ["test", "demo"]
    actions = [FakeAction("run"), FakeAction("analyze")]
    complexity_score = 0.8


class FakeResult:
    skill_id = "skill.test"
    action = "run"
    status = "success"
    data = {"key": "value"}
    error = None
    latency_ms = 42.5
    trace_id = "trace_001"


# ===========================================================================
# 数据模型测试（不依赖 FastAPI）
# ===========================================================================

def test_invoke_request_defaults():
    req = InvokeRequest(skill_id="s1")
    assert req.action == "default"
    assert req.agent_id == "default_agent"
    assert req.cache_scope == "public"


def test_invoke_request_with_custom_values():
    """测试 InvokeRequest 自定义参数"""
    req = InvokeRequest(
        skill_id="s1",
        action="custom_action",
        agent_id="agent_007",
        cache_scope="private",
    )
    assert req.skill_id == "s1"
    assert req.action == "custom_action"
    assert req.agent_id == "agent_007"
    assert req.cache_scope == "private"


def test_manifest_to_skill_info():
    info = manifest_to_skill_info(FakeManifest())
    assert info.skill_id == "skill.test"
    assert info.name == "TestSkill"
    assert info.actions == ["run", "analyze"]
    assert info.complexity_score == 0.8


def test_manifest_to_skill_info_tags():
    """测试 manifest 到 SkillInfo 的标签转换"""
    info = manifest_to_skill_info(FakeManifest())
    assert info.tags == ["test", "demo"]
    assert info.category == "test"


def test_result_to_dict():
    d = result_to_dict(FakeResult())
    assert d["status"] == "success"
    assert d["data"] == {"key": "value"}
    assert d["latency_ms"] == 42.5


def test_result_to_dict_with_error():
    """测试错误结果的字典转换"""
    class ErrorResult:
        skill_id = "skill.test"
        action = "run"
        status = "error"
        data = None
        error = "Something went wrong"
        latency_ms = 10.0
        trace_id = "trace_002"

    d = result_to_dict(ErrorResult())
    assert d["status"] == "error"
    assert d["error"] == "Something went wrong"
    assert d["trace_id"] == "trace_002"


def test_search_response():
    resp = SearchResponse(
        query="test",
        results=[manifest_to_skill_info(FakeManifest())],
        total=1,
    )
    assert resp.total == 1


def test_search_response_empty():
    """测试空搜索结果"""
    resp = SearchResponse(
        query="nonexistent",
        results=[],
        total=0,
    )
    assert resp.total == 0
    assert resp.results == []


def test_health_response():
    resp = HealthResponse(status="healthy", score=0.95, components=[])
    assert resp.status == "healthy"


def test_health_response_unhealthy():
    """测试不健康状态响应"""
    resp = HealthResponse(
        status="unhealthy",
        score=0.3,
        components=[{"name": "db", "status": "degraded"}, {"name": "cache", "status": "down"}],
    )
    assert resp.status == "unhealthy"
    assert resp.score == 0.3
    assert len(resp.components) == 2
    assert resp.components[0]["name"] == "db"


# ===========================================================================
# create_app 测试
# ===========================================================================

def test_create_app_without_fastapi():
    """FastAPI 不存在时返回 None."""
    import skill_cluster.api.http as mod
    orig = mod._fastapi_available
    mod._fastapi_available = False
    app = create_app()
    assert app is None
    mod._fastapi_available = orig


@pytest.mark.skipif(not _fastapi_available, reason="FastAPI not installed")
def test_create_app_with_fastapi():
    """FastAPI 存在时返回 FastAPI 实例."""
    app = create_app()
    assert app is not None
    assert "Skill" in app.title


@pytest.mark.skipif(not _fastapi_available, reason="FastAPI not installed")
def test_create_app_routes_registered():
    """测试 FastAPI 应用是否注册了必要的路由."""
    app = create_app()
    assert app is not None
    # 检查路由数量（至少有健康检查等基本路由）
    routes = [route.path for route in app.routes]
    # 应该至少有一条路由
    assert len(routes) > 0


def test_skill_info_dataclass():
    """测试 SkillInfo 数据类的字段"""
    info = SkillInfo(
        skill_id="test.skill",
        name="Test Skill",
        description="A test",
        category="test",
        tags=["t1"],
        actions=["run"],
        complexity_score=0.5,
    )
    assert info.skill_id == "test.skill"
    assert info.name == "Test Skill"
    assert info.complexity_score == 0.5
