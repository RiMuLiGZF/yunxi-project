"""M4 场景引擎 - FastAPI 主应用.

创建 FastAPI 应用，注册路由，初始化服务，配置中间件。
"""

from __future__ import annotations

import os
import hmac
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# ---------------------------------------------------------------------------
# 应用创建
# ---------------------------------------------------------------------------

app = FastAPI(
    title="M4 场景引擎 API",
    description="云汐项目模块四：场景识别、切换与上下文管理引擎",
    version="1.0.0",
)

# ---------------------------------------------------------------------------
# CORS 中间件
# ---------------------------------------------------------------------------

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
# 服务初始化
# ---------------------------------------------------------------------------

def _init_services() -> None:
    """初始化所有服务并挂载到 app.state."""
    from src.services.recognizer import SceneRecognizer
    from src.services.switcher import SceneSwitchManager
    from src.services.context_store import ContextStore
    from src.m8_api.health_endpoints import HealthMetricsService
    from src.models import DEFAULT_SCENE

    base_dir = Path(__file__).resolve().parent.parent
    data_dir = base_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    # 全局配置
    config = {
        "default_scene": os.environ.get("M4_DEFAULT_SCENE", DEFAULT_SCENE),
        "auto_switch": os.environ.get("M4_AUTO_SWITCH", "true").lower() == "true",
        "switch_confidence_threshold": float(
            os.environ.get("M4_SWITCH_THRESHOLD", "0.7")
        ),
        "recognize_keyword_threshold": float(
            os.environ.get("M4_KEYWORD_THRESHOLD", "0.7")
        ),
        "enable_llm_enhance": os.environ.get(
            "M4_ENABLE_LLM", "false"
        ).lower() == "true",
        "llm_base_url": os.environ.get("M4_LLM_BASE_URL", ""),
        "llm_model_name": os.environ.get("M4_LLM_MODEL", ""),
        "max_history_records": int(os.environ.get("M4_MAX_HISTORY", "100")),
        "port": int(os.environ.get("M4_PORT", "8004")),
        "env": os.environ.get("M4_ENV", "development"),
    }

    app.state.config = config

    # 场景识别器
    recognizer = SceneRecognizer(
        keyword_threshold=config["recognize_keyword_threshold"],
        enable_llm=config["enable_llm_enhance"],
        llm_base_url=config["llm_base_url"],
        llm_model_name=config["llm_model_name"],
    )
    app.state.recognizer = recognizer

    # 场景切换管理器
    switch_manager = SceneSwitchManager(
        default_scene=config["default_scene"],
        max_history=config["max_history_records"],
    )
    app.state.switch_manager = switch_manager

    # 上下文存储
    persist_path = os.environ.get("M4_DATA_PATH", "")
    context_store = ContextStore(
        persist_path=persist_path,
        auto_save=True,
    )
    app.state.context_store = context_store

    # 健康指标服务
    health_metrics = HealthMetricsService(
        data_path=str(data_dir),
        context_store=context_store,
        switch_manager=switch_manager,
        recognizer=recognizer,
    )
    app.state.health_metrics = health_metrics

    # 鉴权中间件
    from src.m8_api.m8_auth_middleware import M8TokenAuthMiddleware
    auth_middleware = M8TokenAuthMiddleware(
        token_env_var="M4_ADMIN_TOKEN",
        env=config["env"],
    )
    app.state.auth_middleware = auth_middleware


_init_services()


# ---------------------------------------------------------------------------
# 请求中间件：trace_id + 指标记录 + 鉴权
# ---------------------------------------------------------------------------

@app.middleware("http")
async def add_trace_id_and_auth(request: Request, call_next):
    """为每个请求注入 trace_id，记录指标，检查鉴权."""
    start_time = time.time()
    trace_id = uuid.uuid4().hex[:16]

    # 将 trace_id 存入 request state
    request.state.trace_id = trace_id

    # 鉴权检查（仅对需要鉴权的路径）
    auth_middleware = getattr(app.state, "auth_middleware", None)
    if auth_middleware is not None:
        path = request.url.path
        headers = dict(request.headers)

        # 只对 /api/v1/admin/* 下的非白名单路径进行鉴权
        if path.startswith("/api/v1/admin/") and path != "/api/v1/admin/health":
            auth_ok, auth_code, auth_msg = auth_middleware.check_auth(path, headers)
            if not auth_ok:
                response = JSONResponse(
                    status_code=401,
                    content={
                        "code": auth_code,
                        "message": auth_msg,
                        "data": {},
                        "trace_id": trace_id,
                    },
                )
                response.headers["X-Trace-Id"] = trace_id
                return response

    # 处理请求
    response = await call_next(request)

    # 记录响应时间到指标收集器
    elapsed_ms = (time.time() - start_time) * 1000
    health_metrics = getattr(app.state, "health_metrics", None)
    if health_metrics is not None:
        success = response.status_code < 500
        health_metrics.metrics.record_request(success=success, response_ms=elapsed_ms)

    response.headers["X-Trace-Id"] = trace_id
    return response


# ---------------------------------------------------------------------------
# 健康检查（公开）
# ---------------------------------------------------------------------------

@app.get("/health", tags=["Health"], summary="健康检查")
async def health_check():
    """健康检查端点，公开访问."""
    health_metrics = getattr(app.state, "health_metrics", None)
    if health_metrics is not None:
        result = await health_metrics.get_health()
        return {
            "code": 0,
            "message": "ok",
            "data": result,
        }

    return {
        "code": 0,
        "message": "ok",
        "data": {
            "status": "healthy",
            "version": "1.0.0",
            "module": "m4",
            "uptime_seconds": 0,
        },
    }


