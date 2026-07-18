"""直接运行可观测性测试（不通过pytest）"""
import sys
import os
import time
from shared.observability import (
    UnifiedLogger,
    get_logger,
    TraceContext,
    Span,
    start_trace,
    end_trace,
    start_span,
    end_span,
    get_trace_id,
    get_current_trace,
    MetricsCollector,
    Counter,
    Gauge,
    Histogram,
    get_metrics,
)

passed = 0
failed = 0

def test(name, fn):
    global passed, failed
    try:
        fn()
        print(f"  ✓ {name}")
        passed += 1
    except Exception as e:
        print(f"  ✗ {name}: {e}")
        import traceback
        traceback.print_exc()
        failed += 1


print("=== UnifiedLogger Tests ===")

def test_logger_creation():
    logger = get_logger("test_logger_1")
    assert logger is not None
    assert logger.name == "test_logger_1"
test("logger creation", test_logger_creation)

def test_logger_singleton():
    l1 = get_logger("test_singleton")
    l2 = get_logger("test_singleton")
    assert l1 is l2
test("logger singleton", test_logger_singleton)

def test_log_levels():
    logger = get_logger("test_levels")
    logger.set_level("DEBUG")
    assert logger.level == 10
    logger.set_level("INFO")
    assert logger.level == 20
test("log levels", test_log_levels)

def test_context_injection():
    logger = get_logger("test_context")
    logger.set_context(user_id="u1", trace_id="t1")
    assert logger._context["user_id"] == "u1"
    logger.clear_context()
    assert len(logger._context) == 0
test("context injection", test_context_injection)


print("\n=== Tracing Tests ===")

def test_trace_creation():
    trace = TraceContext()
    assert trace.trace_id is not None
    assert len(trace.trace_id) == 32
test("trace creation", test_trace_creation)

def test_custom_trace_id():
    trace = TraceContext(trace_id="custom-123")
    assert trace.trace_id == "custom-123"
test("custom trace id", test_custom_trace_id)

def test_span_creation():
    trace = TraceContext()
    span = trace.start_span("test_op")
    assert span.name == "test_op"
    assert span.trace_id == trace.trace_id
    assert span.status == "running"
test("span creation", test_span_creation)

def test_span_end():
    trace = TraceContext()
    span = trace.start_span("op")
    time.sleep(0.01)
    trace.end_span(span)
    assert span.status == "ok"
    assert span.duration_ms > 0
test("span end", test_span_end)

def test_nested_spans():
    trace = TraceContext()
    outer = trace.start_span("outer")
    inner = trace.start_span("inner")
    assert inner.parent_span_id == outer.span_id
    trace.end_span(inner)
    trace.end_span(outer)
    assert len(trace.spans) == 2
test("nested spans", test_nested_spans)

def test_trace_summary():
    trace = TraceContext()
    span = trace.start_span("op1")
    trace.end_span(span)
    s = trace.get_trace_summary()
    assert s["span_count"] == 1
    assert s["completed_count"] == 1
test("trace summary", test_trace_summary)

def test_context_var():
    trace = start_trace("ctx-test")
    assert get_trace_id() == "ctx-test"
    assert get_current_trace() is trace
    summary = end_trace()
    assert summary is not None
    assert get_current_trace() is None
test("context var", test_context_var)


print("\n=== Metrics Tests ===")

def test_counter():
    c = Counter(name="test")
    assert c.value() == 0
    c.inc()
    assert c.value() == 1
    c.inc(5)
    assert c.value() == 6
    c.reset()
    assert c.value() == 0
test("counter", test_counter)

def test_gauge():
    g = Gauge(name="test")
    g.set(100)
    assert g.value() == 100
    g.inc(10)
    assert g.value() == 110
    g.dec(30)
    assert g.value() == 80
test("gauge", test_gauge)

def test_histogram():
    h = Histogram(name="test")
    h.observe(0.1)
    h.observe(0.5)
    h.observe(1.5)
    val = h.value()
    assert val["count"] == 3
    assert abs(val["sum"] - 2.1) < 0.01
test("histogram", test_histogram)

def test_collector():
    mc = MetricsCollector()
    mc.inc("req_total", labels={"method": "GET"})
    mc.inc("req_total", labels={"method": "POST"})
    all_m = mc.get_all()
    assert all_m["total_metrics"] == 2
test("collector counter", test_collector)

def test_prometheus():
    mc = MetricsCollector()
    mc.inc("test_req", 10, labels={"status": "200"})
    mc.set_gauge("test_active", 5)
    out = mc.to_prometheus()
    assert "test_req" in out
    assert "test_active" in out
    assert "TYPE" in out
test("prometheus format", test_prometheus)

def test_global_metrics():
    m = get_metrics()
    assert m is not None
    m2 = get_metrics()
    assert m is m2
test("global metrics singleton", test_global_metrics)


print(f"\n{'='*50}")
print(f"结果: {passed} 通过, {failed} 失败")
if failed == 0:
    print("✓ 所有测试通过!")
else:
    print("✗ 有测试失败")
    sys.exit(1)
