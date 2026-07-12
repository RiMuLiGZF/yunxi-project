"""调用日志回写器单元测试.

验证 CallLogWriter 的缓冲写入、批量刷新、自动回写循环及异常恢复。

目标：提升 edge_cloud_kernel.sync.call_log_writer 覆盖率。
"""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio

from edge_cloud_kernel.models.call_log import CallLogRecord
from edge_cloud_kernel.sync.call_log_writer import CallLogWriter


class TestCallLogWriter:
    """CallLogWriter 核心测试集."""

    @pytest_asyncio.fixture
    async def writer(self):
        """创建 CallLogWriter 实例并在测试后停止."""
        w = CallLogWriter(buffer_size=10, flush_interval_s=1.0)
        yield w
        await w.stop()

    @pytest.mark.asyncio
    async def test_write_appends_to_buffer(self, writer):
        """write 应将记录追加到缓冲区."""
        record = CallLogRecord(task_id="t1", agent_name="a1")
        await writer.write(record)
        assert writer.buffer_size == 1

    @pytest.mark.asyncio
    async def test_write_triggers_flush_when_full(self, writer):
        """缓冲区满时应自动触发刷新."""
        for i in range(10):
            await writer.write(CallLogRecord(task_id=f"t{i}"))
        # 第 10 条写入后触发 flush
        assert writer.buffer_size == 0

    @pytest.mark.asyncio
    async def test_flush_clears_buffer(self, writer):
        """flush 应清空缓冲区并返回写入数量."""
        await writer.write(CallLogRecord(task_id="t1"))
        await writer.write(CallLogRecord(task_id="t2"))
        count = await writer.flush()
        assert count == 2
        assert writer.buffer_size == 0

    @pytest.mark.asyncio
    async def test_flush_empty_buffer_returns_zero(self, writer):
        """空缓冲区 flush 应返回 0."""
        assert await writer.flush() == 0

    @pytest.mark.asyncio
    async def test_write_batch(self, writer):
        """write_batch 应支持批量写入."""
        records = [CallLogRecord(task_id=f"t{i}") for i in range(5)]
        await writer.write_batch(records)
        assert writer.buffer_size == 5

    @pytest.mark.asyncio
    async def test_start_stop_idempotent(self, writer):
        """start/stop 应为幂等操作."""
        await writer.start()
        assert writer._running is True
        await writer.stop()
        assert writer._running is False
        # 再次 stop 不应报错
        await writer.stop()

    @pytest.mark.asyncio
    async def test_auto_flush_loop(self, writer):
        """后台 flush 循环应定期自动刷新缓冲区."""
        await writer.start()
        await writer.write(CallLogRecord(task_id="t_auto"))
        await asyncio.sleep(1.2)
        assert writer.buffer_size == 0

    @pytest.mark.asyncio
    async def test_buffer_size_property(self, writer):
        """buffer_size 应正确反映当前缓冲区长度."""
        assert writer.buffer_size == 0
        await writer.write(CallLogRecord(task_id="t1"))
        assert writer.buffer_size == 1
