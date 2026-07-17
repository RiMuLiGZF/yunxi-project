"""
云汐 API 网关 - 管理 API 增强模块

提供完整的网关管理 API：
- 路由管理：动态增删改路由（无需重启）
- 限流配置管理
- 熔断状态查询和手动控制
- 缓存管理（查询、清除）
- 插件管理（列表、启用、禁用）
- 统计和指标
"""
import time
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from ..config import ModuleRoute
from ..routing.weighted_router import RouteTarget


# ===================================================================
# 请求/响应模型
# ===================================================================

class RouteCreateRequest(BaseModel):
    """创建路由请求"""
    key: str
    name: str
    target_url: str
    prefix: str
    enabled: bool = True
    timeout: float = 30.0
    health_path: str = "/health"
    auth_required: bool = True
    public_paths: List[str] = Field(default_factory=list)
    rate_limit_per_minute: int = 60
    rate_limit_per_ip: int = 30
    rate_limit_tier: str = "public"
    supports_websocket: bool = False
    supports_sse: bool = False
    cb_failure_threshold: int = 5
    cb_recovery_time: int = 30
    description: str = ""


class RouteUpdateRequest(BaseModel):
    """更新路由请求"""
    name: Optional[str] = None
    target_url: Optional[str] = None
    prefix: Optional[str] = None
    enabled: Optional[bool] = None
    timeout: Optional[float] = None
    health_path: Optional[str] = None
    auth_required: Optional[bool] = None
    public_paths: Optional[List[str]] = None
    rate_limit_per_minute: Optional[int] = None
    rate_limit_per_ip: Optional[int] = None
    rate_limit_tier: Optional[str] = None
    cb_failure_threshold: Optional[int] = None
    cb_recovery_time: Optional[int] = None
    description: Optional[str] = None


class WeightedTargetRequest(BaseModel):
    """权重目标请求"""
    url: str
    weight: int = 50
    name: str = ""
    healthy: bool = True


class RateLimitUpdateRequest(BaseModel):
    """限流配置更新请求"""
    global_rate: Optional[float] = None
    global_capacity: Optional[int] = None
    ip_rate: Optional[float] = None
    ip_capacity: Optional[int] = None
    user_rate: Optional[float] = None
    user_capacity: Optional[int] = None


class RetryConfigUpdateRequest(BaseModel):
    """重试配置更新请求"""
    max_retries: int = 2
    base_delay: float = 0.1
    max_delay: float = 5.0
    backoff_factor: float = 2.0
    jitter: bool = True
    only_idempotent: bool = True


class CacheConfigUpdateRequest(BaseModel):
    """缓存配置更新请求"""
    enabled: bool = False
    default_ttl: int = 60
    max_size: int = 104857600
    max_entries: int = 10000


class CircuitBreakerControlRequest(BaseModel):
    """熔断器控制请求"""
    action: str  # reset, open, close
    slow_request_enabled: Optional[bool] = None
    slow_request_threshold_ms: Optional[float] = None
    adaptive_enabled: Optional[bool] = None
    progressive_enabled: Optional[bool] = None


class RewriteRuleRequest(BaseModel):
    """重写规则请求"""
    pattern: str
    replacement: str = ""
    type: str = "regex"
    order: int = 100
    enabled: bool = True


# ===================================================================
# 管理 API 路由器
# ===================================================================

