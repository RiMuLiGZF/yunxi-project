"""
云汐 API 网关 - 主入口
"""
import time
import sys
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
from .services.proxy_service import get_proxy_service

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
    logger.info(f"Loaded {len(settings.routes)} module routes")
    yield
    # 关闭时
    proxy = get_proxy_service()
    await proxy.close()
    logger.info("Yunxi API Gateway stopped")


app = FastAPI(
    title="云汐 API 网关",
    description="Yunxi API Gateway - 统一接入层，负责路由转发、认证鉴权、限流熔断",
    version="1.0.0",
    lifespan=lifespan,
)

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
        exclude_paths=["/health", "/m8/health", "/m8/metrics", "/routes"],
    )
    logger.info("可观测性中间件已注册（统一日志 + 链路追踪 + 慢请求告警）")

# 速率限制中间件
app.add_middleware(RateLimitMiddleware)

# 认证中间件
app.add_middleware(AuthMiddleware)


@app.get("/health")
async def health_check():
    """网关健康检查"""
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "status": "healthy",
            "service": "yunxi-api-gateway",
            "version": "1.0.0",
            "routes_count": len(settings.routes),
            "timestamp": int(time.time()),
        },
    }


@app.get("/m8/health")
async def m8_health():
    """M8标准健康检查接口"""
    proxy = get_proxy_service()
    circuit_stats = proxy._circuit_breaker.get_stats()
    
    healthy_count = sum(
        1 for s in circuit_stats.values() if s["state"] == "closed"
    )
    
    return {
        "code": 0,
        "message": "healthy",
        "data": {
            "status": "healthy",
            "version": "1.0.0",
            "uptime": 0,
            "modules": {
                "total": len(settings.routes),
                "healthy": healthy_count,
                "circuit_breakers": circuit_stats,
            },
        },
    }


@app.get("/m8/metrics")
async def m8_metrics():
    """M8标准指标接口"""
    from .services.rate_limiter import get_rate_limiter
    
    rate_stats = get_rate_limiter().get_stats()
    proxy = get_proxy_service()
    circuit_stats = proxy._circuit_breaker.get_stats()
    
    return {
        "code": 0,
        "message": "success",
        "data": {
            "rate_limit": rate_stats,
            "circuit_breakers": circuit_stats,
            "routes_count": len(settings.routes),
        },
    }


@app.get("/routes")
async def list_routes():
    """列出所有路由配置"""
    return {
        "code": 0,
        "message": "success",
        "data": [
            {
                "key": r.key,
                "name": r.name,
                "prefix": r.prefix,
                "target": r.target_url,
                "enabled": r.enabled,
                "timeout": r.timeout,
            }
            for r in settings.routes
        ],
    }


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
async def proxy_request(request: Request, path: str):
    """
    通用代理转发
    
    将请求根据路径前缀转发到对应的模块服务。
    例如：
      /m8/api/v1/chat  →  M8 控制塔 /api/v1/chat
      /m1/agents       →  M1 Agent集群 /agents
    """
    full_path = "/" + path
    proxy = get_proxy_service()
    
    # 获取客户端IP
    client_ip = request.client.host if request.client else "unknown"
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        client_ip = xff.split(",")[0].strip()
    
    # 读取请求体
    body = await request.body()
    
    # 转发请求
    status_code, response_headers, response_body = await proxy.forward_request(
        method=request.method,
        path=full_path,
        headers=dict(request.headers),
        query_params=dict(request.query_params),
        body=body,
        client_ip=client_ip,
    )
    
    return Response(
        content=response_body,
        status_code=status_code,
        headers=response_headers,
    )


logger.info("Yunxi API Gateway initialized")
