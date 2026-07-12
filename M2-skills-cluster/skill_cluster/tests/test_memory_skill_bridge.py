from __future__ import annotations

import pytest

from skill_cluster.agent_memory import AgentMemory
from skill_cluster.memory_skill_bridge import MemorySkillBridge
from skill_cluster.skill_experience import SkillExperienceBank


def test_archive_to_working_memory() -> None:
    memory = AgentMemory("agent1")
    bridge = MemorySkillBridge(memory=memory)

    entry = bridge.archive_invocation(
        skill_id="skill.doc",
        action="parse",
        outcome="success",
        latency_ms=120.0,
        agent_id="agent1",
        memory_type="working",
    )

    assert entry is not None
    assert "skill.doc" in entry.content
    stats = memory.get_stats()
    assert stats["working_count"] == 1


def test_archive_failure_high_importance() -> None:
    memory = AgentMemory("agent1")
    bridge = MemorySkillBridge(memory=memory)

    entry = bridge.archive_invocation(
        skill_id="skill.doc",
        action="parse",
        outcome="failure",
        latency_ms=50.0,
        error="Format error",
        memory_type="long_term",
    )

    assert entry is not None
    assert entry.importance == 5.0  # 失败经验更重要


def test_archive_no_memory() -> None:
    bridge = MemorySkillBridge()
    entry = bridge.archive_invocation(
        skill_id="skill.x", action="run", outcome="success", latency_ms=100.0,
    )
    assert entry is None


def test_enrich_recommendation_signal() -> None:
    memory = AgentMemory("agent1")
    memory.add_long_term(
        "调用技能 skill.doc parse 结果: success 延迟: 80ms",
        tags=["skill:skill.doc", "action:parse", "success"],
        importance=5.0,
    )
    memory.add_long_term(
        "调用技能 skill.img generate 结果: failure 延迟: 200ms",
        tags=["skill:skill.img", "action:generate", "failure"],
        importance=4.0,
    )

    bridge = MemorySkillBridge(memory=memory)
    prefs = bridge.enrich_recommendation_signal("parse document")

    assert "skill.doc" in prefs
    assert prefs["skill.doc"] > 0


def test_enrich_no_memory() -> None:
    bridge = MemorySkillBridge()
    prefs = bridge.enrich_recommendation_signal("test")
    assert prefs == {}


def test_tidal_flow() -> None:
    memory = AgentMemory("agent1")
    bridge = MemorySkillBridge(memory=memory)

    # 填充工作记忆
    for i in range(12):
        bridge.archive_invocation(
            skill_id=f"skill.{i}", action="run", outcome="success",
            latency_ms=100.0, memory_type="working",
        )

    # 执行潮汐流转
    result = bridge.tidal_flow(working_threshold=10)
    assert result["summarized"] >= 1
    assert len(memory._working) < 12  # 工作记忆被压缩


def test_sync_experience_to_memory() -> None:
    memory = AgentMemory("agent1")
    exp_bank = SkillExperienceBank()
    for _ in range(10):
        exp_bank.record("skill.doc", "parse", {"fmt": "pdf"}, "success", 100.0)

    bridge = MemorySkillBridge(memory=memory, experience=exp_bank)
    synced = bridge.sync_experience_to_memory()

    assert synced >= 1
    lt_entries = memory.search_by_tag("experience")
    assert len(lt_entries) >= 1


def test_sync_no_experience() -> None:
    memory = AgentMemory("agent1")
    bridge = MemorySkillBridge(memory=memory)
    synced = bridge.sync_experience_to_memory()
    assert synced == 0


def test_get_stats() -> None:
    memory = AgentMemory("agent1")
    bridge = MemorySkillBridge(memory=memory)
    bridge.archive_invocation(
        skill_id="skill.x", action="run", outcome="success", latency_ms=100.0,
    )
    stats = bridge.get_stats()
    assert stats["total_archived"] == 1


def test_double_tidal_flow() -> None:
    """连续两次潮汐流转不会出错."""
    memory = AgentMemory("agent1")
    bridge = MemorySkillBridge(memory=memory)

    for i in range(15):
        bridge.archive_invocation(
            skill_id=f"skill.{i}", action="run", outcome="success",
            latency_ms=100.0, memory_type="working",
        )

    bridge.tidal_flow(working_threshold=5)
    result2 = bridge.tidal_flow(working_threshold=5)
    # 第二次不应该再压缩（工作记忆已清空）
    assert result2["summarized"] == 0