def create_admin_router(
    proxy_service=None,
    token_bucket_limiter=None,
    advanced_circuit_breaker=None,
    retry_manager=None,
    response_cache=None,
    plugin_manager=None,
    weighted_routers: Optional[Dict[str, Any]] = None,
    path_rewriters: Optional[Dict[str, Any]] = None,
    header_transformers: Optional[Dict[str, Any]] = None,
) -> APIRouter:
    """创建管理 API 路由器

    Args:
        proxy_service: 代理服务实例
        token_bucket_limiter: 令牌桶限流器
        advanced_circuit_breaker: 增强版熔断器
        retry_manager: 重试管理器
        response_cache: 响应缓存
        plugin_manager: 插件管理器
        weighted_routers: 权重路由器字典（按路由 key）
        path_rewriters: 路径重写器字典
        header_transformers: 头转换器字典

    Returns:
        FastAPI APIRouter
    """
    router = APIRouter(prefix="/gateway/admin", tags=["gateway-admin"])

    # ===================================================================
    # 路由管理
    # ===================================================================

    @router.post("/routes")
    async def create_route(req: RouteCreateRequest):
        """创建新路由"""
        from ..config import settings

        # 检查是否已存在
        for route in settings.routes:
            if route.key == req.key:
                return JSONResponse(
                    status_code=409,
                    content={
                        "code": 409,
                        "message": f"Route '{req.key}' already exists",
                        "data": None,
                    },
                )

        new_route = ModuleRoute(
            key=req.key,
            name=req.name,
            target_url=req.target_url,
            prefix=req.prefix,
            enabled=req.enabled,
            timeout=req.timeout,
            health_path=req.health_path,
            auth_required=req.auth_required,
            public_paths=req.public_paths,
            rate_limit_per_minute=req.rate_limit_per_minute,
            rate_limit_per_ip=req.rate_limit_per_ip,
            rate_limit_tier=req.rate_limit_tier,
            supports_websocket=req.supports_websocket,
            supports_sse=req.supports_sse,
            cb_failure_threshold=req.cb_failure_threshold,
            cb_recovery_time=req.cb_recovery_time,
            description=req.description,
        )

        settings.routes.append(new_route)

        return {
            "code": 0,
            "message": "Route created successfully",
            "data": {"key": req.key, "name": req.name},
        }

    @router.put("/routes/{route_key}")
    async def update_route(route_key: str, req: RouteUpdateRequest):
        """更新路由配置"""
        from ..config import settings

        route = None
        for r in settings.routes:
            if r.key == route_key:
                route = r
                break

        if not route:
            return JSONResponse(
                status_code=404,
                content={
                    "code": 404,
                    "message": f"Route '{route_key}' not found",
                    "data": None,
                },
            )

        # 更新字段
        update_data = req.dict(exclude_unset=True)
        for field_name, value in update_data.items():
            if hasattr(route, field_name):
                setattr(route, field_name, value)

        # 重建 HTTP 客户端
        if proxy_service:
            await proxy_service.reload_route(route_key)

        return {
            "code": 0,
            "message": "Route updated successfully",
            "data": {"key": route_key, "updated_fields": list(update_data.keys())},
        }

    @router.delete("/routes/{route_key}")
    async def delete_route(route_key: str):
        """删除路由"""
        from ..config import settings

        original_len = len(settings.routes)
        settings.routes = [r for r in settings.routes if r.key != route_key]

        if len(settings.routes) == original_len:
            return JSONResponse(
                status_code=404,
                content={
                    "code": 404,
                    "message": f"Route '{route_key}' not found",
                    "data": None,
                },
            )

        # 清理相关资源
        if proxy_service:
            await proxy_service.reload_route(route_key)

        return {
            "code": 0,
            "message": "Route deleted successfully",
            "data": {"key": route_key},
        }

    # ===================================================================
    # 权重路由管理
    # ===================================================================

    @router.get("/routes/{route_key}/weighted-targets")
    async def list_weighted_targets(route_key: str):
        """获取路由的权重目标列表"""
        if not weighted_routers or route_key not in weighted_routers:
            return {
                "code": 0,
                "message": "success",
                "data": {"targets": [], "route_key": route_key},
            }

        wr = weighted_routers[route_key]
        return {
            "code": 0,
            "message": "success",
            "data": {
                "route_key": route_key,
                "targets": wr.get_targets(),
                "stats": wr.get_stats(),
            },
        }

    @router.post("/routes/{route_key}/weighted-targets")
    async def add_weighted_target(route_key: str, req: WeightedTargetRequest):
        """添加权重目标"""
        if weighted_routers is None:
            return JSONResponse(
                status_code=503,
                content={"code": 503, "message": "Weighted routing not available", "data": None},
            )

        if route_key not in weighted_routers:
            from ..routing.weighted_router import WeightedRouter
            weighted_routers[route_key] = WeightedRouter()

        target = RouteTarget(
            url=req.url,
            weight=req.weight,
            name=req.name or req.url,
            healthy=req.healthy,
        )
        weighted_routers[route_key].add_target(target)

        return {
            "code": 0,
            "message": "Target added successfully",
            "data": {"route_key": route_key, "target": req.name or req.url},
        }

    @router.delete("/routes/{route_key}/weighted-targets/{target_name}")
    async def remove_weighted_target(route_key: str, target_name: str):
        """移除权重目标"""
        if not weighted_routers or route_key not in weighted_routers:
            return JSONResponse(
                status_code=404,
                content={"code": 404, "message": "Route or router not found", "data": None},
            )

        success = weighted_routers[route_key].remove_target(target_name)
        if not success:
            return JSONResponse(
                status_code=404,
                content={"code": 404, "message": f"Target '{target_name}' not found", "data": None},
            )

        return {
            "code": 0,
            "message": "Target removed successfully",
            "data": {"route_key": route_key, "target": target_name},
        }

    # ===================================================================
    # 路径重写管理
    # ===================================================================

    @router.get("/routes/{route_key}/rewrite-rules")
    async def list_rewrite_rules(route_key: str):
        """获取路径重写规则"""
        if not path_rewriters or route_key not in path_rewriters:
            return {
                "code": 0,
                "message": "success",
                "data": {"rules": [], "route_key": route_key},
            }

        rewriter = path_rewriters[route_key]
        return {
            "code": 0,
            "message": "success",
            "data": {
                "route_key": route_key,
                "rules": rewriter.get_rules(),
                "stats": rewriter.get_stats(),
            },
        }

    @router.post("/routes/{route_key}/rewrite-rules")
    async def add_rewrite_rule(route_key: str, req: RewriteRuleRequest):
        """添加路径重写规则"""
        if path_rewriters is None:
            return JSONResponse(
                status_code=503,
                content={"code": 503, "message": "Path rewriting not available", "data": None},
            )

        if route_key not in path_rewriters:
            from ..routing.path_rewriter import PathRewriter
            path_rewriters[route_key] = PathRewriter()

        from ..routing.path_rewriter import RewriteRule
        rule = RewriteRule(
            pattern=req.pattern,
            replacement=req.replacement,
            type=req.type,
            order=req.order,
            enabled=req.enabled,
        )
        path_rewriters[route_key].add_rule(rule)

        return {
            "code": 0,
            "message": "Rewrite rule added successfully",
            "data": {"route_key": route_key, "pattern": req.pattern, "type": req.type},
        }

    # ===================================================================
    # 限流配置管理
    # ===================================================================

    @router.get("/rate-limit/config")
    async def get_rate_limit_config():
        """获取限流配置"""
        if not token_bucket_limiter:
            return JSONResponse(
                status_code=503,
                content={"code": 503, "message": "Rate limiter not available", "data": None},
            )

        stats = token_bucket_limiter.get_stats()
        return {
            "code": 0,
            "message": "success",
            "data": {
                "config": {
                    "global_rate": stats.get("global_rate"),
                    "global_capacity": stats.get("global_capacity"),
                    "ip_limits_count": stats.get("ip_limits_count"),
                    "user_limits_count": stats.get("user_limits_count"),
                    "path_limits_count": stats.get("path_limits_count"),
                },
                "stats": stats,
            },
        }

    @router.put("/rate-limit/config")
    async def update_rate_limit_config(req: RateLimitUpdateRequest):
        """更新限流配置"""
        if not token_bucket_limiter:
            return JSONResponse(
                status_code=503,
                content={"code": 503, "message": "Rate limiter not available", "data": None},
            )

        updated = []
        if req.global_rate is not None and req.global_capacity is not None:
            token_bucket_limiter.set_global_config(req.global_rate, req.global_capacity)
            updated.append("global")

        if req.ip_rate is not None and req.ip_capacity is not None:
            token_bucket_limiter.set_default_ip_limit(req.ip_rate, req.ip_capacity)
            updated.append("ip_default")

        if req.user_rate is not None and req.user_capacity is not None:
            token_bucket_limiter.set_default_user_limit(req.user_rate, req.user_capacity)
            updated.append("user_default")

        return {
            "code": 0,
            "message": "Rate limit config updated",
            "data": {"updated": updated},
        }

    @router.get("/rate-limit/stats")
    async def get_rate_limit_stats():
        """获取限流统计"""
        if not token_bucket_limiter:
            return JSONResponse(
                status_code=503,
                content={"code": 503, "message": "Rate limiter not available", "data": None},
            )

        return {
            "code": 0,
            "message": "success",
            "data": token_bucket_limiter.get_stats(),
        }

    # ===================================================================
    # 熔断管理
    # ===================================================================

    @router.get("/circuit-breakers")
    async def list_circuit_breakers():
        """获取所有熔断器状态"""
        if not advanced_circuit_breaker:
            from ..services.circuit_breaker import get_circuit_breaker
            cb = get_circuit_breaker()
            return {
                "code": 0,
                "message": "success",
                "data": cb.get_stats(),
            }

        return {
            "code": 0,
            "message": "success",
            "data": advanced_circuit_breaker.get_stats(),
        }

    @router.get("/circuit-breakers/{route_key}")
    async def get_circuit_breaker_detail(route_key: str):
        """获取单个熔断器详情"""
        if not advanced_circuit_breaker:
            from ..services.circuit_breaker import get_circuit_breaker
            cb = get_circuit_breaker()
            all_stats = cb.get_stats()
            stats = all_stats.get(route_key)
            if not stats:
                return JSONResponse(
                    status_code=404,
                    content={"code": 404, "message": "Circuit breaker not found", "data": None},
                )
            return {"code": 0, "message": "success", "data": stats}

        all_stats = advanced_circuit_breaker.get_stats()
        stats = all_stats.get(route_key)
        if not stats:
            return JSONResponse(
                status_code=404,
                content={"code": 404, "message": "Circuit breaker not found", "data": None},
            )
        return {"code": 0, "message": "success", "data": stats}

    @router.post("/circuit-breakers/{route_key}/control")
    async def control_circuit_breaker(route_key: str, req: CircuitBreakerControlRequest):
        """控制熔断器"""
        if not advanced_circuit_breaker:
            from ..services.circuit_breaker import get_circuit_breaker
            cb = get_circuit_breaker()
            if req.action == "reset":
                success = await cb.reset(route_key)
                if not success:
                    return JSONResponse(
                        status_code=404,
                        content={"code": 404, "message": "Circuit breaker not found", "data": None},
                    )
                return {"code": 0, "message": "Circuit breaker reset", "data": {"action": "reset"}}
            return JSONResponse(
                status_code=400,
                content={"code": 400, "message": f"Unsupported action: {req.action}", "data": None},
            )

        # 增强版熔断器
        if req.action == "reset":
            success = await advanced_circuit_breaker.reset(route_key)
            if not success:
                return JSONResponse(
                    status_code=404,
                    content={"code": 404, "message": "Circuit breaker not found", "data": None},
                )
        else:
            return JSONResponse(
                status_code=400,
                content={"code": 400, "message": f"Unsupported action: {req.action}", "data": None},
            )

        return {
            "code": 0,
            "message": f"Circuit breaker {req.action} executed",
            "data": {"action": req.action, "route_key": route_key},
        }

    # ===================================================================
    # 重试配置管理
    # ===================================================================

    @router.get("/retry/config")
    async def get_retry_config():
        """获取重试配置"""
        if not retry_manager:
            return JSONResponse(
                status_code=503,
                content={"code": 503, "message": "Retry manager not available", "data": None},
            )

        config = retry_manager.get_config()
        return {
            "code": 0,
            "message": "success",
            "data": {
                "max_retries": config.max_retries,
                "base_delay": config.base_delay,
                "max_delay": config.max_delay,
                "backoff_factor": config.backoff_factor,
                "jitter": config.jitter,
                "only_idempotent": config.only_idempotent,
                "retryable_status_codes": list(config.retryable_status_codes),
            },
        }

    @router.put("/retry/config")
    async def update_retry_config(req: RetryConfigUpdateRequest):
        """更新重试配置"""
        if not retry_manager:
            return JSONResponse(
                status_code=503,
                content={"code": 503, "message": "Retry manager not available", "data": None},
            )

        from ..traffic.retry_manager import RetryConfig
        old_config = retry_manager.get_config()
        new_config = RetryConfig(
            max_retries=req.max_retries,
            base_delay=req.base_delay,
            max_delay=req.max_delay,
            backoff_factor=req.backoff_factor,
            jitter=req.jitter,
            only_idempotent=req.only_idempotent,
            retryable_status_codes=old_config.retryable_status_codes,
        )
        retry_manager.update_config(new_config)

        return {
            "code": 0,
            "message": "Retry config updated",
            "data": {"max_retries": req.max_retries},
        }

    @router.get("/retry/stats")
    async def get_retry_stats():
        """获取重试统计"""
        if not retry_manager:
            return JSONResponse(
                status_code=503,
                content={"code": 503, "message": "Retry manager not available", "data": None},
            )

        return {
            "code": 0,
            "message": "success",
            "data": retry_manager.get_stats(),
        }

    # ===================================================================
    # 缓存管理
    # ===================================================================

    @router.get("/cache/config")
    async def get_cache_config():
        """获取缓存配置"""
        if not response_cache:
            return JSONResponse(
                status_code=503,
                content={"code": 503, "message": "Cache not available", "data": None},
            )

        config = response_cache.get_config()
        return {
            "code": 0,
            "message": "success",
            "data": {
                "enabled": config.enabled,
                "default_ttl": config.default_ttl,
                "max_size": config.max_size,
                "max_entries": config.max_entries,
                "cache_methods": config.cache_methods,
                "include_auth_in_key": config.include_auth_in_key,
                "vary_headers": config.vary_headers,
            },
        }

    @router.put("/cache/config")
    async def update_cache_config(req: CacheConfigUpdateRequest):
        """更新缓存配置"""
        if not response_cache:
            return JSONResponse(
                status_code=503,
                content={"code": 503, "message": "Cache not available", "data": None},
            )

        from ..cache.response_cache import CacheConfig
        old_config = response_cache.get_config()
        new_config = CacheConfig(
            enabled=req.enabled,
            default_ttl=req.default_ttl,
            max_size=req.max_size,
            max_entries=req.max_entries,
            cache_methods=old_config.cache_methods,
            include_auth_in_key=old_config.include_auth_in_key,
            vary_headers=old_config.vary_headers,
        )
        response_cache.update_config(new_config)

        return {
            "code": 0,
            "message": "Cache config updated",
            "data": {"enabled": req.enabled, "default_ttl": req.default_ttl},
        }

    @router.get("/cache/stats")
    async def get_cache_stats():
        """获取缓存统计"""
        if not response_cache:
            return JSONResponse(
                status_code=503,
                content={"code": 503, "message": "Cache not available", "data": None},
            )

        return {
            "code": 0,
            "message": "success",
            "data": response_cache.get_stats(),
        }

    @router.post("/cache/invalidate")
    async def invalidate_cache_all():
        """清空所有缓存"""
        if not response_cache:
            return JSONResponse(
                status_code=503,
                content={"code": 503, "message": "Cache not available", "data": None},
            )

        count = response_cache.invalidate_all()
        return {
            "code": 0,
            "message": "Cache invalidated",
            "data": {"invalidated_count": count},
        }

    @router.post("/cache/invalidate/{pattern}")
    async def invalidate_cache_pattern(pattern: str):
        """按模式失效缓存"""
        if not response_cache:
            return JSONResponse(
                status_code=503,
                content={"code": 503, "message": "Cache not available", "data": None},
            )

        count = response_cache.invalidate_pattern(pattern)
        return {
            "code": 0,
            "message": "Cache pattern invalidated",
            "data": {"invalidated_count": count, "pattern": pattern},
        }

    # ===================================================================
    # 插件管理
    # ===================================================================

    @router.get("/plugins")
    async def list_plugins():
        """列出所有插件"""
        if not plugin_manager:
            return JSONResponse(
                status_code=503,
                content={"code": 503, "message": "Plugin manager not available", "data": None},
            )

        return {
            "code": 0,
            "message": "success",
            "data": {
                "plugins": plugin_manager.list_plugins(),
                "stats": plugin_manager.get_stats(),
            },
        }

    @router.get("/plugins/{plugin_name}")
    async def get_plugin_detail(plugin_name: str):
        """获取插件详情"""
        if not plugin_manager:
            return JSONResponse(
                status_code=503,
                content={"code": 503, "message": "Plugin manager not available", "data": None},
            )

        plugin = plugin_manager.get_plugin(plugin_name)
        if not plugin:
            return JSONResponse(
                status_code=404,
                content={"code": 404, "message": f"Plugin '{plugin_name}' not found", "data": None},
            )

        return {
            "code": 0,
            "message": "success",
            "data": plugin.get_stats(),
        }

    @router.post("/plugins/{plugin_name}/enable")
    async def enable_plugin(plugin_name: str):
        """启用插件"""
        if not plugin_manager:
            return JSONResponse(
                status_code=503,
                content={"code": 503, "message": "Plugin manager not available", "data": None},
            )

        success = await plugin_manager.enable(plugin_name)
        if not success:
            return JSONResponse(
                status_code=404,
                content={"code": 404, "message": f"Plugin '{plugin_name}' not found", "data": None},
            )

        return {
            "code": 0,
            "message": f"Plugin '{plugin_name}' enabled",
            "data": {"plugin": plugin_name, "enabled": True},
        }

    @router.post("/plugins/{plugin_name}/disable")
    async def disable_plugin(plugin_name: str):
        """禁用插件"""
        if not plugin_manager:
            return JSONResponse(
                status_code=503,
                content={"code": 503, "message": "Plugin manager not available", "data": None},
            )

        success = await plugin_manager.disable(plugin_name)
        if not success:
            return JSONResponse(
                status_code=404,
                content={"code": 404, "message": f"Plugin '{plugin_name}' not found", "data": None},
            )

        return {
            "code": 0,
            "message": f"Plugin '{plugin_name}' disabled",
            "data": {"plugin": plugin_name, "enabled": False},
        }

    # ===================================================================
    # 综合统计
    # ===================================================================

    @router.get("/stats")
    async def get_all_stats():
        """获取所有统计信息"""
        result: Dict[str, Any] = {
            "timestamp": int(time.time()),
        }

        if proxy_service:
            result["proxy"] = proxy_service.get_metrics()

        if token_bucket_limiter:
            result["rate_limit"] = token_bucket_limiter.get_stats()

        if advanced_circuit_breaker:
            result["circuit_breakers"] = advanced_circuit_breaker.get_stats()

        if retry_manager:
            result["retry"] = retry_manager.get_stats()

        if response_cache:
            result["cache"] = response_cache.get_stats()

        if plugin_manager:
            result["plugins"] = plugin_manager.get_stats()

        return {
            "code": 0,
            "message": "success",
            "data": result,
        }

    @router.get("/metrics/prometheus")
    async def get_prometheus_metrics():
        """获取 Prometheus 格式指标"""
        lines = []

        if plugin_manager:
            metrics_plugin = plugin_manager.get_plugin("metrics")
            if metrics_plugin and hasattr(metrics_plugin, "get_prometheus_metrics"):
                lines.append(metrics_plugin.get_prometheus_metrics())

        if response_cache:
            cache_stats = response_cache.get_stats()
            lines.append("# HELP gateway_cache_hits_total Total cache hits")
            lines.append("# TYPE gateway_cache_hits_total counter")
            lines.append(f'gateway_cache_hits_total {cache_stats.get("cache_hits", 0)}')
            lines.append("# HELP gateway_cache_misses_total Total cache misses")
            lines.append("# TYPE gateway_cache_misses_total counter")
            lines.append(f'gateway_cache_misses_total {cache_stats.get("cache_misses", 0)}')

        if retry_manager:
            retry_stats = retry_manager.get_stats()
            lines.append("# HELP gateway_retries_total Total retries")
            lines.append("# TYPE gateway_retries_total counter")
            lines.append(f'gateway_retries_total {retry_stats.get("total_retries", 0)}')

        return PlainTextResponse(content="\n".join(lines) + "\n", media_type="text/plain")

    return router
