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
from .routers import auth_router, deploy_router, monitor_router, task_router, system_router, memory_router, chat_router, agents_router, growth_router, workflow_router, modules_router, work_dev_router, review_router, study_plan_router, life_management_router, emotion_comfort_router, social_relation_router, appearance_router, m6_devices_router, compute_sources_router, compute_groups_router, compute_models_router, compute_routing_router, compute_monitor_router, compute_config_router, compute_skills_router, compute_gpu_router, inspection_agents_router, watch_router, git_status_router, audit_router, modes_router, security_router, users_router, evolution_planner_router, evolution_deployer_router, evolution_auditor_router, voice_router, m4_gateway_router
from .m4_proxy_middleware import register_m4_proxy_middleware
from shared.logger import get_logger

logger = get_logger("m8.backend")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期"""
    # 启动时
    logger.info(f"Starting M8 Control Tower v{settings.version}...")
    init_db()
    logger.info("Database initialized")
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
    app.include_router(review_router, prefix="/api/review", tags=["复盘总结"])
    app.include_router(study_plan_router, prefix="/api/study-plan", tags=["学业规划"])
    app.include_router(life_management_router, prefix="/api/life-management", tags=["生活管理"])
    app.include_router(emotion_comfort_router, prefix="/api/emotion-comfort", tags=["情绪陪伴"])
    app.include_router(social_relation_router, prefix="/api/social-relation", tags=["人际关系"])
    app.include_router(appearance_router, prefix="/api/appearance", tags=["形象工坊"])
    app.include_router(m6_devices_router, prefix="/api/v1/m6", tags=["M6穿戴设备"])
    # ---- 算力调度中台 (M8-CS) ----
    app.include_router(compute_sources_router, prefix="/api/compute/sources", tags=["算力调度-算力源"])
    app.include_router(compute_gpu_router, prefix="/api/compute/gpu", tags=["GPU算力管理"])
    app.include_router(compute_groups_router, prefix="/api/compute/groups", tags=["算力调度-密钥分组"])
    app.include_router(compute_models_router, prefix="/api/compute/models", tags=["算力调度-模型绑定"])
    app.include_router(compute_routing_router, prefix="/api/compute/routing", tags=["算力调度-路由调度"])
    app.include_router(compute_monitor_router, prefix="/api/compute/monitor", tags=["算力调度-监控大盘"])
    app.include_router(compute_config_router, prefix="/api/compute/config", tags=["算力调度-配置管理"])
    app.include_router(compute_skills_router, prefix="/api/compute/skills", tags=["算力调度-技能绑定"])
    # ---- 巡检Agent ----
    app.include_router(inspection_agents_router, prefix="/api/inspection", tags=["巡检Agent"])
    # ---- 手表交互 ----
    app.include_router(watch_router, prefix="/api/watch", tags=["手表交互"])
    app.include_router(git_status_router, prefix="/api/git", tags=["Git状态看板"])
    # ---- 审计与安全 ----
    app.include_router(audit_router, prefix="/api/audit", tags=["审计日志"])
   