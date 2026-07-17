"""
云汐 API 网关 - 主入口（增强版）

功能特性：
1. 12个模块全量路由接入（M1-M12）
2. HTTP 代理转发 + SSE 流式透传
3. JWT + API Key 双重认证
4. 令牌桶限流 + 分级限速
5. 熔断器（按模块独立配置）
6. 网关管理 API（routes/status/metrics/reload）
7. 请求链路追踪（X-Trace-Id 透传）
8. 用户信息注入（X-User-Id 等）
"""
import time
import sys
import uuid
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

# 将项目根目录加入 path，以便导入 shared 模块
_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from .config import settings
from .middleware.auth import AuthMiddleware
from .middleware.rate_limit import RateLimitMiddleware
from .services.proxy_service import get_proxy_service_sync, ProxyService

# 统一日志和可观测性（优先使用 shared observability，回退到标准 logging）
try:
    from shared.core.observability import init_module_logger, ObservabilityMiddleware
    _observability_available = True
except ImportError:
    import logging
    _observability_available = False
    ObservabilityMiddleware = None  # type: ignore

# 初始化日志系统
if _observability_available:
    logger = init_module_logger("gateway")
else:
    import logging
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger("yunxi-gateway")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期"""
    # 启动时
    logger.info(f"Starting Yunxi API Gateway on {settings.host}:{settings.port}...")
    logger.info(f"Loaded {len(settings.routes)} module routes:")
    for route in settings.routes:
        status = "enabled" if route.enabled else "disabled"
        logger.info(
            f"  [{status}] {route.key:4s} - {route.name:20s} "
            f"-> {route.target_url} (timeout={route.timeout}s)"
        )

    # 预初始化代理服务
    proxy = get_proxy_service_sync()
    app.state.proxy = proxy

    yield

    # 关闭时
    proxy = app.state.proxy
    await proxy.close()
    logger.info("Yunxi API Gateway stopped")


app = FastAPI(
    title="云汐 API 网关",
    description="Yunxi API Gateway - 统一接入层，负责路由转发、认证鉴权、限流熔断、链路追踪",
    version="2.0.0",
    lifespan=lifespan,
)

# 安全头中间件（X-Content-Type-Options, X-Frame-Options, CSP, HSTS 等）
try:
    _project_root_sec = Path(__file__).resolve().parent.parent.parent
    if str(_project_root_sec) not in sys.path:
        sys.path.insert(0, str(_project_root_sec))
    from shared.core.middleware.security_headers import SecurityHeadersMiddleware
    _security_headers_available = True
except ImportError:
    _security_headers_available = False

if _security_headers_available:
    _sec_env = settings.env.lower()
    _sec_is_prod = _sec_env in ("production", "prod", "release")
    app.add_middleware(
        SecurityHeadersMiddleware,
        env="production" if _sec_is_prod else "development",
    )
    logger.info("安全响应头中间件已注册")

# CORS 中间件（统一安全策略：生产环境禁用通配符，开发环境默认localhost）
def _resolve_cors_origins() -> list:
    """解析 CORS 来源列表，应用统一安全策略"""
    env = settings.env.lower()
    is_prod = env in ("production", "prod", "release")
    raw = settings.cors_origins

    if raw == "*" or not raw.strip():
        if is_prod:
            raise RuntimeError(
                "[CORS] 生产环境安全校验失败：API-Gateway 的 CORS origins "
                f"配置为 '{raw}'。生产环境必须显式配置具体的允许来源，"
                "禁止使用通配符 '*'。请设置 GATEWAY_CORS_ORIGINS 或 CORS_ORIGINS 环境变量。"
            )
        # 开发环境默认 localhost 常用端口
        dev_ports = [3000, 5173, 8080] + list(range(8000, 8013))
        origins = [f"http://localhost:{p}" for p in dev_ports] + \
                  [f"http://127.0.0.1:{p}" for p in dev_ports]
        logger.warning(
            f"[CORS] 开发环境 CORS 配置为 '{raw}'，"
            f"已自动替换为 localhost 默认端口列表（{len(origins)} 个来源）。"
        )
        return origins

    return [o.strip() for o in raw.split(",") if o.strip()]


_cors_origins = _resolve_cors_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 可观测性中间件（统一日志 + 链路追踪 + 慢请求告警）
if _observability_available:
    app.add_middleware(
        ObservabilityMiddleware,
        service_name="gateway",
        log_level=settings.log_level,
        slow_request_threshold=5.0,  # 网关超时阈值稍高
        exclude_paths=["/health", "/gateway/health", "/gateway/metrics", "/gateway/routes"],
    )
    logger.info("可观测性中间件已注册（统一日志 + 链路追踪 + 慢请求告警）")

# 速率限制中间件
app.add_middleware(RateLimitMiddleware)

# 认证中间件
app.add_middleware(AuthMiddleware)


# ============================================================================
# 标准化可观测性路由（健康检查 + Prometheus 指标）
# ============================================================================
if _observability_available:
    try:
        from shared.core.observability import HealthChecker, create_observability_router
        from shared.core.health import CheckResult

        # 创建网关健康检查器
        gw_checker = HealthChecker(
            module_name="gateway",
            version="2.0.0",
            module_display_name="API 网关",
        )

        # 注册轻量检查：内存
        gw_checker.register_memory_check(threshold_percent=90.0, lightweight=True)

        # 注册轻量检查：磁盘
        gw_checker.register_disk_check(
            path=".",
            threshold_percent=90.0,
            lightweight=True,
        )

        # 注册轻量检查：路由配置
        def _check_routes() -> CheckResult:
            start_t = time.time()
            total = len(settings.routes)
            enabled = sum(1 for r in settings.routes if r.enabled)
            resp_ms = (time.time() - start_t) * 1000
            return CheckResult.healthy(
                total_routes=total,
                enabled_routes=enabled,
                disabled_routes=total - enabled,
                response_time_ms=resp_ms,
            )

        gw_checker.register_check("routes", _check_routes, critical=False, lightweight=True)

        # 注册深度检查：所有模块健康状态
        async def _check_modules_health() -> CheckResult:
            start_t = time.time()
            try:
                proxy: ProxyService = app.state.proxy
                health_results = await proxy.health_check_all()
                total = len(health_results)
                healthy = sum(
                    1 for h in health_results.values()
                    if h.get("status") == "healthy"
                )
                unhealthy = sum(
                    1 for h in health_results.values()
                    if h.get("status") in ("unhealthy", "unreachable")
                )
                resp_ms = (time.time() - start_t) * 1000

                if unhealthy == 0:
                    return CheckResult.healthy(
                        total_modules=total,
                        healthy_modules=healthy,
                        unhealthy_modules=unhealthy,
                        response_time_ms=resp_ms,
                    )
                elif unhealthy < total * 0.5:
                    return CheckResult.degraded(
                        error=f"{unhealthy} modules unhealthy",
                        total_modules=total,
                        healthy_modules=healthy,
                        unhealthy_modules=unhealthy,
                        response_time_ms=resp_ms,
                    )
                else:
                    return CheckResult.unhealthy(
                        error=f"Majority of modules unhealthy ({unhealthy}/{total})",
                        total_modules=total,
                        healthy_modules=healthy,
                        unhealthy_modules=unhealthy,
                        response_time_ms=resp_ms,
                    )
            except Exception as e:
                resp_ms = (time.time() - start_t) * 1000
                return CheckResult.degraded(
                    error=str(e),
                    response_time_ms=resp_ms,
                )

        gw_checker.register_async_check(
            "modules_health",
            _check_modules_health,
            critical=False,
            lightweight=False,
        )

        # 注册深度检查：熔断器状态
        def _check_circuit_breakers() -> CheckResult:
            start_t = time.time()
            try:
                from .services.circuit_breaker import get_circuit_breaker
                cb = get_circuit_breaker()
                stats = cb.get_stats()
                total = len(stats)
                open_count = sum(1 for s in stats.values() if s.get("state") == "open")
                half_open_count = sum(1 for s in stats.values() if s.get("state") == "half_open")
                resp_ms = (time.time() - start_t) * 1000

                if open_count == 0:
                    return CheckResult.healthy(
                        total_circuits=total,
                        open_circuits=open_count,
                        half_open_circuits=half_open_count,
                        closed_circuits=total - open_count - half_open_count,
                        response_time_ms=resp_ms,
                    )
                elif open_count < total * 0.5:
                    return CheckResult.degraded(
                        error=f"{open_count} circuits open",
                        total_circuits=total,
                        open_circuits=open_count,
                        half_open_circuits=half_open_count,
                        response_time_ms=resp_ms,
                    )
                else:
                    return CheckResult.unhealthy(
                        error=f"Majority of circuits open ({open_count}/{total})",
                        total_circuits=total,
                        open_circuits=open_count,
                        response_time_ms=resp_ms,
                    )
            except Exception as e:
                resp_ms = (time.time() - start_t) * 1000
                return CheckResult.degraded(
                    error=str(e),
                    response_time_ms=resp_ms,
                )

        gw_checker.register_check(
            "circuit_breakers",
            _check_circuit_breakers,
            critical=False,
            lightweight=False,
        )

        # 注册深度检查：限流器
        def _check_rate_limiter() -> CheckResult:
            start_t = time.time()
            try:
                from .services.rate_limiter import get_rate_limiter
                rl = get_rate_limiter()
                stats = rl.get_stats()
                resp_ms = (time.time() - start_t) * 1000
                return CheckResult.healthy(
                    rate_limit_stats=stats,
                    response_time_ms=resp_ms,
                )
            except Exception as e:
                resp_ms = (time.time() - start_t) * 1000
                return CheckResult.degraded(
                    error=str(e),
                    response_time_ms=resp_ms,
                )

        gw_checker.register_check(
            "rate_limiter",
            _check_rate_limiter,
            critical=False,
            lightweight=False,
        )

        # 创建可观测性路由并注册
        obs_router = create_observability_router(
            service_name="gateway",
            version="2.0.0",
            health_checker=gw_checker,
        )
        app.include_router(obs_router)
        logger.info("标准化可观测性路由已注册（/health + /metrics）")
    except Exception as e:
        logger.warning(f"标准化可观测性路由注册失败: {e}")


# ============================================================================
# 网关管理 API（/gateway/*）
# ============================================================================

@app.get("/health")
async def health_check():
    """网关健康检查"""
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "status": "healthy",
            "service": "yunxi-api-gateway",
            "version": "2.0.0",
            "routes_count": len(settings.routes),
            "timestamp": int(time.time()),
        },
    }


@app.get("/gateway/health")
async def gateway_health():
    """网关健康检查（标准路径）"""
    return await health_check()


@app.get("/gateway/routes")
async def list_routes():
    """查看所有路由配置"""
    routes_info = []
    for route in settings.routes:
        routes_info.append({
            "key": route.key,
            "name": route.name,
            "description": route.description,
            "prefix": route.prefix,
            "target_url": route.target_url,
            "enabled": route.enabled,
            "timeout": route.timeout,
            "health_path": route.health_path,
            "auth_required": route.auth_required,
            "public_paths": route.public_paths,
            "rate_limit_per_minute": route.rate_limit_per_minute,
            "rate_limit_per_ip": route.rate_limit_per_ip,
            "rate_limit_tier": route.rate_limit_tier,
            "supports_websocket": route.supports_websocket,
            "supports_sse": route.supports_sse,
            "cb_failure_threshold": route.cb_failure_threshold,
            "cb_recovery_time": route.cb_recovery_time,
        })

    return {
        "code": 0,
        "message": "success",
        "data": {
            "total": len(routes_info),
            "enabled_count": sum(1 for r in settings.routes if r.enabled),
            "routes": routes_info,
        },
    }


@app.get("/gateway/routes/{route_key}")
async def get_route_detail(route_key: str):
    """查看单个路由配置详情"""
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

    return {
        "code": 0,
        "message": "success",
        "data": {
            "key": route.key,
            "name": route.name,
            "description": route.description,
            "prefix": route.prefix,
            "target_url": route.target_url,
            "enabled": route.enabled,
            "timeout": route.timeout,
            "health_path": route.health_path,
            "health_timeout": route.health_timeout,
            "auth_required": route.auth_required,
            "public_paths": route.public_paths,
            "rate_limit_per_minute": route.rate_limit_per_minute,
            "rate_limit_per_ip": route.rate_limit_per_ip,
            "rate_limit_tier": route.rate_limit_tier,
            "supports_websocket": route.supports_websocket,
            "supports_sse": route.supports_sse,
            "cb_failure_threshold": route.cb_failure_threshold,
            "cb_recovery_time": route.cb_recovery_time,
        },
    }


@app.get("/gateway/status")
async def gateway_status():
    """查看网关状态（各模块健康状态 + 熔断器状态）"""
    proxy: ProxyService = app.state.proxy

    # 获取各模块健康状态（异步执行）
    health_results = await proxy.health_check_all()

    # 获取熔断器状态
    from .services.circuit_breaker import get_circuit_breaker
    cb_stats = get_circuit_breaker().get_stats()

    # 统计汇总
    modules_total = len(settings.routes)
    modules_healthy = sum(
        1 for h in health_results.values()
        if h.get("status") == "healthy"
    )
    modules_unhealthy = sum(
        1 for h in health_results.values()
        if h.get("status") in ("unhealthy", "unreachable")
    )
    modules_disabled = sum(
        1 for h in health_results.values()
        if h.get("status") == "disabled"
    )
    circuits_open = sum(
        1 for s in cb_stats.values()
        if s.get("state") == "open"
    )
    circuits_half_open = sum(
        1 for s in cb_stats.values()
        if s.get("state") == "half_open"
    )

    overall_status = "healthy"
    if modules_unhealthy > modules_total * 0.5:
        overall_status = "degraded"
    if circuits_open > 3:
        overall_status = "critical"

    return {
        "code": 0,
        "message": "success",
        "data": {
            "gateway": {
                "status": overall_status,
                "version": "2.0.0",
                "uptime": int(time.time() - proxy.get_metrics().get("uptime_seconds", 0)),
                "timestamp": int(time.time()),
            },
            "modules": {
                "total": modules_total,
                "healthy": modules_healthy,
                "unhealthy": modules_unhealthy,
                "disabled": modules_disabled,
                "details": health_results,
            },
            "circuit_breakers": {
                "total": len(cb_stats),
                "open": circuits_open,
                "half_open": circuits_half_open,
                "closed": len(cb_stats) - circuits_open - circuits_half_open,
                "details": cb_stats,
            },
        },
    }


@app.get("/gateway/metrics")
async def gateway_metrics():
    """查看网关指标（请求量、延迟、错误率、限流统计）"""
    proxy: ProxyService = app.state.proxy
    proxy_metrics = proxy.get_metrics()

    # 限流统计
    from .services.rate_limiter import get_rate_limiter
    rate_stats = get_rate_limiter().get_stats()

    # 熔断器统计
    from .services.circuit_breaker import get_circuit_breaker
    cb_stats = get_circuit_breaker().get_stats()

    return {
        "code": 0,
        "message": "success",
        "data": {
            "proxy": proxy_metrics,
            "rate_limit": rate_stats,
            "circuit_breakers": {
                "total": len(cb_stats),
                "details": cb_stats,
            },
            "routes_count": len(settings.routes),
        },
    }


@app.post("/gateway/routes/{route_key}/reload")
async def reload_route(route_key: str):
    """重新加载指定路由配置（重建HTTP客户端连接）"""
    proxy: ProxyService = app.state.proxy

    # 检查路由是否存在
    route_exists = any(r.key == route_key for r in settings.routes)
    if not route_exists:
        return JSONResponse(
            status_code=404,
            content={
                "code": 404,
                "message": f"Route '{route_key}' not found",
                "data": None,
            },
        )

    await proxy.reload_route(route_key)

    return {
        "code": 0,
        "message": f"Route '{route_key}' reloaded successfully",
        "data": {
            "route_key": route_key,
            "reloaded": True,
            "timestamp": int(time.time()),
        },
    }


@app.post("/gateway/routes/reload")
async def reload_all_routes():
    """重新加载所有路由配置"""
    proxy: ProxyService = app.state.proxy
    count = await proxy.reload_all_routes()

    return {
        "code": 0,
        "message": f"All {count} routes reloaded successfully",
        "data": {
            "reloaded_count": count,
            "timestamp": int(time.time()),
        },
    }


@app.post("/gateway/circuit-breakers/{route_key}/reset")
async def reset_circuit_breaker(route_key: str):
    """重置指定模块的熔断器"""
    from .services.circuit_breaker import get_circuit_breaker
    cb = get_circuit_breaker()

    success = await cb.reset(route_key)

    if not success:
        return JSONResponse(
            status_code=404,
            content={
                "code": 404,
                "message": f"Circuit breaker for '{route_key}' not found",
                "data": None,
            },
        )

    return {
        "code": 0,
        "message": f"Circuit breaker for '{route_key}' reset",
        "data": {
            "route_key": route_key,
            "reset": True,
        },
    }


@app.post("/gateway/circuit-breakers/reset")
async def reset_all_circuit_breakers():
    """重置所有熔断器"""
    from .services.circuit_breaker import get_circuit_breaker
    cb = get_circuit_breaker()
    await cb.reset_all()

    return {
        "code": 0,
        "message": "All circuit breakers reset",
        "data": {
            "reset": True,
        },
    }


# 兼容旧接口
@app.get("/m8/health")
async def m8_health():
    """M8标准健康检查接口（兼容旧路径）"""
    return await gateway_status()


@app.get("/m8/metrics")
async def m8_metrics():
    """M8标准指标接口（兼容旧路径）"""
    return await gateway_metrics()


@app.get("/routes")
async def list_routes_old():
    """列出所有路由配置（兼容旧路径）"""
    return await list_routes()


# ============================================================================
# 通用代理转发
# ============================================================================

def _get_client_ip(request: Request) -> str:
    """获取客户端真实IP"""
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()

    xri = request.headers.get("X-Real-IP")
    if xri:
        return xri

    return request.client.host if request.client else "unknown"


def _is_sse_request(request: Request) -> bool:
    """判断是否为 SSE 请求"""
    accept = request.headers.get("accept", "").lower()
    if "text/event-stream" in accept:
        return True

    path = request.url.path
    sse_patterns = ["/sse", "/stream", "/events", "/watch"]
    for pattern in sse_patterns:
        if path.endswith(pattern) or f"{pattern}/" in path:
            return True

    return False


@app.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
)
async def proxy_request(request: Request, path: str):
    """
    通用代理转发

    将请求根据路径前缀转发到对应的模块服务。
    支持：
    - 普通 HTTP 请求转发
    - SSE 流式透传
    - 用户信息注入请求头
    - 链路追踪 ID 透传

    例如：
      /m8/api/v1/chat  ->  M8 控制塔 /api/v1/chat
      /m1/agents       ->  M1 Agent集群 /agents
      /m11/sse         ->  M11 MCP总线 SSE 流
    """
    full_path = "/" + path
    proxy: ProxyService = app.state.proxy

    # 获取客户端IP
    client_ip = _get_client_ip(request)

    # 获取用户信息（认证中间件已注入）
    user_info = None
    if hasattr(request.state, "authenticated") and request.state.authenticated:
        user_info = getattr(request.state, "user", None)

    # 读取请求体
    body = await request.body()

    # 判断是否为 SSE 请求
    if _is_sse_request(request):
        # SSE 流式透传
        sse_stream = await proxy.forward_sse(
            method=request.method,
            path=full_path,
            headers=dict(request.headers),
            query_params=dict(request.query_params),
            body=body,
            client_ip=client_ip,
            user_info=user_info,
        )

        if sse_stream is None:
            # SSE 转发失败，降级为普通错误响应
            return JSONResponse(
                status_code=502,
                content={
                    "code": 502,
                    "message": "SSE stream unavailable",
                    "data": None,
                },
            )

        return StreamingResponse(
            sse_stream,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # 普通 HTTP 请求转发
    status_code, response_headers, response_body = await proxy.forward_request(
        method=request.method,
        path=full_path,
        headers=dict(request.headers),
        query_params=dict(request.query_params),
        body=body,
        client_ip=client_ip,
        user_info=user_info,
    )

    # 确保响应头包含 trace_id
    if not any(k.lower() == "x-trace-id" for k in response_headers):
        trace_id = request.headers.get("X-Trace-Id", uuid.uuid4().hex)
        response_headers["X-Trace-Id"] = trace_id

    return Response(
        content=response_body,
        status_code=status_code,
        headers=response_headers,
    )


logger.info("Yunxi API Gateway v2.0.0 initialized (12 modules full routing)")
