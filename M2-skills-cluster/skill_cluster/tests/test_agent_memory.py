from __future__ import annotations

import time

import pytest

from skill_cluster.agent_memory import AgentMemory, MemoryEntry


def test_add_working_memory() -> None:
    mem = AgentMemory("agent1")
    entry = mem.add_working("用户喜欢Python", tags=["preference"], importance=2.0)
    assert entry.memory_type == "working"
    assert entry.content == "用户喜欢Python"
    assert entry.importance == 2.0


def test_add_session_memory() -> None:
    mem = AgentMemory("agent1")
    entry = mem.add_session("会话摘要", tags=["summary"])
    assert entry.memory_type == "session"
    assert entry.importance == 3.0


def test_add_long_term_memory() -> None:
    mem = AgentMemory("agent1")
    entry = mem.add_long_term("长期知识", tags=["knowledge"], importance=7.0)
    assert entry.memory_type == "long_term"
    assert entry.embedding is not None
    assert len(entry.embedding) == 64


def test_retrieve_fusion_scoring() -> None:
    mem = AgentMemory("agent1")
    mem.add_long_term("Python 是最好的编程语言", tags=["tech"], importance=8.0)
    mem.add_long_term("JavaScript 用于前端开发", tags=["tech"], importance=5.0)
    mem.add_long_term("Go 语言适合并发", tags=["tech"], importance=6.0)

    results = mem.retrieve("Python 编程", top_k=2)
    assert len(results) == 2
    # 第一条应该与 Python 最相关
    assert "Python" in results[0][0].content
    assert results[0][1] > results[1][1]


def test_retrieve_by_memory_type() -> None:
    mem = AgentMemory("agent1")
    mem.add_working("working_data")
    mem.add_session("session_data")
    mem.add_long_term("long_term_data")

    results = mem.retrieve("data", memory_types=["working"])
    assert len(results) == 1
    assert results[0][0].memory_type == "working"


def test_retrieve_by_tags() -> None:
    mem = AgentMemory("agent1")
    mem.add_long_term("A", tags=["tag1"])
    mem.add_long_term("B", tags=["tag2"])

    results = mem.retrieve("A", tags=["tag1"])
    assert len(results) == 1
    assert results[0][0].content == "A"


def test_search_by_tag() -> None:
    mem = AgentMemory("agent1")
    mem.add_working("w1", tags=["urgent"])
    mem.add_session("s1", tags=["urgent"])

    results = mem.search_by_tag("urgent")
    assert len(results) == 2


def test_summarize_working() -> None:
    mem = AgentMemory("agent1")
    mem.add_working("msg1")
    mem.add_working("msg2")
    summary = mem.summarize_working()
    assert summary is not None
    assert "msg1" in summary
    assert len(mem._working) == 0
    assert len(mem._session) == 1


def test_summarize_working_empty() -> None:
    mem = AgentMemory("agent1")
    assert mem.summarize_working() is None


def test_compress_session() -> None:
    mem = AgentMemory("agent1")
    mem.add_session("important fact", importance=9.0)
    mem.add_session("less important", importance=2.0)
    promoted = mem.compress_session()
    assert promoted == "important fact"
    assert len(mem._long_term) == 1
    assert len(mem._session) == 1


def test_compress_session_empty() -> None:
    mem = AgentMemory("agent1")
    assert mem.compress_session() is None


def test_forget_old() -> None:
    mem = AgentMemory("agent1")
    mem.add_long_term("old", importance=1.0)
    # 手动修改时间戳为很久以前
    mem._long_term[0].timestamp = time.time() - 999999
    removed = mem.forget_old(max_age_hours=1.0)
    assert removed == 1
    assert len(mem._long_term) == 0


def test_clear_working() -> None:
    mem = AgentMemory("agent1")
    mem.add_working("temp")
    mem.clear_working()
    assert len(mem._working) == 0


def test_get_stats() -> None:
    mem = AgentMemory("agent1")
    mem.add_working("w")
    mem.add_session("s")
    mem.add_long_term("l")
    stats = mem.get_stats()
    assert stats["working_count"] == 1
    assert stats["session_count"] == 1
    assert stats["long_term_count"] == 1
    assert stats["total_count"] == 3


def test_memory_entry_model() -> None:
    entry = MemoryEntry(
        entry_id="e1",
        content="test",
        tags=["a"],
        importance=5.0,
        source="agent1",
    )
    assert entry.entry_id == "e1"
    assert entry.memory_type == "long_term"
