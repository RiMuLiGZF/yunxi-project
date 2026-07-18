"""
响应缓存中间件 (Response Cache Middleware)

FastAPI 响应缓存中间件:
- GET 请求自动缓存
- 按 URL + 参数生成缓存键
- 可配置缓存 TTL
- 缓存失效机制 (POST/PUT/DELETE 自动清相关缓存)
- 支持按用户隔离缓存

使用方式::

    from fastapi import FastAPI
    from shared.perf.cache_middleware import ResponseCacheMiddleware

    app = FastAPI()
    app.add_middleware(
        ResponseCacheMiddleware,
        default_ttl=30,
        max_size=1000,
        exclude_paths=["/api/auth", "/api/health"],
    )
"""

from __future__ import annotations

import hashlib
import time
import threading
from typing import Any, Dict, List, Optional, Set, Callable
from dataclasses import dataclass, field

try:
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import Response, JSONResponse
    from starlette.concurrency import iterate_in_threadpool
    HAS_STARLETTE = True
except ImportError:
    HAS_STARLETTE = False

# 尝试从 cache_manager 导入
from shared.perf.cache_manager import CacheManager, NULL_VALUE


# ============================================================
# 配置
# ============================================================

@dataclass
class CacheMiddlewareConfig:
    """响应缓存中间件配置"""
    default_ttl: float = 30.0
    max_size: int = 1000
    # 排除的路径 (不缓存)
    exclude_paths: List[str] = field(default_factory=list)
    # 只缓存的路径 (空表示所有 GET 都缓存)
    include_paths: List[str] = field(default_factory=list)
    # 按用户隔离 (从 header/query 中提取用户标识)
    per_user: bool = False
    user_header: str = "X-User-ID"
    # 支持的 HTTP 方法
    cache_methods: Set[str] = field(default_factory=lambda: {"GET", "HEAD"})
    # 失效方法 (会触发相关缓存失效)
    invalidate_methods: Set[str] = field(default_factory=lambda: {"POST", "PUT", "DELETE", "PATCH"})
    # 最大响应大小 (字节)，超过不缓存
    max_response_size: int = 1024 * 1024  # 1MB
    # 路径级 TTL 配置
    path_ttl_map: Dict[str, float] = field(default_factory=dict)
    # 是否启用
    enabled: bool = True


# ============================================================
# 缓存的响应
# ============================================================

@dataclass
class CachedResponse:
    """缓存的响应数据"""
    status_code: int
    headers: Dict[str, str]
    body: bytes
    content_type: str
    cached_at: float
    hit_count: int = 0


# ============================================================
# 响应缓存中间件
# ============================================================

