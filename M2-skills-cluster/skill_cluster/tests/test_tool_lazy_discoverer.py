"""Tests for ToolLazyDiscoverer."""

import pytest

from skill_cluster.interfaces import ISkill, SkillManifest, SkillInvokeRequest, SkillInvokeResult
from skill_cluster.skill_registry import SkillRegistry
from skill_cluster.tool_lazy_discoverer import ToolLazyDiscoverer


class FakeSkill(ISkill):
    def __init__(self, manifest):
        self._manifest = manifest

    async def invoke(self, request):
        return SkillInvokeResult(
            skill_id=self._manifest.skill_id, action=request.action,
            status="success", latency_ms=10.0, trace_id=request.trace_id,
        )

    async def health(self):
        return {"healthy": True}

    async def configure(self, config):
        pass


def _make_manifest(sid, name, desc, tags=None):
    return SkillManifest(
        skill_id=sid, name=name, version="1.0.0",
        description=desc, author="test",
        tags=tags or [],
        entrypoint="FakeSkill",
    )


@pytest.fixture
def registry():
    reg = SkillRegistry()
    reg.register(FakeSkill(_make_manifest("skill.search", "Web Search", "Search the web for information", ["web", "search"])))
    reg.register(FakeSkill(_make_manifest("skill.calc", "Calculator", "Perform mathematical calculations", ["math", "calc"])))
    reg.register(FakeSkill(_make_manifest("skill.translate", "Translator", "Translate text between languages", ["nlp", "translate"])))
    reg.register(FakeSkill(_make_manifest("skill.email", "Email Sender", "Send emails to recipients", ["email", "communication"])))
    reg.register(FakeSkill(_make_manifest("skill.calendar", "Calendar", "Manage calendar events", ["calendar", "schedule"])))
    return reg


@pytest.fixture
def discoverer(registry):
    return ToolLazyDiscoverer(registry, always_loaded=["skill.search", "skill.calc"])


def test_build_index(discoverer):
    discoverer.build_index()
    assert discoverer._built
    assert len(discoverer._lazy_cache) == 5


def test_get_always_loaded(discoverer):
    discoverer.build_index()
    always = discoverer.get_always_loaded()
    assert len(always) == 2
    sids = {r.skill_id for r in always}
    assert "skill.search" in sids
    assert "skill.calc" in sids


def test_get_always_loaded_device_drone(discoverer):
    """【整改R03】drone 设备额外加载低延迟工具."""
    discoverer.build_index()
    loaded = discoverer.get_always_loaded(device_type="drone")
    # 2 always-loaded + up to 10 extras
    assert len(loaded) >= 2


def test_get_always_loaded_device_watch(discoverer):
    """watch 设备仅返回 always_loaded."""
    discoverer.build_index()
    loaded = discoverer.get_always_loaded(device_type="watch")
    assert len(loaded) == 2


def test_get_lazy_summaries(discoverer):
    discoverer.build_index()
    lazy = discoverer.get_lazy_summaries()
    assert len(lazy) == 3  # 5 total - 2 always loaded
    sids = {s["skill_id"] for s in lazy}
    assert "skill.search" not in sids


def test_search_keyword(discoverer):
    discoverer.build_index()
    results = discoverer.search("translate language", top_k=3)
    assert len(results) > 0
    sids = {r.skill_id for r in results}
    assert "skill.translate" in sids


def test_search_exclude_loaded(discoverer):
    discoverer.build_index()
    results = discoverer.search("calculate math", top_k=5, exclude_loaded=True)
    for r in results:
        assert r.skill_id not in {"skill.search", "skill.calc"}


def test_load_unload_tool(discoverer):
    discoverer.build_index()
    ref = discoverer.load_tool("skill.translate")
    assert ref is not None
    assert ref.is_loaded

    always = discoverer.get_always_loaded()
    assert "skill.translate" in {r.skill_id for r in always}

    discoverer.unload_tool("skill.translate")
    ref2 = discoverer._lazy_cache["skill.translate"]
    assert not ref2.is_loaded


def test_stats(discoverer):
    discoverer.build_index()
    stats = discoverer.get_stats()
    assert stats["total_tools"] == 5
    assert stats["always_loaded"] == 2
    assert stats["lazy_tools"] == 3
    assert stats["token_savings_ratio"] > 0
