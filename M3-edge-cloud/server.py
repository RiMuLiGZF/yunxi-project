"""M3 端云协同内核 FastAPI 服务启动文件.

将 M3 纯 Python 库包装为 HTTP 服务，提供 M8 标准 API 接口。

运行方式:
    python server.py

默认端口: 8003 (通过环境变量 M3_PORT 配置)
配置来源优先级: 环境变量 > 项目根目录 config/yunxi.env > 模块 config/config.yaml > 默认值
"""

from __future__ import annotations

import os
import hmac
import shutil
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import structlog
import uvicorn
from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# 日志配置
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# 路径配置
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent

# edge_cloud_kernel 包目录
PKG_DIR = BASE_DIR / "edge_cloud_kernel"

# 确保 BASE_DIR 在 sys.path 中，以便 import edge_cloud_kernel
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# 查找项目根目录（包含 config/yunxi.env 的目录）
def _find_project_root() -> Path | None:
    """从当前目录向上查找包含 config/yunxi.env 的项目根目录."""
    current = BASE_DIR
    for _ in range(10):
        if (current / "config" / "yunxi.env").exists():
            return current
        current = current.parent
    return None

PROJECT_ROOT = _find_project_root()

CONFIG_DIR = PKG_DIR / "config"
CONFIG_EXAMPLE_PATH = CONFIG_DIR / "config.example.yaml"
CONFIG_PATH = CONFIG_DIR / "config.yaml"

# ---------------------------------------------------------------------------
# 加载 yunxi.env 全局配置
# ---------------------------------------------------------------------------
def _load_yunxi_env() -> None:
    """从项目根目录的 config/yunxi.env 加载环境变量."""
    if PROJECT_ROOT is None:
        logger.warning("yunxi_env.not_found", hint="项目根目录未找到，将使用默认配置")
        return

    env_path = PROJECT_ROOT / "config" / "yunxi.env"
    if not env_path.exists():
        logger.warning("yunxi_env.file_not_found", path=str(env_path))
        return

    try:
        from dotenv import load_dotenv
        load_dotenv(env_path, override=False)
        logger.info("yunxi_env.loaded", path=str(env_path))
    except ImportError:
        # python-dotenv 不可用时手动解析
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key and key not in os.environ:
                        os.environ[key] = value
            logger.info("yunxi_env.loaded_manual", path=str(env_path))
        except Exception as e:
            logger.warning("yunxi_env.load_failed", error=str(e))

_load_yunxi_env()

# ---------------------------------------------------------------------------
# 配置文件初始化
# ---------------------------------------------------------------------------
def _ensure_config_file() -> None:
    """从 config.example.yaml 复制创建 config.yaml（如果不存在）."""
    if CONFIG_PATH.exists():
        logger.info("config.file_exists", path=str(CONFIG_PATH))
        return

    if not CONFIG_EXAMPLE_PATH.exists():
        logger.warning("config.example_not_found", path=str(CONFIG_EXAMPLE_PATH))
        return

    # 确保 config 目录存在
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    shutil.copy2(CONFIG_EXAMPLE_PATH, CONFIG_PATH)
    logger.info("config.created_from_example", path=str(CONFIG_PATH))


_ensure_config_file()

# ---------------------------------------------------------------------------
# M3 核心组件导入与初始化
# ---------------------------------------------------------------------------
# 全局服务实例（延迟初始化，失败时降级为 mock）
_m3_services: dict[str, Any] = {}
_mock_mode: dict[str, bool] = {}


