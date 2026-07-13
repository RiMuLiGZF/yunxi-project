from __future__ import annotations

"""Memory-Skill Bridge - 记忆层与技能层数据联动桥.

独创设计：打通潮汐分层记忆与技能集群的数据通道，
实现三个核心联动：
1. 技能使用经验沉淀到长期记忆（调用日志 → MemoryEntry）
2. 基于记忆上下文动态调整技能推荐权重
3. 技能调用日志归档到潮汐记忆（支持潮汐记忆的原生分层架构）
"""

import time
from typing import Any

import structlog
from pydantic import BaseModel, Field

from skill_cluster.agent.memory import AgentMemory, MemoryEntry
from skill_cluster.agent.experience.bank import SkillExperienceBank

logger = structlog.get_logger()


class BridgeStats(BaseModel):
    """桥接统计."""

    total_archived: int = Field(default=0, description="归档总数")
    memory_enriched: int = Field(default=0, description="记忆丰富次数")
    last_archive_at: float = Field(default=0.0, description="最后归档时间")
    last_enrich_at: float = Field(default=0.0, description="最后丰富时间")


class MemorySkillBridge:
    """记忆层-技能层数据联动桥.

    核心职责：
    - 技能调用日志自动归档到 AgentMemory 长期记忆
    - 从记忆中提取技能偏好丰富推荐信号
    - 支持潮汐记忆分层（working → session → long-term）的自动流转
    """

    def __init__(
        self,
        memory: AgentMemory | None = None,
        experience: SkillExperienceBank | None = None,
    ) -> None:
        self._memory = memory
        self._experience = experience
        self._stats = BridgeStats()
        self._pending_working: list[str] = []  # 待归档的工作记忆条目

    # ---- 核心：技能调用归档到记忆 ----

    def archive_invocation(
        self,
        skill_id: str,
        action: str,
        outcome: str,
        latency_ms: float,
        params_summary: dict[str, Any] | None = None,
        error: str | None = None,
        agent_id: str = "",
        memory_type: str = "working",
    ) -> MemoryEntry | None:
        """将技能调用归档到 AgentMemory.

        调用结果首先进入 Working Memory，后续可通过
        summarize_working() 自动提升到 Session → Long-term。

        Args:
            skill_id: 技能 ID.
            action: 动作.
            outcome: 结果.
            latency_ms: 延迟.
            params_summary: 参数摘要.
            error: 错误信息.
            agent_id: Agent ID.
            memory_type: 初始记忆层级 (working/session/long_term).

        Returns:
            创建的记忆条目.
        """
        if self._memory is None:
            return None

        content_parts = [
            f"调用技能 {skill_id}",
            f"动作: {action}",
            f"结果: {outcome}",
            f"延迟: {latency_ms:.0f}ms",
        ]
        if error:
            content_parts.append(f"错误: {error}")
        content = " | ".join(content_parts)

        tags = [f"skill:{skill_id}", f"action:{action}", outcome]
        if agent_id:
            tags.append(f"agent:{agent_id}")

        # 根据结果确定重要性
        importance = 1.0
        if outcome == "success" and latency_ms < 500:
            importance = 3.0
        elif outcome == "failure":
            importance = 5.0  # 失败经验更重要
        elif outcome == "timeout":
            importance = 4.0

        if memory_type == "working":
            entry = self._memory.add_working(
                content, tags=tags, importance=importance
            )
        elif memory_type == "session":
            entry = self._memory.add_session(
                content, tags=tags, importance=importance
            )
        else:
            entry = self._memory.add_long_term(
                content, tags=tags, importance=importance
            )

        self._pending_working.append(entry.entry_id)
        self._stats.total_archived += 1
        self._stats.last_archive_at = time.time()

        logger.debug(
            "bridge_archive",
            skill_id=skill_id,
            action=action,
            outcome=outcome,
            memory_type=memory_type,
        )
        return entry

    # ---- 核心：记忆丰富技能推荐 ----

    def enrich_recommendation_signal(
        self, goal: str, agent_id: str = ""
    ) -> dict[str, float]:
        """从记忆中提取技能偏好信号，用于丰富推荐.

        检索与 goal 相关的记忆条目，提取其中的技能引用
        和使用频率，返回技能 → 偏好评分的映射。

        Args:
            goal: 用户目标.
            agent_id: Agent ID.

        Returns:
            {skill_id: preference_score} 映射.
        """
        if self._memory is None:
            return {}

        # 从长期记忆中检索相关经验
        results = self._memory.retrieve(
            goal, top_k=20, memory_types=["long_term", "session"]
        )

        skill_freq: dict[str, int] = {}
        skill_success: dict[str, int] = {}
        skill_total: dict[str, int] = {}

        for entry, score in results:
            content = entry.content
            for tag in entry.tags:
                if tag.startswith("skill:"):
                    sid = tag[len("skill:"):]
                    skill_freq[sid] = skill_freq.get(sid, 0) + 1
                    skill_total[sid] = skill_total.get(sid, 0) + 1
                    if "success" in entry.tags:
                        skill_success[sid] = (
                            skill_success.get(sid, 0) + 1
                        )

        # 计算偏好评分
        preferences: dict[str, float] = {}
        max_freq = max(skill_freq.values()) if skill_freq else 1

        for sid, freq in skill_freq.items():
            # 频率归一化
            freq_score = freq / max_freq
            # 成功率加成
            success_rate = (
                skill_success.get(sid, 0) / skill_total.get(sid, 1)
            )
            preferences[sid] = freq_score * 0.6 + success_rate * 0.4

        self._stats.memory_enriched += 1
        self._stats.last_enrich_at = time.time()

        return preferences

    # ---- 核心：潮汐记忆分层流转 ----

    def tidal_flow(
        self,
        agent_id: str = "",
        working_threshold: int = 10,
        session_threshold: int = 20,
    ) -> dict[str, int]:
        """执行潮汐记忆分层流转.

        Working → Session: 当工作记忆超过阈值时自动压缩
        Session → Long-term: 当会话记忆超过阈值时自动提升

        Args:
            agent_id: Agent ID.
            working_threshold: 工作记忆压缩阈值.
            session_threshold: 会话记忆提升阈值.

        Returns:
            各层级操作计数.
        """
        result = {"summarized": 0, "promoted": 0}

        if self._memory is None:
            return result

        # Working → Session
        if len(self._memory._working) >= working_threshold:
            summary = self._memory.summarize_working()
            if summary:
                result["summarized"] += 1

        # Session → Long-term
        if len(self._memory._session) >= session_threshold:
            promoted = self._memory.compress_session()
            if promoted:
                result["promoted"] += 1

        return result

    # ---- 经验-记忆双向同步 ----

    def sync_experience_to_memory(
        self, agent_id: str = "", limit: int = 50
    ) -> int:
        """将经验库中的高价值经验同步到长期记忆.

        选择质量评分最高的成功经验，写入长期记忆。

        Returns:
            同步条数.
        """
        if self._experience is None or self._memory is None:
            return 0

        synced = 0
        # 获取经验最丰富的技能
        top_skills = self._experience.get_top_skills(n=10)

        for sid, quality, count in top_skills:
            stats = self._experience.get_skill_stats(sid)
            if stats["total_calls"] < 5:
                continue

            content = (
                f"技能 {sid} 使用经验: "
                f"调用 {stats['total_calls']} 次, "
                f"成功率 {stats['success_rate']:.0%}, "
                f"平均延迟 {stats['avg_latency_ms']:.0f}ms, "
                f"P90 延迟 {stats['p90_latency_ms']:.0f}ms"
            )

            # 检查是否已有类似记忆
            existing = self._memory.search_by_tag(f"skill:{sid}")
            if existing and any(e.content.startswith(f"技能 {sid} 使用经验") for e in existing):
                continue

            self._memory.add_long_term(
                content,
                tags=[f"skill:{sid}", "experience", "stats"],
                importance=min(quality * 10, 8.0),
            )
            synced += 1
            if synced >= limit:
                break

        logger.info(
            "bridge_sync_experience_to_memory",
            synced=synced,
            agent_id=agent_id,
        )
        return synced

    # ---- 查询 ----

    def get_stats(self) -> dict[str, Any]:
        """获取桥接统计."""
        return self._stats.model_dump()
