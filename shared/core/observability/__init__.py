"""
云汐可观测性模块
统一日志、链路追踪、监控指标

核心功能：
- UnifiedLogger: 统一结构化日志（JSON/文本格式、敏感字段脱敏、多输出目标）
- TraceContext / Span: 全链路追踪（trace_id、span_id、跨模块传播）
- ObservabilityMiddleware: FastAPI 可观测性中间件（请求日志、追踪、指标、慢请求告警）
- MetricsCollector: 监控指标收集（Counter/Gauge/Histogram、Prometheus 格式）

快速开始：
    from shared.core.observability import get_logger, init_module_logger
    from shared.core.observability import start_trace, start_span, get_trace_headers
    from shared.core.observability import ObservabilityMiddleware

    # 1. 初始化模块日志
    logger = init_module_logger("m8")

    # 2. 在 FastAPI 中注册中间件
    app.add_middleware(ObservabilityMiddleware, service_name="m8")

    # 3. 跨模块调用传递 trace_id
    headers = get_trace_headers()
    response = httpx.get(url, headers=headers)
"""
from .unified_logger import (
    UnifiedLogger,
    get_logger,
    set_log_context,
    clear_log_context,
    get_log_context,
    init_module_logger,
    set_global_level,
    mask_sensitive_data,
    SENSITIVE_FIELDS,
    JsonFormatter,
    TextFormatter,
    RedisLogHandler,
    ContextFilter,
)
from .tracing import (
    TraceContext,
    Span,
    get_trace_id,
    get_span_id,
    get_current_trace,
    start_trace,
    end_trace,
    start_span,
    end_span,
    get_trace_headers,
    extract_trace_headers,
    extract_span_headers,
    set_trace_attribute,
)
from .metrics import MetricsCollector, Counter, Gauge, Histogram, get_metrics
from .fastapi_middleware import (
    ObservabilityMiddleware,
    RequestLoggingMiddleware,
    MetricsEndpoint,
)

__all__ = [
    # ---- Logger ----
    "UnifiedLogger",
    "get_logger",
    "set_log_context",
    "clear_log_context",
    "get_log_context",
    "init_module_logger",
    "set_global_level",
    "mask_sensitive_data",
    "SENSITIVE_FIELDS",
    "JsonFormatter",
    "TextFormatter",
    "RedisLogHandler",
    "ContextFilter",
    # ---- Tracing ----
    "TraceContext",
    "Span",
    "get_trace_id",
    "get_span_id",
    "get_current_trace",
    "start_trace",
    "end_trace",
    "start_span",
    "end_span",
    "get_trace_headers",
    "extract_trace_headers",
    "extract_span_headers",
    "set_trace_attribute",
    # ---- Metrics ----
    "MetricsCollector",
    "Counter",
    "Gauge",
    "Histogram",
    "get_metrics",
    # ---- Middleware ----
    "ObservabilityMiddleware",
    "RequestLoggingMiddleware",
    "MetricsEndpoint",
]