def _init_components() -> None:
    """初始化所有 M3 核心组件.

    使用默认配置，尽量简单。
    每个组件独立 try/except，失败时标记为 mock 模式，
    确保服务能够正常启动。
    """
    global _m3_services, _mock_mode

    # ---- 1. 配置管理器 ----
    try:
        from edge_cloud_kernel.m8_api.config_endpoints import ConfigManager

        config_manager = ConfigManager(config_path=str(CONFIG_PATH))
        # 用环境变量覆盖关键配置
        _apply_env_overrides(config_manager)
        _m3_services["config_manager"] = config_manager
        _mock_mode["config_manager"] = False
        logger.info("component.init_ok", name="ConfigManager")
    except Exception as e:
        logger.error("component.init_failed", name="ConfigManager", error=str(e))
        _mock_mode["config_manager"] = True

    # ---- 2. 设备注册表 ----
    try:
        from edge_cloud_kernel.m8_api.device_registry import create_device_registry
        # P2-6: 默认使用 sqlite 持久化，重启不丢失
        _reg_type = "sqlite"
        _db_path = str(Path(PROJECT_ROOT) / "M3-edge-cloud" / "data" / "devices.db") if PROJECT_ROOT else str(BASE_DIR / "data" / "devices.db")
        try:
            _reg_type = config_manager.get("devices.registry_type", "sqlite")
            _db_path = config_manager.get("devices.db_path", _db_path)
        except Exception:
            pass
        Path(_db_path).parent.mkdir(parents=True, exist_ok=True)
        device_registry = create_device_registry(registry_type=_reg_type, db_path=_db_path)
        _m3_services["device_registry"] = device_registry
        _mock_mode["device_registry"] = False
        logger.info("component.init_ok", name=f"DeviceRegistry({_reg_type})")
    except Exception as e:
        logger.error("component.init_failed", name="DeviceRegistry", error=str(e))
        _mock_mode["device_registry"] = True

    # ---- 3. 冲突解决器 ----
    try:
        from edge_cloud_kernel.local_data.conflict_resolver import ConflictResolver
        conflict_resolver = ConflictResolver()
        _m3_services["conflict_resolver"] = conflict_resolver
        _mock_mode["conflict_resolver"] = False
        logger.info("component.init_ok", name="ConflictResolver")
    except Exception as e:
        logger.error("component.init_failed", name="ConflictResolver", error=str(e))
        _mock_mode["conflict_resolver"] = True

    # ---- 4. 离线影子代理（可选，依赖较多，失败则跳过） ----
    try:
        from edge_cloud_kernel.sync.offline_shadow_proxy import OfflineShadowProxy
        # 使用默认配置，不实际连接云端
        data_dir = BASE_DIR / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        offline_proxy = OfflineShadowProxy(
            db_path=str(data_dir / "offline_queue.db"),
        )
        _m3_services["offline_proxy"] = offline_proxy
        _mock_mode["offline_proxy"] = False
        logger.info("component.init_ok", name="OfflineShadowProxy")
    except Exception as e:
        logger.warning("component.init_skipped", name="OfflineShadowProxy", error=str(e))
        _mock_mode["offline_proxy"] = True

    # ---- 5. 健康探测器（可选） ----
    try:
        from edge_cloud_kernel.gateway.health_checker import HealthChecker
        health_checker = HealthChecker()
        _m3_services["health_checker"] = health_checker
        _mock_mode["health_checker"] = False
        logger.info("component.init_ok", name="HealthChecker")
    except Exception as e:
        logger.warning("component.init_skipped", name="HealthChecker", error=str(e))
        _mock_mode["health_checker"] = True

    # ---- 6. 上下文同步控制器（可选） ----
    try:
        from edge_cloud_kernel.sync.context_sync_controller import ContextSyncController
        sync_controller = ContextSyncController()
        _m3_services["sync_controller"] = sync_controller
        _mock_mode["sync_controller"] = False
        logger.info("component.init_ok", name="ContextSyncController")
    except Exception as e:
        logger.warning("component.init_skipped", name="ContextSyncController", error=str(e))
        _mock_mode["sync_controller"] = True

    # ---- 7. 健康指标服务 ----
    try:
        from edge_cloud_kernel.m8_api.health_endpoints import HealthMetricsService
        data_dir = BASE_DIR / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        health_metrics = HealthMetricsService(
            db_path="",
            storage_path=str(data_dir),
            offline_proxy=_m3_services.get("offline_proxy"),
            conflict_resolver=_m3_services.get("conflict_resolver"),
            health_checker=_m3_services.get("health_checker"),
        )
        _m3_services["health_metrics"] = health_metrics
        _mock_mode["health_metrics"] = False
        logger.info("component.init_ok", name="HealthMetricsService")
    except Exception as e:
        logger.error("component.init_failed", name="HealthMetricsService", error=str(e))
        _mock_mode["health_metrics"] = True

    # ---- 8. M8 API 服务 ----
    try:
        from edge_cloud_kernel.m8_api.m8_api_service import M8APIService
        m8_api = M8APIService(
            sync_controller=_m3_services.get("sync_controller"),
            conflict_resolver=_m3_services.get("conflict_resolver"),
            offline_proxy=_m3_services.get("offline_proxy"),
            health_checker=_m3_services.get("health_checker"),
            device_registry=_m3_services.get("device_registry"),
        )
        _m3_services["m8_api"] = m8_api
        _mock_mode["m8_api"] = False
        logger.info("component.init_ok", name="M8APIService")
    except Exception as e:
        logger.error("component.init_failed", name="M8APIService", error=str(e))
        _mock_mode["m8_api"] = True

    # 统计
    total = len(_mock_mode)
    ok_count = sum(1 for v in _mock_mode.values() if not v)
    logger.info(
        "components.init_summary",
        total=total,
        ok=ok_count,
        mock=total - ok_count,
    )


