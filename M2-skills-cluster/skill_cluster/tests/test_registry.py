from __future__ import annotations

"""SkillRegistry 单元测试."""

import pytest

from skill_cluster.interfaces import ISkill, SkillInvokeRequest, SkillInvokeResult, SkillManifest
from skill_cluster.skill_registry import (
    DependencyNotFoundError,
    SkillAlreadyExistsError,
    SkillDependencyOccupiedError,
    SkillRegistry,
)


class DummySkill(ISkill):
    def __init__(self, skill_id: str, version: str = "1.0.0", dependencies: list[str] | None = None) -> None:
        manifest = SkillManifest(
            skill_id=skill_id,
            name="Dummy",
            version=version,
            description="Test skill",
            author="test",
            dependencies=dependencies or [],
            entrypoint="DummySkill",
        )
        super().__init__(manifest)

    async def invoke(self, request: SkillInvokeRequest) -> SkillInvokeResult:
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
def registry() -> SkillRegistry:
    return SkillRegistry()


def test_register_and_get(registry: SkillRegistry) -> None:
    skill = DummySkill("skill.dummy")
    registry.register(skill)
    assert registry.get_skill("skill.dummy") is skill
    assert registry.get_manifest("skill.dummy") == skill.manifest


def test_register_duplicate_version(registry: SkillRegistry) -> None:
    skill = DummySkill("skill.dummy", version="1.0.0")
    registry.register(skill)
    with pytest.raises(SkillAlreadyExistsError):
        registry.register(DummySkill("skill.dummy", version="1.0.0"))


def test_register_upgrade_version(registry: SkillRegistry) -> None:
    skill = DummySkill("skill.dummy", version="1.0.0")
    registry.register(skill)
    skill2 = DummySkill("skill.dummy", version="1.1.0")
    registry.register(skill2)
    assert registry.get_skill("skill.dummy") is skill2


def test_register_missing_dependency(registry: SkillRegistry) -> None:
    skill = DummySkill("skill.child", dependencies=["skill.parent"])
    with pytest.raises(DependencyNotFoundError):
        registry.register(skill)


def test_unregister_with_dependents(registry: SkillRegistry) -> None:
    parent = DummySkill("skill.parent")
    child = DummySkill("skill.child", dependencies=["skill.parent"])
    registry.register(parent)
    registry.register(child)
    with pytest.raises(SkillDependencyOccupiedError):
        registry.unregister("skill.parent")


def test_unregister_force(registry: SkillRegistry) -> None:
    parent = DummySkill("skill.parent")
    child = DummySkill("skill.child", dependencies=["skill.parent"])
    registry.register(parent)
    registry.register(child)
    registry.unregister("skill.parent", force=True)
    assert registry.get_skill("skill.parent") is None


def test_discover_by_name(registry: SkillRegistry) -> None:
    manifest = SkillManifest(
        skill_id="skill.alpha",
        name="alpha skill",
        version="1.0.0",
        description="Test",
        author="test",
        entrypoint="DummySkill",
    )
    skill = DummySkill("skill.alpha")
    skill._manifest = manifest
    registry.register(skill)
    from skill_cluster.interfaces import SkillQuery

    results = registry.discover(SkillQuery(name="alpha"))
    assert len(results) == 1
    assert results[0].skill_id == "skill.alpha"


def test_discover_by_tags(registry: SkillRegistry) -> None:
    manifest = SkillManifest(
        skill_id="skill.tagged",
        name="Tagged",
        version="1.0.0",
        description="Test",
        author="test",
        tags=["a", "b"],
        entrypoint="DummySkill",
    )
    skill = DummySkill("skill.tagged")
    skill._manifest = manifest
    registry.register(skill)
    from skill_cluster.interfaces import SkillQuery

    results = registry.discover(SkillQuery(tags=["a"]))
    assert len(results) == 1


def test_discover_by_capability(registry: SkillRegistry) -> None:
    manifest = SkillManifest(
        skill_id="skill.cap",
        name="Cap",
        version="1.0.0",
        description="Test",
        author="test",
        capabilities=["cap1", "cap2"],
        entrypoint="DummySkill",
    )
    skill = DummySkill("skill.cap")
    skill._manifest = manifest
    registry.register(skill)
    from skill_cluster.interfaces import SkillQuery

    results = registry.discover(SkillQuery(capability="cap1"))
    assert len(results) == 1


def test_discover_semantic(registry: SkillRegistry) -> None:
    manifest = SkillManifest(
        skill_id="skill.sem",
        name="Semantic",
        version="1.0.0",
        description="hello world test",
        author="test",
        capabilities=["cap_hello"],
        entrypoint="DummySkill",
    )
    skill = DummySkill("skill.sem")
    skill._manifest = manifest
    registry.register(skill)
    from skill_cluster.interfaces import SkillQuery

    results = registry.discover(SkillQuery(semantic_query="hello world"))
    assert len(results) == 1


def test_versions(registry: SkillRegistry) -> None:
    registry.register(DummySkill("skill.v", version="1.0.0"))
    registry.register(DummySkill("skill.v", version="1.1.0"))
    assert registry.get_latest_version("skill.v") == "1.1.0"
    assert registry.get_versions("skill.v") == ["1.0.0", "1.1.0"]
