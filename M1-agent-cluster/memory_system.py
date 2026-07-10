"""
云汐内核 V3 - 分层记忆系统

灵感来源：Agentic Memory (AgeMem) 论文 + 分层记忆架构
https://arxiv.org/pdf/2601.01885v2

将记忆分为三层：
- 工作记忆 (Working Memory): 当前任务上下文，TTL 极短
- 短期记忆 (Short-Term Memory): 最近 N 轮对话历史，滑动窗口
- 长期记忆 (Long-Term Memory): 用户偏好、知识积累、历史决策，持久化

记忆生命周期：编码 → 存储 → 检索 → 更新 → 遗忘
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class MemoryEntry:
    """记忆条目"""

    entry_id: str = ""
    content: str = ""
    memory_type: str = "generic"  # generic | preference | fact | decision | emotion
    source: str = ""  # 来源 Agent ID 或 user
    importance: float = 0.5  # 0-1，重要性分数
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    access_count: int = 0
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def touch(self) -> None:
        """更新访问时间"""
        self.last_accessed = time.time()
        self.access_count += 1


# ── 工作记忆 ────────────────────────────────────────────────


class WorkingMemory:
    """工作记忆

    维护当前 Agent 迭代执行任务所需的上下文。
    类似于 LLM 的上下文窗口，TTL 极短（秒级）。
    """

    def __init__(self, max_entries: int = 10, ttl_seconds: float = 30.0) -> None:
        self._entries: list[MemoryEntry] = []
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds

    def add(self, entry: MemoryEntry) -> None:
        """添加条目"""
        self._entries.append(entry)
        # 超出容量时移除最旧的
        while len(self._entries) > self.max_entries:
            self._entries.pop(0)
        self._cleanup()

    def get_recent(self, n: int = 5) -> list[MemoryEntry]:
        """获取最近 n 条"""
        self._cleanup()
        return self._entries[-n:]

    def get_all(self) -> list[MemoryEntry]:
        """获取全部有效条目"""
        self._cleanup()
        return list(self._entries)

    def clear(self) -> None:
        """清空"""
        self._entries.clear()

    def _cleanup(self) -> None:
        """清理过期条目"""
        now = time.time()
        self._entries = [
            e for e in self._entries
            if now - e.created_at < self.ttl_seconds
        ]


# ── 短期记忆 ────────────────────────────────────────────────


class ShortTermMemory:
    """短期记忆

    最近 N 轮对话历史，滑动窗口管理。
    支持按 trace_id 隔离会话。
    """

    def __init__(self, max_rounds: int = 20, max_sessions: int = 1000) -> None:
        self._sessions: dict[str, list[MemoryEntry]] = {}
        self.max_rounds = max_rounds
        self.max_sessions = max_sessions

    def add(self, trace_id: str, entry: MemoryEntry) -> None:
        """添加会话条目"""
        if trace_id not in self._sessions:
            # LRU 淘汰最旧的 session
            if len(self._sessions) >= self.max_sessions:
                oldest_key = next(iter(self._sessions))
                del self._sessions[oldest_key]
            self._sessions[trace_id] = []
        self._sessions[trace_id].append(entry)
        # 滑动窗口
        while len(self._sessions[trace_id]) > self.max_rounds:
            self._sessions[trace_id].pop(0)

    def get_history(self, trace_id: str, n: int | None = None) -> list[MemoryEntry]:
        """获取会话历史"""
        history = self._sessions.get(trace_id, [])
        if n:
            return history[-n:]
        return list(history)

    def summarize(self, trace_id: str) -> str:
        """生成会话摘要（简单实现）"""
        history = self._sessions.get(trace_id, [])
        if not history:
            return ""
        # 提取关键信息
        topics: set[str] = set()
        for entry in history:
            topics.update(entry.tags)
        return f"会话涉及主题: {', '.join(topics) if topics else '一般对话'}"

    def clear_session(self, trace_id: str) -> None:
        """清除指定会话"""
        self._sessions.pop(trace_id, None)

    def clear_all(self) -> None:
        """清除全部"""
        self._sessions.clear()


# ── 长期记忆 ────────────────────────────────────────────────


class LongTermMemory:
    """长期记忆

    用户偏好、知识积累、历史决策。
    基于重要性分数和访问频率进行遗忘/保留决策。

    生产环境应接入向量数据库（如 ChromaDB、Milvus）。
    当前实现使用内存字典作为基线。
    """

    def __init__(
        self,
        capacity: int = 1000,
        consolidation_threshold: float = 0.6,
    ) -> None:
        self._entries: dict[str, MemoryEntry] = {}
        self.capacity = capacity
        self.consolidation_threshold = consolidation_threshold
        self._logger = logger.bind(memory_tier="ltm")

    def store(self, entry: MemoryEntry) -> None:
        """存储记忆

        如果容量已满，触发遗忘机制。
        """
        if len(self._entries) >= self.capacity:
            self._forget_least_important()

        self._entries[entry.entry_id] = entry
        self._logger.debug("memory_stored", entry_id=entry.entry_id, importance=entry.importance)

    def retrieve(self, entry_id: str) -> MemoryEntry | None:
        """按 ID 检索"""
        entry = self._entries.get(entry_id)
        if entry:
            entry.touch()
        return entry

    def search_by_tags(self, tags: list[str]) -> list[MemoryEntry]:
        """按标签搜索"""
        results = []
        for entry in self._entries.values():
            if any(tag in entry.tags for tag in tags):
                entry.touch()
                results.append(entry)
        # 按重要性排序
        results.sort(key=lambda e: e.importance, reverse=True)
        return results

    def search_by_content(self, keyword: str) -> list[MemoryEntry]:
        """按内容关键词搜索"""
        kw_lower = keyword.lower()
        results = []
        for entry in self._entries.values():
            if kw_lower in entry.content.lower():
                entry.touch()
                results.append(entry)
        results.sort(key=lambda e: e.importance, reverse=True)
        return results

    def update(self, entry_id: str, updates: dict[str, Any]) -> bool:
        """更新记忆条目"""
        entry = self._entries.get(entry_id)
        if not entry:
            return False
        for key, value in updates.items():
            if hasattr(entry, key):
                setattr(entry, key, value)
        entry.touch()
        return True

    def consolidate(self, trace_id: str, stm: ShortTermMemory) -> int:
        """记忆巩固：将短期记忆中有价值的信息转入长期记忆

        筛选标准：
        - 用户明确表达偏好
        - 重要决策记录
        - 多次被访问的信息
        """
        history = stm.get_history(trace_id)
        consolidated = 0
        for entry in history:
            # 重要性评估
            score = entry.importance
            if entry.memory_type in ("preference", "decision"):
                score += 0.3
            if entry.access_count >= 2:
                score += 0.1

            if score >= self.consolidation_threshold:
                self.store(entry)
                consolidated += 1

        self._logger.info(
            "memory_consolidated",
            trace_id=trace_id,
            consolidated_count=consolidated,
        )
        return consolidated

    def _forget_least_important(self) -> None:
        """遗忘机制：移除重要性最低且最久未访问的记忆"""
        if not self._entries:
            return

        # 计算遗忘分数（重要性越低、越久未访问越容易被遗忘）
        now = time.time()

        def forget_score(entry: MemoryEntry) -> float:
            recency = now - entry.last_accessed
            return entry.importance * 0.7 - recency * 0.0001 - entry.access_count * 0.01

        victim = min(self._entries.values(), key=forget_score)
        del self._entries[victim.entry_id]
        self._logger.info(
            "memory_forgotten",
            entry_id=victim.entry_id,
            importance=victim.importance,
        )

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息"""
        return {
            "total_entries": len(self._entries),
            "capacity": self.capacity,
            "avg_importance": (
                sum(e.importance for e in self._entries.values()) / len(self._entries)
                if self._entries else 0
            ),
        }


