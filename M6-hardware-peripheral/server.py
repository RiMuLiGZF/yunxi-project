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
from pathlib import Path
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

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
    print("\n" + "=" * 60)
    print("  M6 硬件外设模拟服务 - 启动中...")
    print("=" * 60)

    # 1. 加载配置
    config = M6Config()
    app.state.config = config
    print(f"  配置: 已加载 (环境: {config.env})")

    # P2-2/P2-4: 初始化全局指标收集器与数据采集熔断器
    metrics = Metrics()
    app.state.metrics = metrics
    collector_breaker = CircuitBreaker(
        name="data_collector",
        failure_threshold=5,
        recovery_timeout=30.0,
    )
    app.state.collector_breaker = collector_breaker
    print(f"  Metrics 指标收集器: 已就绪")
    print(f"  数据采集熔断器: 已就绪 (阈值={collector_breaker.failure_threshold}, 恢复={collector_breaker.recovery_timeout}s)")

    # 2. 初始化设备管理器
    device_manager = DeviceManager()
    app.state.device_manager = device_manager
    device_stats = device_manager.get_stats()
    print(f"  设备管理器: 已加载 {device_stats['total']} 台设备")
    print(f"    - 在线: {device_stats['online']}  离线: {device_stats['offline']}  警告: {device_stats['warning']}")

    # 3. 初始化数据采集服务（注入 config 和 device_manager）
    data_collector = DataCollector(config=config, device_manager=device_manager)
    app.state.data_collector = data_collector
    print(f"  数据采集服务: 已就绪 (间隔 {config.collection_interval}s)")
    await data_collector.start()

    # 4. 初始化通知服务（注入 device_manager）
    notification_service = NotificationService(device_manager=device_manager)
    app.state.notification_service = notification_service
    print(f"  通知推送服务: 已就绪")

    # 5. 初始化 SSE 推送服务（注入 device_manager 和 notification_service）
    sse_manager = SSEManager(
        device_manager=device_manager,
        notification_service=notification_service,
    )
    app.state.sse_manager = sse_manager
    await sse_manager.start()
    print(f"  SSE 推送服务: 已启动")

    print("-" * 60)
    print(f"  模拟模式: {'开启' if config.simulation_mode else '关闭'}")
    print(f"  数据库: {config.database_path}")
    print("=" * 60 + "\n")

    yield

    # ===== 关闭时清理 =====
    print("\n正在关闭 M6 硬件外设服务...")
    data_collector = app.state.data_collector
    await data_collector.stop()
    sse_manager = app.state.sse_manager
    await sse_manager.stop()
    print("M6 硬件外设服务已关闭\n")


# ---------------------------------------------------------------------------
# FastAPI 应用
# ---------------------------------------------------------------------------
app = FastAPI(
    title="M6 硬件外设模拟服务 API",
    description="云汐系统模块六：智能穿戴设备、无人机、桌面终端等硬件外设的模拟服务，支持实时传感器数据采集和SSE推送",
    version="1.0.0",
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
# CORS 中间件
# ---------------------------------------------------------------------------
from m6_hardware.config import get_config as _get_config_compat
_cors_config = _get_config_compat()
cors_origins = _cors_config.cors_origins
if cors_origins == "*":
    allow_origins = ["*"]
else:
    allow_origins = cors_origins.split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# M8 统一鉴权中间件
app.add_middleware(M8AuthMiddleware)


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

def _verify_m8_token(x_m8_token: str = "") -> bool:
    expected = os.environ.get("M6_ADMIN_TOKEN", "")
    if not expected:
        return True
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

    print("\n" + "=" * 60)
    print("  M6 硬件外设模拟服务")
    print("  M6 Hardware Peripheral Simulation Service")
    print("=" * 60)
    print(f"  版本:        1.0.0")
    print(f"  模块名:      {_cfg.module_name}")
    print(f"  监听地址:    {host}:{port}")
    print(f"  模拟模式:    {'开启' if _cfg.simulation_mode else '关闭'}")
    print(f"  文档地址:    http://localhost:{port}/docs")
    print(f"  健康检查:    http://localhost:{port}/health")
    print(f"  设备列表:    http://localhost:{port}/api/v1/devices")
    print(f"  SSE 流:      http://localhost:{port}/api/v1/sse/stream")
    print("=" * 60)
    print()

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level=_cfg.log_level,
    )


if __name__ == "__main__":
    main()