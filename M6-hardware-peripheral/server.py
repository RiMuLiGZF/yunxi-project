"""
M6 硬件外设模拟服务 - FastAPI 启动入口

云汐系统模块六：智能穿戴与硬件外设模拟服务
提供设备管理、传感器数据采集、SSE 实时推送等能力

运行方式:
    python server.py

默认端口: 8006 (通过环境变量 M6_PORT 配置)
"""

from __future__ import annotations

import os
import hmac
import sys
import time
import uuid
import logging
from pathlib import Path
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

# ---------------------------------------------------------------------------
# 统一基础设施接入（第二阶段：shared.core）
# 优先使用统一实现，失败则回退到模块原有实现
# ---------------------------------------------------------------------------

# 尝试将项目根目录加入 path
try:
    _current_m6 = Path(__file__).resolve()
    for _ in range(10):
        _current_m6 = _current_m6.parent
        if (_current_m6 / "shared" / "core" / "observability" / "__init__.py").exists():
            if str(_current_m6) not in sys.path:
                sys.path.insert(0, str(_current_m6))
            break
except Exception:
    pass

# 统一可观测性
try:
    from shared.core.observability import init_module_logger, ObservabilityMiddleware
    _unified_observability_m6 = True
except ImportError:
    _unified_observability_m6 = False
    ObservabilityMiddleware = None  # type: ignore

# 统一异常处理器
try:
    from shared.core.responses import register_global_exception_handler
    _unified_exception_handler_m6 = True
except ImportError:
    _unified_exception_handler_m6 = False

# 统一日志 logger（优先使用）
if _unified_observability_m6:
    logger = init_module_logger("m6")
else:
    logger = logging.getLogger("m6")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# 路径配置
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
PKG_DIR = BASE_DIR / "m6_hardware"

# 确保 BASE_DIR 在 sys.path 中
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# ---------------------------------------------------------------------------
# 导入 M6 核心组件
# ---------------------------------------------------------------------------
from m6_hardware.config import M6Config
from m6_hardware.api import api_router
from m6_hardware.api.m8_auth_middleware import M8AuthMiddleware
from m6_hardware.services.device_manager import DeviceManager
from m6_hardware.services.data_collector import DataCollector
from m6_hardware.services.notification import NotificationService
from m6_hardware.realtime.sse_manager import SSEManager
from m6_hardware.models.errors import M6Exception

# P2-2/P2-4 改造：导入熔断器与指标收集器
from m6_hardware.utils.circuit_breaker import CircuitBreaker
from m6_hardware.utils.metrics import Metrics

