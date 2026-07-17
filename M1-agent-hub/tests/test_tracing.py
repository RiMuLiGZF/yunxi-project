"""Tracing 链路追踪系统单元测试"""
import sys
sys.path.insert(0, "/workspace/agent_cluster")
sys.path.insert(0, "/workspace")

import pytest
import time

from agent_cluster.observability.tracing import Tracer, SpanKind, SpanStatus, Trace, Span


def test_start_trace():
    tracer = Tracer()
    trace = tracer.start_trace()
    assert trace.trace_id
    assert trace.start_time > 0
    assert len(trace.spans) == 0


def test_start_and_finish_span():
    tracer = Tracer()
    trace = tracer.start_trace("t1")
    span = tracer.start_span("test_span", SpanKind.AGENT, trace_id="t1")
    assert span.span_id
    assert span.trace_id == "t1"
    assert span.kind == SpanKind.AGENT

    time.sleep(0.01)
    finished = tracer.finish_span(span.span_id)
    assert finished is not None
    assert finished.end_time is not None
    assert finished.duration_ms >= 10


def test_nested_spans():
    tracer = Tracer()
    trace = tracer.start_trace("t2")
    root = tracer.start_span("root", SpanKind.WORKFLOW, trace_id="t2")
    child = tracer.start_span("child", SpanKind.AGENT, parent_id=root.span_id, trace_id="t2")

    assert child.parent_id == root.span_id
    tracer.finish_span(child.span_id)
    tracer.finish_span(root.span_id)
    trace.add_span(root)
    trace.add_span(child)
    assert len(trace.spans) == 2


def test_span_events_and_attributes():
    span = Span(name="test", kind=SpanKind.TOOL)
    span.set_attribute("model", "gpt-4")
    span.add_event("token_usage", {"tokens": 150})
    span.finish()

    assert span.attributes["model"] == "gpt-4"
    assert len(span.events) == 1
    assert span.events[0]["name"] == "token_usage"


def test_trace_success_status():
    tracer = Tracer()
    trace = tracer.start_trace("t3")
    s1 = tracer.start_span("ok1", SpanKind.AGENT, trace_id="t3")
    tracer.finish_span(s1.span_id, SpanStatus.OK)
    trace.add_span(s1)
    assert trace.is_success


def test_trace_error_status():
    tracer = Tracer()
    trace = tracer.start_trace("t4")
    s1 = tracer.start_span("err1", SpanKind.AGENT, trace_id="t4")
    tracer.finish_span(s1.span_id, SpanStatus.ERROR)
    trace.add_span(s1)
    assert not trace.is_success


def test_trace_to_dict():
    tracer = Tracer()
    trace = tracer.start_trace("t5")
    s1 = tracer.start_span("span1", SpanKind.AGENT, trace_id="t5")
    tracer.finish_span(s1.span_id)
    trace.add_span(s1)
    trace.finish()

    d = trace.to_dict()
    assert d["trace_id"] == "t5"
    assert d["span_count"] == 1
    assert "duration_ms" in d


def test_get_trace():
    tracer = Tracer()
    tracer.start_trace("my_trace")
    found = tracer.get_trace("my_trace")
    assert found is not None
    assert tracer.get_trace("not_exist") is None


def test_list_traces():
    tracer = Tracer()
    tracer.start_trace("a")
    tracer.start_trace("b")
    assert len(tracer.list_traces()) == 2


def test_clear():
    tracer = Tracer()
    tracer.start_trace("x")
    tracer.clear()
    assert len(tracer.list_traces()) == 0
    assert len(tracer._active_spans) == 0


def test_span_context_manager_sync():
    tracer = Tracer()
    trace = tracer.start_trace("t_ctx")
    with tracer.span("sync_span", SpanKind.CUSTOM, trace_id="t_ctx") as span:
        assert span.name == "sync_span"
    # 退出后 span 应被 finish
    assert span.end_time is not None


@pytest.mark.asyncio
async def test_span_context_manager_async():
    tracer = Tracer()
    trace = tracer.start_trace("t_ctx_async")
    async with tracer.span("async_span", SpanKind.CUSTOM, trace_id="t_ctx_async") as span:
        assert span.name == "async_span"
    assert span.end_time is not None


@pytest.mark.asyncio
async def test_span_context_manager_error():
    tracer = Tracer()
    trace = tracer.start_trace("t_err")
    span = None
    try:
        async with tracer.span("fail_span", SpanKind.AGENT, trace_id="t_err") as s:
            span = s
            raise ValueError("boom")
    except ValueError:
        pass
    assert span is not None
    assert span.status == SpanStatus.ERROR
