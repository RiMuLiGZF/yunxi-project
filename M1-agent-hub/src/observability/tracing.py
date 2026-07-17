"""
云汐内核 V2 - Tracing 链路追踪系统

灵感来源：OpenAI Agents SDK Tracing
https://openai.github.io/openai-agents-python/tracing/

收集 Agent 运行过程中的全链路事件记录，
支持 LLM 调用、工具调用、Handoff、Guardrails、自定义事件的可视化追踪。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class SpanKind(str, Enum):
    """Span 类型"""

    WORKFLOW = "workflow"      # 工作流
    AGENT = "agent"            # Agent 调用
    HANDOFF = "handoff"        # Agent 转交
    TOOL = "tool"              # 工具/Skill 调用
    LLM = "llm"                # LLM 调用
    GUARDRAIL = "guardrail"    # 护栏检查
    CUSTOM = "custom"          # 自定义事件


class SpanStatus(str, Enum):
    """Span 状态"""

    OK = "ok"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass
class Span:
    """链路追踪 Span

    代表一次操作的时间跨度，包含开始/结束时间、属性、事件等。
    """

    span_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    parent_id: str | None = None
    trace_id: str = ""
    name: str = ""
    kind: SpanKind = SpanKind.CUSTOM
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None
    status: SpanStatus = SpanStatus.OK
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)

    def finish(self, status: SpanStatus = SpanStatus.OK) -> None:
        """结束 Span"""
        self.end_time = time.time()
        self.status = status

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        """添加事件"""
        self.events.append({
            "name": name,
            "timestamp": time.time(),
            "attributes": attributes or {},
        })

    def set_attribute(self, key: str, value: Any) -> None:
        """设置属性"""
        self.attributes[key] = value

    @property
    def duration_ms(self) -> float:
        """Span 持续时间（毫秒）"""
        end = self.end_time or time.time()
        return (end - self.start_time) * 1000


@dataclass
class Trace:
    """完整链路追踪

    一个 Trace 包含多个 Span，代表一次完整的用户请求处理链路。
    """

    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    root_span_id: str | None = None
    spans: list[Span] = field(default_factory=list)
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_span(self, span: Span) -> Span:
        """添加 Span 到 Trace（自动去重）"""
        span.trace_id = self.trace_id
        if not any(s.span_id == span.span_id for s in self.spans):
            self.spans.append(span)
        return span

    def finish(self) -> None:
        """结束 Trace"""
        self.end_time = time.time()

    @property
    def duration_ms(self) -> float:
        """Trace 总持续时间"""
        end = self.end_time or time.time()
        return (end - self.start_time) * 1000

    @property
    def is_success(self) -> bool:
        """是否全部成功"""
        return all(s.status == SpanStatus.OK for s in self.spans)

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典"""
        return {
            "trace_id": self.trace_id,
            "duration_ms": self.duration_ms,
            "span_count": len(self.spans),
            "spans": [
                {
                    "span_id": s.span_id,
                    "parent_id": s.parent_id,
                    "name": s.name,
                    "kind": s.kind.value,
                    "duration_ms": s.duration_ms,
                    "status": s.status.value,
                    "attributes": s.attributes,
                    "events": s.events,
                }
                for s in self.spans
            ],
            "metadata": self.metadata,
        }


# ── Tracer 主类 ─────────────────────────────────────────────


class Tracer:
    """链路追踪器

    负责创建和管理 Trace/Span，支持嵌套 Span。
    """

    def __init__(self) -> None:
        self._traces: dict[str, Trace] = {}
        self._active_spans: dict[str, Span] = {}
        self._logger = logger.bind(service="tracer")

    def start_trace(self, trace_id: str | None = None, metadata: dict[str, Any] | None = None) -> Trace:
        """开始一个新的 Trace"""
        trace = Trace(
            trace_id=trace_id or uuid.uuid4().hex,
            metadata=metadata or {},
        )
        self._traces[trace.trace_id] = trace
        self._logger.info("trace_started", trace_id=trace.trace_id)
        return trace

    def start_span(
        self,
        name: str,
        kind: SpanKind = SpanKind.CUSTOM,
        parent_id: str | None = None,
        trace_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> Span:
        """开始一个新的 Span"""
        span = Span(
            trace_id=trace_id or "",
            name=name,
            kind=kind,
            parent_id=parent_id,
            attributes=attributes or {},
        )
        self._active_spans[span.span_id] = span
        # 自动关联到 Trace
        if trace_id and trace_id in self._traces:
            self._traces[trace_id].add_span(span)
        return span

    def finish_span(self, span_id: str, status: SpanStatus = SpanStatus.OK) -> Span | None:
        """结束 Span"""
        span = self._active_spans.pop(span_id, None)
        if span:
            span.finish(status)
        return span

    def finish_trace(self, trace_id: str) -> Trace | None:
        """结束 Trace"""
        trace = self._traces.get(trace_id)
        if trace:
            trace.finish()
            self._logger.info(
                "trace_finished",
                trace_id=trace_id,
                duration_ms=trace.duration_ms,
                span_count=len(trace.spans),
            )
        return trace

    def get_trace(self, trace_id: str) -> Trace | None:
        """获取指定 Trace"""
        return self._traces.get(trace_id)

    def list_traces(self) -> list[Trace]:
        """列出所有 Trace"""
        return list(self._traces.values())

    def clear(self) -> None:
        """清空所有追踪数据"""
        self._traces.clear()
        self._active_spans.clear()

    # ── 上下文管理器支持 ──────────────────────────────────

    def span(
        self,
        name: str,
        kind: SpanKind = SpanKind.CUSTOM,
        trace_id: str | None = None,
        parent_id: str | None = None,
    ) -> SpanContext:
        """创建 Span 上下文管理器"""
        return SpanContext(self, name, kind, trace_id, parent_id)


class SpanContext:
    """Span 上下文管理器

    支持 with 语句自动开始和结束 Span。
    """

    def __init__(
        self,
        tracer: Tracer,
        name: str,
        kind: SpanKind,
        trace_id: str | None,
        parent_id: str | None,
    ) -> None:
        self.tracer = tracer
        self.name = name
        self.kind = kind
        self.trace_id = trace_id
        self.parent_id = parent_id
        self.span: Span | None = None

    async def __aenter__(self) -> Span:
        self.span = self.tracer.start_span(
            name=self.name,
            kind=self.kind,
            trace_id=self.trace_id,
            parent_id=self.parent_id,
        )
        return self.span

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self.span:
            status = SpanStatus.ERROR if exc_type else SpanStatus.OK
            self.tracer.finish_span(self.span.span_id, status)

    def __enter__(self) -> Span:
        self.span = self.tracer.start_span(
            name=self.name,
            kind=self.kind,
            trace_id=self.trace_id,
            parent_id=self.parent_id,
        )
        return self.span

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self.span:
            status = SpanStatus.ERROR if exc_type else SpanStatus.OK
            self.tracer.finish_span(self.span.span_id, status)