# ---------------------------------------------------------------------------
# 生命周期管理
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理

    P0-4 改造：按顺序创建各服务实例并注入依赖，存入 app.state，
    消除 __new__ 单例的竞态条件风险。

    初始化顺序: config -> device_manager -> data_collector -> notification_service -> sse_manager
    """
    # ===== 启动时初始化 =====
    logger.info("=" * 60)
    logger.info("  M6 硬件外设模拟服务 - 启动中...")
    logger.info("=" * 60)

    # 1. 加载配置
    config = M6Config()
    app.state.config = config
    logger.info(f"  配置: 已加载 (环境: {config.env})")

    # P2-2/P2-4: 初始化全局指标收集器与数据采集熔断器
    metrics = Metrics()
    app.state.metrics = metrics
    collector_breaker = CircuitBreaker(
        name="data_collector",
        failure_threshold=5,
        recovery_timeout=30.0,
    )
    app.state.collector_breaker = collector_breaker
    logger.info("  Metrics 指标收集器: 已就绪")
    logger.info(f"  数据采集熔断器: 已就绪 (阈值={collector_breaker.failure_threshold}, 恢复={collector_breaker.recovery_timeout}s)")

    # 2. 初始化设备管理器
    device_manager = DeviceManager()
    app.state.device_manager = device_manager
    device_stats = device_manager.get_stats()
    logger.info(f"  设备管理器: 已加载 {device_stats['total']} 台设备", device_total=device_stats['total'])
    logger.info(f"    - 在线: {device_stats['online']}  离线: {device_stats['offline']}  警告: {device_stats['warning']}",
                device_online=device_stats['online'], device_offline=device_stats['offline'], device_warning=device_stats['warning'])

    # 3. 初始化数据采集服务（注入 config 和 device_manager）
    data_collector = DataCollector(config=config, device_manager=device_manager)
    app.state.data_collector = data_collector
    logger.info(f"  数据采集服务: 已就绪 (间隔 {config.collection_interval}s)", collection_interval=config.collection_interval)
    await data_collector.start()

    # 4. 初始化通知服务（注入 device_manager）
    notification_service = NotificationService(device_manager=device_manager)
    app.state.notification_service = notification_service
    logger.info("  通知推送服务: 已就绪")

    # 5. 初始化 SSE 推送服务（注入 device_manager 和 notification_service）
    sse_manager = SSEManager(
        device_manager=device_manager,
        notification_service=notification_service,
    )
    app.state.sse_manager = sse_manager
    await sse_manager.start()
    logger.info("  SSE 推送服务: 已启动")

    logger.info("-" * 60)
    logger.info(f"  模拟模式: {'开启' if config.simulation_mode else '关闭'}", simulation_mode=config.simulation_mode)
    logger.info(f"  数据库: {config.database_path}", database_path=config.database_path)
    logger.info("=" * 60)

    yield

    # ===== 关闭时清理 =====
    logger.info("正在关闭 M6 硬件外设服务...")
    data_collector = app.state.data_collector
    await data_collector.stop()
    sse_manager = app.state.sse_manager
    await sse_manager.stop()
    logger.info("M6 硬件外设服务已关闭")


# ---------------------------------------------------------------------------
# FastAPI 应用
# ---------------------------------------------------------------------------
app = FastAPI(
    title="M6 硬件外设模拟服务 API",
    description="云汐系统模块六：智能穿戴设备、无人机、桌面终端等硬件外设的模拟服务，支持实时传感器数据采集和SSE推送",
    version="1.2.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# P1-4: 统一异常处理器
# ---------------------------------------------------------------------------
@app.exception_handler(M6Exception)
async def m6_exception_handler(request, exc: M6Exception):
    """捕获 M6Exception 并返回标准化 JSONResponse"""
    return exc.to_json_response()

# ---------------------------------------------------------------------------
# CORS 中间件（统一安全策略：生产环境禁用通配符，开发环境默认localhost）
# ---------------------------------------------------------------------------
from m6_hardware.config import get_config as _get_config_compat
_cors_config = _get_config_compat()
_cors_env = os.environ.get("YUNXI_ENV", os.environ.get("ENV", "development")).lower()
_cors_is_prod = _cors_env in ("production", "prod", "release")
_cors_raw = _cors_config.cors_origins

if _cors_raw == "*" or not _cors_raw.strip():
    if _cors_is_prod:
        raise RuntimeError(
            "[CORS] 生产环境安全校验失败：M6 硬件外设的 CORS origins "
            f"配置为 '{_cors_raw}'。生产环境必须显式配置具体的允许来源，"
            "禁止使用通配符 '*'。请设置 CORS_ORIGINS 环境变量。"
        )
    # 开发环境默认 localhost 常用端口
    _cors_dev_ports = [3000, 5173, 8080] + list(range(8000, 8013))
    allow_origins = [f"http://localhost:{p}" for p in _cors_dev_ports] + \
                    [f"http://127.0.0.1:{p}" for p in _cors_dev_ports]
else:
    allow_origins = [o.strip() for o in _cors_raw.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# M8 统一鉴权中间件
app.add_middleware(M8AuthMiddleware)

# 可观测性中间件（统一日志 + 链路追踪 + 慢请求告警）
if _unified_observability_m6 and ObservabilityMiddleware is not None:
    app.add_middleware(
        ObservabilityMiddleware,
        service_name="m6",
        log_level="INFO",
        slow_request_threshold=3.0,
        exclude_paths=["/api/v1/health", "/health"],
    )
    logger.info("可观测性中间件已注册（统一日志 + 链路追踪 + 慢请求告警）")


# ---------------------------------------------------------------------------
# 请求中间件：request_id 注入
# ---------------------------------------------------------------------------
@app.middleware("http")
async def add_request_id(request: Request, call_next):
    """为每个请求注入 request_id，记录响应时间，并埋点 Metrics 指标

    P2-4 改造：在中间件层统一记录请求数、响应延迟直方图，
    Metrics 单例随 app.state 注入。
    """
    start_time = time.time()
    request_id = uuid.uuid4().hex[:16]
    request.state.request_id = request_id

    response = await call_next(request)

    elapsed_ms = (time.time() - start_time) * 1000
    response.headers["X-Request-Id"] = request_id
    response.headers["X-Response-Time"] = f"{elapsed_ms:.2f}ms"

    # P2-4 埋点：请求计数 + 延迟直方图
    try:
        metrics: Metrics = request.app.state.metrics
        metrics.inc("requests_total", labels={"path": request.url.path, "method": request.method})
        metrics.inc("response_status", labels={"code": str(response.status_code)})
        metrics.observe("response_latency_ms", elapsed_ms)
    except Exception:
        pass  # Metrics 不可用时静默降级

    return response


# ---------------------------------------------------------------------------
# 根路径 - 服务信息
# ---------------------------------------------------------------------------
@app.get("/", tags=["Info"], summary="服务信息")
async def root(request: Request):
    """根路径：返回服务基本信息"""
    device_manager = request.app.state.device_manager
    config = request.app.state.config
    stats = device_manager.get_stats()

    return {
        "name": "M6 硬件外设模拟服务",
        "module": "m6-hardware",
        "version": "1.0.0",
        "status": "running",
        "simulation_mode": config.simulation_mode,
        "docs": "/docs",
        "openapi": "/openapi.json",
        "device_stats": stats,
        "endpoints": {
            "health": "/api/v1/health",
            "devices": "/api/v1/devices",
            "sensors": "/api/v1/sensors",
            "control": "/api/v1/control",
            "sse": "/api/v1/sse/stream",
        },
    }


# ---------------------------------------------------------------------------
# 健康检查（标准端点）
# ---------------------------------------------------------------------------
@app.get("/health", tags=["Health"], summary="健康检查")
async def health():
    """标准健康检查端点"""
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "status": "healthy",
            "module": "m6-hardware",
            "version": "1.0.0",
        },
        "request_id": uuid.uuid4().hex[:16],
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# M8 标准对接接口
# ---------------------------------------------------------------------------
from fastapi import Header, HTTPException

_start_time_m8 = time.time()

def _is_production_env() -> bool:
    """检查是否处于生产环境.

    当 YUNXI_ENV 设置为 production 或 prod 时返回 True.
    """
    return os.environ.get("YUNXI_ENV", "").lower() in ("production", "prod")


def _verify_m8_token(x_m8_token: str = "") -> bool:
    """验证 M8 管理令牌（使用 hmac.compare_digest 防止时序攻击）.

    安全策略：
    - 生产环境（YUNXI_ENV=production/prod）：token 未配置时拒绝访问（secure by default）
    - 开发环境（默认）：token 未配置时放行并告警，便于本地调试
    - token 存在时：使用 hmac.compare_digest 安全比较
    """
    expected = os.environ.get("M6_ADMIN_TOKEN", "")
    if not expected:
        if _is_production_env():
            logger.warning(
                "m6.auth.token_not_configured_rejected",
                message="M6_ADMIN_TOKEN 未配置，生产环境下 M8 标准接口拒绝所有访问",
            )
            return False
        logger.warning(
            "m6.auth.dev_mode_no_token",
            message="M6_ADMIN_TOKEN 未配置，开发环境下 M8 标准接口允许空 token 访问",
        )
        return True
    # 拒绝空 Token，防止空值绕过
    if not x_m8_token:
        return False
    return hmac.compare_digest(x_m8_token, expected)


def _get_m6_real_metrics(request: Request | None = None):
    """获取真实 M6 性能指标

    P0-4 改造：优先从 request.app.state 获取服务实例；
    若 request 为 None 则回退到兼容层。
    """
    import os
    try:
        import psutil
        cpu_usage = psutil.cpu_percent(interval=0.1)
        memory_mb = int(psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024)
    except Exception:
        cpu_usage = 0.0
        memory_mb = 0
    
    devices_online = 0
    sensors_total = 0
    try:
        if request is not None:
            dm = request.app.state.device_manager
        else:
            from m6_hardware.services.device_manager import get_device_manager
            dm = get_device_manager()
        devices = dm.list_devices()
        devices_online = sum(1 for d in devices if d.get("status") == "online")
        sensors_total = sum(len(d.get("sensors", [])) for d in devices)
    except Exception:
        pass
    
    sse_connections = 0
    try:
        if request is not None:
            sm = request.app.state.sse_manager
        else:
            from m6_hardware.realtime.sse_manager import get_sse_manager
            sm = get_sse_manager()
        if hasattr(sm, "client_count"):
            sse_connections = sm.client_count
        elif hasattr(sm, "get_connection_count"):
            sse_connections = sm.get_connection_count()
    except Exception:
        pass
    
    return {
        "cpu_usage": round(cpu_usage, 1),
        "memory_mb": memory_mb,
        "devices_online": devices_online,
        "sensors_total": sensors_total,
        "sse_connections": sse_connections,
    }

@app.get("/m8/health", tags=["M8-标准接口"], summary="M8标准健康检查")
async def m8_std_health(x_m8_token: str = Header(default="")):
    if not _verify_m8_token(x_m8_token):
        raise HTTPException(status_code=401, detail="Invalid M8 token")
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "status": "healthy",
            "module": "m6",
            "module_name": "硬件外设系统",
            "version": "1.0.0",
            "uptime_seconds": int(time.time() - _start_time_m8),
            "device_count": 6,
        }
    }

@app.get("/m8/metrics", tags=["M8-标准接口"], summary="M8标准性能指标")
async def m8_std_metrics(request: Request, x_m8_token: str = Header(default="")):
    if not _verify_m8_token(x_m8_token):
        raise HTTPException(status_code=401, detail="Invalid M8 token")

    # P2-4: 合并系统指标 + Metrics 快照 + CircuitBreaker 状态
    real_metrics = _get_m6_real_metrics(request)

    metrics_snapshot = {}
    breaker_stats = {}
    try:
        metrics_snapshot = request.app.state.metrics.snapshot()
        breaker_stats = request.app.state.collector_breaker.stats
    except Exception:
        pass

    return {
        "code": 0,
        "message": "ok",
        "data": {
            **real_metrics,
            "metrics": metrics_snapshot,
            "circuit_breaker": breaker_stats,
        }
    }

@app.get("/m8/config", tags=["M8-标准接口"], summary="M8标准配置查询")
async def m8_std_config(x_m8_token: str = Header(default="")):
    if not _verify_m8_token(x_m8_token):
        raise HTTPException(status_code=401, detail="Invalid M8 token")
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "module": "m6",
            "version": "1.0.0",
            "env": os.environ.get("YUNXI_ENV", "development"),
            "simulation_mode": True,
            "device_types": 6,
            "sse_enabled": True,
        }
    }


# ---------------------------------------------------------------------------
# 挂载 API 路由
# ---------------------------------------------------------------------------
app.include_router(api_router)


# ---------------------------------------------------------------------------
# 统一异常处理器（优先使用，覆盖原有装饰器注册的 M6Exception 处理器）
# ---------------------------------------------------------------------------

if _unified_exception_handler_m6:
    register_global_exception_handler(app, logger=logger)
    logger.info("统一异常处理器已注册（6 位错误码体系）")


# ---------------------------------------------------------------------------
# SSE 端点
# ---------------------------------------------------------------------------
@app.get("/api/v1/sse/stream", tags=["SSE"], summary="SSE 实时数据流")
async def sse_stream(request: Request):
    """SSE 实时数据流端点

    订阅设备状态变更、传感器数据、告警通知等实时事件。

    事件类型:
    - connected: 连接建立
    - initial_state: 初始状态
    - sensor_data: 传感器数据更新
    - device_status: 设备状态变更
    - alerts: 告警通知
    - notification: 设备通知
    - ping: 心跳
    """
    sse_manager = request.app.state.sse_manager
    return await sse_manager.connect(request)


# ---------------------------------------------------------------------------
# 启动入口
# ---------------------------------------------------------------------------
def main() -> None:
    """启动 FastAPI 服务"""
    # 启动阶段使用兼容层获取配置（单线程环境，无竞态风险）
    from m6_hardware.config import get_config as _get_config_compat
    _cfg = _get_config_compat()
    port = _cfg.port
    host = _cfg.host

    logger.info("=" * 60)
    logger.info("  M6 硬件外设模拟服务")
    logger.info("  M6 Hardware Peripheral Simulation Service")
    logger.info("=" * 60)
    logger.info(f"  版本:        1.0.0")
    logger.info(f"  模块名:      {_cfg.module_name}")
    logger.info(f"  监听地址:    {host}:{port}")
    logger.info(f"  模拟模式:    {'开启' if _cfg.simulation_mode else '关闭'}", simulation_mode=_cfg.simulation_mode)
    logger.info(f"  文档地址:    http://localhost:{port}/docs")
    logger.info(f"  健康检查:    http://localhost:{port}/health")
    logger.info(f"  设备列表:    http://localhost:{port}/api/v1/devices")
    logger.info(f"  SSE 流:      http://localhost:{port}/api/v1/sse/stream")
    logger.info("=" * 60)

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level=_cfg.log_level,
    )


if __name__ == "__main__":
    main()