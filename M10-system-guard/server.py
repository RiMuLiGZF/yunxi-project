"""
M10 系统卫士服务 - FastAPI 启动入口

云汐系统模块十：系统卫士（System Guard）
提供系统资源监控、进程管理、阈值防护、启动安全检查、
审计日志、硬件保护报告、沙箱任务调度等功能。

沙盒模式优先：默认使用模拟数据，不调用真实系统 API。

运行方式:
    python server.py

默认端口: 8010 (通过环境变量 M10_PORT 配置)
"""

from __future__ import annotations

import os
import sys
import time
import uuid
import hmac
from pathlib import Path
from contextlib import asynccontextmanager

import structlog
import uvicorn
from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

logger = structlog.get_logger("m10.server")

# ---------------------------------------------------------------------------
# 路径配置
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
PKG_DIR = BASE_DIR / "m10_system_guard"

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# ---------------------------------------------------------------------------
# 加载环境变量
# ---------------------------------------------------------------------------
def _load_env() -> None:
    """加载环境变量（先全局后模块）."""
    project_root = BASE_DIR.parent
    global_env = project_root / "config" / "yunxi.env"
    if global_env.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(str(global_env), override=False)
        except ImportError:
            try:
                with open(global_env, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        if key and key not in os.environ:
                            os.environ[key] = value
            except Exception:
                pass

    env_path = BASE_DIR / ".env"
    if env_path.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(str(env_path), override=True)
        except ImportError:
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        os.environ[key] = value
            except Exception:
                pass

_load_env()

# ---------------------------------------------------------------------------
# 导入 M10 核心组件
# ---------------------------------------------------------------------------
from m10_system_guard.config import get_config
from m10_system_guard.api import api_router
from m10_system_guard.system_monitor import get_system_monitor
from m10_system_guard.process_manager import get_process_manager
from m10_system_guard.guard_engine import get_guard_engine
from m10_system_guard.startup_check import get_startup_checker
from m10_system_guard.audit_logger import get_audit_logger
from m10_system_guard.report_generator import get_report_generator
from m10_system_guard.sandbox_scheduler import get_sandbox_scheduler
from m10_system_guard.auth_middleware import M10AuthMiddleware
from m10_system_guard.prometheus_exporter import (
    generate_prometheus_metrics,
    generate_metrics_json,
    is_prometheus_available,
    get_prometheus_exporter,
    get_m8_reporter,
    start_prometheus_exporter,
    stop_prometheus_exporter,
    exporter_health_check,
)

# ---------------------------------------------------------------------------
# 加载配置
# ---------------------------------------------------------------------------
config = get_config()

# ---------------------------------------------------------------------------
# 生命周期管理
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理."""
    print("\n" + "=" * 60)
    print("  M10 系统卫士服务 - 启动中...")
    print("=" * 60)

    # 初始化系统监控
    sm = get_system_monitor()
    sm.start()
    print(f"  系统监控: 已启动 (采样间隔 {config.sandbox.sample_interval_seconds}s)")

    # 初始化进程管理
    pm = get_process_manager()
    proc_stats = pm.get_process_stats()
    print(f"  进程管理: 已就绪 (模拟进程 {proc_stats['total_processes']} 个)")

    # 初始化防护引擎
    ge = get_guard_engine()
    ge.check_all()
    guard_status = ge.get_status_summary()
    print(f"  防护引擎: 已就绪 (当前级别: {guard_status['overall_level']})")

    # 初始化启动检查器
    sc = get_startup_checker()
    print(f"  启动检查: 已就绪")

    # 初始化数据库
    from m10_system_guard.database import init_db
    try:
        init_db()
        db_ready = True
    except Exception as e:
        print(f"  数据库: 初始化失败 ({e})")
        db_ready = False

    # 初始化审计日志
    al = get_audit_logger()
    if db_ready:
        al.enable_db_persistence()
    print(f"  审计日志: 已就绪 ({'数据库持久化' if db_ready else '仅内存存储'})")

    # 初始化报告生成器
    rg = get_report_generator()
    print(f"  报告生成: 已就绪")

    # 初始化沙箱调度器
    ss = get_sandbox_scheduler()
    ss.start()
    print(f"  沙箱调度: 已启动")

    # 初始化 Prometheus Exporter
    pe = get_prometheus_exporter()
    pe.start()
    print(f"  Prometheus: {'已启动 (' + str(len(pe.registry.list_metrics())) + ' 个指标)' if pe.enabled else '已禁用'}")

    # 初始化 M8 指标上报器
    m8_reporter = get_m8_reporter()
    if m8_reporter and m8_reporter.enabled:
        m8_reporter.start()
        print(f"  M8 上报: 已启动 (间隔 {m8_reporter.report_interval}s)")
    else:
        print(f"  M8 上报: 已禁用")

    print("-" * 60)
    print(f"  沙盒模式: {'开启 (模拟数据)' if config.sandbox.enabled else '关闭 (真实数据)'}")
    print(f"  服务端口: {config.basic.port}")
    print("=" * 60 + "\n")

    yield

    # 关闭时清理（按顺序）
    print("\n正在关闭 M10 系统卫士服务...")

    import signal
    # 0. 停止 M8 指标上报
    m8_reporter = get_m8_reporter()
    if m8_reporter:
        m8_reporter.stop()
        print("  M8 上报: 已停止")

    # 1. 停止 Prometheus 采集
    stop_prometheus_exporter()
    print("  Prometheus: 已停止")

    # 2. 停止接受新任务
    ss = get_sandbox_scheduler()
    ss.stop()
    print("  沙箱调度: 已停止")

    # 2. 停止数据采集
    sm = get_system_monitor()
    sm.stop()
    print("  系统监控: 已停止")

    # 3. 刷新审计日志到数据库
    al = get_audit_logger()
    al.stop()
    print("  审计日志: 已刷新")

    # 4. 关闭数据库连接
    if db_ready:
        try:
            from m10_system_guard.database import SessionLocal
            SessionLocal.close_all()
            print("  数据库: 已关闭")
        except Exception as e:
            print(f"  数据库: 关闭失败 ({e})")

    print("M10 系统卫士服务已关闭\n")


# ---------------------------------------------------------------------------
# FastAPI 应用
# ---------------------------------------------------------------------------
app = FastAPI(
    title="M10 系统卫士 API",
    description="云汐系统模块十：系统资源监控、进程管理、阈值防护、启动安全检查、审计日志、硬件保护报告、沙箱任务调度",
    version="1.1.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# 全局异常处理
# ---------------------------------------------------------------------------
from m10_system_guard.errors import register_exception_handlers
register_exception_handlers(app)

# ---------------------------------------------------------------------------
# CORS 中间件（统一安全策略：生产环境禁用通配符，开发环境默认localhost）
# ---------------------------------------------------------------------------
_cors_env = os.environ.get("YUNXI_ENV", os.environ.get("ENV", "development")).lower()
_cors_is_prod = _cors_env in ("production", "prod", "release")
_cors_raw = config.cors_origins

if _cors_raw == "*" or not _cors_raw.strip():
    if _cors_is_prod:
        raise RuntimeError(
            "[CORS] 生产环境安全校验失败：M10 系统卫士的 CORS origins "
            f"配置为 '{_cors_raw}'。生产环境必须显式配置具体的允许来源，"
            "禁止使用通配符 '*'。请设置 M10_CORS_ORIGINS 环境变量。"
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

# ---------------------------------------------------------------------------
# 认证中间件：保护 /api/v1/* 所有业务接口
# ---------------------------------------------------------------------------
app.add_middleware(M10AuthMiddleware)


# ---------------------------------------------------------------------------
# 请求中间件：request_id 注入
# ---------------------------------------------------------------------------
@app.middleware("http")
async def add_request_id(request: Request, call_next):
    """为每个请求注入 request_id，并记录响应时间."""
    start_time = time.time()
    request_id = uuid.uuid4().hex[:16]
    request.state.request_id = request_id

    response = await call_next(request)

    elapsed_ms = (time.time() - start_time) * 1000
    response.headers["X-Request-Id"] = request_id
    response.headers["X-Response-Time"] = f"{elapsed_ms:.2f}ms"
    return response


# ---------------------------------------------------------------------------
# 根路径 - 服务信息
# ---------------------------------------------------------------------------
@app.get("/", tags=["Info"], summary="服务信息")
async def root():
    """根路径：返回服务基本信息."""
    ge = get_guard_engine()
    guard_status = ge.get_status_summary()

    return {
        "name": "M10 系统卫士服务",
        "module": "m10-system-guard",
        "version": config.basic.version,
        "status": "running",
        "sandbox_mode": config.sandbox.enabled,
        "docs": "/docs",
        "openapi": "/openapi.json",
        "guard_level": guard_status["overall_level"],
        "endpoints": {
            "status": "/api/v1/status",
            "process": "/api/v1/process",
            "guard": "/api/v1/guard",
            "startup_check": "/api/v1/startup-check",
            "audit": "/api/v1/audit",
            "report": "/api/v1/report",
        },
    }


# ---------------------------------------------------------------------------
# 标准化可观测性路由（健康检查 + Prometheus 指标）
# ---------------------------------------------------------------------------
try:
    import sys as _sys_m10_obs
    _project_root_m10 = BASE_DIR.parent
    if str(_project_root_m10) not in _sys_m10_obs.path:
        _sys_m10_obs.path.insert(0, str(_project_root_m10))

    from shared.core.observability import create_observability_router, HealthChecker
    from shared.core.health import CheckResult, HealthStatus

    _m10_obs_available = True

    # 创建 M10 自定义健康检查器
    m10_checker = HealthChecker(
        module_name="m10",
        version=config.basic.version,
        module_display_name="系统卫士",
    )

    # 注册轻量检查：内存
    m10_checker.register_memory_check(threshold_percent=90.0, lightweight=True)

    # 注册轻量检查：磁盘
    m10_checker.register_disk_check(
        path=str(BASE_DIR),
        threshold_percent=90.0,
        lightweight=True,
    )

    # 注册深度检查：数据库（核心依赖）
    def _check_m10_db() -> CheckResult:
        start_t = time.time()
        try:
            from m10_system_guard.database import SessionLocal
            db = SessionLocal()
            try:
                db.execute("SELECT 1")
                resp_ms = (time.time() - start_t) * 1000
                return CheckResult.healthy(
                    type="sqlalchemy",
                    response_time_ms=resp_ms,
                )
            except Exception as e:
                resp_ms = (time.time() - start_t) * 1000
                return CheckResult.unhealthy(
                    error=str(e),
                    type="sqlalchemy",
                    response_time_ms=resp_ms,
                )
            finally:
                db.close()
        except Exception as e:
            resp_ms = (time.time() - start_t) * 1000
            return CheckResult.degraded(
                error=str(e),
                type="sqlalchemy",
                response_time_ms=resp_ms,
            )

    m10_checker.register_check("database", _check_m10_db, critical=True, lightweight=False)

    # 注册深度检查：系统监控（M10 特有）
    def _check_m10_system_monitor() -> CheckResult:
        start_t = time.time()
        try:
            from m10_system_guard.system_monitor import get_system_monitor
            sm = get_system_monitor()
            latest = sm.get_latest()
            resp_ms = (time.time() - start_t) * 1000
            return CheckResult.healthy(
                cpu_percent=latest.cpu.usage_percent,
                memory_percent=latest.memory.usage_percent,
                response_time_ms=resp_ms,
            )
        except Exception as e:
            resp_ms = (time.time() - start_t) * 1000
            return CheckResult.degraded(
                error=str(e),
                response_time_ms=resp_ms,
            )

    m10_checker.register_check("system_monitor", _check_m10_system_monitor, critical=False, lightweight=False)

    # 注册深度检查：防护引擎（M10 特有）
    def _check_m10_guard_engine() -> CheckResult:
        start_t = time.time()
        try:
            from m10_system_guard.guard_engine import get_guard_engine
            ge = get_guard_engine()
            status = ge.get_status_summary()
            resp_ms = (time.time() - start_t) * 1000
            return CheckResult.healthy(
                overall_level=status.get("overall_level", "unknown"),
                policy_count=status.get("policy_count", 0),
                response_time_ms=resp_ms,
            )
        except Exception as e:
            resp_ms = (time.time() - start_t) * 1000
            return CheckResult.degraded(
                error=str(e),
                response_time_ms=resp_ms,
            )

    m10_checker.register_check("guard_engine", _check_m10_guard_engine, critical=False, lightweight=False)

    # 注册深度检查：进程管理（M10 特有）
    def _check_m10_process_manager() -> CheckResult:
        start_t = time.time()
        try:
            from m10_system_guard.process_manager import get_process_manager
            pm = get_process_manager()
            stats = pm.get_process_stats()
            resp_ms = (time.time() - start_t) * 1000
            return CheckResult.healthy(
                total_processes=stats.get("total_processes", 0),
                yunxi_processes=stats.get("yunxi_processes", 0),
                response_time_ms=resp_ms,
            )
        except Exception as e:
            resp_ms = (time.time() - start_t) * 1000
            return CheckResult.degraded(
                error=str(e),
                response_time_ms=resp_ms,
            )

    m10_checker.register_check("process_manager", _check_m10_process_manager, critical=False, lightweight=False)

    # 创建可观测性路由并注册
    obs_router = create_observability_router(
        service_name="m10",
        version=config.basic.version,
        health_checker=m10_checker,
    )
    app.include_router(obs_router)
    logger.info("标准化可观测性路由已注册（/health + /metrics）")

except ImportError as _m10_obs_err:
    _m10_obs_available = False
    logger.warning(f"标准化可观测性不可用: {_m10_obs_err}")
except Exception as _m10_obs_err:
    _m10_obs_available = False
    logger.warning(f"标准化可观测性初始化失败: {_m10_obs_err}")


# ---------------------------------------------------------------------------
# 健康检查（标准端点）- 向后兼容
# ---------------------------------------------------------------------------
@app.get("/health", tags=["Health"], summary="健康检查")
async def health():
    """标准健康检查端点."""
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "status": "healthy",
            "module": "m10-system-guard",
            "version": config.basic.version,
            "sandbox_mode": config.sandbox.enabled,
        },
        "request_id": uuid.uuid4().hex[:16],
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# M8 标准对接接口
# ---------------------------------------------------------------------------
_start_time_m8 = time.time()


def _verify_m8_token(x_m8_token: str = "") -> bool:
    """验证 M8 token（使用 hmac.compare_digest 防止时序攻击）.

    Args:
        x_m8_token: 请求头中携带的令牌.

    Returns:
        True 表示验证通过.
    """
    expected = os.environ.get("M10_ADMIN_TOKEN", "")
    if not expected:
        logger.warning(
            "m10.auth.token_not_configured",
            message="M10_ADMIN_TOKEN 未配置，M8 标准接口暂不鉴权",
        )
        return True
    # 拒绝空 Token，防止空值绕过
    if not x_m8_token:
        return False
    return hmac.compare_digest(x_m8_token, expected)


@app.get("/m8/health", tags=["M8-标准接口"], summary="M8标准健康检查")
async def m8_std_health(x_m8_token: str = Header(default="")):
    """M8 标准健康检查接口."""
    if not _verify_m8_token(x_m8_token):
        raise HTTPException(status_code=401, detail="Invalid M8 token")
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "status": "healthy",
            "module": "m10",
            "module_name": "系统卫士",
            "version": config.basic.version,
            "uptime_seconds": int(time.time() - _start_time_m8),
            "sandbox_mode": config.sandbox.enabled,
        }
    }


@app.get("/m8/metrics", tags=["M8-标准接口"], summary="M8标准性能指标")
async def m8_std_metrics(x_m8_token: str = Header(default="")):
    """M8 标准性能指标接口."""
    if not _verify_m8_token(x_m8_token):
        raise HTTPException(status_code=401, detail="Invalid M8 token")
    sm = get_system_monitor()
    latest = sm.get_latest()
    pm = get_process_manager()
    proc_stats = pm.get_process_stats()
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "cpu_usage": latest.cpu.usage_percent,
            "memory_usage": latest.memory.usage_percent,
            "memory_mb": latest.memory.used_mb,
            "process_count": proc_stats["total_processes"],
            "yunxi_processes": proc_stats["yunxi_processes"],
            "temperature": latest.temperature.highest_temp_celsius,
            "guard_level": get_guard_engine().get_overall_level().value,
        }
    }


@app.get("/m8/config", tags=["M8-标准接口"], summary="M8标准配置查询")
async def m8_std_config(x_m8_token: str = Header(default="")):
    """M8 标准配置查询接口."""
    if not _verify_m8_token(x_m8_token):
        raise HTTPException(status_code=401, detail="Invalid M8 token")
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "module": "m10",
            "version": config.basic.version,
            "env": os.environ.get("YUNXI_ENV", "development"),
            "sandbox_mode": config.sandbox.enabled,
            "sample_interval": config.sandbox.sample_interval_seconds,
            "guard_policies": 4,
        }
    }


# ---------------------------------------------------------------------------
# Prometheus /metrics 端点（增强版）
# ---------------------------------------------------------------------------
@app.get("/api/v1/metrics", tags=["Observability"], summary="Prometheus 指标")
async def metrics_endpoint():
    """Prometheus 格式的系统指标端点.

    如果 prometheus_client 已安装，返回标准 Prometheus 文本格式；
    否则返回 JSON 格式的模拟指标。
    """
    content_type, body = generate_prometheus_metrics()
    if not is_prometheus_available():
        return generate_metrics_json()
    from fastapi import Response
    return Response(content=body, media_type=content_type)


@app.get("/api/v1/metrics/health", tags=["Observability"], summary="Exporter 健康状态")
async def exporter_health_endpoint():
    """Prometheus Exporter 健康检查端点."""
    health = exporter_health_check()
    return {
        "code": 0,
        "message": "ok",
        "data": health,
    }


@app.get("/api/v1/metrics/json", tags=["Observability"], summary="JSON 格式指标")
async def metrics_json_endpoint():
    """JSON 格式的所有指标数据（便于调试）."""
    return generate_metrics_json()


@app.get("/api/v1/metrics/list", tags=["Observability"], summary="指标列表")
async def metrics_list_endpoint(category: str = ""):
    """列出所有已注册的指标元信息.

    - **category**: 可选类别过滤 (system/gpu/tide/guard/process)
    """
    pe = get_prometheus_exporter()
    metrics_info = pe.registry.list_metrics(category if category else None)
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "total": len(metrics_info),
            "metrics": [
                {
                    "name": m.name,
                    "type": m.metric_type,
                    "help": m.help_text,
                    "labels": m.labels,
                    "category": m.category,
                }
                for m in metrics_info
            ],
        },
    }


# ---------------------------------------------------------------------------
# M8 上报状态端点
# ---------------------------------------------------------------------------
@app.get("/api/v1/m8-report/status", tags=["M8-上报"], summary="M8上报状态")
async def m8_report_status():
    """获取 M8 指标上报的状态信息."""
    m8_reporter = get_m8_reporter()
    if not m8_reporter:
        return {
            "code": 0,
            "message": "ok",
            "data": {"enabled": False, "running": False},
        }
    return {
        "code": 0,
        "message": "ok",
        "data": m8_reporter.get_stats(),
    }


# ---------------------------------------------------------------------------
# 挂载 API 路由
# ---------------------------------------------------------------------------
app.include_router(api_router)
from m10_system_guard.api.tide import router as tide_router
app.include_router(tide_router, prefix="/api/v1/tide", tags=["潮汐引擎"])



# ---------------------------------------------------------------------------
# 启动入口
# ---------------------------------------------------------------------------
def main() -> None:
    """启动 FastAPI 服务."""
    port = config.basic.port
    host = config.basic.host

    print("\n" + "=" * 60)
    print("  M10 系统卫士服务")
    print("  M10 System Guard Service")
    print("=" * 60)
    print(f"  版本:        {config.basic.version}")
    print(f"  模块名:      {config.basic.name}")
    print(f"  监听地址:    {host}:{port}")
    print(f"  沙盒模式:    {'开启 (模拟数据)' if config.sandbox.enabled else '关闭 (真实数据)'}")
    print(f"  文档地址:    http://localhost:{port}/docs")
    print(f"  健康检查:    http://localhost:{port}/health")
    print(f"  系统状态:    http://localhost:{port}/api/v1/status")
    print("=" * 60)
    print()

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level=config.basic.log_level,
    )


if __name__ == "__main__":
    main()
