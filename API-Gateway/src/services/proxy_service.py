"""
云汐 API 网关 - 代理转发服务（增强版）

功能特性：
1. HTTP 代理转发（基于 httpx 异步客户端）
2. SSE（Server-Sent Events）流式透传
3. WebSocket 代理（预留接口，基于 HTTP Upgrade）
4. 请求头透传与增强（X-Trace-Id, X-User-Id 等）
5. 响应头透传与网关信息注入
6. 完善的错误处理（超时、连接失败、服务不可用）
7. 可配置超时（按模块差异化配置）
8. 指标统计（请求量、延迟、错误率）
9. 熔断器集成（按模块独立熔断）
"""
import httpx
import asyncio
import time
import logging
from typing import Optional, Dict, Any, Tuple, AsyncIterator
from urllib.parse import urljoin

from ..config import settings, ModuleRoute
from .circuit_breaker import get_circuit_breaker, CircuitBreaker

logger = logging.getLogger("yunxi-gateway.proxy")


class ProxyMetrics:
    """代理服务指标统计"""

    def __init__(self):
        self._total_requests = 0
        self._success_requests = 0
        self._failed_requests = 0
        self._total_latency_ms = 0.0
        self._module_stats: Dict[str, Dict[str, Any]] = {}
        self._start_time = time.time()
        self._lock = asyncio.Lock()

    async def record_request(self, module_key: str, latency_ms: float, success: bool):
        """记录一次请求"""
        async with self._lock:
            self._total_requests += 1
            self._total_latency_ms += latency_ms

            if success:
                self._success_requests += 1
            else:
                self._failed_requests += 1

            if module_key not in self._module_stats:
                self._module_stats[module_key] = {
                    "total": 0,
                    "success": 0,
                    "failed": 0,
                    "total_latency_ms": 0.0,
                }

            stats = self._module_stats[module_key]
            stats["total"] += 1
            stats["total_latency_ms"] += latency_ms
            if success:
                stats["success"] += 1
            else:
                stats["failed"] += 1

    def get_stats(self) -> Dict[str, Any]:
        """获取统计指标"""
        uptime = int(time.time() - self._start_time)
        avg_latency = (
            self._total_latency_ms / self._total_requests
            if self._total_requests > 0
            else 0
        )
        error_rate = (
            self._failed_requests / self._total_requests
            if self._total_requests > 0
            else 0
        )

        module_stats = {}
        for key, stats in self._module_stats.items():
            module_avg = (
                stats["total_latency_ms"] / stats["total"]
                if stats["total"] > 0
                else 0
            )
            module_error = (
                stats["failed"] / stats["total"] if stats["total"] > 0 else 0
            )
            module_stats[key] = {
                "total": stats["total"],
                "success": stats["success"],
                "failed": stats["failed"],
                "avg_latency_ms": round(module_avg, 2),
                "error_rate": round(module_error * 100, 2),
            }

        return {
            "uptime_seconds": uptime,
            "total_requests": self._total_requests,
            "success_requests": self._success_requests,
            "failed_requests": self._failed_requests,
            "avg_latency_ms": round(avg_latency, 2),
            "error_rate_percent": round(error_rate * 100, 2),
            "modules": module_stats,
        }


