from __future__ import annotations

"""Trace Aggregator - 调用链路追踪聚合器.

【第五轮优化 - 原创创新机制】
将分散的 trace_id 聚合为完整调用链视图，提供：
- 调用链自动关联（parent → child trace）
- 端到端延迟追踪（从首次调用到最终结果）
- 跨技能调用拓扑图
- 异常传播追踪

参考：
- OpenTelemetry Span 模型
- MCP 2026 progress_token 进度通知机制
"""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass
class TraceSpan:
    """单个调用链路 Span（类比 OpenTelemetry Span）."""

    trace_id: str
    span_id: str
    skill_id: str
    action: str
    agent_id: str
    parent_span_id: str | None = None
    status: str = "pending"
    start_time: float = 0.0
    end_time: float = 0.0
    latency_ms: float = 0.0
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    children: list[str] = field(default_factory=list)  # child span_ids

    @property
    def duration_ms(self) -> float:
        if self.end_time > 0:
            return (self.end_time - self.start_time) * 1000
        return 0.0


@dataclass
class TraceChain:
    """完整调用链（一棵 trace 树）."""

    trace_id: str
    root_span_id: str
    spans: dict[str, TraceSpan] = field(default_factory=dict)
    total_latency_ms: float = 0.0
    status: str = "pending"
    error_summary: str | None = None

    def to_summary(self) -> dict[str, Any]:
        """输出摘要."""
        return {
            "trace_id": self.trace_id,
            "root_span_id": self.root_span_id,
            "span_count": len(self.spans),
            "total_latency_ms": round(self.total_latency_ms, 2),
            "status": self.status,
            "error_summary": self.error_summary,
            "topology": self._build_topology(),
        }

    def _build_topology(self) -> list[dict[str, Any]]:
        """构建调用拓扑（深度优先）."""
        result: list[dict[str, Any]] = []

        def _walk(span_id: str, depth: int) -> None:
            span = self.spans.get(span_id)
            if span is None:
                return
            result.append({
                "span_id": span_id,
                "skill_id": span.skill_id,
                "action": span.action,
                "depth": depth,
                "status": span.status,
                "latency_ms": round(span.duration_ms, 2),
                "error": span.error,
            })
            for child_id in span.children:
                _walk(child_id, depth + 1)

        _walk(self.root_span_id, 0)
        return result


class TraceAggregator:
    """调用链路追踪聚合器.

    核心 API：
    - start_span(): 开始一个新的 span
    - finish_span(): 完成 span（记录结果/错误）
    - get_chain(): 获取完整调用链
    - get_active_traces(): 获取当前活跃的 trace 列表

    设计特点：
    - span 自动关联 parent → child
    - 端到端延迟聚合
    - 内存可控（max_chains 限制）
    """

    def __init__(self, max_chains: int = 1000) -> None:
        self._chains: dict[str, TraceChain] = {}
        self._max_chains = max_chains
        self._span_counter = 0

    def _next_span_id(self) -> str:
        self._span_counter += 1
        return f"span_{self._span_counter:08d}"

    def start_span(
        self,
        trace_id: str,
        skill_id: str,
        action: str,
        agent_id: str,
        parent_span_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """开始一个新的 Span.

        Args:
            trace_id: 调用链 ID（请求级别唯一）.
            skill_id: 技能 ID.
            action: 动作标识.
            agent_id: Agent ID.
            parent_span_id: 父 Span ID（子调用时传入）.
            metadata: 附加元数据.

        Returns:
            span_id.
        """
        import time as _time

        span_id = self._next_span_id()

        # 获取或创建 chain
        chain = self._chains.get(trace_id)
        if chain is None:
            if len(self._chains) >= self._max_chains:
                # 淘汰最旧的 chain
                oldest_key = next(iter(self._chains))
                del self._chains[oldest_key]
            chain = TraceChain(
                trace_id=trace_id,
                root_span_id=span_id,
            )
            self._chains[trace_id] = chain

        # 创建 span
        span = TraceSpan(
            trace_id=trace_id,
            span_id=span_id,
            skill_id=skill_id,
            action=action,
            agent_id=agent_id,
            parent_span_id=parent_span_id,
            status="running",
            start_time=_time.time(),
            metadata=metadata or {},
        )
        chain.spans[span_id] = span

        # 关联 parent
        if parent_span_id and parent_span_id in chain.spans:
            chain.spans[parent_span_id].children.append(span_id)

        return span_id

    def finish_span(
        self,
        trace_id: str,
        span_id: str,
        status: str = "success",
        error: str | None = None,
    ) -> None:
        """完成一个 Span.

        Args:
            trace_id: 调用链 ID.
            span_id: Span ID.
            status: 完成状态.
            error: 错误信息.
        """
        import time as _time

        chain = self._chains.get(trace_id)
        if chain is None or span_id not in chain.spans:
            return

        span = chain.spans[span_id]
        span.end_time = _time.time()
        span.status = status
        span.error = error

        # 更新 chain 总延迟
        root = chain.spans.get(chain.root_span_id)
        if root:
            chain.total_latency_ms = root.duration_ms

        # 更新 chain 状态（取最差状态）
        if status == "failure" or status == "timeout":
            chain.status = status
            chain.error_summary = error
        elif chain.status != "failure" and chain.status != "timeout":
            chain.status = status

    def get_chain(self, trace_id: str) -> TraceChain | None:
        """获取完整调用链."""
        return self._chains.get(trace_id)

    def get_active_traces(self) -> list[dict[str, Any]]:
        """获取当前活跃（running）的 trace 列表."""
        result: list[dict[str, Any]] = []
        for chain in self._chains.values():
            root = chain.spans.get(chain.root_span_id)
            if root and root.status == "running":
                result.append({
                    "trace_id": chain.trace_id,
                    "skill_id": root.skill_id,
                    "elapsed_ms": round(
                        (root.start_time - root.start_time) * 1000
                        if root.end_time == 0
                        else root.duration_ms,
                        2,
                    ),
                    "span_count": len(chain.spans),
                })
        return result

    def get_stats(self) -> dict[str, Any]:
        """获取聚合器统计."""
        total = len(self._chains)
        running = sum(
            1 for c in self._chains.values()
            if c.spans.get(c.root_span_id, None)
            and c.spans[c.root_span_id].status == "running"
        )
        failed = sum(1 for c in self._chains.values() if c.status in ("failure", "timeout"))
        return {
            "total_traces": total,
            "running_traces": running,
            "failed_traces": failed,
            "max_chains": self._max_chains,
        }

    def cleanup_expired(self, max_age_seconds: float = 3600) -> int:
        """清理过期的 trace 链.

        Args:
            max_age_seconds: 最大存活时间.

        Returns:
            清理数量.
        """
        import time as _time
        now = _time.time()
        expired_keys: list[str] = []
        for trace_id, chain in self._chains.items():
            root = chain.spans.get(chain.root_span_id)
            if root and root.end_time > 0:
                age = now - root.end_time
                if age > max_age_seconds:
                    expired_keys.append(trace_id)
        for key in expired_keys:
            del self._chains[key]
        if expired_keys:
            logger.info("trace_cleanup", removed=len(expired_keys))
        return len(expired_keys)
