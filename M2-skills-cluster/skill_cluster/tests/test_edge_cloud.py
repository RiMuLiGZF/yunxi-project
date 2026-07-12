"""Tests for EdgeCloudOrchestrator."""

import asyncio

import pytest

from skill_cluster.edge_cloud_orchestrator import (
    EdgeCloudConfig,
    EdgeCloudOrchestrator,
)
from skill_cluster.interfaces import (
    SkillInvokeRequest,
    SkillInvokeResult,
)
from skill_cluster.token_budget import TokenBudget


class FakeRouter:
    """模拟路由器."""

    def __init__(self, responses):
        self._responses = responses
        self._calls = []

    async def invoke(self, request, agent_id):
        self._calls.append((request.skill_id, request.action))
        key = (request.skill_id, request.action)
        return self._responses.get(key, SkillInvokeResult(
            skill_id=request.skill_id,
            action=request.action,
            status="failure",
            error="not configured",
            latency_ms=0.0,
            trace_id=request.trace_id,
        ))


@pytest.fixture
def budget():
    return TokenBudget(total_budget=1000)


@pytest.fixture
def edge_router():
    return FakeRouter({
        ("skill.a", "act1"): SkillInvokeResult(
            skill_id="skill.a", action="act1",
            status="success", latency_ms=100.0, trace_id="t1",
        ),
        ("skill.b", "act1"): SkillInvokeResult(
            skill_id="skill.b", action="act1",
            status="timeout", error="timeout", latency_ms=5000.0, trace_id="t1",
        ),
    })


@pytest.fixture
def cloud_router():
    return FakeRouter({
        ("skill.a", "act1"): SkillInvokeResult(
            skill_id="skill.a", action="act1",
            status="success", latency_ms=200.0, trace_id="t1",
        ),
        ("skill.b", "act1"): SkillInvokeResult(
            skill_id="skill.b", action="act1",
            status="success", latency_ms=200.0, trace_id="t1",
        ),
    })


@pytest.fixture
def orchestrator(edge_router, cloud_router, budget):
    return EdgeCloudOrchestrator(
        edge_router, cloud_router, budget,
        config=EdgeCloudConfig(budget_threshold_for_cloud=0.8),
    )


@pytest.mark.asyncio
async def test_edge_success_no_fallback(orchestrator, edge_router):
    req = SkillInvokeRequest(
        skill_id="skill.a", action="act1", params={}, trace_id="t1"
    )
    result = await orchestrator.invoke(req, "agent1")
    assert result.status == "success"
    assert result.latency_ms == 100.0
    assert len(edge_router._calls) == 1


@pytest.mark.asyncio
async def test_edge_timeout_fallback_to_cloud(orchestrator, edge_router, cloud_router):
    req = SkillInvokeRequest(
        skill_id="skill.b", action="act1", params={}, trace_id="t1"
    )
    result = await orchestrator.invoke(req, "agent1")
    assert result.status == "success"
    assert result.latency_ms == 200.0
    assert len(edge_router._calls) == 1
    assert len(cloud_router._calls) == 1


@pytest.mark.asyncio
async def test_force_cloud(edge_router, cloud_router, budget):
    orch = EdgeCloudOrchestrator(
        edge_router, cloud_router, budget,
        config=EdgeCloudConfig(),
    )
    req = SkillInvokeRequest(
        skill_id="skill.a", action="act1", params={}, trace_id="t1"
    )
    result = await orch.invoke(req, "agent1", force_cloud=True)
    assert result.status == "success"
    assert len(edge_router._calls) == 0
    assert len(cloud_router._calls) == 1


@pytest.mark.asyncio
async def test_high_budget_direct_cloud(edge_router, cloud_router, budget):
    orch = EdgeCloudOrchestrator(
        edge_router, cloud_router, budget,
        config=EdgeCloudConfig(budget_threshold_for_cloud=0.5),
    )
    # 消耗 600 tokens，使 usage_ratio > 0.5
    for _ in range(6):
        budget.consume(100, "input")
    req = SkillInvokeRequest(
        skill_id="skill.a", action="act1", params={}, trace_id="t1"
    )
    result = await orch.invoke(req, "agent1")
    # 预算高时直接走云端
    assert len(cloud_router._calls) >= 1


def test_get_stats(orchestrator):
    stats = orchestrator.get_stats()
    assert stats["edge_calls"] == 0
    assert stats["cloud_calls"] == 0
    assert stats["budget_usage_ratio"] == 0.0


def test_get_available_tools_full(budget):
    orch = EdgeCloudOrchestrator(None, None, budget)
    tools = [{"name": f"tool{i}"} for i in range(10)]
    result = orch.get_available_tools(tools, budget_ratio=0.3)
    assert len(result) == 10


def test_get_available_tools_medium(budget):
    orch = EdgeCloudOrchestrator(None, None, budget)
    tools = [{"name": f"tool{i}"} for i in range(10)]
    result = orch.get_available_tools(tools, budget_ratio=0.6)
    assert len(result) == 7  # 70%


def test_get_available_tools_tight(budget):
    orch = EdgeCloudOrchestrator(None, None, budget)
    tools = [{"name": f"tool{i}"} for i in range(10)]
    result = orch.get_available_tools(tools, budget_ratio=0.9)
    assert len(result) == 3  # 30%


def test_cloud_timeout_multiplier():
    config = EdgeCloudConfig(cloud_timeout_multiplier=2.5)
    assert config.cloud_timeout_multiplier == 2.5
