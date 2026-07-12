"""MemoryCoverageAdapter 单元测试.

验证记忆覆盖率防腐层的空对象回退、运行时注入、异常降级、
数值裁剪及召回接口行为。

设计依据：M3 v2.1.0 评审报告 REV-20250628-M3-001。
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from edge_cloud_kernel.sync.memory_coverage_adapter import (
    MemoryCoverageAdapter,
    MemoryCoverageSource,
    MemoryRecallSource,
    _NoOpCoverageSource,
    _NoOpRecallSource,
)


class TestMemoryCoverageAdapter:
    """记忆覆盖率适配器核心测试集."""

    @pytest.mark.asyncio
    async def test_no_source_returns_zero(self):
        """未注入覆盖率源时应返回 0.0."""
        adapter = MemoryCoverageAdapter()
        result = await adapter.get_coverage("agent1")
        assert result == 0.0

    @pytest.mark.asyncio
    async def test_source_injection(self):
        """注入的源应返回其原始值."""
        source = AsyncMock(spec=MemoryCoverageSource)
        source.get_coverage = AsyncMock(return_value=0.75)
        adapter = MemoryCoverageAdapter(coverage_source=source)
        result = await adapter.get_coverage("agent1", "emotion")
        assert result == 0.75
        source.get_coverage.assert_awaited_once_with("agent1", "emotion")

    @pytest.mark.asyncio
    async def test_source_failure_falls_back(self):
        """覆盖率源抛出异常时应降级为 0.0."""
        source = AsyncMock(spec=MemoryCoverageSource)
        source.get_coverage = AsyncMock(side_effect=Exception("boom"))
        adapter = MemoryCoverageAdapter(coverage_source=source)
        result = await adapter.get_coverage("agent1")
        assert result == 0.0

    @pytest.mark.asyncio
    async def test_coverage_clamped(self):
        """覆盖率值应被裁剪到 [0.0, 1.0] 区间."""
        source = AsyncMock(spec=MemoryCoverageSource)
        source.get_coverage = AsyncMock(return_value=1.5)
        adapter = MemoryCoverageAdapter(coverage_source=source)
        result = await adapter.get_coverage("agent1")
        assert result == 1.0

        source.get_coverage = AsyncMock(return_value=-0.5)
        result = await adapter.get_coverage("agent1")
        assert result == 0.0

    @pytest.mark.asyncio
    async def test_coverage_returns_none(self):
        """覆盖率源返回 None 时应降级为 0.0."""
        source = AsyncMock(spec=MemoryCoverageSource)
        source.get_coverage = AsyncMock(return_value=None)
        adapter = MemoryCoverageAdapter(coverage_source=source)
        result = await adapter.get_coverage("agent1")
        assert result == 0.0

    @pytest.mark.asyncio
    async def test_set_source_runtime(self):
        """set_source 应支持运行时注入."""
        adapter = MemoryCoverageAdapter()
        assert adapter.has_coverage_source is False
        source = AsyncMock(spec=MemoryCoverageSource)
        adapter.set_source(source)
        assert adapter.has_coverage_source is True

    def test_clear_source(self):
        """clear_source 应清除已注入的覆盖率源."""
        adapter = MemoryCoverageAdapter()
        source = AsyncMock(spec=MemoryCoverageSource)
        adapter.set_source(source)
        adapter.clear_source()
        assert adapter.has_coverage_source is False

    def test_set_source_type_mismatch(self):
        """set_source 对类型不匹配的对象应记录 warning 但仍接受."""
        adapter = MemoryCoverageAdapter()
        adapter.set_source("not_a_source")
        assert adapter.has_coverage_source is True

    @pytest.mark.asyncio
    async def test_recall_no_source(self):
        """未注入召回源时应返回空列表."""
        adapter = MemoryCoverageAdapter()
        result = await adapter.recall("query", "agent1")
        assert result == []

    @pytest.mark.asyncio
    async def test_recall_with_source(self):
        """注入的召回源应返回其结果."""
        source = AsyncMock(spec=MemoryRecallSource)
        source.recall = AsyncMock(return_value=[{"content": "hello"}])
        adapter = MemoryCoverageAdapter(recall_source=source)
        result = await adapter.recall("query", "agent1", top_k=3)
        assert len(result) == 1
        source.recall.assert_awaited_once_with("query", "agent1", 3)

    @pytest.mark.asyncio
    async def test_recall_bad_return_type(self):
        """召回源返回非列表时应降级为空列表."""
        source = AsyncMock(spec=MemoryRecallSource)
        source.recall = AsyncMock(return_value="not a list")
        adapter = MemoryCoverageAdapter(recall_source=source)
        result = await adapter.recall("q", "a1")
        assert result == []

    @pytest.mark.asyncio
    async def test_recall_source_failure_falls_back(self):
        """召回源抛出异常时应降级为空列表."""
        source = AsyncMock(spec=MemoryRecallSource)
        source.recall = AsyncMock(side_effect=RuntimeError("recall failed"))
        adapter = MemoryCoverageAdapter(recall_source=source)
        result = await adapter.recall("q", "a1")
        assert result == []

    def test_get_status_empty(self):
        """初始状态快照应反映未注入任何源."""
        adapter = MemoryCoverageAdapter()
        status = adapter.get_status()
        assert status["has_coverage_source"] is False
        assert status["has_recall_source"] is False
        assert status["fallback_coverage_type"] == "_NoOpCoverageSource"
        assert status["fallback_recall_type"] == "_NoOpRecallSource"

    def test_get_status_with_sources(self):
        """注入源后的状态快照应正确反映源类型."""
        cov = AsyncMock(spec=MemoryCoverageSource)
        rec = AsyncMock(spec=MemoryRecallSource)
        adapter = MemoryCoverageAdapter(
            coverage_source=cov, recall_source=rec
        )
        status = adapter.get_status()
        assert status["has_coverage_source"] is True
        assert status["has_recall_source"] is True
        assert status["coverage_source_type"] == "AsyncMock"
        assert status["recall_source_type"] == "AsyncMock"

    def test_set_recall_source_runtime(self):
        """set_recall_source 应支持运行时注入召回源."""
        adapter = MemoryCoverageAdapter()
        assert adapter.has_recall_source is False
        source = AsyncMock(spec=MemoryRecallSource)
        adapter.set_recall_source(source)
        assert adapter.has_recall_source is True

    def test_clear_recall_source(self):
        """clear_recall_source 应清除已注入的召回源."""
        adapter = MemoryCoverageAdapter()
        source = AsyncMock(spec=MemoryRecallSource)
        adapter.set_recall_source(source)
        adapter.clear_recall_source()
        assert adapter.has_recall_source is False


class TestNoOpSources:
    """空对象回退实现测试集."""

    @pytest.mark.asyncio
    async def test_noop_coverage(self):
        """_NoOpCoverageSource 始终返回 0.0."""
        s = _NoOpCoverageSource()
        assert await s.get_coverage("a") == 0.0
        assert await s.get_coverage("a", "topic") == 0.0

    @pytest.mark.asyncio
    async def test_noop_recall(self):
        """_NoOpRecallSource 始终返回空列表."""
        s = _NoOpRecallSource()
        assert await s.recall("q", "a") == []
        assert await s.recall("q", "a", top_k=10) == []
