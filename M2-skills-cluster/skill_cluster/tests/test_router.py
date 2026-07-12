from __future__ import annotations

"""SkillRouter 单元测试."""

import asyncio

import pytest

from skill_cluster.interfaces import ISkill, SkillInvokeRequest, SkillInvokeResult, SkillManifest
from skill_cluster.permissions import SkillPermissionManager
from skill_cluster.skill_registry import SkillRegistry
from skill_cluster.skill_router import SkillRouter


class DummySkill(ISkill):
    def __init__(self, skill_id: str, delay: float = 0.0) -> None:
        manifest = SkillManifest(
            skill_id=skill_id,
            name="Dummy",
            version="1.0.0",
            description="Test skill",
            author="test",
            entrypoint="DummySkill",
        )
        super().__init__(manifest)
        self.delay = delay

    async def invoke(self, request: SkillInvokeRequest) -> SkillInvokeResult:
        if self.delay:
            await asyncio.sleep(self.delay)
        return SkillInvokeResult(
            skill_id=self.manifest.skill_id,
            action=request.action,
            status="success",
            latency_ms=0.0,
            trace_id=request.trace_id,
        )

    async def health(self) -> dict:
        return {"healthy": True}

    async def configure(self, config: dict) -> None:
        pass


@pytest.fixture
def router(tmp_path) -> SkillRouter:
    # 重置单例
    SkillRouter._instance = None
    registry = SkillRegistry()
    pm = SkillPermissionManager(config_dir=str(tmp_path / "config"))
    return SkillRouter(registry=registry, permission_manager=pm)


@pytest.mark.asyncio
async def test_mount_and_invoke(router: SkillRouter) -> None:
    skill = DummySkill("skill.dummy")
    router.mount(skill)
    req = SkillInvokeRequest(
        skill_id="skill.dummy",
        action="test",
        trace_id="t1",
    )
    result = await router.invoke(req, agent_id="agent1")
    assert result.status == "success"
    assert result.skill_id == "skill.dummy"


@pytest.mark.asyncio
async def test_invoke_not_found(router: SkillRouter) -> None:
    req = SkillInvokeRequest(
        skill_id="skill.missing",
        action="test",
        trace_id="t1",
    )
    result = await router.invoke(req, agent_id="agent1")
    assert result.status == "not_found"


@pytest.mark.asyncio
async def test_invoke_unauthorized(router: SkillRouter) -> None:
    skill = DummySkill("skill.tide_memory")
    router.mount(skill)
    req = SkillInvokeRequest(
        skill_id="skill.tide_memory",
        action="test",
        trace_id="t1",
    )
    result = await router.invoke(req, agent_id="agent1")
    assert result.status == "unauthorized"


@pytest.mark.asyncio
async def test_invoke_timeout(router: SkillRouter) -> None:
    skill = DummySkill("skill.slow", delay=5.0)
    router.mount(skill)
    req = SkillInvokeRequest(
        skill_id="skill.slow",
        action="test",
        trace_id="t1",
        timeout=1,
    )
    result = await router.invoke(req, agent_id="agent1")
    assert result.status == "timeout"


@pytest.mark.asyncio
async def test_invoke_batch(router: SkillRouter) -> None:
    router.mount(DummySkill("skill.a"))
    router.mount(DummySkill("skill.b"))
    requests = [
        SkillInvokeRequest(skill_id="skill.a", action="test", trace_id="t1"),
        SkillInvokeRequest(skill_id="skill.b", action="test", trace_id="t1"),
    ]
    results = await router.invoke_batch(requests, agent_id="agent1")
    assert len(results) == 2
    assert all(r.status == "success" for r in results)


@pytest.mark.asyncio
async def test_health_check_all(router: SkillRouter) -> None:
    router.mount(DummySkill("skill.h1"))
    health = await router.health_check_all()
    assert "skill.h1" in health
    assert health["skill.h1"]["healthy"] is True


@pytest.mark.asyncio
async def test_invoke_latency(router: SkillRouter) -> None:
    skill = DummySkill("skill.latency")
    router.mount(skill)
    req = SkillInvokeRequest(
        skill_id="skill.latency",
        action="test",
        trace_id="t1",
    )
    result = await router.invoke(req, agent_id="agent1")
    assert result.latency_ms >= 0
