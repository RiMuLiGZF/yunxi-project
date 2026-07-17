"""
云汐 API 网关 - 代理转发服务
"""
import httpx
import asyncio
from typing import Optional, Dict, Any, Tuple
from urllib.parse import urljoin

from ..config import settings, ModuleRoute
from .circuit_breaker import get_circuit_breaker


class ProxyService:
    """代理转发服务"""
    
    def __init__(self):
        self._clients: Dict[str, httpx.AsyncClient] = {}
        self._circuit_breaker = get_circuit_breaker()
    
    def _get_client(self, route: ModuleRoute) -> httpx.AsyncClient:
        """获取或创建模块对应的HTTP客户端"""
        if route.key not in self._clients:
            self._clients[route.key] = httpx.AsyncClient(
                base_url=route.target_url,
                timeout=httpx.Timeout(route.timeout),
                follow_redirects=True,
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
        for route in settings.routes:
            if not route.enabled:
                continue
            if path.startswith(route.prefix):
                remaining_path = path[len(route.prefix):]
                if not remaining_path.startswith("/"):
                    remaining_path = "/" + remaining_path
                return route, remaining_path
        return None
    
    async def forward_request(
        self,
        method: str,
        path: str,
        headers: Dict[str, str],
        query_params: Optional[Dict[str, Any]] = None,
        body: Optional[bytes] = None,
        client_ip: str = "unknown",
    ) -> Tuple[int, Dict[str, str], bytes]:
        """
        转发请求到目标模块
        
        Args:
            method: HTTP方法
            path: 请求路径
            headers: 请求头
            query_params: 查询参数
            body: 请求体
            client_ip: 客户端IP
        
        Returns:
            (状态码, 响应头, 响应体)
        """
        route_match = self.find_route(path)
        if not route_match:
            return 404, {"Content-Type": "application/json"}, (
                b'{"code": 404, "message": "Route not found", "data": null}'
            )
        
        route, remaining_path = route_match
        
        # 检查熔断器
        if not await self._circuit_breaker.can_execute(route.key):
            return 503, {"Content-Type": "application/json"}, (
                b'{"code": 503, "message": "Service unavailable (circuit breaker open)", "data": null}'
            )
        
        client = self._get_client(route)
        
        # 过滤请求头（移除hop-by-hop头）
        hop_by_hop = {
            "connection", "keep-alive", "proxy-authenticate",
            "proxy-authorization", "te", "trailers",
            "transfer-encoding", "upgrade", "host",
            "content-length",
        }
        forwarded_headers = {
            k: v for k, v in headers.items()
            if k.lower() not in hop_by_hop
        }
        
        # 添加X-Forwarded头
        forwarded_headers["X-Forwarded-For"] = client_ip
        forwarded_headers["X-Forwarded-Proto"] = "http"
        forwarded_headers["X-Gateway"] = "yunxi-api-gateway"

        # 确保 trace_id / span_id 被传递（跨模块链路追踪）
        # 如果请求已有 X-Trace-Id 则直接传递，否则从上下文生成
        has_trace_id = any(k.lower() == "x-trace-id" for k in forwarded_headers)
        if not has_trace_id:
            try:
                from shared.core.observability import get_trace_headers
                trace_headers = get_trace_headers()
                forwarded_headers.update(trace_headers)
            except ImportError:
                pass
        
        try:
            response = await client.request(
                method=method,
                url=remaining_path,
                headers=forwarded_headers,
                params=query_params,
                content=body,
            )
            
            # 记录成功
            await self._circuit_breaker.record_success(route.key)
            
            # 过滤响应头
            response_headers = {
                k: v for k, v in response.headers.items()
                if k.lower() not in hop_by_hop
            }
            response_headers["X-Gateway-Module"] = route.key
            response_headers["X-Gateway-Latency"] = str(
                response.elapsed.total_seconds() * 1000
            )
            
            return response.status_code, response_headers, response.content
            
        except httpx.TimeoutException:
            await self._circuit_breaker.record_failure(route.key)
            return 504, {"Content-Type": "application/json"}, (
                b'{"code": 504, "message": "Gateway timeout", "data": null}'
            )
        except httpx.ConnectError:
            await self._circuit_breaker.record_failure(route.key)
            return 502, {"Content-Type": "application/json"}, (
                b'{"code": 502, "message": "Bad gateway - connection failed", "data": null}'
            )
        except Exception as e:
            await self._circuit_breaker.record_failure(route.key)
            return 500, {"Content-Type": "application/json"}, (
                f'{{"code": 500, "message": "Gateway error: {str(e)}", "data": null}}'
            ).encode("utf-8")
    
    async def health_check_all(self) -> Dict[str, Any]:
        """检查所有模块的健康状态"""
        results = {}
        for route in settings.routes:
            if not route.enabled:
                results[route.key] = {"status": "disabled", "name": route.name}
                continue
            
            try:
                client = self._get_client(route)
                response = await client.get("/m8/health", timeout=5.0)
                data = response.json()
                results[route.key] = {
                    "status": "healthy" if response.status_code == 200 else "unhealthy",
                    "name": route.name,
                    "status_code": response.status_code,
                    "data": data.get("data", {}) if isinstance(data, dict) else {},
                }
            except Exception as e:
                results[route.key] = {
                    "status": "unreachable",
                    "name": route.name,
                    "error": str(e),
                }
        
        return results
    
    async def close(self):
        """关闭所有HTTP客户端"""
        for client in self._clients.values():
            await client.aclose()
        self._clients.clear()


# 全局代理服务实例
_proxy_service: Optional[ProxyService] = None


def get_proxy_service() -> ProxyService:
    """获取全局代理服务实例"""
    global _proxy_service
    if _proxy_service is None:
        _proxy_service = ProxyService()
    return _proxy_service
