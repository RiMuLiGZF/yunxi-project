"""
云汐 M12 安全盾 - FastAPI 应用主入口
负责创建应用实例、注册路由、配置中间件、初始化数据库

提供 create_app() 工厂函数，支持灵活的应用创建和测试。
"""

import logging
import os
import sys
from pathlib import Path
from typing import Optional, Callable
from contextlib import asynccontextmanager

# ---------------------------------------------------------------------------
# 统一基础设施接入（第二阶段：shared.core）
# 优先使用统一实现，失败则回退到模块原有实现
# ---------------------------------------------------------------------------

# 尝试将项目根目录加入 path
try:
    _current_m12 = Path(__file__).resolve()
    for _ in range(10):
        _current_m12 = _current_m12.parent
        if (_current_m12 / "shared" / "core" / "observability" / "__init__.py").exists():
            if str(_current_m12) not in sys.path:
                sys.path.insert(0, str(_current_m12))
            break
except Exception:
    pass

# 统一可观测性
try:
    from shared.core.observability import init_module_logger, ObservabilityMiddleware
    _unified_observability_m12 = True
except ImportError:
    _unified_observability_m12 = False
    ObservabilityMiddleware = None  # type: ignore

# 统一异常处理器
try:
    from shared.core.responses import register_global_exception_handler
    _unified_exception_handler_m12 = True
except ImportError:
    _unified_exception_handler_m12 = False

# 统一日志 logger（优先使用）
if _unified_observability_m12:
    logger = init_module_logger("m12")
else:
    logger = logging.getLogger(__name__)

# 加载环境变量（优先从项目根目录加载）
_env_path = Path(__file__).resolve().parent.parent.parent / "config" / "yunxi.env"
if _env_path.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=_env_path, override=False)
    except ImportError:
        pass

# 兼容相对导入和直接运行
try:
    from .config import get_settings
    from .database import init_db
except ImportError:
    from config import get_settings
    from database import init_db

from fastapi import FastAPI
from fastapi.responses import JSONResponse


# ===========================================================================
# 应用工厂
# ===========================================================================

def create_app(lifespan: Optional[Callable] = None) -> FastAPI:
    """
    创建 FastAPI 应用实例

    Args:
        lifespan: 可选的生命周期管理函数（asynccontextmanager）

    Returns:
        配置完成的 FastAPI 应用实例
    """
    settings = get_settings()

    # 创建应用
    app = FastAPI(
        title="M12 安全盾 API",
        description="云汐系统模块十二：安全防护核心模块，提供 WAF 防护墙、API 密钥管理、IP 黑白名单、速率限制、安全审计、威胁检测等全方位安全防护能力。",
        version=settings.version,
        debug=settings.debug,
        lifespan=lifespan if lifespan else _default_lifespan,
    )

    # 可观测性中间件（统一日志 + 链路追踪 + 慢请求告警）
    if _unified_observability_m12 and ObservabilityMiddleware is not None:
        app.add_middleware(
            ObservabilityMiddleware,
            service_name="m12",
            log_level=settings.log_level.upper() if hasattr(settings, 'log_level') else "INFO",
            slow_request_threshold=3.0,
            exclude_paths=["/health", "/api/v1/status/health", "/status/health"],
        )
        logger.info("可观测性中间件已注册（统一日志 + 链路追踪 + 慢请求告警）")

    # 注册路由
    _register_routers(app)

    # 注册异常处理器（优先使用统一处理器，回退到模块原有实现）
    if _unified_exception_handler_m12:
        register_global_exception_handler(app, logger=logger)
        logger.info("统一异常处理器已注册（6 位错误码体系）")
    else:
        _register_exception_handlers(app)

    return app


# ===========================================================================
# 默认生命周期
# ===========================================================================

