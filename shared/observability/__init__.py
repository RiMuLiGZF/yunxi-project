"""
云汐可观测性模块
统一日志、追踪、监控
"""
from .unified_logger import UnifiedLogger, get_logger
from .tracing import (
    TraceContext,
    Span,
    get_trace_id,
    get_current_trace,
    start_trace,
    end_trace,
    start_span,
    end_span,
    get_trace_headers,
    extract_trace_headers,
)
from .metrics import MetricsCollector, Counter, Gauge, Histogram, get_metrics
from .fastapi_middleware import ObservabilityMiddleware, MetricsEndpoint

__all__ = [
    # Logger
    "UnifiedLogger",
    "get_logger",
    # Tracing
    "TraceContext",
    "Span",
    "get_trace_id",
    "get_current_trace",
    "start_trace",
    "end_trace",
    "start_span",
    "end_span",
    "get_trace_headers",
    "extract_trace_headers",
    # Metrics
    "MetricsCollector",
    "Counter",
    "Gauge",
    "Histogram",
    "get_metrics",
    # Middleware
    "ObservabilityMiddleware",
    "MetricsEndpoint",
]
