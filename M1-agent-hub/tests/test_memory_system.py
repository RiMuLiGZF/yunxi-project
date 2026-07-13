"""分层记忆系统单元测试"""
import sys
sys.path.insert(0, "/workspace/agent_cluster")
sys.path.insert(0, "/workspace")

import pytest
import time

from agent_cluster.memory_system import (
    MemoryManager,
    WorkingMemory,
    ShortTermMemory,
    LongTermMemory,
    MemoryEntry,
)


def test_working_memory_ttl():
    """测试工作记忆 TTL 过期"""
    wm = WorkingMemory(max_entries=5, ttl_seconds=0.1)
    wm.add(MemoryEntry(entry_id="e1", content="test"))
    assert len(wm.get_all()) == 1
    time.sleep(0.15)
    assert len(wm.get_all()) == 0


def test_working_memory_capacity():
    """测试工作记忆容量限制"""
    wm = WorkingMemory(max_entries=3, ttl_seconds=60)
    for i in range(5):
        wm.add(MemoryEntry(entry_id=f"e{i}", content=f"content {i}"))
    assert len(wm.get_all()) == 3
    assert wm.get_all()[0].entry_id == "e2"


def test_short_term_memory_session_isolation():
    """测试短期记忆会话隔离"""
    stm = ShortTermMemory(max_rounds=10)
    stm.add("sess1", MemoryEntry(entry_id="a", content="hello"))
    stm.add("sess2", MemoryEntry(entry_id="b", content="world"))
    assert len(stm.get_history("sess1")) == 1
    assert len(stm.get_history("sess2")) == 1
    assert stm.get_history("sess1")[0].content == "hello"


def test_short_term_memory_sliding_window():
    """测试短期记忆滑动窗口"""
    stm = ShortTermMemory(max_rounds=3)
    for i in range(5):
        stm.add("sess1", MemoryEntry(entry_id=f"e{i}", content=str(i)))
    history = stm.get_history("sess1")
    assert len(history) == 3
    assert history[0].content == "2"


def test_short_term_memory_summarize():
    """测试会话摘要"""
    stm = ShortTermMemory()
    stm.add("s1", MemoryEntry(entry_id="a", content="hello", tags=["greeting"]))
    summary = stm.summarize("s1")
    assert "greeting" in summary


def test_long_term_memory_store_and_retrieve():
    """测试长期记忆存储与检索"""
    ltm = LongTermMemory(capacity=10)
    entry = MemoryEntry(entry_id="lt1", content="important fact", importance=0.9)
    ltm.store(entry)
    retrieved = ltm.retrieve("lt1")
    assert retrieved is not None
    assert retrieved.content == "important fact"
    assert retrieved.access_count == 1


def test_long_term_memory_search_by_tags():
    """测试按标签搜索"""
    ltm = LongTermMemory()
    ltm.store(MemoryEntry(entry_id="a", content="note", tags=["work"], importance=0.8))
    ltm.store(MemoryEntry(entry_id="b", content="diary", tags=["life"], importance=0.6))
    results = ltm.search_by_tags(["work"])
    assert len(results) == 1
    assert results[0].entry_id == "a"


def test_long_term_memory_search_by_content():
    """测试按内容搜索"""
    ltm = LongTermMemory()
    ltm.store(MemoryEntry(entry_id="a", content="python programming"))
    ltm.store(MemoryEntry(entry_id="b", content="java programming"))
    results = ltm.search_by_content("python")
    assert len(results) == 1
    assert results[0].entry_id == "a"


def test_long_term_memory_forget():
    """测试遗忘机制"""
    ltm = LongTermMemory(capacity=2)
    ltm.store(MemoryEntry(entry_id="a", content="low", importance=0.1))
    ltm.store(MemoryEntry(entry_id="b", content="mid", importance=0.5))
    ltm.store(MemoryEntry(entry_id="c", content="high", importance=0.9))
    # 容量为 2，最不重要且最久未访问的应被移除
    assert len(ltm._entries) == 2


def test_long_term_memory_consolidate():
    """测试记忆巩固"""
    stm = ShortTermMemory()
    ltm = LongTermMemory(capacity=100, consolidation_threshold=0.5)

    stm.add("s1", MemoryEntry(entry_id="e1", content="preference", memory_type="preference", importance=0.8))
    stm.add("s1", MemoryEntry(entry_id="e2", content="generic", memory_type="generic", importance=0.2))

    count = ltm.consolidate("s1", stm)
    assert count == 1  # 只有 preference 达到阈值
    assert "e1" in ltm._entries


def test_memory_manager_full_flow():
    """测试记忆管理器完整流程"""
    mm = MemoryManager()

    # 写入三层记忆
    mm.add_working_memory("current context", source="system")
    mm.add_short_term("trace_1", "user said hello", source="user", tags=["greeting"])
    mm.add_long_term("user likes python", source="agent.note", memory_type="preference", importance=0.9)

    # 读取上下文
    ctx = mm.get_context("trace_1", query="python")
    assert len(ctx["working_memory"]) >= 1
    assert len(ctx["short_term_history"]) >= 1
    assert len(ctx["long_term_relevant"]) >= 1


def test_memory_manager_stats():
    """测试统计信息"""
    mm = MemoryManager()
    mm.add_working_memory("test")
    mm.add_short_term("t1", "test", source="user")
    mm.add_long_term("test", source="agent", importance=0.5)
    stats = mm.stats()
    assert stats["working_memory"] >= 1
    assert stats["short_term_sessions"] >= 1
    assert stats["long_term"]["total_entries"] >= 1
