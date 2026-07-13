from __future__ import annotations

"""Middleware 单元测试."""

import asyncio

import pytest

from skill_cluster.interfaces import SkillInvokeRequest, SkillInvokeResult
from skill_cluster.middleware import (
    MiddlewarePipeline,
    logging_middleware,
)
from skill_cluster.infrastructure.metrics import MetricsCollector


@pytest.mark.asyncio
async def test_middleware_pipeline_order() -> None:
    order: list[str] = []

    async def mw_a(request: SkillInvokeRequest, agent_id: str, next_handler: Any) -> SkillInvokeResult:
        order.append("a_before")
        result = await next_handler()
        order.append("a_after")
        return result

    async def mw_b(request: SkillInvokeRequest, agent_id: str, next_handler: Any) -> SkillInvokeResult:
        order.append("b_before")
        result = await next_handler()
        order.append("b_after")
        return result

    async def handler() -> SkillInvokeResult:
        order.append("handler")
        return SkillInvokeResult(
            skill_id="test",
            action="test",
            status="success",
            latency_ms=0.0,
            trace_id="t1",
        )

    pipeline = MiddlewarePipeline()
    pipeline.use(mw_a).use(mw_b)

    request = SkillInvokeRequest(skill_id="test", action="test", trace_id="t1")
    result = await pipeline.execute(request, "agent1", handler)

    assert result.status == "success"
    # 洋葱模型：a_before -> b_before -> handler -> b_after -> a_after
    assert order == ["a_before", "b_before", "handler", "b_after", "a_after"]


@pytest.mark.asyncio
async def test_middleware_modify_result() -> None:
    async def mw_add_tag(request: SkillInvokeRequest, agent_id: str, next_handler: Any) -> SkillInvokeResult:
        result = await next_handler()
        if result.data is None:
            result.data = {}
        result.data["tag"] = "processed"
        return result

    async def handler() -> SkillInvokeResult:
        return SkillInvokeResult(
            skill_id="test",
            action="test",
            status="success",
            latency_ms=0.0,
            trace_id="t1",
        )

    pipeline = MiddlewarePipeline()
    pipeline.use(mw_add_tag)

    request = SkillInvokeRequest(skill_id="test", action="test", trace_id="t1")
    result = await pipeline.execute(request, "agent1", handler)

    assert result.data == {"tag": "processed"}


@pytest.mark.asyncio
async def test_middleware_short_circuit() -> None:
    async def mw_block(request: SkillInvokeRequest, agent_id: str, next_handler: Any) -> SkillInvokeResult:
        return SkillInvokeResult(
            skill_id="test",
            action="test",
            status="failure",
            latency_ms=0.0,
            trace_id="t1",
        )

    async def handler() -> SkillInvokeResult:
        return SkillInvokeResult(
            skill_id="test",
            action="test",
            status="success",
            latency_ms=0.0,
            trace_id="t1",
        )

    pipeline = MiddlewarePipeline()
    pipeline.use(mw_block)

    request = SkillInvokeRequest(skill_id="test", action="test", trace_id="t1")
    result = await pipeline.execute(request, "agent1", handler)

    assert result.status == "failure"


@pytest.mark.asyncio
async def test_metrics_middleware() -> None:
    from skill_cluster.middleware import metrics_middleware

    collector = MetricsCollector()
    mw = metrics_middleware(collector)

    async def handler() -> SkillInvokeResult:
        await asyncio.sleep(0.01)
        return SkillInvokeResult(
            skill_id="skill.test",
            action="action1",
            status="success",
            latency_ms=10.0,
            trace_id="t1",
        )

    pipeline = MiddlewarePipeline()
    pipeline.use(mw)

    request = SkillInvokeRequest(skill_id="skill.test", action="action1", trace_id="t1")
    await pipeline.execute(request, "agent1", handler)

    total = collector.counter("skill_invocations_total")
    assert total.get({"skill_id": "skill.test", "action": "action1", "agent_id": "agent1", "status": "success"}) == 1


@pytest.mark.asyncio
async def test_logging_middleware() -> None:
    mw = logging_middleware()

    async def handler() -> SkillInvokeResult:
        return SkillInvokeResult(
            skill_id="test",
            action="test",
            status="success",
            latency_ms=0.0,
            trace_id="t1",
        )

    pipeline = MiddlewarePipeline()
    pipeline.use(mw)

    request = SkillInvokeRequest(skill_id="test", action="test", trace_id="t1")
    result = await pipeline.execute(request, "agent1", handler)
    assert result.status == "success"