def _apply_env_overrides(config_manager: Any) -> None:
    """用环境变量覆盖配置管理器中的关键配置项."""
    updates: dict[str, Any] = {}

    # 端口
    port = os.environ.get("M3_PORT")
    if port:
        try:
            updates["basic.port"] = int(port)
        except Exception:
            pass

    # 环境
    env = os.environ.get("YUNXI_ENV") or os.environ.get("M3_ENV")
    if env:
        updates["basic.env"] = env

    # 日志级别
    log_level = os.environ.get("YUNXI_LOG_LEVEL")
    if log_level:
        updates["basic.log_level"] = log_level
        updates["logging.level"] = log_level

    # Admin Token
    admin_token = os.environ.get("M3_ADMIN_TOKEN")
    if admin_token:
        updates["security.admin_token"] = admin_token

    # 加密密钥
    encryption_key = os.environ.get("M3_ENCRYPTION_KEY")
    if encryption_key:
        updates["security.encryption_key"] = encryption_key

    # CORS
    cors_origins = os.environ.get("CORS_ORIGINS")
    if cors_origins:
        updates["security.cors_origins"] = cors_origins.split(",")

    # 数据库路径
    db_path = os.environ.get("M3_DATABASE_PATH")
    if db_path:
        updates["database.path"] = db_path

    # 批量应用更新（敏感字段会被 update_config 自动拒绝，属于正常情况）
    if updates:
        try:
            config_manager.update_config(updates=updates, request_id="env_override")
        except Exception:
            pass


_init_components()

# 记录启动时间
_m3_services["_start_time"] = time.time()


# ---------------------------------------------------------------------------
# FastAPI 应用
# ---------------------------------------------------------------------------
# M8 统一 API 组件（P1-5 复用 m8_api 子模块）
from edge_cloud_kernel.m8_api import HealthMetricsService, ConfigManager

app = FastAPI(
    title="M3 端云协同内核 API",
    description="云汐项目模块三：端云数据同步、通信网关、资源监控与硬件桥接能力",
    version="0.4.0",
)

# CORS 中间件
cors_origins = os.environ.get("CORS_ORIGINS", "*")
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


# ---------------------------------------------------------------------------
# 请求中间件：trace_id 注入 + 指标记录
# ---------------------------------------------------------------------------
@app.middleware("http")
async def add_trace_id_and_metrics(request: Request, call_next):
    """为每个请求注入 trace_id，并记录请求指标."""
    start_time = time.time()
    trace_id = uuid.uuid4().hex[:16]

    # 将 trace_id 存入 request state
    request.state.trace_id = trace_id

    response = await call_next(request)

    # 记录响应时间到指标收集器
    elapsed_ms = (time.time() - start_time) * 1000
    health_metrics = _m3_services.get("health_metrics")
    if health_metrics is not None and hasattr(health_metrics, "metrics"):
        success = response.status_code < 500
        health_metrics.metrics.record_request(success=success, response_ms=elapsed_ms)

    response.headers["X-Trace-Id"] = trace_id
    return response


# ---------------------------------------------------------------------------
# Mock 数据辅助函数
# ---------------------------------------------------------------------------
def _mock_health_data() -> dict[str, Any]:
    """Mock 健康检查数据（带 mock 标识）."""
    return {
        "mode": "mock",
        "status": "healthy",
        "version": "2.1.2",
        "uptime_seconds": int(time.time() - _m3_services.get("_start_time", time.time())),
        "module": "m3",
        "checks": {
            "database": "healthy",
            "storage": "healthy",
            "network": "unknown",
            "sync_engine": "healthy",
        },
    }


