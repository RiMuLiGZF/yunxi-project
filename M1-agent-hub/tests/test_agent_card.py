"""AgentCard 能力发现系统单元测试"""
import sys
import pytest

from agent_cluster.agents.agent_card import (
    AgentCard,
    AgentCapability,
    AgentCardRegistry,
    build_agent_card,
)


def test_agent_card_creation():
    card = AgentCard(
        agent_id="agent.note",
        agent_name="笔记 Agent",
        version="1.0.0",
        description="管理学习笔记",
        capabilities=[
            AgentCapability(id="note.create", name="创建笔记"),
            AgentCapability(id="note.search", name="搜索笔记"),
        ],
        tags=["productivity", "knowledge"],
    )
    assert card.agent_id == "agent.note"
    assert card.has_capability("note.create")
    assert not card.has_capability("note.delete")


def test_find_capability():
    card = AgentCard(
        agent_id="agent.test",
        capabilities=[
            AgentCapability(id="code.review", name="代码审查", description="Review code"),
            AgentCapability(id="code.debug", name="调试", description="Debug code"),
        ],
    )
    results = card.find_capability("review")
    assert len(results) == 1
    assert results[0].id == "code.review"


def test_match_score():
    card = AgentCard(
        agent_id="agent.dev",
        agent_name="开发 Agent",
        capabilities=[AgentCapability(id="dev.code", name="代码辅助")],
        tags=["coding", "programming"],
    )
    assert card.match_score("dev") > 0
    assert card.match_score("code") > 0
    assert card.match_score("random_xyz") == 0


def test_card_to_dict():
    card = build_agent_card("a1", "Test", "1.0", ["cap1", "cap2"])
    d = card.to_dict()
    assert d["agent_id"] == "a1"
    assert len(d["capabilities"]) == 2


def test_registry_register_and_get():
    reg = AgentCardRegistry()
    card = build_agent_card("a1", "Agent1", "1.0", ["cap1"])
    reg.register(card)
    assert reg.get("a1") == card
    assert reg.get("a2") is None


def test_registry_unregister():
    reg = AgentCardRegistry()
    card = build_agent_card("a1", "Agent1", "1.0", ["cap1"])
    reg.register(card)
    reg.unregister("a1")
    assert reg.get("a1") is None


def test_registry_discover_by_capability():
    reg = AgentCardRegistry()
    reg.register(build_agent_card("a1", "Agent1", "1.0", ["note.create", "note.search"]))
    reg.register(build_agent_card("a2", "Agent2", "1.0", ["emotion.chat"]))

    results = reg.discover(capability_id="note.create")
    assert len(results) == 1
    assert results[0][0].agent_id == "a1"
    assert results[0][1] == 1.0  # full match score


def test_registry_discover_by_keyword():
    reg = AgentCardRegistry()
    reg.register(build_agent_card("a1", "NoteAgent", "1.0", ["note.create"], tags=["notes"]))
    reg.register(build_agent_card("a2", "DevAgent", "1.0", ["dev.code"], tags=["coding"]))

    results = reg.discover(keyword="note")
    assert len(results) == 1
    assert results[0][0].agent_id == "a1"


def test_registry_discover_by_tag():
    reg = AgentCardRegistry()
    reg.register(build_agent_card("a1", "A1", "1.0", ["c1"], tags=["productivity"]))
    reg.register(build_agent_card("a2", "A2", "1.0", ["c2"], tags=["dev"]))

    results = reg.discover(tag="productivity")
    assert len(results) == 1
    assert results[0][0].agent_id == "a1"


def test_registry_semantic_search():
    reg = AgentCardRegistry()
    reg.register(build_agent_card("a1", "笔记助手", "1.0", ["note.create", "note.tag"]))
    reg.register(build_agent_card("a2", "代码助手", "1.0", ["dev.code", "dev.qa"]))
    reg.register(build_agent_card("a3", "情绪陪伴", "1.0", ["emotion.chat"]))

    results = reg.semantic_search("笔记", top_k=2)
    assert len(results) == 1
    assert results[0][0].agent_id == "a1"
    assert results[0][1] > 0


def test_registry_list_all():
    reg = AgentCardRegistry()
    reg.register(build_agent_card("a1", "A1", "1.0", ["c1"]))
    reg.register(build_agent_card("a2", "A2", "1.0", ["c2"]))
    assert len(reg.list_all()) == 2