class ProxyService:
    """代理转发服务（增强版）"""

    # Hop-by-hop 头（不转发）
    HOP_BY_HOP_HEADERS = {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "host",
        "content-length",
    }

    def __init__(self):
        self._clients: Dict[str, httpx.AsyncClient] = {}
        self._circuit_breaker = get_circuit_breaker()
        self._metrics = ProxyMetrics()
        self._client_lock = asyncio.Lock()

    async def _get_client(self, route: ModuleRoute) -> httpx.AsyncClient:
        """获取或创建模块对应的HTTP客户端（线程安全）"""
        if route.key not in self._clients:
            async with self._client_lock:
                if route.key not in self._clients:
                    self._clients[route.key] = httpx.AsyncClient(
                        base_url=route.target_url,
                        timeout=httpx.Timeout(route.timeout),
                        follow_redirects=True,
                        http2=True,
                        limits=httpx.Limits(
                            max_connections=100,
                            max_keepalive_connections=20,
                            keepalive_expiry=30.0,
                        ),
                    )
        return self._clients[route.key]

    def find_route(self, path: str) -> Optional[Tuple[ModuleRoute, str]]:
        """
        根据请求路径查找匹配的路由

        Args:
            path: 请求路径

        Returns:
            (路由配置, 去除前缀后的路径) 或 None
        """
        # 按前缀长度排序，优先匹配更长的前缀
        sorted_routes = sorted(
            settings.routes, key=lambda r: len(r.prefix), reverse=True
        )
        for route in sorted_routes:
            if not route.enabled:
                continue
            if path.startswith(route.prefix):
                remaining_path = path[len(route.prefix):]
                if not remaining_path.startswith("/"):
                    remaining_path = "/" + remaining_path
                return route, remaining_path
        return None

    def _build_forward_headers(
        self,
        headers: Dict[str, str],
        client_ip: str,
        route: ModuleRoute,
        user_info: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, str]:
        """构建转发请求头

        处理逻辑：
        1. 移除 Hop-by-hop 头
        2. 添加 X-Forwarded-* 系列头
        3. 透传 X-Trace-Id（无则生成）
        4. 注入用户信息头（认证通过时）
        5. 添加网关标识头
        """
        # 过滤 hop-by-hop 头
        forwarded = {
            k: v
            for k, v in headers.items()
            if k.lower() not in self.HOP_BY_HOP_HEADERS
        }

        # X-Forwarded 系列
        forwarded["X-Forwarded-For"] = client_ip
        forwarded["X-Forwarded-Proto"] = "http"
        forwarded["X-Forwarded-Host"] = headers.get("host", "")
        forwarded["X-Forwarded-Path"] = headers.get(":path", "")

        # 网关标识
        forwarded["X-Gateway"] = "yunxi-api-gateway"
        forwarded["X-Gateway-Module"] = route.key

        # Trace ID 透传（无则生成）
        has_trace_id = any(k.lower() == "x-trace-id" for k in forwarded)
        if not has_trace_id:
            try:
                from shared.core.observability import get_trace_headers

                trace_headers = get_trace_headers()
                forwarded.update(trace_headers)
            except ImportError:
                import uuid

                forwarded["X-Trace-Id"] = uuid.uuid4().hex

        # 用户信息注入（认证通过时）
        if user_info:
            auth_type = user_info.get("auth_type", "")
            forwarded["X-User-Auth-Type"] = auth_type
            if user_id := user_info.get("user_id"):
                forwarded["X-User-Id"] = str(user_id)
            if username := user_info.get("username"):
                forwarded["X-User-Name"] = str(username)
            if roles := user_info.get("roles"):
                if isinstance(roles, list):
                    forwarded["X-User-Roles"] = ",".join(str(r) for r in roles)
                else:
                    forwarded["X-User-Roles"] = str(roles)
            if scopes := user_info.get("scopes"):
                if isinstance(scopes, list):
                    forwarded["X-User-Scopes"] = ",".join(str(s) for s in scopes)
                else:
                    forwarded["X-User-Scopes"] = str(scopes)
            if jti := user_info.get("jti"):
                forwarded["X-User-Jti"] = str(jti)

        return forwarded

    def _build_response_headers(
        self,
        response_headers: httpx.Headers,
        route: ModuleRoute,
        latency_ms: float,
    ) -> Dict[str, str]:
        """构建响应头

        处理逻辑：
        1. 移除 Hop-by-hop 头
        2. 添加网关信息头
        3. 透传业务响应头
        """
        result = {
            k: v
            for k, v in response_headers.items()
            if k.lower() not in self.HOP_BY_HOP_HEADERS
        }
        result["X-Gateway-Module"] = route.key
        result["X-Gateway-Latency"] = f"{latency_ms:.2f}"
        return result

    def _is_sse_request(
        self, route: ModuleRoute, headers: Dict[str, str], path: str
    ) -> bool:
        """判断是否为 SSE 请求"""
        if not route.supports_sse:
            return False

        accept = headers.get("accept", "").lower()
        if "text/event-stream" in accept:
            return True

        # 常见 SSE 路径模式
        sse_patterns = ["/sse", "/stream", "/events", "/watch"]
        for pattern in sse_patterns:
            if path.endswith(pattern) or f"{pattern}/" in path:
                return True

        return False

    async def forward_request(
        self,
        method: str,
        path: str,
        headers: Dict[str, str],
        query_params: Optional[Dict[str, Any]] = None,
        body: Optional[bytes] = None,
        client_ip: str = "unknown",
        user_info: Optional[Dict[str, Any]] = None,
    ) -> Tuple[int, Dict[str, str], bytes]:
        """
        转发请求到目标模块（普通 HTTP 请求）

        Args:
            method: HTTP方法
            path: 请求路径
            headers: 请求头
            query_params: 查询参数
            body: 请求体
            client_ip: 客户端IP
            user_info: 用户信息（认证通过时）

        Returns:
            (状态码, 响应头, 响应体)
        """
        start_time = time.time()
        route_match = self.find_route(path)

        if not route_match:
            await self._metrics.record_request("unknown", 0, False)
            return 404, {"Content-Type": "application/json"}, (
                b'{"code": 404, "message": "Route not found", "data": null}'
            )

        route, remaining_path = route_match
        latency_ms = 0.0

        # 检查熔断器
        if not await self._circuit_breaker.can_execute(route.key):
            latency_ms = (time.time() - start_time) * 1000
            await self._metrics.record_request(route.key, latency_ms, False)
            return 503, {"Content-Type": "application/json"}, (
                b'{"code": 503, "message": "Service unavailable (circuit breaker open)", "data": null}'
            )

        client = await self._get_client(route)
        forwarded_headers = self._build_forward_headers(
            headers, client_ip, route, user_info
        )

        try:
            response = await client.request(
                method=method,
                url=remaining_path,
                headers=forwarded_headers,
                params=query_params,
                content=body,
            )

            latency_ms = response.elapsed.total_seconds() * 1000
            success = 200 <= response.status_code < 500

            # 记录熔断器状态
            if success:
                await self._circuit_breaker.record_success(route.key)
            else:
                await self._circuit_breaker.record_failure(route.key)

            await self._metrics.record_request(route.key, latency_ms, success)

            response_headers = self._build_response_headers(
                response.headers, route, latency_ms
            )

            return response.status_code, response_headers, response.content

        except httpx.TimeoutException:
            latency_ms = (time.time() - start_time) * 1000
            await self._circuit_breaker.record_failure(route.key)
            await self._metrics.record_request(route.key, latency_ms, False)
            return 504, {"Content-Type": "application/json", "X-Gateway-Module": route.key}, (
                b'{"code": 504, "message": "Gateway timeout", "data": null}'
            )
        except httpx.ConnectError:
            latency_ms = (time.time() - start_time) * 1000
            await self._circuit_breaker.record_failure(route.key)
            await self._metrics.record_request(route.key, latency_ms, False)
            return 502, {"Content-Type": "application/json", "X-Gateway-Module": route.key}, (
                b'{"code": 502, "message": "Bad gateway - connection failed", "data": null}'
            )
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            await self._circuit_breaker.record_failure(route.key)
            await self._metrics.record_request(route.key, latency_ms, False)
            logger.error(f"Proxy error for {route.key}: {e}", exc_info=True)
            return 500, {"Content-Type": "application/json", "X-Gateway-Module": route.key}, (
                f'{{"code": 500, "message": "Gateway error", "data": null}}'
            ).encode("utf-8")

    async def forward_sse(
        self,
        method: str,
        path: str,
        headers: Dict[str, str],
        query_params: Optional[Dict[str, Any]] = None,
        body: Optional[bytes] = None,
        client_ip: str = "unknown",
        user_info: Optional[Dict[str, Any]] = None,
    ) -> Optional[AsyncIterator[bytes]]:
        """
        SSE 流式透传

        Args:
            method: HTTP方法
            path: 请求路径
            headers: 请求头
            query_params: 查询参数
            body: 请求体
            client_ip: 客户端IP
            user_info: 用户信息

        Returns:
            SSE 数据流异步迭代器，失败返回 None
        """
        route_match = self.find_route(path)
        if not route_match:
            return None

        route, remaining_path = route_match

        # 检查熔断器
        if not await self._circuit_breaker.can_execute(route.key):
            return None

        client = await self._get_client(route)
        forwarded_headers = self._build_forward_headers(
            headers, client_ip, route, user_info
        )
        # 确保 SSE 相关头
        forwarded_headers["Accept"] = "text/event-stream"
        forwarded_headers["Cache-Control"] = "no-cache"
        forwarded_headers["Connection"] = "keep-alive"

        try:
            response = await client.request(
                method=method,
                url=remaining_path,
                headers=forwarded_headers,
                params=query_params,
                content=body,
                stream=True,
            )

            if response.status_code != 200:
                return None

            async def sse_generator():
                try:
                    async for chunk in response.aiter_bytes():
                        yield chunk
                except Exception as e:
                    logger.warning(f"SSE stream error: {e}")
                finally:
                    await response.aclose()

            return sse_generator()

        except Exception as e:
            logger.error(f"SSE proxy error for {route.key}: {e}")
            await self._circuit_breaker.record_failure(route.key)
            return None

    async def health_check_module(self, route_key: str) -> Dict[str, Any]:
        """检查单个模块的健康状态"""
        route = None
        for r in settings.routes:
            if r.key == route_key:
                route = r
                break

        if not route:
            return {"status": "unknown", "error": "Module not found"}

        if not route.enabled:
            return {"status": "disabled", "name": route.name}

        try:
            client = await self._get_client(route)
            response = await client.get(
                route.health_path, timeout=route.health_timeout
            )
            data = {}
            try:
                data = response.json()
            except Exception as e:
                # 健康检查响应 JSON 解析失败不影响健康状态判断
                logger.debug("解析健康检查响应 JSON 失败: %s", e)

            return {
                "status": "healthy" if response.status_code == 200 else "unhealthy",
                "name": route.name,
                "description": route.description,
                "status_code": response.status_code,
                "response_time_ms": round(response.elapsed.total_seconds() * 1000, 2),
                "data": data.get("data", {}) if isinstance(data, dict) else {},
            }
        except Exception as e:
            return {
                "status": "unreachable",
                "name": route.name,
                "description": route.description,
                "error": str(e),
            }

    async def health_check_all(self) -> Dict[str, Any]:
        """检查所有模块的健康状态"""
        results = {}
        for route in settings.routes:
            if not route.enabled:
                results[route.key] = {
                    "status": "disabled",
                    "name": route.name,
                    "description": route.description,
                }
                continue

            results[route.key] = await self.health_check_module(route.key)

        return results

    def get_metrics(self) -> Dict[str, Any]:
        """获取代理服务指标"""
        return self._metrics.get_stats()

    async def reload_route(self, route_key: str) -> bool:
        """重新加载指定模块的路由配置（重建HTTP客户端）"""
        if route_key in self._clients:
            async with self._client_lock:
                if route_key in self._clients:
                    client = self._clients.pop(route_key)
                    await client.aclose()
        return True

    async def reload_all_routes(self) -> int:
        """重新加载所有路由配置（重建所有HTTP客户端）"""
        count = 0
        async with self._client_lock:
            for key in list(self._clients.keys()):
                client = self._clients.pop(key)
                await client.aclose()
                count += 1
        return count

    async def close(self):
        """关闭所有HTTP客户端"""
        async with self._client_lock:
            for client in self._clients.values():
                await client.aclose()
            self._clients.clear()


# 全局代理服务实例
_proxy_service: Optional[ProxyService] = None
_proxy_lock = asyncio.Lock()


async def get_proxy_service() -> ProxyService:
    """获取全局代理服务实例（异步安全初始化）"""
    global _proxy_service
    if _proxy_service is None:
        async with _proxy_lock:
            if _proxy_service is None:
                _proxy_service = ProxyService()
    return _proxy_service


def get_proxy_service_sync() -> ProxyService:
    """同步获取全局代理服务实例（用于非async上下文，如启动时）"""
    global _proxy_service
    if _proxy_service is None:
        _proxy_service = ProxyService()
    return _proxy_service
