from __future__ import annotations

import pytest

from skill_cluster.interfaces import SkillManifest
from skill_cluster.skill_graph import ComposableChain, GraphEdge, SkillGraph


def _make_manifest(skill_id: str, deps: list[str] | None = None) -> SkillManifest:
    return SkillManifest(
        skill_id=skill_id,
        name=skill_id,
        version="1.0.0",
        description=f"Test skill {skill_id}",
        author="test",
        entrypoint=skill_id,
        dependencies=deps or [],
    )


def test_add_skill_with_deps() -> None:
    g = SkillGraph()
    g.add_skill(_make_manifest("skill.a", ["skill.b", "skill.c"]))
    g.add_skill(_make_manifest("skill.b"))
    g.add_skill(_make_manifest("skill.c"))

    assert g.get_stats()["node_count"] == 3
    assert g.get_stats()["edge_count"] == 2


def test_no_cycle() -> None:
    g = SkillGraph()
    g.add_skill(_make_manifest("skill.a", ["skill.b"]))
    g.add_skill(_make_manifest("skill.b", ["skill.c"]))
    g.add_skill(_make_manifest("skill.c"))

    assert g.detect_cycle() is None


def test_detect_cycle() -> None:
    g = SkillGraph()
    g.add_skill(_make_manifest("skill.a"))
    g.add_skill(_make_manifest("skill.b"))
    g.add_edge("skill.a", "skill.b")
    g.add_edge("skill.b", "skill.a")

    cycle = g.detect_cycle()
    assert cycle is not None
    assert len(cycle) >= 2


def test_topological_sort() -> None:
    g = SkillGraph()
    g.add_skill(_make_manifest("skill.a", ["skill.b"]))
    g.add_skill(_make_manifest("skill.b", ["skill.c"]))
    g.add_skill(_make_manifest("skill.c"))

    order = g.topological_sort()
    # a 依赖 b 依赖 c，所以 c 先执行，a 最后执行
    assert order.index("skill.c") < order.index("skill.b")
    assert order.index("skill.b") < order.index("skill.a")


def test_get_dependencies_direct() -> None:
    g = SkillGraph()
    g.add_skill(_make_manifest("skill.a", ["skill.b", "skill.c"]))
    g.add_skill(_make_manifest("skill.b"))
    g.add_skill(_make_manifest("skill.c"))

    deps = g.get_dependencies("skill.a", transitive=False)
    assert "skill.b" in deps
    assert "skill.c" in deps


def test_get_dependencies_transitive() -> None:
    g = SkillGraph()
    g.add_skill(_make_manifest("skill.a", ["skill.b"]))
    g.add_skill(_make_manifest("skill.b", ["skill.c"]))
    g.add_skill(_make_manifest("skill.c"))

    deps = g.get_dependencies("skill.a", transitive=True)
    assert "skill.b" in deps
    assert "skill.c" in deps


def test_get_dependents() -> None:
    g = SkillGraph()
    g.add_skill(_make_manifest("skill.a", ["skill.b"]))
    g.add_skill(_make_manifest("skill.b"))

    dependents = g.get_dependents("skill.b")
    assert "skill.a" in dependents


def test_find_chains() -> None:
    g = SkillGraph()
    # skill.analyze 依赖 skill.search，skill.search 依赖 skill.fetch
    g.add_skill(_make_manifest("skill.search", ["skill.fetch"]))
    g.add_skill(_make_manifest("skill.fetch"))
    g.add_skill(_make_manifest("skill.analyze", ["skill.search"]))

    # 从 fetch 出发，找到依赖 fetch 的链
    chains = g.find_chains("skill.fetch")
    assert len(chains) >= 1
    assert chains[0].skills[0] == "skill.fetch"


def test_find_chains_specific_end() -> None:
    g = SkillGraph()
    g.add_skill(_make_manifest("skill.a", ["skill.b"]))
    g.add_skill(_make_manifest("skill.b", ["skill.c"]))
    g.add_skill(_make_manifest("skill.c"))

    # 从 c 出发，找到依赖链到 a
    chains = g.find_chains("skill.c", end_id="skill.a")
    assert len(chains) == 1
    assert chains[0].skills == ["skill.c", "skill.b", "skill.a"]


def test_validate_skill_ready() -> None:
    g = SkillGraph()
    g.add_skill(_make_manifest("skill.a", ["skill.b"]))
    g.add_skill(_make_manifest("skill.b"))

    ok, missing = g.validate_skill_ready("skill.a")
    assert ok is True
    assert missing == []

    ok2, missing2 = g.validate_skill_ready("skill.c")
    assert ok2 is True  # 不在图中的技能无依赖


def test_validate_skill_missing_deps() -> None:
    g = SkillGraph()
    g.add_skill(_make_manifest("skill.a", ["skill.b"]))
    # skill.b 未注册

    ok, missing = g.validate_skill_ready("skill.a")
    assert ok is False
    assert "skill.b" in missing


def test_remove_skill() -> None:
    g = SkillGraph()
    g.add_skill(_make_manifest("skill.a", ["skill.b"]))
    g.add_skill(_make_manifest("skill.b"))
    g.remove_skill("skill.b")

    assert "skill.b" not in g.get_stats()
    deps = g.get_dependencies("skill.a")
    assert "skill.b" not in deps


def test_get_execution_order() -> None:
    g = SkillGraph()
    g.add_skill(_make_manifest("skill.c", ["skill.b"]))
    g.add_skill(_make_manifest("skill.b", ["skill.a"]))
    g.add_skill(_make_manifest("skill.a"))

    order = g.get_execution_order(["skill.c", "skill.a"])
    # c 依赖 b 依赖 a，所以 a 先于 c 执行
    assert order.index("skill.a") < order.index("skill.c")


def test_isolated_nodes() -> None:
    g = SkillGraph()
    g.add_skill(_make_manifest("skill.a"))
    g.add_skill(_make_manifest("skill.b"))
    g.add_skill(_make_manifest("skill.c", ["skill.b"]))

    stats = g.get_stats()
    assert "skill.a" in stats["isolated_nodes"]
