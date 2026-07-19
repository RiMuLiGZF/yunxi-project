"""
M8 管理工作台 - 主应用入口（ARC-005 重构版）

重构说明：
- 健康检查逻辑移至 services/health_service.py
- 路由注册移至 router_config.py（配置列表 + 循环注册）
- 静态文件挂载移至 static_files.py
- 中间件配置移至 middleware_config.py
- 主文件从 969 行精简到 ~200 行
"""

import sys
import os
from pathlib import Path
from contextlib import asynccontextmanager

# 将项目根目录加入 path，以便导入 shared 模块
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from fastapi import FastAPI, HTTPException

from .config import settings
from .models import init_db
from .m4_proxy_middleware import register_m4_proxy_middleware
from .router_config import register_all_routers
from .static_files import mount_frontend_static
from .middleware_config import setup_cors, setup_distributed_cluster
from .services.health_service import (
    register_m8_std_endpoints,
    register_module_status_endpoint,
    register_system_check_endpoint,
    register_observability_routes,
    register_public_health_endpoint,
)

# WAF 安全防护中间件（优先使用 shared 内嵌引擎版，回退到 M8 本地远程调用版）
try:
    from shared.core.waf_middleware import register_waf_middleware, create_waf_router
    _waf_middleware_available = True
    _waf_middleware_type = "shared_embedded"
except ImportError:
    try:
        from .middleware.waf_middleware import register_waf_middleware
        _waf_middleware_available = True
        _waf_middleware_type = "local_remote"
        create_waf_router = None
    except ImportError:
        _waf_middleware_available = False
        _waf_middleware_type = "none"
        create_waf_router = None

# 统一日志和可观测性（优先使用 observability 新实现，回退到旧 logger）
try:
    from shared.core.observability import init_module_logger, ObservabilityMiddleware
    _observability_available = True
except ImportError:
    from shared.core.logger import get_logger
    _observability_available = False
    ObservabilityMiddleware = None  # type: ignore

# 渐进式启动编排器
try:
    from shared.business.startup_orchestrator import get_startup_orchestrator
    _startup_orchestrator_available = True
except ImportError:
    _startup_orchestrator_available = False

# 初始化模块日志（使用统一日志系统）
if _observability_available:
    logger = init_module_logger("m8")
else:
    logger = get_logger("m8.backend")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期"""
    # 启动时
    logger.info(f"Starting M8 Control Tower v{settings.version}...")
    init_db()
    logger.info("Database initialized")

    # 安全配置校验（SC-002 / SC-003 / SC-004）
    _security_warnings = settings.validate_security()
    if _security_warnings:
        logger.warning("=" * 60)
        logger.warning("M8 安全配置检查报告")
        logger.warning("=" * 60)
        for _w in _security_warnings:
            if "[ERROR]" in _w:
                logger.critical(_w)
            else:
                logger.warning(_w)
        logger.warning("=" * 60)
        # 生产环境有 ERROR 级别的安全问题则拒绝启动
        if settings.is_production and any("[ERROR]" in w for w in _security_warnings):
            raise RuntimeError(
                "生产环境安全配置校验失败，请修复上述安全问题后再启动。\n"
                "主要检查项：\n"
                "  - M8_ADMIN_PASSWORD 必须为强密码（至少12位，含大小写字母、数字、特殊字符）\n"
                "  - M8_JWT_SECRET 必须为安全的随机密钥\n"
                "  - CORS_ORIGINS 不得使用通配符 *\n"
                "  - WAF_MODE 必须为 block"
            )

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
        from shared.business.reminder_voice import get_reminder_voice_notifier
        reminder_notifier = get_reminder_voice_notifier()
        reminder_notifier.start()
        logger.info("Reminder voice notifier activated")
    except Exception as e:
        logger.warning(f"Reminder voice notifier failed to start: {e}")

    # 启动备份调度中心
    try:
        from .services.backup_scheduler import get_backup_orchestrator_service
        backup_service = get_backup_orchestrator_service()
        backup_service.initialize()
        logger.info("Backup scheduler initialized")
    except Exception as e:
        logger.warning(f"Backup scheduler failed to start: {e}")

    logger.info(f"M8 Control Tower started on {settings.host}:{settings.port}")

    yield

    # 关闭时
    logger.info("M8 Control Tower shutting down...")

    # 关闭备份调度中心
    try:
        from .services.backup_scheduler import get_backup_orchestrator_service
        backup_service = get_backup_orchestrator_service()
        backup_service.shutdown()
        logger.info("Backup scheduler shutdown complete")
    except Exception as e:
        logger.warning(f"Backup scheduler shutdown error: {e}")


def create_app() -> FastAPI:
    """创建 FastAPI 应用"""
    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        description="云汐系统 M8 管理工作台 - 整合枢纽",
        lifespan=lifespan,
    )

    # ---- 中间件层 ----
    setup_cors(app, settings, logger)

    # 可观测性中间件（统一日志 + 链路追踪 + 慢请求告警）
    if _observability_available:
        app.add_middleware(
            ObservabilityMiddleware,
            service_name="m8",
            log_level=getattr(settings, "log_level", "INFO"),
            slow_request_threshold=3.0,
            exclude_paths=["/health", "/m8/health", "/m8/metrics", "/api/system/check"],
        )
        logger.info("可观测性中间件已注册（统一日志 + 链路追踪 + 慢请求告警）")

    # 统一异常处理器（6 位错误码体系 + 标准化响应格式）
    try:
        from shared.core.responses import register_global_exception_handler
        register_global_exception_handler(app, logger=logger)
        logger.info("统一异常处理器已注册（6 位错误码体系）")
    except ImportError:
        logger.warning("统一异常处理器不可用，将使用 FastAPI 默认异常处理")

    # M4 业务代理中间件（流量切换开关）
    register_m4_proxy_middleware(app)

    # WAF 安全防护中间件（内嵌 WAF 引擎，零外部依赖）
    if _waf_middleware_available:
        _waf_mw = register_waf_middleware(app)
        if _waf_mw:
            logger.info("WAF 中间件已注册（%s模式）", _waf_middleware_type)
        else:
            logger.info("WAF 中间件未启用（配置禁用）")

    # 注册 WAF 状态路由（健康检查、状态、统计）
    if _waf_middleware_available and create_waf_router is not None:
        waf_router = create_waf_router(prefix="/api/waf")
        app.include_router(waf_router)
        logger.info("WAF 状态路由已注册")

    # ---- 业务路由（通过配置列表统一注册） ----
    register_all_routers(app)

    # ---- 分布式集群管理 ----
    setup_distributed_cluster(app, logger)

    # ---- 健康检查与系统检测端点 ----
    register_m8_std_endpoints(app, settings, logger)
    register_module_status_endpoint(app, logger)
    register_system_check_endpoint(app, logger, project_root)
    register_observability_routes(app, settings, logger, project_root, _observability_available)
    register_public_health_endpoint(app, settings, logger, _observability_available)

    # ---- 前端静态文件 ----
    mount_frontend_static(app, project_root, settings, logger)

    return app


app = create_app()