def _mock_metrics_data() -> dict[str, Any]:
    """Mock 性能指标数据（带 mock 标识）."""
    return {
        "mode": "mock",
        "cpu_percent": 0.0,
        "memory_mb": 0.0,
        "disk_usage_mb": 0.0,
        "requests_total": 0,
        "requests_per_second": 0.0,
        "avg_response_ms": 0.0,
        "error_rate": 0.0,
        "sync_tasks_total": 0,
        "sync_success_rate": 1.0,
        "pending_sync_items": 0,
        "conflict_count": 0,
        "offline_queue_size": 0,
    }


def _mock_m8_response(data: Any = None, code: int = 0, message: str = "Success") -> dict[str, Any]:
    """Mock M8 标准响应格式（带 mock 标识）."""
    # 给 dict 类型的 data 添加 mock 模式标识
    if isinstance(data, dict):
        data = {"mode": "mock", **data}
    return {
        "code": code,
        "message": message,
        "data": data,
        "trace_id": uuid.uuid4().hex[:16],
        "timestamp": time.time(),
    }


def _mock_config_data() -> dict[str, Any]:
    """Mock 配置数据（脱敏，带 mock 标识）."""
    return {
        "mode": "mock",
        "basic": {
            "name": "m3-sync",
            "version": "2.1.2",
            "port": 8003,
            "log_level": "info",
            "env": "production",
        },
        "security": {
            "encryption_key": "***",
            "admin_token": "***",
            "cors_origins": ["http://localhost:3000"],
            "e2ee": {"enabled": True, "algorithm": "AES-256-GCM"},
        },
        "sync": {
            "mode": "auto",
            "interval": 60,
            "conflict_strategy": "newest_wins",
            "max_concurrent": 10,
            "max_file_size": 100,
        },
        "storage": {
            "local_path": "./data/sync",
            "cloud_type": "local",
            "cloud_path": "./data/cloud",
            "cache_size": 512,
        },
        "offline": {
            "queue_size": 1000,
            "retry": {"max_attempts": 5, "backoff": "exponential"},
        },
        "database": {"type": "sqlite", "path": "./data/m3.db"},
        "logging": {
            "format": "json",
            "level": "info",
            "file": "./logs/m3.log",
            "max_size": "100MB",
            "max_files": 10,
            "sensitive_fields": ["encryption_key", "password"],
        },
        "devices": {"registry_type": "memory", "db_path": "./data/devices.db"},
    }


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------
class ConfigUpdateRequest(BaseModel):
    """配置更新请求体."""
    updates: dict[str, Any] = Field(..., description="点路径的更新字典")


class SyncTriggerRequest(BaseModel):
    """同步触发请求体."""
    scope: list[str] | None = Field(None, description="同步范围，如 ['conversation', 'memory']")
    conflict_strategy: str = Field("newest_wins", description="冲突解决策略")


# ---------------------------------------------------------------------------
# API 路由
# ---------------------------------------------------------------------------

# ---- 健康检查（标准格式） ----
@app.get("/health", tags=["Health"], summary="健康检查")
async def health_check():
    """健康检查端点，返回标准格式.

    返回格式:
        {"code": 0, "message": "ok", "data": {"status": "healthy"}}
    """
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "status": "healthy",
            "version": "2.1.2",
            "module": "m3",
            "uptime_seconds": int(time.time() - _m3_services.get("_start_time", time.time())),
        },
    }


@app.get("/api/v3/health", tags=["Health"], summary="M8 标准健康检查")
async def m8_health_check(request: Request):
    """M8 标准健康检查接口（白名单，无需鉴权）."""
    trace_id = getattr(request.state, "trace_id", "")
    health_metrics = _m3_services.get("health_metrics")

    if health_metrics is not None and not _mock_mode.get("health_metrics", True):
        try:
            result = await health_metrics.get_health(request_id=trace_id)
            result["mode"] = "real"
            return {
                "code": 0,
                "message": "ok",
                "data": result,
            }
        except Exception as e:
            logger.error("health_check.failed", error=str(e), trace_id=trace_id)

    # Mock 模式
    return {
        "code": 0,
        "message": "ok",
        "data": _mock_health_data(),
    }


