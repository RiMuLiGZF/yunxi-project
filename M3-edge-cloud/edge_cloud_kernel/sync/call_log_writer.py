"""调用日志异步回写器.

将推理调用日志异步写入本地存储。
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from edge_cloud_kernel.models.call_log import CallLogRecord

logger = structlog.get_logger(__name__)

# 默认配置
DEFAULT_BUFFER_SIZE: int = 100
DEFAULT_FLUSH_INTERVAL_S: float = 5.0


class CallLogWriter:
    """调用日志异步回写器.

    接收推理调用日志记录，缓冲后批量写入本地 SQLite 存储。
    避免同步写操作阻塞推理请求。

    Attributes:
        _buffer: 日志缓冲区.
        _buffer_size: 缓冲区最大容量.
        _flush_interval_s: 自动刷新间隔（秒）.
        _running: 是否正在运行.
    """

    def __init__(
        self,
        buffer_size: int = DEFAULT_BUFFER_SIZE,
        flush_interval_s: float = DEFAULT_FLUSH_INTERVAL_S,
        db_path: str = "",
    ) -> None:
        """初始化 CallLogWriter.

        Args:
            buffer_size: 缓冲区最大容量.
            flush_interval_s: 自动刷新间隔（秒）.
            db_path: SQLite 数据库路径.
        """
        self._buffer: list[CallLogRecord] = []
        self._buffer_size = buffer_size
        self._flush_interval_s = flush_interval_s
        self._db_path = db_path
        self._running = False
        self._flush_task: asyncio.Task[None] | None = None
        logger.info(
            "call_log_writer.init",
            buffer_size=buffer_size,
            flush_interval=flush_interval_s,
        )

    async def start(self) -> None:
        """启动日志回写器."""
        if self._running:
            return
        self._running = True
        self._flush_task = asyncio.create_task(self._flush_loop())
        logger.info("call_log_writer.started")

    async def stop(self) -> None:
        """停止日志回写器，刷新缓冲区."""
        self._running = False
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        # 最终刷新
        await self.flush()
        logger.info("call_log_writer.stopped")

    async def write(self, record: CallLogRecord) -> None:
        """写入一条调用日志记录.

        Args:
            record: 调用日志记录.
        """
        self._buffer.append(record)

        if len(self._buffer) >= self._buffer_size:
            await self.flush()

        logger.debug(
            "call_log_writer.write",
            task_id=record.task_id,
            buffer_size=len(self._buffer),
        )

    async def write_batch(self, records: list[CallLogRecord]) -> None:
        """批量写入调用日志记录.

        Args:
            records: 调用日志记录列表.
        """
        self._buffer.extend(records)
        if len(self._buffer) >= self._buffer_size:
            await self.flush()
        logger.debug(
            "call_log_writer.write_batch",
            count=len(records),
            buffer_size=len(self._buffer),
        )

    async def flush(self) -> int:
        """刷新缓冲区，将日志写入存储.

        Returns:
            写入的记录数.
        """
        if not self._buffer:
            return 0

        records = self._buffer.copy()
        self._buffer.clear()

        try:
            # TODO: 使用 aiosqlite 写入 SQLite
            # async with aiosqlite.connect(self._db_path) as db:
            #     for record in records:
            #         await db.execute("INSERT INTO call_logs ...", (...))
            #     await db.commit()

            logger.info(
                "call_log_writer.flushed",
                count=len(records),
            )
            return len(records)
        except Exception as e:
            # 写入失败，将记录放回缓冲区
            self._buffer.extend(records)
            logger.error(
                "call_log_writer.flush_error",
                error=str(e),
                recovered_count=len(self._buffer),
            )
            return 0

    async def _flush_loop(self) -> None:
        """定时刷新循环."""
        while self._running:
            try:
                await asyncio.sleep(self._flush_interval_s)
                await self.flush()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("call_log_writer.flush_loop_error")

    @property
    def buffer_size(self) -> int:
        """当前缓冲区大小.

        Returns:
            缓冲区中的记录数.
        """
        return len(self._buffer)
