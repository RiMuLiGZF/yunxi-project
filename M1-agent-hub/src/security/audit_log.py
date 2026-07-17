"""
安全审计日志 — AuditLog

操作日志留痕系统，记录所有安全相关操作，
支持按 Agent、时间范围、涉密等级查询与统计。
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional

import structlog

from shared_models import SecurityClassification

logger = structlog.get_logger(__name__)


@dataclass
class AuditEntry:
    """审计日志条目

    Attributes:
        entry_id:       条目唯一标识
        timestamp:      操作时间戳
        agent_id:       执行操作的Agent ID
        action:         操作类型（如 classify / check_access / strip）
        resource:       操作资源标识
        classification: 涉密等级
        result:         操作结果（allow / deny / error）
        detail:         操作详情
    """

    entry_id: str = field(default_factory=lambda: f"audit_{int(time.time() * 1000_000)}")
    timestamp: float = field(default_factory=time.time)
    agent_id: str = ""
    action: str = ""
    resource: str = ""
    classification: str = SecurityClassification.PUBLIC.name
    result: str = ""  # allow / deny / error
    detail: str = ""


class AuditLog:
    """操作日志留痕

    特性：
    - 内存存储，最大 100000 条
    - 支持 Agent 维度、时间范围、涉密等级查询
    - 提供统计摘要
    """

    def __init__(self, max_entries: int = 100_000) -> None:
        self._entries: list[AuditEntry] = []
        self._max_entries: int = max_entries
        self._logger = logger.bind(component="audit_log")

    def record(
        self,
        agent_id: str,
        action: str,
        resource: str = "",
        classification: str = SecurityClassification.PUBLIC.name,
        result: str = "",
        detail: str = "",
    ) -> AuditEntry:
        """记录一条审计日志

        当条目数超过上限时，自动淘汰最旧的条目（FIFO）。

        Args:
            agent_id:       执行操作的Agent ID
            action:         操作类型
            resource:       操作资源标识
            classification: 涉密等级名称
            result:         操作结果
            detail:         操作详情

        Returns:
            新创建的 AuditEntry
        """
        entry = AuditEntry(
            entry_id=f"audit_{int(time.time() * 1_000_000)}_{len(self._entries)}",
            timestamp=time.time(),
            agent_id=agent_id,
            action=action,
            resource=resource,
            classification=classification,
            result=result,
            detail=detail,
        )

        # 容量控制：超过上限时FIFO淘汰
        if len(self._entries) >= self._max_entries:
            evicted = self._entries.pop(0)
            self._logger.warning(
                "audit_log_capacity_evicted",
                evicted_entry_id=evicted.entry_id,
                current_size=len(self._entries),
                max_entries=self._max_entries,
            )

        self._entries.append(entry)

        self._logger.debug(
            "audit_entry_recorded",
            entry_id=entry.entry_id,
            agent_id=agent_id,
            action=action,
            result=result,
        )
        return entry

    def query(
        self,
        agent_id: str | None = None,
        time_range: tuple[float, float] | None = None,
        classification: str | None = None,
    ) -> list[AuditEntry]:
        """查询审计日志

        Args:
            agent_id:       按Agent ID过滤（None表示不过滤）
            time_range:     时间范围 (start, end)，None表示不过滤
            classification: 按涉密等级过滤（None表示不过滤）

        Returns:
            匹配的审计条目列表
        """
        result: list[AuditEntry] = self._entries

        if agent_id is not None:
            result = [e for e in result if e.agent_id == agent_id]

        if time_range is not None:
            start, end = time_range
            result = [e for e in result if start <= e.timestamp <= end]

        if classification is not None:
            result = [e for e in result if e.classification == classification]

        self._logger.debug(
            "audit_log_queried",
            filters={
                "agent_id": agent_id,
                "time_range": time_range,
                "classification": classification,
            },
            result_count=len(result),
        )
        return result

    def stats(self) -> dict[str, Any]:
        """生成审计统计摘要

        Returns:
            包含总数、按Agent统计、按操作类型统计、按结果统计的字典
        """
        total = len(self._entries)

        # 按 Agent 统计
        agent_counts: dict[str, int] = defaultdict(int)
        for entry in self._entries:
            agent_counts[entry.agent_id] += 1

        # 按操作类型统计
        action_counts: dict[str, int] = defaultdict(int)
        for entry in self._entries:
            action_counts[entry.action] += 1

        # 按结果统计
        result_counts: dict[str, int] = defaultdict(int)
        for entry in self._entries:
            result_counts[entry.result] += 1

        # 按涉密等级统计
        class_counts: dict[str, int] = defaultdict(int)
        for entry in self._entries:
            class_counts[entry.classification] += 1

        return {
            "total_entries": total,
            "max_entries": self._max_entries,
            "utilization_ratio": round(total / self._max_entries, 4) if self._max_entries > 0 else 0.0,
            "by_agent": dict(agent_counts),
            "by_action": dict(action_counts),
            "by_result": dict(result_counts),
            "by_classification": dict(class_counts),
        }