@app.get("/api/v3/metrics", tags=["Health"], summary="性能指标")
async def m8_metrics(request: Request):
    """获取性能指标（需鉴权，当前开放）."""
    trace_id = getattr(request.state, "trace_id", "")
    health_metrics = _m3_services.get("health_metrics")

    if health_metrics is not None and not _mock_mode.get("health_metrics", True):
        try:
            result = await health_metrics.get_metrics(request_id=trace_id)
            result["mode"] = "real"
            return {
                "code": 0,
                "message": "ok",
                "data": result,
            }
        except Exception as e:
            logger.error("metrics.failed", error=str(e), trace_id=trace_id)

    # Mock 模式
    return {
        "code": 0,
        "message": "ok",
        "data": _mock_metrics_data(),
    }


# ---- 配置管理 ----
@app.get("/api/v3/config", tags=["Config"], summary="获取配置")
async def get_config(request: Request):
    """获取配置（敏感字段脱敏）."""
    trace_id = getattr(request.state, "trace_id", "")
    config_manager = _m3_services.get("config_manager")

    if config_manager is not None and not _mock_mode.get("config_manager", True):
        try:
            result = config_manager.get_config_sanitized(request_id=trace_id)
            return _mock_m8_response(data=result)
        except Exception as e:
            logger.error("config.get.failed", error=str(e), trace_id=trace_id)

    # Mock 模式
    return _mock_m8_response(data=_mock_config_data())


@app.post("/api/v3/config/update", tags=["Config"], summary="更新配置")
async def update_config(request: Request, body: ConfigUpdateRequest):
    """更新配置（点路径方式，热更新）."""
    trace_id = getattr(request.state, "trace_id", "")
    config_manager = _m3_services.get("config_manager")

    if config_manager is not None and not _mock_mode.get("config_manager", True):
        try:
            success, result = config_manager.update_config(
                updates=body.updates,
                request_id=trace_id,
            )
            if not success:
                raise HTTPException(status_code=400, detail=result)
            return _mock_m8_response(data=result)
        except HTTPException:
            raise
        except Exception as e:
            logger.error("config.update.failed", error=str(e), trace_id=trace_id)
            raise HTTPException(status_code=500, detail=str(e))

    # Mock 模式
    return _mock_m8_response(data={
        "updated_keys": list(body.updates.keys()),
        "rejected_keys": [],
        "restart_required": False,
    })


# ---- 同步管理 ----
@app.get("/api/v3/sync/status", tags=["Sync"], summary="同步状态")
async def sync_status(request: Request):
    """获取同步状态."""
    trace_id = getattr(request.state, "trace_id", "")
    m8_api = _m3_services.get("m8_api")

    if m8_api is not None and not _mock_mode.get("m8_api", True):
        try:
            result = await m8_api.get_sync_status(trace_id=trace_id)
            return result.to_dict()
        except Exception as e:
            logger.error("sync.status.failed", error=str(e), trace_id=trace_id)

    # Mock 模式
    return _mock_m8_response(data={
        "status": "idle",
        "last_sync_at": None,
        "last_sync_result": None,
        "pending_changes": 0,
        "conflict_count": 0,
        "queue_depth": 0,
        "network_state": "unknown",
        "health_endpoints": [],
    })


@app.post("/api/v3/sync/trigger", tags=["Sync"], summary="触发同步")
async def sync_trigger(request: Request, body: SyncTriggerRequest | None = None):
    """手动触发同步."""
    trace_id = getattr(request.state, "trace_id", "")
    m8_api = _m3_services.get("m8_api")

    scope = body.scope if body else None
    conflict_strategy = body.conflict_strategy if body else "newest_wins"

    if m8_api is not None and not _mock_mode.get("m8_api", True):
        try:
            result = await m8_api.trigger_sync(
                scope=scope,
                conflict_strategy=conflict_strategy,
                trace_id=trace_id,
            )
            return result.to_dict()
        except Exception as e:
            logger.error("sync.trigger.failed", error=str(e), trace_id=trace_id)

    # Mock 模式
    return _mock_m8_response(data={
        "sync_id": uuid.uuid4().hex[:16],
        "scope": scope or ["all"],
        "conflict_strategy": conflict_strategy,
        "status": "triggered",
        "triggered_at": time.time(),
    })