# ── 统一记忆管理器 ──────────────────────────────────────────


class MemoryManager:
    """统一记忆管理器

    协调工作记忆、短期记忆、长期记忆三层架构。
    """

    def __init__(
        self,
        wm_ttl: float = 30.0,
        stm_max_rounds: int = 20,
        ltm_capacity: int = 1000,
    ) -> None:
        self.wm = WorkingMemory(ttl_seconds=wm_ttl)
        self.stm = ShortTermMemory(max_rounds=stm_max_rounds)
        self.ltm = LongTermMemory(capacity=ltm_capacity)
        self._logger = logger.bind(service="memory_manager")

    # ── 写入接口 ────────────────────────────────────────

    def add_working_memory(
        self,
        content: str,
        source: str = "",
        tags: list[str] | None = None,
    ) -> MemoryEntry:
        """写入工作记忆"""
        entry = MemoryEntry(
            entry_id=f"wm_{int(time.time() * 1000)}",
            content=content,
            source=source,
            tags=tags or [],
        )
        self.wm.add(entry)
        return entry

    def add_short_term(
        self,
        trace_id: str,
        content: str,
        source: str = "",
        memory_type: str = "generic",
        importance: float = 0.5,
        tags: list[str] | None = None,
    ) -> MemoryEntry:
        """写入短期记忆"""
        entry = MemoryEntry(
            entry_id=f"stm_{trace_id}_{int(time.time() * 1000)}",
            content=content,
            source=source,
            memory_type=memory_type,
            importance=importance,
            tags=tags or [],
        )
        self.stm.add(trace_id, entry)
        return entry

    def add_long_term(
        self,
        content: str,
        source: str = "",
        memory_type: str = "generic",
        importance: float = 0.5,
        tags: list[str] | None = None,
    ) -> MemoryEntry:
        """写入长期记忆"""
        entry = MemoryEntry(
            entry_id=f"ltm_{int(time.time() * 1000)}",
            content=content,
            source=source,
            memory_type=memory_type,
            importance=importance,
            tags=tags or [],
        )
        self.ltm.store(entry)
        return entry

    # ── 读取接口 ────────────────────────────────────────

    def get_context(
        self,
        trace_id: str,
        query: str = "",
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """获取完整上下文（三层聚合）

        Returns:
            {
                "working_memory": [...],
                "short_term_history": [...],
                "long_term_relevant": [...],
            }
        """
        wm_entries = self.wm.get_recent()
        stm_history = self.stm.get_history(trace_id, n=10)

        ltm_relevant: list[MemoryEntry] = []
        if query:
            ltm_relevant.extend(self.ltm.search_by_content(query))
        if tags:
            ltm_relevant.extend(self.ltm.search_by_tags(tags))
        # 去重
        seen = set()
        ltm_relevant = [e for e in ltm_relevant if not (e.entry_id in seen or seen.add(e.entry_id))]

        return {
            "working_memory": wm_entries,
            "short_term_history": stm_history,
            "long_term_relevant": ltm_relevant[:5],  # Top-5
        }

    def consolidate(self, trace_id: str) -> int:
        """触发记忆巩固"""
        return self.ltm.consolidate(trace_id, self.stm)

    def stats(self) -> dict[str, Any]:
        """获取三层记忆统计"""
        return {
            "working_memory": len(self.wm.get_all()),
            "short_term_sessions": len(self.stm._sessions),
            "long_term": self.ltm.get_stats(),
        }
