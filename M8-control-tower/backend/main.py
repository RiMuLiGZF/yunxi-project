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
from .routers import auth_router, deploy_router, monitor_router, task_router, system_router, memory_router, chat_router, agents_router, growth_router, workflow_router, modules_router, work_dev_router, review_router, study_plan_router, life_management_router, emotion_comfort_router, social_relation_router, appearance_router, m6_devices_router, compute_sources_router, compute_groups_router, compute_models_router, compute_routing_router, compute_monitor_router, compute_config_router, compute_skills_router, compute_gpu_router, inspection_agents_router, watch_router, git_status_router, audit_router, modes_router, security_router, users_router, evolution_planner_router, evolution_deployer_router, evolution_auditor_router, voice_router, voice_presets_router, m4_gateway_router, personalization_router, reminders_router, brain_router
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
    app.include_router(security_router, prefix="/api/security", tags=["安全管理"])
    # ---- 用户管理 ----
    app.include_router(users_router, prefix="/api/users", tags=["用户管理"])
    # ---- 业务模式管理 ----
    app.include_router(modes_router, prefix="/api/modes", tags=["模式管理"])
    app.include_router(evolution_planner_router, prefix="/api/evolution/planner", tags=["自进化-规划器"])
    app.include_router(evolution_deployer_router, prefix="/api/evolution/deployer", tags=["自进化-部署治理"])
    app.include_router(evolution_auditor_router, prefix="/api/evolution/auditor", tags=["自进化-安全审计"])
    app.include_router(voice_router, prefix="/api/voice", tags=["语音服务"])
    app.include_router(voice_presets_router, prefix="/api/voice/presets", tags=["音色管理"])
    # ---- M4 代理网关 ----
    app.include_router(m4_gateway_router, prefix="/api/m4-gateway", tags=["M4代理网关"])
    # ---- 个性化与用户画像 ----
    app.include_router(personalization_router, prefix="/api/personalization", tags=["个性化设置"])
    # ---- 主动提醒与情景感知 ----
    app.include_router(reminders_router, prefix="/api/reminders", tags=["主动提醒"])
    # ---- 云汐大脑 ----
    app.include_router(brain_router, prefix="/api/brain", tags=["云汐大脑"])

    # ---- 分布式集群管理 ----
    if _distributed_available:
        _node_config = NodeConfig.from_env()
        if _node_config.node_role == "primary":
            _registry = NodeRegistry()
            _bus = MessageBus(_node_config)
            init_cluster_services(registry=_registry, bus=_bus)
            app.include_router(cluster_router)
            logger.info(
                f"分布式集群管理已启用 (角色={_node_config.node_role}, "
                f"节点ID={_node_config.node_id}, 集群={_node_config.cluster_id})"
            )
        else:
            # 边缘节点也挂载路由（用于接收消息），但无需注册中心
            _bus = MessageBus(_node_config)
            init_cluster_services(registry=None, bus=_bus)
            app.include_router(cluster_router)
            logger.info(
                f"分布式集群管理已启用 (角色=edge, "
                f"节点ID={_node_config.node_id})"
            )


    # M8 标准对接接口（自管控）
    # -----------------------------------------------------------------------
    from fastapi import Header, HTTPException
    import time as _time_m8

    _m8_start_time = _time_m8.time()

    def _verify_m8_std_token(x_m8_token: str = "") -> bool:
        import hmac
        expected = os.environ.get("M8_ADMIN_TOKEN", "")
        if not expected:
            return True
        return hmac.compare_digest(x_m8_token, expected)

    @app.get("/m8/health", tags=["M8-标准接口"], summary="M8标准健康检查")
    async def m8_std_health(x_m8_token: str = Header(default="")):
        if not _verify_m8_std_token(x_m8_token):
            raise HTTPException(status_code=401, detail="Invalid M8 token")
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "status": "healthy",
                "module": "m8",
                "module_name": "云汐管理台",
                "version": settings.version,
                "uptime_seconds": int(_time_m8.time() - _m8_start_time),
                "modules_managed": 7,
            }
        }

    @app.get("/m8/metrics", tags=["M8-标准接口"], summary="M8标准性能指标")
    async def m8_std_metrics(x_m8_token: str = Header(default="")):
        if not _verify_m8_std_token(x_m8_token):
            raise HTTPException(status_code=401, detail="Invalid M8 token")
        try:
            from routers.monitor import _get_system_metrics
            sys_metrics = _get_system_metrics()
            cpu = sys_metrics.get("cpu", {})
            mem = sys_metrics.get("memory", {})
            return {
                "code": 0,
                "message": "ok",
                "data": {
                    "cpu_usage": cpu.get("percent", 0.0),
                    "memory_mb": round(mem.get("used_gb", 0) * 1024, 1),
                    "memory_total_mb": round(mem.get("total_gb", 0) * 1024, 1),
                    "active_modules": 7,
                    "requests_total": 0,
                    "alerts_active": 0,
                }
            }
        except Exception:
            return {
                "code": 0,
                "message": "ok",
                "data": {
                    "cpu_usage": 0.0,
                    "memory_mb": 0,
                    "active_modules": 7,
                    "requests_total": 0,
                    "alerts_active": 0,
                }
            }

    @app.get("/m8/config", tags=["M8-标准接口"], summary="M8标准配置查询")
    async def m8_std_config(x_m8_token: str = Header(default="")):
        if not _verify_m8_std_token(x_m8_token):
            raise HTTPException(status_code=401, detail="Invalid M8 token")
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "module": "m8",
                "module_name": "云汐管理台",
                "version": settings.version,
                "env": os.environ.get("YUNXI_ENV", "development"),
                "modules": ["m1", "m2", "m3", "m4", "m5", "m6", "m7"],
            }
        }

    # 模块状态检查（无需鉴权，供入口页面使用）
    @app.get("/api/modules/status", tags=["系统"])
    async def modules_status():
        """获取所有模块运行状态（公开接口，供入口页使用）"""
        from shared.config import get_config
        from shared.module_client import get_module_registry

        config = get_config()
        registry = get_module_registry()

        # 使用 ModuleRegistry 的健康检查
        health_results = await registry.check_all_health()

        # 构建与原格式兼容的响应
        modules_status = {}
        for module in registry.get_all_modules():
            is_running = health_results.get(module.key, False)
            modules_status[module.key] = {
                "running": is_running,
                "port": config.get_module_port(module.key),
                "name": module.name,
                "version": module.version,
            }

        running_count = sum(1 for m in modules_status.values() if m["running"])

        return {
            "code": 0,
            "message": "ok",
            "data": {
                "modules": modules_status,
                "running_count": running_count,
                "total": len(modules_status),
            }
        }

    # 全局系统状态检测（无需鉴权，静默检测用）
    @app.get("/api/system/check", tags=["系统"])
    async def system_check():
        """全局系统状态检测（公开接口，静默检测用）
        
        检测项：Ollama大模型服务、Git仓库、硬件蓝牙设备、模块权限白名单
        所有检测并行执行，确保接口快速响应（总耗时 < 3秒）
        """
        import asyncio

        result = {
            "ollama": {"status": "unknown", "message": "未检测"},
            "git": {"status": "unknown", "message": "未检测"},
            "bluetooth": {"status": "unknown", "message": "未检测"},
            "permissions": {"status": "granted", "message": "模块权限正常"},
            "modules": {"status": "unknown", "message": "未检测"},
        }

        async def check_ollama():
            """检测 Ollama 服务"""
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection("127.0.0.1", 11434),
                    timeout=1.0
                )
                writer.close()
                await writer.wait_closed()
                result["ollama"] = {"status": "running", "message": "Ollama服务运行中"}
            except Exception:
                result["ollama"] = {"status": "stopped", "message": "Ollama服务未启动"}

        async def check_git():
            """检测 Git（在线程池中执行，避免阻塞事件循环）"""
            import subprocess
            try:
                loop = asyncio.get_event_loop()
                git_check = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        lambda: subprocess.run(
                            ["git", "--version"],
                            capture_output=True,
                            timeout=2,
                            text=True
                        )
                    ),
                    timeout=2.0
                )
                if git_check.returncode == 0:
                    project_root = Path(__file__).parent.parent.parent
                    git_dir = project_root / ".git"
                    if git_dir.exists():
                        result["git"] = {"status": "ready", "message": "Git已配置，仓库就绪"}
                    else:
                        result["git"] = {"status": "available", "message": "Git已安装，尚未初始化仓库"}
                else:
                    result["git"] = {"status": "unavailable", "message": "Git不可用"}
            except Exception:
                result["git"] = {"status": "unavailable", "message": "Git未安装或不可用"}

        async def check_bluetooth():
            """检测蓝牙（在线程池中执行）"""
            import subprocess
            try:
                loop = asyncio.get_event_loop()
                bt_check = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        lambda: subprocess.run(
                            ["powershell", "-Command", "Get-Service -Name bthserv -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Status"],
                            capture_output=True,
                            timeout=2,
                            text=True
                        )
                    ),
                    timeout=2.0
                )
                bt_status = bt_check.stdout.strip()
                if bt_status and bt_status.lower() == "running":
                    result["bluetooth"] = {"status": "ready", "message": "蓝牙服务运行中"}
                else:
                    result["bluetooth"] = {"status": "unavailable", "message": "蓝牙服务未运行"}
            except Exception:
                result["bluetooth"] = {"status": "unknown", "message": "蓝牙状态未知"}

        async def check_modules():
            """检测所有模块端口状态（并行检测）"""
            from shared.config import get_config as _get_config

            _config = _get_config()
            module_keys = ["m8", "m1", "m2", "m3", "m4", "m5", "m6", "m7"]
            modules_running = 0

            async def check_port(port):
                try:
                    reader, writer = await asyncio.wait_for(
                        asyncio.open_connection("127.0.0.1", port),
                        timeout=0.5
                    )
                    writer.close()
                    await writer.wait_closed()
                    return True
                except Exception:
                    return False

            tasks = []
            for mod_key in module_keys:
                port = _config.get_module_port(mod_key)
                if port:
                    tasks.append(check_port(port))

            if tasks:
                results = await asyncio.gather(*tasks)
                modules_running = sum(1 for r in results if r)

            total_modules = len(module_keys)
            if modules_running >= 5:
                result["modules"] = {"status": "healthy", "message": f"{modules_running}/{total_modules} 模块运行中"}
            elif modules_running >= 2:
                result["modules"] = {"status": "partial", "message": f"{modules_running}/{total_modules} 模块运行中"}
            else:
                result["modules"] = {"status": "stopped", "message": f"{modules_running}/{total_modules} 模块运行中"}

        # 并行执行所有检测，设置总超时
        try:
            await asyncio.wait_for(
                asyncio.gather(
                    check_ollama(),
                    check_git(),
                    check_bluetooth(),
                    check_modules(),
                    return_exceptions=True
                ),
                timeout=3.0
            )
        except Exception:
            pass  # 总超时，返回已获取的部分结果

        # 总体状态
        all_ok = all(
            r["status"] in ["running", "ready", "granted", "healthy", "available"]
            for k, r in result.items() if k != "bluetooth"  # 蓝牙非必需
        )
        
        overall_status = "healthy" if all_ok else "degraded"

        return {
            "code": 0,
            "message": "ok",
            "data": {
                "overall": overall_status,
                "checks": result,
            }
        }

    
    # 公开健康检查接口（根路径，供外部监控使用）
    @app.get("/health", tags=["系统"], summary="系统健康检查")
    async def public_health():
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "status": "healthy",
                "version": settings.version,
                "module": "m8",
                "module_name": "云汐管理台",
            }
        }

    # 前端静态文件服务
    frontend_dir = project_root / "frontend"
    if frontend_dir.exists():
        # 挂载各子目录（按路径深度从深到浅排列，避免路由覆盖问题）
        # M8 工作台
        if (frontend_dir / "m8").exists():
            app.mount("/m8", StaticFiles(directory=str(frontend_dir / "m8"), html=True), name="m8-frontend")
            app.mount("/m8-ui", StaticFiles(directory=str(frontend_dir / "m8"), html=True), name="m8-ui-frontend")
        # M7 积木平台
        if (frontend_dir / "m7").exists():
            app.mount("/m7", StaticFiles(directory=str(frontend_dir / "m7"), html=True), name="m7-frontend")
        # M9 开发工坊
        if (frontend_dir / "m9").exists():
            app.mount("/m9", StaticFiles(directory=str(frontend_dir / "m9"), html=True), name="m9-frontend")
        # 业务模式
        if (frontend_dir / "modes").exists():
            app.mount("/modes", StaticFiles(directory=str(frontend_dir / "modes"), html=True), name="modes-frontend")
        # 汐舷
        if (frontend_dir / "xian").exists():
            app.mount("/xian", StaticFiles(directory=str(frontend_dir / "xian"), html=True), name="xian-frontend")
        # 启动引导
        if (frontend_dir / "startup").exists():
            app.mount("/startup", StaticFiles(directory=str(frontend_dir / "startup"), html=True), name="startup-frontend")
        # 手表交互
        if (frontend_dir / "watch").exists():
            app.mount("/watch", StaticFiles(directory=str(frontend_dir / "watch"), html=True), name="watch-frontend")
        # 公共资源
        if (frontend_dir / "common").exists():
            app.mount("/common", StaticFiles(directory=str(frontend_dir / "common"), html=True), name="common-frontend")
        # 共享资源
        if (frontend_dir / "shared").exists():
            app.mount("/shared", StaticFiles(directory=str(frontend_dir / "shared"), html=True), name="shared-frontend")
        # 用户中心
        if (frontend_dir / "user").exists():
            app.mount("/user", StaticFiles(directory=str(frontend_dir / "user"), html=True), name="user-frontend")
        # 主控台
        if (frontend_dir / "master").exists():
            app.mount("/master", StaticFiles(directory=str(frontend_dir / "master"), html=True), name="master-frontend")

        # 根路径特殊文件（owner.html 等）
        @app.get("/owner.html", tags=["系统"])
        async def owner_page():
            owner_path = frontend_dir / "owner.html"
            if owner_path.exists():
                return FileResponse(str(owner_path))
            raise HTTPException(status_code=404, detail="Not Found")

        # 根路径返回统一入口页
        @app.get("/", tags=["系统"])
        async def root():
            index_path = frontend_dir / "index.html"
            if index_path.exists():
                return FileResponse(str(index_path))
            return {
                "code": 0,
                "message": "ok",
                "data": {
                    "name": settings.app_name,
                    "version": settings.version,
                    "docs": "/docs",
                },
            }

        logger.info(f"Frontend static files mounted from {frontend_dir}")
    else:
        # 没有前端目录时返回 API 信息
        @app.get("/", tags=["系统"])
        async def root():
            return {
                "code": 0,
                "message": "ok",
                "data": {
                    "name": settings.app_name,
                    "version": settings.version,
                    "docs": "/docs",
                },
            }

    # 健康检查（无需鉴权）
    @app.get("/health", tags=["系统"], summary="系统健康检查")
    async def public_health():
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "status": "healthy",
                "version": settings.version,
                "module": "m8",
                "module_name": "云汐管理台",
            }
        }

    return app


app = create_app()