@app.get("/api/v3/sync/conflicts", tags=["Sync"], summary="冲突列表")
async def sync_conflicts(
    request: Request,
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
):
    """获取冲突列表."""
    trace_id = getattr(request.state, "trace_id", "")
    m8_api = _m3_services.get("m8_api")

    if m8_api is not None and not _mock_mode.get("m8_api", True):
        try:
            result = await m8_api.list_conflicts(
                page=page,
                page_size=page_size,
                trace_id=trace_id,
            )
            return result.to_dict()
        except Exception as e:
            logger.error("sync.conflicts.failed", error=str(e), trace_id=trace_id)

    # Mock 模式
    return _mock_m8_response(data={
        "total": 0,
        "page": page,
        "page_size": page_size,
        "conflicts": [],
    })


@app.post("/api/v3/sync/conflicts/{conflict_id}/resolve", tags=["Sync"], summary="解决冲突")
async def resolve_conflict(
    request: Request,
    conflict_id: str,
    body: dict = Body(default_factory=dict),
):
    """解决同步冲突."""
    trace_id = getattr(request.state, "trace_id", "")
    m8_api = _m3_services.get("m8_api")

    if m8_api is not None and not _mock_mode.get("m8_api", True):
        try:
            result = await m8_api.resolve_conflict(
                conflict_id=conflict_id,
                resolution=body.get("resolution", ""),
                trace_id=trace_id,
            )
            return result.to_dict()
        except Exception as e:
            logger.error("sync.conflict.resolve.failed", error=str(e), trace_id=trace_id)

    # Mock 模式
    return _mock_m8_response(data={
        "conflict_id": conflict_id,
        "resolved": True,
        "resolution": body.get("resolution", ""),
        "source": "mock",
    })


# ---- 设备管理 ----
@app.get("/api/v3/devices", tags=["Devices"], summary="设备列表")
async def list_devices(
    request: Request,
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    status: str | None = Query(None, description="按状态过滤"),
):
    """获取设备列表."""
    trace_id = getattr(request.state, "trace_id", "")
    m8_api = _m3_services.get("m8_api")

    if m8_api is not None and not _mock_mode.get("m8_api", True):
        try:
            result = await m8_api.list_devices(
                page=page,
                page_size=page_size,
                status=status,
                trace_id=trace_id,
            )
            return result.to_dict()
        except Exception as e:
            logger.error("devices.list.failed", error=str(e), trace_id=trace_id)

    # Mock 模式
    return _mock_m8_response(data={
        "total": 0,
        "page": page,
        "page_size": page_size,
        "devices": [],
    })


@app.post("/api/v3/devices/{device_id}/remove", tags=["Devices"], summary="移除设备")
async def remove_device(
    request: Request,
    device_id: str,
):
    """移除设备."""
    trace_id = getattr(request.state, "trace_id", "")
    m8_api = _m3_services.get("m8_api")

    if m8_api is not None and not _mock_mode.get("m8_api", True):
        try:
            result = await m8_api.remove_device(
                device_id=device_id,
                trace_id=trace_id,
            )
            return result.to_dict()
        except Exception as e:
            logger.error("devices.remove.failed", error=str(e), trace_id=trace_id)

    # Mock 模式
    return _mock_m8_response(data={
        "device_id": device_id,
        "removed": True,
        "source": "mock",
    })


# ---------------------------------------------------------------------------
# 根路径与文档
# ---------------------------------------------------------------------------
@app.get("/", tags=["Info"], summary="服务信息")
async def root():
    """根路径：返回服务基本信息."""
    mock_components = [k for k, v in _mock_mode.items() if v]
    real_components = [k for k, v in _mock_mode.items() if not v]

    return {
        "name": "M3 端云协同内核 API",
        "version": "2.1.2",
        "status": "running",
        "docs": "/docs",
        "openapi": "/openapi.json",
        "components": {
            "initialized": real_components,
            "mock_mode": mock_components,
        },
        "endpoints": {
            "health": "/health",
            "m8_health": "/api/v3/health",
            "m8_metrics": "/api/v3/metrics",
            "config": "/api/v3/config",
            "sync_status": "/api/v3/sync/status",
            "sync_conflict_resolve": "/api/v3/sync/conflicts/{id}/resolve",
            "devices": "/api/v3/devices",
            "device_remove": "/api/v3/devices/{id}/remove",
        },
    }


