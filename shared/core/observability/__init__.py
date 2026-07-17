"""
云汐可观测性模块
统一日志、链路追踪、监控指标、健康检查

核心功能：
- UnifiedLogger: 统一结构化日志（JSON/文本格式、敏感字段脱敏、多输出目标）
- TraceContext / Span: 全链路追踪（trace_id、span_id、跨模块传播）
- ObservabilityMiddleware: FastAPI 可观测性中间件（请求日志、追踪、指标、慢请求告警）
- MetricsCollector: 监控指标收集（Counter/Gauge/Histogram/Summary、Prometheus 格式）
- HealthChecker: 标准化健康检查（轻量/深度检查、依赖检查、状态汇总）
- create_observability_router: 一键创建 /health + /metrics 端点

快速开始：
    from shared.core.observability import get_logger, init_module_logger
    from shared.core.observability import start_trace, start_span, get_trace_headers
    from shared.core.observability import ObservabilityMiddleware
    from shared.core.observability import create_observability_router

    # 1. 初始化模块日志
    logger = init_module_logger("m8")

    # 2. 在 FastAPI 中注册中间件
    app.add_middleware(ObservabilityMiddleware, service_name="m8")

    # 3. 注册可观测性路由（健康检查 + 指标）
    obs_router = create_observability_router(
        service_name="m8",
        version="1.0.0",
        db_session_factory=SessionLocal,
    )
    app.include_router(obs_router)

    # 4. 跨模块调用传递 trace_id
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
from .metrics import (
    MetricsCollector,
    Counter,
    Gauge,
    Histogram,
    Summary,
    get_metrics,
    reset_metrics,
    DEFAULT_BUCKETS,
    HTTP_BUCKETS,
    DB_BUCKETS,
)
from .health import (
    HealthChecker,
    HealthStatus,
    HealthResponse,
    CheckResult,
    check_memory,
    check_disk,
    check_database_sqlalchemy,
    check_redis,
    check_http_endpoint,
    get_health_checker,
    set_health_checker,
    create_fastapi_health_router,
)
from .fastapi_middleware import (
    ObservabilityMiddleware,
    RequestLoggingMiddleware,
    MetricsEndpoint,
    create_observability_router,
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
    "Summary",
    "get_metrics",
    "reset_metrics",
    "DEFAULT_BUCKETS",
    "HTTP_BUCKETS",
    "DB_BUCKETS",
    # ---- Health ----
    "HealthChecker",
    "HealthStatus",
    "HealthResponse",
    "CheckResult",
    "check_memory",
    "check_disk",
    "check_database_sqlalchemy",
    "check_redis",
    "check_http_endpoint",
    "get_health_checker",
    "set_health_checker",
    "create_fastapi_health_router",
    # ---- Middleware ----
    "ObservabilityMiddleware",
    "RequestLoggingMiddleware",
    "MetricsEndpoint",
    "create_observability_router",
]
