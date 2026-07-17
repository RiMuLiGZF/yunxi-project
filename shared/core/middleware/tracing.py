"""
云汐系统 - 请求追踪中间件（向后兼容层）

.. deprecated:: 1.0.0
   模块已迁移至 `shared.core.observability`。
   旧路径 ``shared.core.middleware.tracing`` 将在未来版本中移除。

推荐用法：
    from shared.core.observability import ObservabilityMiddleware, get_trace_id

说明：
   本文件为向后兼容层，旧的 TracingMiddleware 仍然可用，
   新代码请直接使用 ObservabilityMiddleware，它集成了追踪、日志和指标。
"""

from __future__ import annotations

import warnings as _warnings

_warnings.warn(
    f"模块 {__name__} 已迁移至 shared.core.observability。"
    f"请更新 import 路径为 'from shared.core.observability import ...'。"
    f"旧路径将在未来版本中移除。",
    DeprecationWarning,
    stacklevel=2,
)

# 从 observability 模块 re-export
try:
    from shared.core.observability import (
        ObservabilityMiddleware,
        RequestLoggingMiddleware,
        get_trace_id,
        get_span_id,
        start_trace,
        end_trace,
        start_span,
        end_span,
        get_trace_headers,
        extract_trace_headers,
    )

    # 兼容旧名称
    TracingMiddleware = ObservabilityMiddleware
    get_request_id = get_trace_id  # 兼容旧接口

    __all__ = [
        "TracingMiddleware",
        "ObservabilityMiddleware",
        "RequestLoggingMiddleware",
        "get_trace_id",
        "get_span_id",
        "get_request_id",
        "start_trace",
        "end_trace",
        "start_span",
        "end_span",
        "get_trace_headers",
        "extract_trace_headers",
    ]
except ImportError:
    # 如果 observability 不可用，提供最小实现
    import uuid
    import time
    from typing import Optional, Awaitable, Callable
    from fastapi import Request, Response
    from starlette.middleware.base import BaseHTTPMiddleware

    class TracingMiddleware(BaseHTTPMiddleware):
        """请求追踪中间件（最小兼容实现）"""

        def __init__(self, app, trace_id_header: str = "x-trace-id"):
            super().__init__(app)
            self.trace_id_header = trace_id_header.lower()

        async def dispatch(
            self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
        ) -> Response:
            start_time = time.time()
            trace_id = request.headers.get(self.trace_id_header) or uuid.uuid4().hex
            request.state.trace_id = trace_id
            response = await call_next(request)
            response.headers["x-trace-id"] = trace_id
            elapsed_ms = (time.time() - start_time) * 1000
            response.headers["x-response-time"] = f"{elapsed_ms:.2f}ms"
            return response

    def get_trace_id(request: Request) -> str:
        return getattr(request.state, "trace_id", "")

    def get_request_id(request: Request) -> str:
        return getattr(request.state, "trace_id", "")

    ObservabilityMiddleware = TracingMiddleware
    __all__ = ["TracingMiddleware", "ObservabilityMiddleware", "get_trace_id", "get_request_id"]