# ---------------------------------------------------------------------------
# v1 API 别名（兼容统一路径规范）
# 将 /api/v1/* 请求转发到 /api/v3/* 对应端点
# ---------------------------------------------------------------------------
from fastapi.responses import JSONResponse

_v1_to_v3_paths = {
    "/api/v1/health": "/api/v3/health",
    "/api/v1/metrics": "/api/v3/metrics",
    "/api/v1/config": "/api/v3/config",
    "/api/v1/sync/status": "/api/v3/sync/status",
    "/api/v1/sync/conflicts": "/api/v3/sync/conflicts",
    "/api/v1/devices": "/api/v3/devices",
}

@app.get("/api/v1/health", tags=["V1 Alias"], summary="v1健康检查（别名）")
async def v1_health(request: Request):
    return await m8_health_check(request)

@app.get("/api/v1/metrics", tags=["V1 Alias"], summary="v1性能指标（别名）")
async def v1_metrics(request: Request):
    return await m8_metrics(request)

@app.get("/api/v1/config", tags=["V1 Alias"], summary="v1获取配置（别名）")
async def v1_config(request: Request):
    return await get_config(request)

@app.get("/api/v1/sync/status", tags=["V1 Alias"], summary="v1同步状态（别名）")
async def v1_sync_status(request: Request):
    return await sync_status(request)

@app.get("/api/v1/sync/conflicts", tags=["V1 Alias"], summary="v1冲突列表（别名）")
async def v1_sync_conflicts(
    request: Request,
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
):
    return await sync_conflicts(request, page=page, page_size=page_size)

@app.get("/api/v1/devices", tags=["V1 Alias"], summary="v1设备列表（别名）")
async def v1_devices(
    request: Request,
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    status: str | None = Query(None, description="按状态过滤"),
):
    return await list_devices(request, page=page, page_size=page_size, status=status)


# ---- M8 标准对接接口（/m8/* 路径） ----
from fastapi import Header, HTTPException

def _verify_m8_token(x_m8_token: str = "") -> bool:
    expected = os.environ.get("M3_ADMIN_TOKEN", "")
    if not expected:
        return True
    return hmac.compare_digest(x_m8_token, expected)

@app.get("/m8/health", tags=["M8-标准接口"], summary="M8标准健康检查")
async def m8_std_health(x_m8_token: str = Header(default="")):
    """M8 标准健康检查（P1-5: 复用 HealthMetricsService）"""
    if not _verify_m8_token(x_m8_token):
        raise HTTPException(status_code=401, detail="Invalid M8 token")
    import uuid
    request_id = uuid.uuid4().hex[:16]
    health_metrics = _m3_services.get("health_metrics")
    if health_metrics:
        health_data = await health_metrics.get_health(request_id=request_id)
    else:
        health_data = {
            "status": "degraded",
            "module": "m3",
            "version": "2.1.2",
            "uptime_seconds": int(time.time() - _m3_services.get("_start_time", time.time())),
        }
    health_data.setdefault("module_name", "端云协同内核")
    return {
        "code": 0,
        "message": "ok",
        "data": health_data,
    }

