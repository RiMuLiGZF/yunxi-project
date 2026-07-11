"""记忆覆盖率防腐层（Anti-Corruption Layer）.

隔离 M3 对模块 5（TideMemory）的直接依赖。
模块 1 的路由决策引擎通过注入 MemoryCoverageSource 实现来提供覆盖率数据，
M3 仅定义协议接口和空对象回退实现（no-op fallback）。

设计依据：评审报告 REV-20250628-M3-001。
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

import structlog

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# 协议定义
# ---------------------------------------------------------------------------


@runtime_checkable
class MemoryCoverageSource(Protocol):
    """记忆覆盖率数据源协议.

    定义获取指定 Agent 在某主题下记忆覆盖率的标准接口。
    模块 5 的 TideMemoryBridge 或模块 1 的路由决策引擎可实现此协议，
    在运行时被注入到 MemoryCoverageAdapter 中。

    Example:
        class TideMemoryCoverage(MemoryCoverageSource):
            async def get_coverage(self, agent_id: str, topic: str | None = None) -> float:
                return await self._tide_memory.compute_coverage(agent_id, topic)
    """

    async def get_coverage(
        self,
        agent_id: str,
        topic: str | None = None,
    ) -> float:
        """获取记忆覆盖率.

        Args:
            agent_id: Agent 唯一标识.
            topic: 可选的主题/领域过滤条件，None 表示全局覆盖率.

        Returns:
            覆盖率比例，范围 [0.0, 1.0]。
            1.0 表示完全覆盖，0.0 表示无可用记忆。

        Raises:
            Exception: 数据源内部错误（由调用方捕获并降级）.
        """
        ...


@runtime_checkable
class MemoryRecallSource(Protocol):
    """记忆召回数据源协议.

    定义从长期记忆中召回与查询相关片段的标准接口。
    与 MemoryCoverageSource 解耦，支持独立注入不同实现。
    """

    async def recall(
        self,
        query: str,
        agent_id: str,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """召回相关记忆片段.

        Args:
            query: 查询文本或关键词.
            agent_id: Agent 唯一标识.
            top_k: 返回的最大条目数，默认 5.

        Returns:
            记忆片段列表，每条片段为 dict，通常包含 content、score、metadata 等字段。

        Raises:
            Exception: 召回失败（由调用方捕获并降级）.
        """
        ...


# ---------------------------------------------------------------------------
# 空对象模式（No-op Fallback）
# ---------------------------------------------------------------------------


class _NoOpCoverageSource:
    """空对象覆盖率源：无可用数据源时安全回退到 0.0.

    遵循空对象模式（Null Object Pattern），避免调用方到处检查 None。
    """

    async def get_coverage(
        self,
        agent_id: str,
        topic: str | None = None,
    ) -> float:
        """始终返回 0.0，表示无覆盖率数据."""
        return 0.0


class _NoOpRecallSource:
    """空对象召回源：无可用数据源时安全回退到空列表."""

    async def recall(
        self,
        query: str,
        agent_id: str,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """始终返回空列表，表示无召回结果."""
        return []


# ---------------------------------------------------------------------------
# 记忆覆盖率适配器
# ---------------------------------------------------------------------------


class MemoryCoverageAdapter:
    """记忆覆盖率防腐层.

    核心职责：
    1. 协议隔离 —— M3 仅依赖本模块定义的 Protocol，不直接引用模块 5 的任何类型。
    2. 运行时注入 —— 模块 1 的路由决策引擎通过 ``set_source()`` / ``set_recall_source()``
       在运行时注入具体实现。
    3. 安全降级 —— 未注入或注入失败时自动回退到 No-op 实现，保证 M3 不崩溃。
    4. 日志可观测 —— 所有覆盖率查询和召回操作均记录 structlog 日志，便于排障。

    Attributes:
        _source: 外部注入的覆盖率数据源（可为 None）.
        _recall_source: 外部注入的召回数据源（可为 None）.
        _fallback_coverage: 覆盖率 No-op 回退实例.
        _fallback_recall: 召回 No-op 回退实例.
    """

    def __init__(
        self,
        coverage_source: MemoryCoverageSource | None = None,
        recall_source: MemoryRecallSource | None = None,
    ) -> None:
        """初始化 MemoryCoverageAdapter.

        Args:
            coverage_source: 可选的初始覆盖率数据源.
            recall_source: 可选的初始召回数据源.
        """
        self._source: MemoryCoverageSource | None = coverage_source
        self._recall_source: MemoryRecallSource | None = recall_source
        self._fallback_coverage = _NoOpCoverageSource()
        self._fallback_recall = _NoOpRecallSource()

        logger.info(
            "memory_coverage_adapter.init",
            has_coverage_source=coverage_source is not None,
            has_recall_source=recall_source is not None,
        )

    # ------------------------------------------------------------------
    # 覆盖率接口
    # ------------------------------------------------------------------

    async def get_coverage(
        self,
        agent_id: str,
        topic: str | None = None,
    ) -> float:
        """获取记忆覆盖率.

        优先使用注入的 ``_source``，若不可用或调用失败则回退到
        ``_fallback_coverage`` 返回 0.0。

        Args:
            agent_id: Agent 唯一标识.
            topic: 可选的主题过滤.

        Returns:
            覆盖率比例 [0.0, 1.0]，失败时返回 0.0。
        """
        source = self._source or self._fallback_coverage
        try:
            coverage = await source.get_coverage(agent_id, topic)
            # 防御性裁剪，确保返回值在合法区间
            coverage = max(0.0, min(1.0, float(coverage)))
            logger.debug(
                "memory_coverage_adapter.get_coverage",
                agent_id=agent_id,
                topic=topic,
                coverage=coverage,
                source_type=type(source).__name__,
            )
            return coverage
        except Exception:
            logger.exception(
                "memory_coverage_adapter.get_coverage_failed",
                agent_id=agent_id,
                topic=topic,
                source_type=type(source).__name__,
            )
            return 0.0

    def set_source(self, source: MemoryCoverageSource) -> None:
        """运行时注入覆盖率数据源.

        通常由模块 1 的路由决策引擎在初始化阶段或热更新时调用。

        Args:
            source: 符合 MemoryCoverageSource 协议的对象.
        """
        if not isinstance(source, MemoryCoverageSource):
            logger.warning(
                "memory_coverage_adapter.set_source_type_mismatch",
                expected="MemoryCoverageSource",
                got=type(source).__name__,
            )
        self._source = source
        logger.info(
            "memory_coverage_adapter.source_set",
            source_type=type(source).__name__,
        )

    def clear_source(self) -> None:
        """清除已注入的覆盖率数据源，回退到 No-op 状态."""
        self._source = None
        logger.info("memory_coverage_adapter.source_cleared")

    @property
    def has_coverage_source(self) -> bool:
        """是否已注入有效的覆盖率数据源.

        Returns:
            True 当且仅当 ``_source`` 不为 None。
        """
        return self._source is not None

    # ------------------------------------------------------------------
    # 召回接口（可选扩展）
    # ------------------------------------------------------------------

    async def recall(
        self,
        query: str,
        agent_id: str,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """召回相关记忆片段.

        优先使用注入的 ``_recall_source``，若不可用或调用失败则回退到
        ``_fallback_recall`` 返回空列表。

        Args:
            query: 查询文本.
            agent_id: Agent 唯一标识.
            top_k: 返回条数上限.

        Returns:
            记忆片段列表，失败时返回空列表。
        """
        source = self._recall_source or self._fallback_recall
        try:
            results = await source.recall(query, agent_id, top_k)
            if not isinstance(results, list):
                logger.warning(
                    "memory_coverage_adapter.recall_bad_return_type",
                    expected="list",
                    got=type(results).__name__,
                    agent_id=agent_id,
                )
                return []

            logger.debug(
                "memory_coverage_adapter.recall",
                agent_id=agent_id,
                query=query[:50],
                top_k=top_k,
                returned=len(results),
                source_type=type(source).__name__,
            )
            return results
        except Exception:
            logger.exception(
                "memory_coverage_adapter.recall_failed",
                agent_id=agent_id,
                query=query[:50],
                top_k=top_k,
                source_type=type(source).__name__,
            )
            return []

    def set_recall_source(self, source: MemoryRecallSource) -> None:
        """运行时注入召回数据源.

        Args:
            source: 符合 MemoryRecallSource 协议的对象.
        """
        if not isinstance(source, MemoryRecallSource):
            logger.warning(
                "memory_coverage_adapter.set_recall_source_type_mismatch",
                expected="MemoryRecallSource",
                got=type(source).__name__,
            )
        self._recall_source = source
        logger.info(
            "memory_coverage_adapter.recall_source_set",
            source_type=type(source).__name__,
        )

    def clear_recall_source(self) -> None:
        """清除已注入的召回数据源，回退到 No-op 状态."""
        self._recall_source = None
        logger.info("memory_coverage_adapter.recall_source_cleared")

    @property
    def has_recall_source(self) -> bool:
        """是否已注入有效的召回数据源.

        Returns:
            True 当且仅当 ``_recall_source`` 不为 None。
        """
        return self._recall_source is not None

    # ------------------------------------------------------------------
    # 诊断与观测
    # ------------------------------------------------------------------

    def get_status(self) -> dict[str, Any]:
        """获取适配器当前状态快照.

        Returns:
            状态字典，包含 source 是否存在、fallback 类型等诊断信息。
        """
        return {
            "has_coverage_source": self.has_coverage_source,
            "has_recall_source": self.has_recall_source,
            "coverage_source_type": (
                type(self._source).__name__ if self._source else "None"
            ),
            "recall_source_type": (
                type(self._recall_source).__name__ if self._recall_source else "None"
            ),
            "fallback_coverage_type": type(self._fallback_coverage).__name__,
            "fallback_recall_type": type(self._fallback_recall).__name__,
        }
