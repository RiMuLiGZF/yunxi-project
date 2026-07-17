"""
云汐系统 - 请求追踪中间件

FastAPI 中间件，为每个请求生成 trace_id / request_id，
记录请求日志并将追踪信息绑定到 structlog 上下文。
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Awaitable, Callable, Optional

import structlog
from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = structlog.get_logger("yunxi.tracing")


class TracingMiddleware(BaseHTTPMiddleware):
    """请求追踪中间件.

    功能：
    - 为每个请求生成 x-request-id（UUID）和 x-trace-id
    - 将 trace_id 注入响应头
    - 记录请求方法、路径、客户端 IP、响应状态码、耗时
    - 将追踪信息附加到 structlog 上下文绑定
    """

    def __init__(
        self,
        app: FastAPI,
        *,
        trace_id_header: str = "x-trace-id",
        request_id_header: str = "x-request-id",
        expose_headers: bool = True,
    ) -> None:
        super().__init__(app)
        self.trace_id_header = trace_id_header.lower()
        self.request_id_header = request_id_header.lower()
        self.expose_headers = expose_headers

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """处理每个 HTTP 请求."""
        start_time = time.time()

        # ------------------------------------------------------------------
        # 生成 / 复用 trace_id 和 request_id
        # ------------------------------------------------------------------
        trace_id = self._get_header(request, self.trace_id_header)
        if not trace_id:
            trace_id = self._generate_id()

        request_id = self._get_header(request, self.request_id_header)
        if not request_id:
            request_id = self._generate_id()

        # 绑定到 request.state，方便后续路由使用
        request.state.trace_id = trace_id
        request.state.request_id = request_id

        # ------------------------------------------------------------------
        # structlog 上下文绑定
        # ------------------------------------------------------------------
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            trace_id=trace_id,
            request_id=request_id,
            client_ip=self._get_client_ip(request),
            method=request.method,
            path=request.url.path,
        )

        # ------------------------------------------------------------------
        # 执行请求
        # ------------------------------------------------------------------
        try:
            response = await call_next(request)
        except Exception as exc:
            # 记录异常并继续抛出
            elapsed_ms = (time.time() - start_time) * 1000
            logger.error(
                "request_failed",
                status_code=500,
                elapsed_ms=round(elapsed_ms, 2),
                error=str(exc),
            )
            raise

        # ------------------------------------------------------------------
        # 计算耗时 & 注入响应头
        # ------------------------------------------------------------------
        elapsed_ms = (time.time() - start_time) * 1000

        response.headers["x-trace-id"] = trace_id
        response.headers["x-request-id"] = request_id
        response.headers["x-response-time"] = f"{elapsed_ms:.2f}ms"

        if self.expose_headers:
            expose = response.headers.get("access-control-expose-headers", "")
            to_expose = ["x-trace-id", "x-request-id", "x-response-time"]
            if expose:
                existing = [h.strip().lower() for h in expose.split(",")]
                for h in to_expose:
                    if h.lower() not in existing:
                        expose += ", " + h
            else:
                expose = ", ".join(to_expose)
            response.headers["access-control-expose-headers"] = expose

        # ------------------------------------------------------------------
        # 记录请求日志
        # ------------------------------------------------------------------
        client_ip = self._get_client_ip(request)
        status_code = response.status_code

        log_data = {
            "method": request.method,
            "path": request.url.path,
            "client_ip": client_ip,
            "status_code": status_code,
            "elapsed_ms": round(elapsed_ms, 2),
            "trace_id": trace_id,
            "request_id": request_id,
        }

        if status_code >= 500:
            logger.error("request_completed", **log_data)
        elif status_code >= 400:
            logger.warning("request_completed", **log_data)
        else:
            logger.info("request_completed", **log_data)

        return response

    @staticmethod
    def _generate_id() -> str:
        """生成唯一 ID（32 位十六进制小写）."""
        return uuid.uuid4().hex

    @staticmethod
    def _get_header(request: Request, name: str) -> Optional[str]:
        """获取请求头（大小写不敏感）."""
        value = request.headers.get(name)
        if value is None:
            # FastAPI 的 headers 已规范化，但为兼容不同版本再检查一次原格式
            value = request.headers.get(name.replace("-", "_"))
        return value

    @staticmethod
    def _get_client_ip(request: Request) -> str:
        """获取客户端真实 IP.

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


def get_trace_id(request: Request) -> str:
    """从 request.state 获取 trace_id.

    Args:
        request: FastAPI Request 对象

    Returns:
        trace_id 字符串，如果不存在则返回空字符串
    """
    return getattr(request.state, "trace_id", "")


def get_request_id(request: Request) -> str:
    """从 request.state 获取 request_id.

    Args:
        request: FastAPI Request 对象

    Returns:
        request_id 字符串，如果不存在则返回空字符串
    """
    return getattr(request.state, "request_id", "")
