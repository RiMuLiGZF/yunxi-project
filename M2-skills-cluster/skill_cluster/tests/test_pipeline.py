from __future__ import annotations

"""Skill Pipeline 单元测试."""

import pytest

from skill_cluster.interfaces import ISkill, SkillInvokeRequest, SkillInvokeResult, SkillManifest
from skill_cluster.permissions import SkillPermissionManager
from skill_cluster.skill_pipeline import PipelineDefinition, PipelineEngine, PipelineStep
from skill_cluster.skill_registry import SkillRegistry
from skill_cluster.skill_router import SkillRouter


class DummySkill(ISkill):
    def __init__(self, skill_id: str) -> None:
        manifest = SkillManifest(
            skill_id=skill_id,
            name="Dummy",
            version="1.0.0",
            description="Test skill",
            author="test",
            entrypoint="DummySkill",
        )
        super().__init__(manifest)
        self.calls: list[dict] = []

    async def invoke(self, request: SkillInvokeRequest) -> SkillInvokeResult:
        self.calls.append({"action": request.action, "params": request.params})
        return SkillInvokeResult(
            skill_id=self.manifest.skill_id,
            action=request.action,
            status="success",
            data={"echo": request.params},
            latency_ms=0.0,
            trace_id=request.trace_id,
        )

    async def health(self) -> dict:
        return {"healthy": True}

    async def configure(self, config: dict) -> None:
        pass


@pytest.fixture
def pipeline_engine(tmp_path) -> PipelineEngine:
    SkillRouter._instance = None
    registry = SkillRegistry()
    pm = SkillPermissionManager(config_dir=str(tmp_path / "config"))
    router = SkillRouter(registry=registry, permission_manager=pm)
    return PipelineEngine(router=router)


@pytest.mark.asyncio
async def test_sequential_pipeline(pipeline_engine: PipelineEngine) -> None:
    skill_a = DummySkill("skill.a")
    skill_b = DummySkill("skill.b")
    pipeline_engine._router.mount(skill_a)
    pipeline_engine._router.mount(skill_b)

    definition = PipelineDefinition(
        pipeline_id="pipe.test",
        name="Test Pipeline",
        mode="sequential",
        steps=[
            PipelineStep(skill_id="skill.a", action="step1", params={"x": 1}),
            PipelineStep(skill_id="skill.b", action="step2", params={"y": 2}),
        ],
    )
    pipeline_engine.register(definition)
    ctx = await pipeline_engine.execute("pipe.test", agent_id="agent1")

    assert ctx.status == "success"
    assert len(ctx.step_results) == 2
    assert skill_a.calls[0]["action"] == "step1"
    assert skill_b.calls[0]["action"] == "step2"


@pytest.mark.asyncio
async def test_parallel_pipeline(pipeline_engine: PipelineEngine) -> None:
    skill_a = DummySkill("skill.a")
    skill_b = DummySkill("skill.b")
    pipeline_engine._router.mount(skill_a)
    pipeline_engine._router.mount(skill_b)

    definition = PipelineDefinition(
        pipeline_id="pipe.parallel",
        name="Parallel Pipeline",
        mode="parallel",
        steps=[
            PipelineStep(skill_id="skill.a", action="p1", params={"x": 1}),
            PipelineStep(skill_id="skill.b", action="p2", params={"y": 2}),
        ],
    )
    pipeline_engine.register(definition)
    ctx = await pipeline_engine.execute("pipe.parallel", agent_id="agent1")

    assert ctx.status == "success"
    assert len(ctx.step_results) == 2


@pytest.mark.asyncio
async def test_params_mapping(pipeline_engine: PipelineEngine) -> None:
    skill_a = DummySkill("skill.a")
    skill_b = DummySkill("skill.b")
    pipeline_engine._router.mount(skill_a)
    pipeline_engine._router.mount(skill_b)

    definition = PipelineDefinition(
        pipeline_id="pipe.mapping",
        name="Mapping Pipeline",
        mode="sequential",
        steps=[
            PipelineStep(skill_id="skill.a", action="step1", params={"x": 1}, step_id="s1"),
            PipelineStep(
                skill_id="skill.b",
                action="step2",
                params={},
                step_id="s2",
                params_mapping={"s1.data.echo.x": "upstream_x"},
            ),
        ],
    )
    pipeline_engine.register(definition)
    ctx = await pipeline_engine.execute("pipe.mapping", agent_id="agent1")

    assert ctx.status == "success"
    assert skill_b.calls[0]["params"].get("upstream_x") == 1


@pytest.mark.asyncio
async def test_condition_skip(pipeline_engine: PipelineEngine) -> None:
    skill_a = DummySkill("skill.a")
    skill_b = DummySkill("skill.b")
    pipeline_engine._router.mount(skill_a)
    pipeline_engine._router.mount(skill_b)

    definition = PipelineDefinition(
        pipeline_id="pipe.condition",
        name="Condition Pipeline",
        mode="sequential",
        steps=[
            PipelineStep(skill_id="skill.a", action="step1", params={}, step_id="s1"),
            PipelineStep(
                skill_id="skill.b",
                action="step2",
                params={},
                step_id="s2",
                condition="s1.status == failure",
            ),
        ],
    )
    pipeline_engine.register(definition)
    ctx = await pipeline_engine.execute("pipe.condition", agent_id="agent1")

    assert ctx.status == "success"
    assert "s1" in ctx.step_results
    assert "s2" not in ctx.step_results
    assert len(skill_b.calls) == 0


@pytest.mark.asyncio
async def test_pipeline_failure_abort(pipeline_engine: PipelineEngine) -> None:
    class FailingSkill(ISkill):
        def __init__(self) -> None:
            super().__init__(SkillManifest(
                skill_id="skill.fail",
                name="Fail",
                version="1.0.0",
                description="Test",
                author="test",
                entrypoint="FailingSkill",
            ))

        async def invoke(self, request: SkillInvokeRequest) -> SkillInvokeResult:
            return SkillInvokeResult(
                skill_id=self.manifest.skill_id,
                action=request.action,
                status="failure",
                error="intentional failure",
                latency_ms=0.0,
                trace_id=request.trace_id,
            )

        async def health(self) -> dict:
            return {"healthy": True}

        async def configure(self, config: dict) -> None:
            pass

    pipeline_engine._router.mount(FailingSkill())
    pipeline_engine._router.mount(DummySkill("skill.b"))

    definition = PipelineDefinition(
        pipeline_id="pipe.fail",
        name="Fail Pipeline",
        mode="sequential",
        steps=[
            PipelineStep(skill_id="skill.fail", action="fail", step_id="s1"),
            PipelineStep(skill_id="skill.b", action="step2", step_id="s2"),
        ],
    )
    pipeline_engine.register(definition)
    ctx = await pipeline_engine.execute("pipe.fail", agent_id="agent1")

    assert ctx.status == "failure"
    assert "s1" in ctx.step_results
    assert ctx.step_results["s1"].status == "failure"
    assert "s2" not in ctx.step_results


def test_pipeline_not_found(pipeline_engine: PipelineEngine) -> None:
    with pytest.raises(ValueError, match="not found"):
        import asyncio
        asyncio.run(pipeline_engine.execute("pipe.missing", agent_id="agent1"))
