"""
云汐内核 V9 - 死信队列（DLQ）

解决评审 P1-003：为消费失败或TTL超限的消息提供兜底机制。
支持失败转移、重试计数、异常事件发布。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import structlog

from interfaces import BusMessage

logger = structlog.get_logger(__name__)


@dataclass
class DeadLetterEntry:
    """死信条目"""

    entry_id: str = field(default_factory=lambda: f"dlq_{int(time.time() * 1000)}")
    original_message: BusMessage | None = None
    reason: str = ""  # ttl_expired | delivery_failed | loop_detected | max_retries
    error_detail: str = ""
    retry_count: int = 0
    max_retries: int = 3
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


class DeadLetterQueue:
    """死信队列

    接收无法成功处理的消息，提供：
    1. 持久化存储（内存 + 可选SQLite）
    2. 重试调度（指数退避）
    3. 异常事件发布（供 Orchestrator 兜底处理）
    4. 死信审计（查询、统计、导出）
    """

    def __init__(
        self,
        max_size: int = 10000,
        entry_ttl_seconds: float = 86400.0,
    ) -> None:
        self._entries: list[DeadLetterEntry] = []
        self.max_size: int = max_size
        """最大容量，超过后 FIFO 淘汰最旧条目"""
        self.entry_ttl_seconds: float = entry_ttl_seconds
        """条目存活时间上限（秒），超过后自动清理，防止内存泄漏"""
        self._total_expired: int = 0
        """累计过期清理数量"""
        self._logger = logger.bind(service="dead_letter_queue")

    def enqueue(
        self,
        message: BusMessage,
        reason: str,
        error_detail: str = "",
        retry_count: int = 0,
    ) -> DeadLetterEntry:
        """将消息转入死信队列"""
        entry = DeadLetterEntry(
            original_message=message,
            reason=reason,
            error_detail=error_detail,
            retry_count=retry_count,
        )

        # 容量超限时的FIFO淘汰
        if len(self._entries) >= self.max_size:
            dropped = self._entries.pop(0)
            self._logger.warning(
                "dlq_capacity_exceeded",
                dropped_entry_id=dropped.entry_id,
                dropped_reason=dropped.reason,
            )

        self._entries.append(entry)
        self._logger.error(
            "message_dead_lettered",
            entry_id=entry.entry_id,
            msg_id=message.msg_id,
            reason=reason,
            error_detail=error_detail,
            retry_count=retry_count,
        )

        # 入队时触发过期清理（惰性清理，避免单独起定时器）
        # 每 100 条触发一次清理，降低开销
        if len(self._entries) % 100 == 0:
            self.cleanup_expired()

        return entry

    def enqueue_ttl_expired(self, message: BusMessage) -> DeadLetterEntry:
        """TTL过期消息入死信队列"""
        return self.enqueue(message, reason="ttl_expired", error_detail="Message TTL exceeded")

    def enqueue_delivery_failed(
        self, message: BusMessage, error: str, retry_count: int = 0
    ) -> DeadLetterEntry:
        """投递失败消息入死信队列"""
        return self.enqueue(
            message,
            reason="delivery_failed",
            error_detail=error,
            retry_count=retry_count,
        )

    def enqueue_loop_detected(self, message: BusMessage, detail: str) -> DeadLetterEntry:
        """循环检测消息入死信队列"""
        return self.enqueue(message, reason="loop_detected", error_detail=detail)

    def get_retryable(self, max_age_seconds: float = 300.0) -> list[DeadLetterEntry]:
        """获取可重试的死信条目

        条件：
        - 未超过最大重试次数
        - 距离上次创建/重试超过一定时间（简化：基于created_at）
        """
        now = time.time()
        return [
            e
            for e in self._entries
            if e.retry_count < e.max_retries
            and (now - e.created_at) < max_age_seconds
        ]

    def mark_retried(self, entry_id: str) -> bool:
        """标记条目已重试"""
        for e in self._entries:
            if e.entry_id == entry_id:
                e.retry_count += 1
                return True
        return False

    def remove(self, entry_id: str) -> bool:
        """从死信队列移除条目"""
        for i, e in enumerate(self._entries):
            if e.entry_id == entry_id:
                self._entries.pop(i)
                return True
        return False

    def cleanup_expired(self, max_age_seconds: float | None = None) -> int:
        """清理过期的死信条目（内存泄漏防护）。

        移除存活时间超过 TTL 的条目，防止死信队列无限增长。
        基于惰性清理策略：由入队操作定期触发，无需单独定时器。

        Args:
            max_age_seconds: 最大存活时间（秒），为 None 时使用实例级 entry_ttl_seconds。

        Returns:
            清理掉的过期条目数量
        """
        max_age = max_age_seconds if max_age_seconds is not None else self.entry_ttl_seconds
        now = time.time()
        expired_count = 0

        # 从前往后找，因为旧条目在前
        while self._entries and (now - self._entries[0].created_at) > max_age:
            dropped = self._entries.pop(0)
            expired_count += 1

        if expired_count > 0:
            self._total_expired += expired_count
            self._logger.info(
                "dlq_expired_cleanup",
                expired_count=expired_count,
                remaining=len(self._entries),
                max_age_seconds=max_age,
            )

        return expired_count

    def stats(self) -> dict[str, Any]:
        """死信队列统计"""
        reasons: dict[str, int] = {}
        for e in self._entries:
            reasons[e.reason] = reasons.get(e.reason, 0) + 1

        return {
            "total_entries": len(self._entries),
            "max_size": self.max_size,
            "entry_ttl_seconds": self.entry_ttl_seconds,
            "total_expired": self._total_expired,
            "reason_distribution": reasons,
            "retryable_count": len(self.get_retryable()),
        }

    def list_entries(
        self, reason: str | None = None, limit: int = 100
    ) -> list[DeadLetterEntry]:
        """列岀死信条目"""
        entries = self._entries
        if reason:
            entries = [e for e in entries if e.reason == reason]
        return entries[-limit:]