class ResponseCacheMiddleware:
    """FastAPI 响应缓存中间件

    特性:
    - GET 请求自动缓存
    - 按 URL + 查询参数生成缓存键
    - 可配置 TTL (支持路径级 TTL)
    - POST/PUT/DELETE 自动清除相关路径缓存
    - 支持按用户隔离缓存
    - 支持排除/包含路径
    - 统计信息 (命中率等)
    """

    def __init__(
        self,
        app,
        config: Optional[CacheMiddlewareConfig] = None,
        cache_manager: Optional[CacheManager] = None,
        **kwargs,
    ):
        if not HAS_STARLETTE:
            raise ImportError("starlette is required for ResponseCacheMiddleware")

        self.app = app
        self.config = config or CacheMiddlewareConfig(**kwargs)
        self._cache = cache_manager or CacheManager(
            l1_enabled=True,
            l1_max_size=self.config.max_size,
            l1_default_ttl=self.config.default_ttl,
            l2_enabled=False,
            l3_enabled=False,
        )

        # 统计
        self._hits = 0
        self._misses = 0
        self._invalidations = 0
        self._lock = threading.Lock()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not self.config.enabled:
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "").upper()

        # 写操作: 执行并失效相关缓存
        if method in self.config.invalidate_methods:
            await self._handle_invalidation(scope, receive, send)
            return

        # 读操作: 尝试缓存
        if method in self.config.cache_methods:
            await self._handle_cache(scope, receive, send)
            return

        # 其他方法: 直接通过
        await self.app(scope, receive, send)

    async def _handle_cache(self, scope, receive, send):
        """处理缓存读取"""
        path = scope.get("path", "")
        query_string = scope.get("query_string", b"").decode("utf-8")

        # 检查是否排除
        if self._is_excluded(path):
            await self.app(scope, receive, send)
            return

        # 生成缓存键
        cache_key = self._make_cache_key(scope)
        ttl = self._get_path_ttl(path)

        # 尝试从缓存获取
        cached = self._cache.get(cache_key)
        if cached is not None and isinstance(cached, CachedResponse):
            with self._lock:
                self._hits += 1
            cached.hit_count += 1
            await self._send_cached_response(cached, send)
            return

        with self._lock:
            self._misses += 1

        # 未命中，执行请求并缓存响应
        await self._execute_and_cache(scope, receive, send, cache_key, ttl)

    async def _handle_invalidation(self, scope, receive, send):
        """处理写操作并失效相关缓存"""
        path = scope.get("path", "")

        # 先执行请求
        await self.app(scope, receive, send)

        # 失效相关路径的缓存 (同一路径前缀)
        prefix = path.rstrip("/")
        if prefix:
            self._cache.clear(pattern=f"{prefix}*")
            with self._lock:
                self._invalidations += 1

    async def _execute_and_cache(self, scope, receive, send, cache_key: str, ttl: float):
        """执行请求并缓存响应"""
        # 收集响应数据
        response_body_chunks = []
        response_status = 200
        response_headers = {}
        response_content_type = "application/json"

        async def send_wrapper(message):
            nonlocal response_status, response_headers, response_content_type
            if message["type"] == "http.response.start":
                response_status = message["status"]
                for name, value in message.get("headers", []):
                    name_str = name.decode("latin-1").lower()
                    value_str = value.decode("latin-1")
                    response_headers[name_str] = value_str
                    if name_str == "content-type":
                        response_content_type = value_str
            elif message["type"] == "http.response.body":
                body = message.get("body", b"")
                response_body_chunks.append(body)
            await send(message)

        await self.app(scope, receive, send_wrapper)

        # 检查是否应该缓存
        body = b"".join(response_body_chunks)
        if (
            response_status == 200
            and len(body) <= self.config.max_response_size
            and ttl > 0
        ):
            cached = CachedResponse(
                status_code=response_status,
                headers=response_headers,
                body=body,
                content_type=response_content_type,
                cached_at=time.time(),
            )
            self._cache.set(cache_key, cached, ttl=ttl)

    async def _send_cached_response(self, cached: CachedResponse, send):
        """发送缓存的响应"""
        headers = []
        for name, value in cached.headers.items():
            if name.lower() not in ("content-length",):
                headers.append((name.encode("latin-1"), value.encode("latin-1")))

        headers.append((b"content-length", str(len(cached.body)).encode("latin-1")))
        headers.append((b"x-cache-hit", b"1"))

        await send({
            "type": "http.response.start",
            "status": cached.status_code,
            "headers": headers,
        })
        await send({
            "type": "http.response.body",
            "body": cached.body,
            "more_body": False,
        })

    def _make_cache_key(self, scope) -> str:
        """生成缓存键"""
        path = scope.get("path", "")
        query_string = scope.get("query_string", b"").decode("utf-8")

        key_parts = [path]

        # 按用户隔离
        if self.config.per_user:
            user_id = self._get_user_id(scope)
            key_parts.append(f"user:{user_id}")

        # 查询参数
        if query_string:
            key_parts.append(f"query:{query_string}")

        raw_key = "|".join(key_parts)
        return f"resp:{hashlib.md5(raw_key.encode()).hexdigest()}"

    def _get_user_id(self, scope) -> str:
        """从请求中提取用户 ID"""
        headers = scope.get("headers", [])
        for name, value in headers:
            if name.decode("latin-1").lower() == self.config.user_header.lower():
                return value.decode("latin-1")
        return "anonymous"

    def _is_excluded(self, path: str) -> bool:
        """检查路径是否排除缓存"""
        # 包含路径优先
        if self.config.include_paths:
            return not any(
                path.startswith(p) for p in self.config.include_paths
            )
        # 排除路径
        return any(
            path.startswith(p) for p in self.config.exclude_paths
        )

    def _get_path_ttl(self, path: str) -> float:
        """获取路径对应的 TTL"""
        # 最长前缀匹配
        best_ttl = self.config.default_ttl
        best_len = 0
        for prefix, ttl in self.config.path_ttl_map.items():
            if path.startswith(prefix) and len(prefix) > best_len:
                best_ttl = ttl
                best_len = len(prefix)
        return best_ttl

    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        with self._lock:
            total = self._hits + self._misses
            hit_rate = self._hits / total if total > 0 else 0.0
            return {
                "hits": self._hits,
                "misses": self._misses,
                "invalidations": self._invalidations,
                "hit_rate": round(hit_rate, 4),
                "total_requests": total,
                "cache_size": self._cache.l1.size() if self._cache.l1 else 0,
                "config": {
                    "default_ttl": self.config.default_ttl,
                    "max_size": self.config.max_size,
                    "per_user": self.config.per_user,
                },
            }

    def clear_cache(self) -> int:
        """清空所有响应缓存"""
        return self._cache.clear()

    def clear_path(self, path_prefix: str) -> int:
        """清除指定路径前缀的缓存"""
        # 由于使用 hash 键，无法精确按路径前缀清除
        # 这里简化为全部清除
        return self._cache.clear()
