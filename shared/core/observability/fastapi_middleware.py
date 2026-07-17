"""
云汐可观测性 FastAPI 中间件

提供开箱即用的可观测性能力：
- 请求追踪（自动生成/传播Trace ID）
- 请求指标（QPS、延迟、状态码分布）
- 日志上下文注入
"""
import time
from typing import Optional
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from .tracing import (
    start_trace,
    end_trace,
    start_span,
    end_span,
    extract_trace_headers,
    get_trace_id,
)
from .metrics import get_metrics
from .unified_logger import get_logger


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """可观测性中间件"""
    
    def __init__(
        self,
        app,
        service_name: str = "yunxi",
        enable_tracing: bool = True,
        enable_metrics: bool = True,
        enable_logging: bool = True,
        log_level: str = "INFO",
    ):
        super().__init__(app)
        self.service_name = service_name
        self.enable_tracing = enable_tracing
        self.enable_metrics = enable_metrics
        self.enable_logging = enable_logging
        
        if self.enable_logging:
            self.logger = get_logger(service_name, level=log_level)
        else:
            self.logger = None
        
        if self.enable_metrics:
            self.metrics = get_metrics()
            # 预注册常用指标
            self.metrics.counter(
                f"{service_name}_requests_total",
                help_text="Total number of HTTP requests",
            )
            self.metrics.counter(
                f"{service_name}_errors_total",
                help_text="Total number of error responses",
            )
            self.metrics.histogram(
                f"{service_name}_request_duration_seconds",
                help_text="HTTP request duration in seconds",
            )
    
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        method = request.method
        path = request.url.path
        
        # --- 追踪 ---
        trace_ctx = None
        if self.enable_tracing:
            # 从请求头提取Trace ID
            trace_id = extract_trace_headers(dict(request.headers))
            trace_ctx = start_trace(trace_id=trace_id)
            
            # 开始请求Span
            span = start_span(f"{method} {path}", method=method, path=path)
            
            # 注入到request state
            request.state.trace_id = trace_ctx.trace_id
            request.state.trace_context = trace_ctx
        
        # --- 日志上下文 ---
        if self.logger and trace_ctx:
            self.logger.set_context(
                trace_id=trace_ctx.trace_id,
                module_key=self.service_name,
            )
        
        try:
            # 处理请求
            response = await call_next(request)
            
            # 记录指标
            duration = time.time() - start_time
            status_code = response.status_code
            
            if self.enable_metrics:
                self.metrics.inc(
                    f"{self.service_name}_requests_total",
                    labels={"method": method, "status": str(status_code)},
                )
                self.metrics.observe(
                    f"{self.service_name}_request_duration_seconds",
                    duration,
                    labels={"method": method},
                )
                if status_code >= 400:
                    self.metrics.inc(
                        f"{self.service_name}_errors_total",
                        labels={"method": method, "status": str(status_code)},
                    )
            
            # 结束Span
            if self.enable_tracing and trace_ctx:
                end_span(span, status="ok")
            
            # 注入Trace ID到响应头
            if self.enable_tracing:
                response.headers["X-Trace-Id"] = get_trace_id() or ""
            
            # 访问日志
            if self.logger and self.enable_logging:
                self.logger.info(
                    f"{method} {path} {status_code} ({duration*1000:.2f}ms)",
                    method=method,
                    path=path,
                    status_code=status_code,
                    duration_ms=round(duration * 1000, 2),
                )
            
            return response
            
        except Exception as e:
            # 错误处理
            duration = time.time() - start_time
            
            if self.enable_metrics:
                self.metrics.inc(
                    f"{self.service_name}_errors_total",
                    labels={"method": method, "status": "500"},
                )
                self.metrics.observe(
                    f"{self.service_name}_request_duration_seconds",
                    duration,
                    labels={"method": method},
                )
            
            if self.enable_tracing and trace_ctx:
                end_span(span, status="error", error_message=str(e))
            
            if self.logger and self.enable_logging:
                self.logger.exception(
                    f"{method} {path} ERROR ({duration*1000:.2f}ms)",
                    method=method,
                    path=path,
                    duration_ms=round(duration * 1000, 2),
                )
            
            raise


class MetricsEndpoint:
    """
    指标端点（供Prometheus抓取）
    
    使用方法：
        app.add_route("/metrics", MetricsEndpoint())
    """
    
    async def __call__(self, request: Request) -> Response:
        metrics = get_metrics()
        return Response(
            content=metrics.to_prometheus(),
            media_type="text/plain; version=0.0.4",
        )
