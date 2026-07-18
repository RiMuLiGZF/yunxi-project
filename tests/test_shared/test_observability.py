"""
可观测性模块单元测试
"""
import pytest
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


class TestUnifiedLogger:
    """统一日志系统测试"""
    
    def test_logger_creation(self):
        """测试日志器创建"""
        logger = get_logger("test_logger_1")
        assert logger is not None
        assert logger.name == "test_logger_1"
    
    def test_logger_singleton(self):
        """测试单例模式"""
        logger1 = get_logger("test_singleton")
        logger2 = get_logger("test_singleton")
        assert logger1 is logger2
    
    def test_log_levels(self):
        """测试日志级别"""
        logger = get_logger("test_levels")
        logger.set_level("DEBUG")
        assert logger.level == 10  # DEBUG
        logger.set_level("INFO")
        assert logger.level == 20  # INFO
        logger.set_level("WARNING")
        assert logger.level == 30  # WARNING
    
    def test_log_output(self, capsys):
        """测试日志输出"""
        logger = get_logger("test_output")
        logger.info("Test message 123")
        captured = capsys.readouterr()
        assert "Test message 123" in captured.out
    
    def test_context_injection(self):
        """测试上下文注入"""
        logger = get_logger("test_context")
        logger.set_context(user_id="test_user", trace_id="abc123")
        assert logger._context["user_id"] == "test_user"
        assert logger._context["trace_id"] == "abc123"
        logger.clear_context()
        assert len(logger._context) == 0


class TestTracing:
    """链路追踪测试"""
    
    def test_trace_creation(self):
        """测试追踪创建"""
        trace = TraceContext()
        assert trace.trace_id is not None
        assert len(trace.trace_id) == 32  # hex uuid
    
    def test_trace_with_custom_id(self):
        """测试自定义Trace ID"""
        trace = TraceContext(trace_id="custom-trace-id-123")
        assert trace.trace_id == "custom-trace-id-123"
    
    def test_span_creation(self):
        """测试Span创建"""
        trace = TraceContext()
        span = trace.start_span("test_operation")
        assert span.name == "test_operation"
        assert span.trace_id == trace.trace_id
        assert span.status == "running"
        assert span.start_time > 0
    
    def test_span_end(self):
        """测试Span结束"""
        trace = TraceContext()
        span = trace.start_span("test_op")
        time.sleep(0.01)
        trace.end_span(span)
        assert span.status == "ok"
        assert span.end_time is not None
        assert span.duration_ms > 0
    
    def test_nested_spans(self):
        """测试嵌套Span"""
        trace = TraceContext()
        outer = trace.start_span("outer")
        inner = trace.start_span("inner")
        assert inner.parent_span_id == outer.span_id
        trace.end_span(inner)
        trace.end_span(outer)
        assert len(trace.spans) == 2
    
    def test_trace_summary(self):
        """测试追踪摘要"""
        trace = TraceContext()
        span = trace.start_span("op1")
        trace.end_span(span)
        summary = trace.get_trace_summary()
        assert summary["trace_id"] == trace.trace_id
        assert summary["span_count"] == 1
        assert summary["completed_count"] == 1
        assert "total_duration_ms" in summary
    
    def test_context_var_trace(self):
        """测试上下文变量追踪"""
        trace = start_trace("ctx-test-1")
        assert get_trace_id() == "ctx-test-1"
        assert get_current_trace() is trace
        summary = end_trace()
        assert summary is not None
        assert get_current_trace() is None
    
    def test_start_span_without_trace(self):
        """测试没有活动追踪时创建Span（自动创建）"""
        # 确保没有活动追踪
        end_trace()
        span = start_span("auto_trace_span")
        assert span is not None
        assert get_current_trace() is not None
        end_span(span)
        end_trace()


class TestMetrics:
    """监控指标测试"""
    
    def test_counter(self):
        """测试计数器"""
        c = Counter(name="test_counter")
        assert c.value() == 0
        c.inc()
        assert c.value() == 1
        c.inc(5)
        assert c.value() == 6
        c.reset()
        assert c.value() == 0
    
    def test_gauge(self):
        """测试仪表盘"""
        g = Gauge(name="test_gauge")
        g.set(100)
        assert g.value() == 100
        g.inc(10)
        assert g.value() == 110
        g.dec(30)
        assert g.value() == 80
    
    def test_histogram(self):
        """测试直方图"""
        h = Histogram(name="test_hist")
        h.observe(0.1)
        h.observe(0.5)
        h.observe(1.5)
        val = h.value()
        assert val["count"] == 3
        assert val["sum"] == pytest.approx(2.1, 0.01)
    
    def test_collector_counter(self):
        """测试收集器计数器"""
        mc = MetricsCollector()
        mc.inc("requests_total", labels={"method": "GET"})
        mc.inc("requests_total", labels={"method": "POST"})
        mc.inc("requests_total", labels={"method": "GET"})
        all_metrics = mc.get_all()
        assert all_metrics["total_metrics"] == 2  # 两个不同标签
    
    def test_collector_gauge(self):
        """测试收集器仪表盘"""
        mc = MetricsCollector()
        mc.set_gauge("active_users", 42)
        all_metrics = mc.get_all()
        assert "active_users" in str(all_metrics["gauges"])
    
    def test_prometheus_format(self):
        """测试Prometheus格式输出"""
        mc = MetricsCollector()
        mc.inc("test_requests_total", 10, labels={"status": "200"})
        mc.set_gauge("test_active", 5)
        output = mc.to_prometheus()
        assert "test_requests_total" in output
        assert "test_active" in output
        assert "TYPE" in output
    
    def test_global_metrics(self):
        """测试全局指标收集器"""
        m = get_metrics()
        assert m is not None
        m2 = get_metrics()
        assert m is m2  # 单例


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