@asynccontextmanager
async def _default_lifespan(app: FastAPI):
    """默认应用生命周期管理

    启动时初始化数据库和各服务组件，关闭时执行清理。
    """
    logger.info("[M12] 正在初始化...")

    # 0. 检查密钥安全性
    try:
        settings.validate_secret_security()
    except ValueError as e:
        logger.error("[M12] %s", e)
        raise SystemExit(1)

    # 1. 初始化数据库
    init_db()
    logger.info("[M12] 数据库初始化完成")

    # 2. 初始化 WAF 引擎
    try:
        from .services.waf_engine import get_waf_engine
        waf = get_waf_engine()
        rule_count = waf.get_rule_count()
        logger.info("[M12] WAF 引擎初始化完成 (%d 条规则)", rule_count)
    except Exception as e:
        logger.warning("[M12] WAF 引擎初始化警告: %s", e)

    # 3. 初始化速率限制器
    try:
        from .services.rate_limiter import get_rate_limiter
        rl = get_rate_limiter()
        logger.info("[M12] 速率限制器初始化完成")
    except Exception as e:
        logger.warning("[M12] 速率限制器初始化警告: %s", e)

    # 4. 初始化 IP 过滤器
    try:
        from .services.ip_filter import get_ip_filter
        ipf = get_ip_filter()
        bl, wl = ipf.get_counts()
        logger.info("[M12] IP 过滤器初始化完成 (黑名单:%d, 白名单:%d)", bl, wl)
    except Exception as e:
        logger.warning("[M12] IP 过滤器初始化警告: %s", e)

    # 5. 初始化审计服务
    try:
        from .services.audit_service import get_audit_service
        audit = get_audit_service()
        logger.info("[M12] 审计服务初始化完成")
    except Exception as e:
        logger.warning("[M12] 审计服务初始化警告: %s", e)

    # 6. 初始化自动响应引擎
    try:
        from .services.auto_response import get_auto_response_engine
        ar_engine = get_auto_response_engine()
        level = ar_engine.get_response_level()
        logger.info("[M12] 自动响应引擎初始化完成 (级别: %s)", level)
    except Exception as e:
        logger.warning("[M12] 自动响应引擎初始化警告: %s", e)

    logger.info("[M12] 安全盾启动完成 - 端口 %d", get_settings().port)

    yield

    # 关闭时清理
    logger.info("[M12] 服务正在关闭...")
    logger.info("[M12] 服务已关闭")


# ===========================================================================
# 路由注册
# ===========================================================================

def _register_routers(app: FastAPI) -> None:
    """注册所有 API 路由

    Args:
        app: FastAPI 应用实例
    """
    # 延迟导入以避免循环引用
    try:
        from .routers.status import router as status_router
        from .routers.waf import router as waf_router
        from .routers.auth_api import router as auth_router
        from .routers.ip_control import router as ip_router
        from .routers.audit import router as audit_router
        from .routers.dashboard import router as dashboard_router
        from .routers.auto_response import router as auto_response_router
    except ImportError:
        from routers.status import router as status_router
        from routers.waf import router as waf_router
        from routers.auth_api import router as auth_router
        from routers.ip_control import router as ip_router
        from routers.audit import router as audit_router
        from routers.dashboard import router as dashboard_router
        from routers.auto_response import router as auto_response_router

    # 注册各模块路由
    app.include_router(status_router)
    app.include_router(waf_router)
    app.include_router(auth_router)
    app.include_router(ip_router)
    app.include_router(audit_router)
    app.include_router(dashboard_router)
    app.include_router(auto_response_router)


# ===========================================================================
# 异常处理器
# ===========================================================================

def _register_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器

    Args:
        app: FastAPI 应用实例
    """

    @app.exception_handler(404)
    async def not_found_handler(request, exc):
        """404 处理器"""
        return JSONResponse(
            status_code=404,
            content={
                "code": 404,
                "message": "请求的资源不存在",
                "data": {"path": request.url.path},
            },
        )

    @app.exception_handler(500)
    async def server_error_handler(request, exc):
        """500 处理器"""
        return JSONResponse(
            status_code=500,
            content={
                "code": 500,
                "message": "服务器内部错误",
                "data": None,
            },
        )


# ===========================================================================
# 直接运行
# ===========================================================================

if __name__ == "__main__":
    import uvicorn
    settings = get_settings()
    app = create_app()
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