@app.get("/m8/metrics", tags=["M8-标准接口"], summary="M8标准性能指标")
async def m8_std_metrics(x_m8_token: str = Header(default="")):
    """M8 标准性能指标（P1-5: 复用 HealthMetricsService，接入真实数据）"""
    if not _verify_m8_token(x_m8_token):
        raise HTTPException(status_code=401, detail="Invalid M8 token")
    import uuid
    request_id = uuid.uuid4().hex[:16]
    health_metrics = _m3_services.get("health_metrics")
    if health_metrics:
        metrics_data = await health_metrics.get_metrics(request_id=request_id)
    else:
        metrics_data = {}
    compatible_data = {
        # 兼容字段（旧字段名）
        "cpu_usage": metrics_data.get("cpu_percent", 0.0),
        "memory_mb": int(metrics_data.get("memory_mb", 0)),
        "devices_connected": metrics_data.get("conflict_count", 0),
        "sync_queue_size": metrics_data.get("pending_sync_items", 0),
        # 新字段（完整指标）
        "cpu_percent": metrics_data.get("cpu_percent", 0.0),
        "disk_usage_mb": metrics_data.get("disk_usage_mb", 0),
        "requests_total": metrics_data.get("requests_total", 0),
        "requests_per_second": metrics_data.get("requests_per_second", 0.0),
        "avg_response_ms": metrics_data.get("avg_response_ms", 0.0),
        "error_rate": metrics_data.get("error_rate", 0.0),
        "sync_tasks_total": metrics_data.get("sync_tasks_total", 0),
        "sync_success_rate": metrics_data.get("sync_success_rate", 0.0),
        "pending_sync_items": metrics_data.get("pending_sync_items", 0),
        "conflict_count": metrics_data.get("conflict_count", 0),
        "offline_queue_size": metrics_data.get("offline_queue_size", 0),
    }
    return {
        "code": 0,
        "message": "ok",
        "data": compatible_data,
    }

@app.get("/m8/config", tags=["M8-标准接口"], summary="M8标准配置查询")
async def m8_std_config(x_m8_token: str = Header(default="")):
    """M8 标准配置查询（P1-5: 复用 ConfigManager）"""
    if not _verify_m8_token(x_m8_token):
        raise HTTPException(status_code=401, detail="Invalid M8 token")
    import uuid
    request_id = uuid.uuid4().hex[:16]
    config_manager = _m3_services.get("config_manager")
    if config_manager:
        config_data = config_manager.get_config_sanitized(request_id=request_id)
    else:
        config_data = {}
    env = os.environ.get("YUNXI_ENV", "development")
    sync_cfg = config_data.get("sync", {}) if isinstance(config_data.get("sync"), dict) else {}
    offline_cfg = config_data.get("offline", {}) if isinstance(config_data.get("offline"), dict) else {}
    compatible_data = {
        # 兼容字段
        "module": "m3",
        "version": "2.1.2",
        "env": env,
        "sync_mode": sync_cfg.get("mode", "auto"),
        "offline_enabled": offline_cfg.get("enabled", True),
        # 完整配置
        "config": config_data,
    }
    return {
        "code": 0,
        "message": "ok",
        "data": compatible_data,
    }


# ---------------------------------------------------------------------------
# 启动入口
# ---------------------------------------------------------------------------
def main() -> None:
    """启动 FastAPI 服务."""
    # 优先从环境变量读取端口（yunxi.env 已加载到环境变量）
    port = int(os.environ.get("M3_PORT", "8003"))

    # 也尝试从配置管理器读取
    config_manager = _m3_services.get("config_manager")
    if config_manager is not None and not _mock_mode.get("config_manager", True):
        try:
            config_port = config_manager.get("basic.port")
            if config_port:
                port = int(config_port)
        except Exception:
            pass

    host = os.environ.get("M3_HOST", "0.0.0.0")

    print("=" * 60)
    print("  M3 端云协同内核 API 服务")
    print("  Edge-Cloud Collaborative Kernel Server")
    print("=" * 60)
    print(f"  版本:      2.1.2")
    print(f"  地址:      {host}:{port}")
    print(f"  配置文件:  {CONFIG_PATH}")
    if PROJECT_ROOT:
        print(f"  项目根目录: {PROJECT_ROOT}")
    print(f"  文档地址:  http://localhost:{port}/docs")
    print(f"  健康检查:  http://localhost:{port}/health")
    print("-" * 60)

    mock_count = sum(1 for v in _mock_mode.values() if v)
    total_count = len(_mock_mode)
    if mock_count > 0:
        print(f"  组件状态:  {total_count - mock_count}/{total_count} 正常, {mock_count} 个使用 Mock 模式")
        mock_names = [k for k, v in _mock_mode.items() if v]
        print(f"  Mock 组件: {', '.join(mock_names)}")
    else:
        print(f"  组件状态:  全部 {total_count} 个组件初始化成功")
    print("=" * 60)
    print()

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
