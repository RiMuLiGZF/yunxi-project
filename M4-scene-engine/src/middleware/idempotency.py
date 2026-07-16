"""幂等性中间件.

基于请求头的幂等键缓存响应结果，对 POST/PUT/DELETE/PATCH 请求提供幂等保护。
"""

from __future__ import annotations

import json
import time
from typing import Any

import structlog
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from src.common.idempotency import get_idempotency_manager

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 幂等性中间件
# ---------------------------------------------------------------------------

class IdempotencyMiddleware(BaseHTTPMiddleware):
    """幂等性中间件（基于请求头的幂等键缓存响应）.

    从请求头 X-Idempotency-Key 或 X-Request-ID 提取幂等键，
    对 POST/PUT/DELETE/PATCH 请求缓存响应结果，重复请求直接返回缓存。

    响应体处理说明：
    - FastAPI/Starlette 的 Response body 对于普通 Response 以字节形式存储，
      可直接通过 response.body 读取。
    - 对于 StreamingResponse 等流式响应，跳过缓存以避免消耗数据流。
    - 缓存前将 body 解析为 JSON 存储，返回时重新构造 JSONResponse。

    Args:
        app: FastAPI 应用实例.
        ttl: 幂等键存活时间（秒），默认 24 小时.
        max_keys: 最大缓存键数量，默认 10000.
        exempt_paths: 免幂等路径列表.
    """

    IDEMPOTENT_METHODS = {"POST", "PUT", "DELETE", "PATCH"}
    IDEMPOTENCY_KEY_HEADERS = ("X-Idempotency-Key", "X-Request-ID")

    def __init__(
        self,
        app,
        ttl: int = 86400,
        max_keys: int = 10000,
        exempt_paths: list[str] | None = None,
    ):
        super().__init__(app)
        self._manager = get_idempotency_manager(ttl=ttl, max_keys=max_keys)
        self.exempt_paths = exempt_paths or ["/health", "/healthz", "/m8/health"]

    def _extract_idempotency_key(self, request: Request) -> str | None:
        """从请求头中提取幂等键.

        优先使用 X-Idempotency-Key，其次使用 X-Request-ID。

        Args:
            request: 请求对象.

        Returns:
            幂等键字符串，不存在则返回 None.
        """
        for header in self.IDEMPOTENCY_KEY_HEADERS:
            value = request.headers.get(header)
            if value:
                return value.strip()
        return None

    async def _read_response_body(self, response: Response) -> bytes:
        """读取响应体内容.

        FastAPI/Starlette 的 BaseHTTPMiddleware 会将响应包装为 _StreamingResponse，
        body 以 body_iterator 形式存在。需要逐块收集迭代器内容来获取完整 body。
        读取后重新设置 body_iterator，确保响应仍可正常发送给客户端。

        Args:
            response: 响应对象.

        Returns:
            响应体字节内容.
        """
        # 优先从 body_iterator 读取（BaseHTTPMiddleware 包装后的流式响应）
        if hasattr(response, "body_iterator") and response.body_iterator is not None:
            chunks: list[bytes] = []
            async for chunk in response.body_iterator:
                if isinstance(chunk, str):
                    chunk = chunk.encode(response.charset or "utf-8")
                chunks.append(chunk)
            body_bytes = b"".join(chunks)

            # 重新设置 body_iterator，确保响应可以正常发送
            async def _body_iterator():
                yield body_bytes

            response.body_iterator = _body_iterator()
            return body_bytes

        # 普通 Response：body 已在初始化时设置为字节串
        if hasattr(response, "body") and isinstance(response.body, bytes):
            return response.body

        # 其他类型响应（文件响应等）不缓存
        return b""

    def _build_cached_response(self, cached: dict[str, Any]) -> JSONResponse:
        """根据缓存数据构造响应.

        Args:
            cached: 缓存的数据字典，包含 status_code、content、headers.

        Returns:
            构造的 JSONResponse 对象.
        """
        response = JSONResponse(
            status_code=cached["status_code"],
            content=cached["content"],
        )
        # 还原关键响应头（跳过 content-length 等由框架自动设置的头）
        for key, value in cached.get("headers", {}).items():
            lower_key = key.lower()
            if lower_key in ("content-length", "content-type"):
                continue
            response.headers[key] = value
        # 标记为幂等缓存命中
        response.headers["X-Idempotency-Hit"] = "true"
        return response

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        path = request.url.path
        method = request.method

        # 免幂等路径直接放行
        if path in self.exempt_paths:
            return await call_next(request)

        # 非幂等方法直接放行
        if method not in self.IDEMPOTENT_METHODS:
            return await call_next(request)

        # 提取幂等键
        idempotency_key = self._extract_idempotency_key(request)
        if not idempotency_key:
            return await call_next(request)

        # 检查缓存是否命中
        exists, cached = self._manager.check(idempotency_key)
        if exists and isinstance(cached, dict):
            logger.info(
                "idempotency.cache_hit",
                key=idempotency_key,
                path=path,
                method=method,
            )
            return self._build_cached_response(cached)

        # 执行请求
        response = await call_next(request)

        # 仅缓存成功响应（2xx）
        if 200 <= response.status_code < 300:
            body_bytes = await self._read_response_body(response)
            if body_bytes:
                try:
                    content = json.loads(body_bytes.decode("utf-8"))
                    cache_data = {
                        "status_code": response.status_code,
                        "content": content,
                        "headers": dict(response.headers),
                    }
                    self._manager.store(idempotency_key, cache_data)
                    logger.debug(
                        "idempotency.cache_store",
                        key=idempotency_key,
                        path=path,
                        method=method,
                        status=response.status_code,
                    )
                except (json.JSONDecodeError, UnicodeDecodeError):
                    # 非 JSON 响应跳过缓存
                    logger.debug(
                        "idempotency.skip_non_json",
                        key=idempotency_key,
                        path=path,
                    )

        return response
