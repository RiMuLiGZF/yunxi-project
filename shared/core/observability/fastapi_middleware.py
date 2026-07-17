"""
云汐可观测性 FastAPI 中间件

提供开箱即用的可观测性能力：
- 请求追踪（自动生成/传播 Trace ID，支持 Span）
- 请求日志（方法、路径、状态码、耗时、IP、User-Agent）
- 慢请求告警（可配置阈值，默认 3s）
- 错误请求详细记录（请求体、错误栈）
- 健康检查路径可配置排除
- 日志上下文自动注入
- 指标统计（QPS、延迟、状态码分布）

使用方式：
    from shared.core.observability import ObservabilityMiddleware

    app = FastAPI()
    app.add_middleware(
        ObservabilityMiddleware,
        service_name="m8",
        slow_request_threshold=3.0,
        exclude_paths=["/health", "/metrics"],
    )
"""
import time
import json
import traceback
from typing import Optional, List, Set
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
    get_span_id,
)
from .unified_logger import get_logger, set_log_context, get_log_context
from .metrics import get_metrics


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """可观测性中间件（增强版）

    集成链路追踪、请求日志、慢请求告警、错误记录等功能。

    Args:
        app: FastAPI 应用实例
        service_name: 服务名称（用于日志和指标前缀）
        log_level: 日志级别
        enable_tracing: 是否启用链路追踪
        enable_request_log: 是否启用请求日志
        enable_metrics: 是否启用指标统计
        slow_request_threshold: 慢请求阈值（秒），默认 3 秒
        exclude_paths: 排除的路径列表（不记录日志和追踪），如 ["/health", "/metrics"]
        log_request_body: 是否记录请求体（仅错误时）
        log_response_body: 是否记录响应体（仅错误时）
        max_body_log_size: 请求体/响应体最大记录大小（字节）
    """

    def __init__(
        self,
        app,
        service_name: str = "yunxi",
        log_level: str = "INFO",
        enable_tracing: bool = True,
        enable_request_log: bool = True,
        enable_metrics: bool = True,
        slow_request_threshold: float = 3.0,
        exclude_paths: Optional[List[str]] = None,
        log_request_body: bool = True,
        log_response_body: bool = False,
        max_body_log_size: int = 4096,
    ):
        super().__init__(app)
        self.service_name = service_name
        self.enable_tracing = enable_tracing
        self.enable_request_log = enable_request_log
        self.enable_metrics = enable_metrics
        self.slow_request_threshold = slow_request_threshold
        self.exclude_paths: Set[str] = set(exclude_paths or ["/health", "/metrics"])
        self.log_request_body = log_request_body
        self.log_response_body = log_response_body
        self.max_body_log_size = max_body_log_size

        # 初始化日志器
        self.logger = get_logger(
            f"yunxi.{service_name}",
            level=log_level,
        )

        # 初始化指标
        if self.enable_metrics:
            self.metrics = get_metrics()
            self._init_metrics()

    def _init_metrics(self):
        """预注册指标"""
        prefix = self.service_name
        self.metrics.counter(
            f"{prefix}_requests_total",
            help_text="Total number of HTTP requests",
        )
        self.metrics.counter(
            f"{prefix}_errors_total",
            help_text="Total number of error responses",
        )
        self.metrics.counter(
            f"{prefix}_slow_requests_total",
            help_text="Total number of slow requests",
        )
        self.metrics.histogram(
            f"{prefix}_request_duration_seconds",
            help_text="HTTP request duration in seconds",
        )

    def _should_exclude(self, path: str) -> bool:
        """判断路径是否应该被排除"""
        return path in self.exclude_paths

    async def _read_body_safely(self, request: Request) -> bytes:
        """安全读取请求体（不影响后续处理）"""
        try:
            body = await request.body()
            return body
        except Exception:
            return b""

    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        method = request.method
        path = request.url.path

        # 排除健康检查等路径
        if self._should_exclude(path):
            return await call_next(request)

        # 获取客户端 IP 和 User-Agent
        client_ip = self._get_client_ip(request)
        user_agent = request.headers.get("user-agent", "")

        # --- 链路追踪 ---
        trace_ctx = None
        request_span = None
        if self.enable_tracing:
            # 从请求头提取 Trace ID
            trace_id = extract_trace_headers(dict(request.headers))
            trace_ctx = start_trace(
                trace_id=trace_id,
                module_key=self.service_name,
            )

            # 开始请求级 Span
            request_span = start_span(
                f"{method} {path}",
                method=method,
                path=path,
                client_ip=client_ip,
            )

            # 注入到 request.state
            request.state.trace_id = trace_ctx.trace_id
            request.state.trace_context = trace_ctx
            request.state.span_id = request_span.span_id

        # --- 日志上下文 ---
        if self.enable_request_log:
            ctx_updates = {
                "method": method,
                "path": path,
                "client_ip": client_ip,
            }
            if trace_ctx:
                ctx_updates["trace_id"] = trace_ctx.trace_id
            set_log_context(**ctx_updates)

        request_body = None
        try:
            # 处理请求
            response = await call_next(request)

            # 计算耗时
            duration = time.time() - start_time
            status_code = response.status_code

            # --- 指标统计 ---
            if self.enable_metrics:
                self._record_metrics(method, path, status_code, duration)

            # --- 结束追踪 Span ---
            if self.enable_tracing and request_span:
                request_span.set_attribute("status_code", status_code)
                if status_code >= 400:
                    end_span(request_span, status="error",
                             error_message=f"HTTP {status_code}")
                else:
                    end_span(request_span, status="ok")

            # --- 注入 Trace ID 到响应头 ---
            if self.enable_tracing:
                response.headers["X-Trace-Id"] = get_trace_id() or ""
                current_span_id = get_span_id()
                if current_span_id:
                    response.headers["X-Span-Id"] = current_span_id

            # --- 请求日志 ---
            if self.enable_request_log:
                self._log_request(
                    method=method,
                    path=path,
                    status_code=status_code,
                    duration=duration,
                    client_ip=client_ip,
                    user_agent=user_agent,
                )

            # --- 慢请求告警 ---
            if duration >= self.slow_request_threshold:
                self._log_slow_request(
                    method=method,
                    path=path,
                    duration=duration,
                    status_code=status_code,
                    client_ip=client_ip,
                )
                if self.enable_metrics:
                    self.metrics.inc(
                        f"{self.service_name}_slow_requests_total",
                        labels={"method": method, "path": path},
                    )

            return response

        except Exception as e:
            # 错误处理
            duration = time.time() - start_time

            # 读取请求体（用于错误日志）
            if self.log_request_body:
                request_body = await self._read_body_safely(request)

            # --- 指标 ---
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

            # --- 结束追踪 ---
            if self.enable_tracing and request_span:
                end_span(request_span, status="error", error_message=str(e))

            # --- 错误日志 ---
            if self.enable_request_log:
                self._log_error(
                    method=method,
                    path=path,
                    duration=duration,
                    error=e,
                    client_ip=client_ip,
                    user_agent=user_agent,
                    request_body=request_body,
                )

            raise

    def _record_metrics(self, method: str, path: str, status_code: int, duration: float):
        """记录请求指标"""
        prefix = self.service_name
        self.metrics.inc(
            f"{prefix}_requests_total",
            labels={"method": method, "status": str(status_code)},
        )
        self.metrics.observe(
            f"{prefix}_request_duration_seconds",
            duration,
            labels={"method": method},
        )
        if status_code >= 400:
            self.metrics.inc(
                f"{prefix}_errors_total",
                labels={"method": method, "status": str(status_code)},
            )

    def _log_request(
        self,
        method: str,
        path: str,
        status_code: int,
        duration: float,
        client_ip: str,
        user_agent: str,
    ):
        """记录请求日志"""
        duration_ms = round(duration * 1000, 2)

        log_kwargs = {
            "method": method,
            "path": path,
            "status_code": status_code,
            "duration_ms": duration_ms,
            "client_ip": client_ip,
            "user_agent": user_agent[:200] if user_agent else "",
        }

        message = f"{method} {path} {status_code} ({duration_ms}ms)"

        if status_code >= 500:
            self.logger.error(message, **log_kwargs)
        elif status_code >= 400:
            self.logger.warning(message, **log_kwargs)
        else:
            self.logger.info(message, **log_kwargs)

    def _log_slow_request(
        self,
        method: str,
        path: str,
        duration: float,
        status_code: int,
        client_ip: str,
    ):
        """记录慢请求告警"""
        duration_ms = round(duration * 1000, 2)
        self.logger.warning(
            f"SLOW REQUEST: {method} {path} took {duration_ms}ms "
            f"(threshold: {self.slow_request_threshold * 1000:.0f}ms)",
            method=method,
            path=path,
            duration_ms=duration_ms,
            status_code=status_code,
            client_ip=client_ip,
            threshold_ms=self.slow_request_threshold * 1000,
            slow_request=True,
        )

    def _log_error(
        self,
        method: str,
        path: str,
        duration: float,
        error: Exception,
        client_ip: str,
        user_agent: str,
        request_body: Optional[bytes] = None,
    ):
        """记录错误请求详细信息"""
        duration_ms = round(duration * 1000, 2)
        error_stack = traceback.format_exc()

        log_kwargs = {
            "method": method,
            "path": path,
            "duration_ms": duration_ms,
            "client_ip": client_ip,
            "user_agent": user_agent[:200] if user_agent else "",
            "error_type": type(error).__name__,
            "error_message": str(error),
            "error_stack": error_stack,
        }

        # 记录请求体（截断 + 脱敏）
        if request_body:
            try:
                body_str = request_body.decode("utf-8", errors="replace")
                if len(body_str) > self.max_body_log_size:
                    body_str = body_str[:self.max_body_log_size] + "...[truncated]"
                # 尝试 JSON 解析后脱敏
                try:
                    body_json = json.loads(body_str)
                    from .unified_logger import mask_sensitive_data
                    log_kwargs["request_body"] = mask_sensitive_data(body_json)
                except (json.JSONDecodeError, ValueError):
                    log_kwargs["request_body"] = body_str
            except Exception:
                log_kwargs["request_body"] = "[unreadable]"

        self.logger.error(
            f"REQUEST FAILED: {method} {path} - {type(error).__name__}: {error}",
            **log_kwargs,
        )

    @staticmethod
    def _get_client_ip(request: Request) -> str:
        """获取客户端真实 IP

        优先读取 X-Forwarded-For，其次 X-Real-IP，最后直接连接 IP。
        """
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()

        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip

        if request.client:
            return request.client.host
        return "unknown"


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    轻量级请求日志中间件（仅日志，无追踪/指标）

    适用于不需要完整可观测性、只需要请求日志的场景。
    """

    def __init__(
        self,
        app,
        service_name: str = "yunxi",
        slow_threshold: float = 3.0,
        exclude_paths: Optional[List[str]] = None,
    ):
        super().__init__(app)
        self.service_name = service_name
        self.slow_threshold = slow_threshold
        self.exclude_paths = set(exclude_paths or ["/health", "/metrics"])
        self.logger = get_logger(f"yunxi.{service_name}.access")

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self.exclude_paths:
            return await call_next(request)

        start = time.time()
        method = request.method
        path = request.url.path
        client_ip = ObservabilityMiddleware._get_client_ip(request)

        try:
            response = await call_next(request)
            elapsed = time.time() - start
            elapsed_ms = round(elapsed * 1000, 2)
            status = response.status_code

            self.logger.info(
                f"{method} {path} {status} ({elapsed_ms}ms)",
                method=method,
                path=path,
                status_code=status,
                duration_ms=elapsed_ms,
                client_ip=client_ip,
            )

            if elapsed >= self.slow_threshold:
                self.logger.warning(
                    f"Slow request: {method} {path} ({elapsed_ms}ms)",
                    method=method, path=path,
                    duration_ms=elapsed_ms,
                    slow=True,
                )

            return response
        except Exception as e:
            elapsed = time.time() - start
            self.logger.error(
                f"Request error: {method} {path} - {e}",
                method=method, path=path,
                duration_ms=round(elapsed * 1000, 2),
                error=str(e),
                exc_info=True,
            )
            raise


class MetricsEndpoint:
    """
    指标端点（供 Prometheus 抓取）

    使用方法：
        app.add_route("/metrics", MetricsEndpoint())
    """

    async def __call__(self, request: Request) -> Response:
        metrics = get_metrics()
        return Response(
            content=metrics.to_prometheus(),
            media_type="text/plain; version=0.0.4",
        )