# ---------------------------------------------------------------------------
# M8 标准对接接口
# ---------------------------------------------------------------------------
from fastapi import Header, HTTPException
import time as _time_m8

_start_time_m8 = _time_m8.time()

def _verify_m8_token(x_m8_token: str = "") -> bool:
    expected = os.environ.get("M4_ADMIN_TOKEN", "")
    if not expected:
        return True
    return hmac.compare_digest(x_m8_token, expected)


def _get_m4_real_metrics():
    """获取真实 M4 性能指标"""
    import os
    try:
        import psutil
        cpu_usage = psutil.cpu_percent(interval=0.1)
        memory_mb = int(psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024)
    except Exception:
        cpu_usage = 0.0
        memory_mb = 0
    try:
        from src.services.scene_recognizer import SceneRecognizer
        recognizer = SceneRecognizer()
        scenes = recognizer.get_all_scenes()
        scenes_total = len(scenes)
        current = recognizer.get_current_scene()
        active_scene = current.scene_id if current else "unknown"
    except Exception:
        scenes_total = 6
        active_scene = "unknown"
    return {
        "cpu_usage": round(cpu_usage, 1),
        "memory_mb": memory_mb,
        "scenes_total": scenes_total,
        "active_scene": active_scene,
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
            "module": "m4",
            "module_name": "场景引擎",
            "version": "1.2.0",
            "uptime_seconds": int(_time_m8.time() - _start_time_m8),
        }
    }

@app.get("/m8/metrics", tags=["M8-标准接口"], summary="M8标准性能指标")
async def m8_std_metrics(x_m8_token: str = Header(default="")):
    if not _verify_m8_token(x_m8_token):
        raise HTTPException(status_code=401, detail="Invalid M8 token")
    return {
        "code": 0,
        "message": "ok",
        "data": _get_m4_real_metrics()
    }

@app.get("/m8/config", tags=["M8-标准接口"], summary="M8标准配置查询")
async def m8_std_config(x_m8_token: str = Header(default="")):
    if not _verify_m8_token(x_m8_token):
        raise HTTPException(status_code=401, detail="Invalid M8 token")
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "module": "m4",
            "version": "1.2.0",
            "env": os.environ.get("YUNXI_ENV", "development"),
            "scene_count": 6,
            "context_enabled": True,
        }
    }


# ---------------------------------------------------------------------------
# 根路径
# ---------------------------------------------------------------------------

@app.get("/", tags=["Info"], summary="服务信息")
async def root():
    """根路径：返回服务基本信息."""
    config = getattr(app.state, "config", {})
    return {
        "name": "M4 场景引擎 API",
        "version": "1.0.0",
        "status": "running",
        "module": "m4",
        "docs": "/docs",
        "openapi": "/openapi.json",
        "config": {
            "default_scene": config.get("default_scene", "emotional"),
            "auto_switch": config.get("auto_switch", True),
            "threshold": config.get("switch_confidence_threshold", 0.7),
            "llm_enabled": config.get("enable_llm_enhance", False),
        },
        "endpoints": {
            "health": "/health",
            "admin_health": "/api/v1/admin/health",
            "admin_metrics": "/api/v1/admin/metrics",
            "admin_config": "/api/v1/admin/config",
            "scene_list": "/api/v1/scenes",
            "scene_current": "/api/v1/scene/current",
            "scene_switch": "/api/v1/scene/switch",
            "scene_recognize": "/api/v1/scene/recognize",
            "scene_history": "/api/v1/scene/history",
            "scene_config": "/api/v1/scene/{scene_id}/config",
            "context_get": "/api/v1/context/{scene_id}",
            "context_status": "/api/v1/context/status",
            "modes_list": "/api/v1/modes",
            "mode_detail": "/api/v1/modes/{mode_id}",
            "mode_enter": "/api/v1/modes/{mode_id}/enter",
            "mode_leave": "/api/v1/modes/{mode_id}/leave",
        },
    }


# ---------------------------------------------------------------------------
# 路由注册
# ---------------------------------------------------------------------------

from src.config import get_settings
from src.routers.scene import router as scene_router
from src.routers.context import router as context_router
from src.routers.config_route import router as config_router
from src.routers.admin import router as admin_router
from src.routers.modes import router as modes_router

app.include_router(scene_router)
app.include_router(context_router)
app.include_router(config_router)
app.include_router(admin_router)
app.include_router(modes_router)


# ---------------------------------------------------------------------------
# 前端静态文件服务
# ---------------------------------------------------------------------------

try:
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse

    _frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
    if _frontend_dir.exists():
        app.mount("/web", StaticFiles(directory=str(_frontend_dir), html=True), name="frontend")

        @app.get("/web/", include_in_schema=False)
        async def frontend_index():
            """前端入口页面."""
            return FileResponse(str(_frontend_dir / "index.html"))
except Exception:
    # 静态文件服务是可选的，失败不影响核心功能
    pass


# ---------------------------------------------------------------------------
# 统一配置入口（推荐使用）
# ---------------------------------------------------------------------------
# 新增统一配置管理模块 src/config.py，集中管理所有环境变量。
# 为保持向后兼容，现有 os.environ.get 逻辑暂不改动。
# 新代码请使用：
#     from src.config import get_settings
#     settings = get_settings()
#     print(settings.port, settings.default_scene)
# ---------------------------------------------------------------------------
