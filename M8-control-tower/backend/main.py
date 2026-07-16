"""
M8 管理工作台 - 主应用入口
"""

import sys
import os
from pathlib import Path
from contextlib import asynccontextmanager

# 将项目根目录加入 path，以便导入 shared 模块
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .config import settings
from .models import init_db
from .routers import auth_router, deploy_router, monitor_router, task_router, system_router, memory_router, chat_router, agents_router, growth_router, workflow_router, modules_router, work_dev_router, review_router, study_plan_router, life_management_router, emotion_comfort_router, social_relation_router, appearance_router, m6_devices_router, compute_sources_router, compute_groups_router, compute_models_router, compute_routing_router, compute_monitor_router, compute_config_router, compute_skills_router, compute_gpu_router, inspection_agents_router, watch_router, git_status_router, audit_router, modes_router, security_router, users_router, evolution_planner_router, evolution_deployer_router, evolution_auditor_router, voice_router, voice_presets_router, m4_gateway_router, personalization_router, reminders_router
from .m4_proxy_middleware import register_m4_proxy_middleware
try:
    from .middleware.waf_middleware import register_waf_middleware
    _waf_middleware_available = True
except ImportError:
    _waf_middleware_available = False
from shared.logger import get_logger

# 渐进式启动编排器
try:
    from shared.startup_orchestrator import get_startup_orchestrator
    _startup_orchestrator_available = True
except ImportError:
    _startup_orchestrator_available = False

# 分布式集群管理
try:
    from shared.distributed.api import router as cluster_router, init_services as init_cluster_services
    from shared.distributed import NodeConfig, NodeRegistry, MessageBus
    _distributed_available = True
except ImportError:
    _distributed_available = False

logger = get_logger("m8.backend")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期"""
    # 启动时
    logger.info(f"Starting M8 Control Tower v{settings.version}...")
    init_db()
    logger.info("Database initialized")

    # 启动渐进式编排（后台异步执行，不阻塞应用启动）
    if _startup_orchestrator_available:
        startup_orch = get_startup_orchestrator(self_module_key="m8")
        # M8 自身已在运行，确保其状态为 running
        m8_state = startup_orch.get_module_state("m8")
        if m8_state:
            m8_state.phase = "running"
            m8_state.progress = 100
            m8_state.message = "已在运行"
        # 后台启动其他模块的渐进式编排
        startup_orch.start_background()
        logger.info("Progressive startup orchestrator activated")
    else:
        logger.warning("Startup orchestrator not available, skipping progressive startup")

    # 启动提醒语音播报器
    try:
        from shared.reminder_voice import get_reminder_voice_notifier
        reminder_notifier = get_reminder_voice_notifier()
        reminder_notifier.start()
        logger.info("Reminder voice notifier activated")
    except Exception as e:
        logger.warning(f"Reminder voice notifier failed to start: {e}")

    logger.info(f"M8 Control Tower started on {settings.host}:{settings.port}")

    yield

    # 关闭时
    logger.info("M8 Control Tower shutting down...")


def create_app() -> FastAPI:
    """创建 FastAPI 应用"""
    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        description="云汐系统 M8 管理工作台 - 整合枢纽",
        lifespan=lifespan,
    )

    # CORS 中间件
    cors_list = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_list if cors_list else ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # M4 业务代理中间件（流量切换开关）
    register_m4_proxy_middleware(app)

    # WAF 安全防护中间件（对接 M12 安全盾）
    if _waf_middleware_available:
        _waf_mw = register_waf_middleware(app)
        if _waf_mw:
            logger.info("WAF 中间件已注册")

    # 注册路由
    app.include_router(auth_router, prefix="/api/auth", tags=["认证"])
    app.include_router(deploy_router, prefix="/api/deploy", tags=["部署中心"])
    app.include_router(monitor_router, prefix="/api/monitor", tags=["监控中心"])
    app.include_router(task_router, prefix="/api/tasks", tags=["汐舷-任务"])
    app.include_router(system_router, prefix="/api/system", tags=["系统管理"])
    app.include_router(memory_router, prefix="/api/memory", tags=["潮汐记忆-M5"])
    app.include_router(chat_router, prefix="/api/chat", tags=["云汐聊天"])
    app.include_router(agents_router, prefix="/api/agents", tags=["Agent管理"])
    app.include_router(growth_router, prefix="/api/growth", tags=["成长中心"])
    app.include_router(workflow_router, prefix="/api/workflows", tags=["积木平台"])
    app.include_router(modules_router, prefix="/api/modules", tags=["模块管理"])
    app.include_router(work_dev_router, prefix="/api/work-dev", tags=["工作开发"])
    app.in