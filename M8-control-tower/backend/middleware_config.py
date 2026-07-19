"""
M8 中间件配置（ARC-005 重构辅助模块）

集中管理 M8 应用的中间件配置，包括：
- CORS 中间件配置
- 安全响应头中间件配置
- 分布式集群管理配置
"""

import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def setup_security_headers(app: FastAPI, settings, logger) -> bool:
    """
    配置安全响应头中间件

    为所有响应添加标准安全头，防止常见的 Web 攻击：
    - X-Content-Type-Options: nosniff
    - X-Frame-Options: SAMEORIGIN（M8 需要在 iframe 中嵌入，所以用 SAMEORIGIN 而不是 DENY）
    - X-XSS-Protection: 1; mode=block
    - Content-Security-Policy
    - Referrer-Policy
    - Permissions-Policy

    优先使用 shared.core.middleware.security_headers 的统一实现，
    不可用时回退到本地实现。
    """
    try:
        from shared.core.middleware.security_headers import (
            SecurityHeadersMiddleware,
            SecurityHeadersConfig,
        )
        env = getattr(settings, "env", "development").lower()
        is_prod = env in ("production", "prod", "release")

        # M8 是控制塔，需要在 iframe 中嵌入，所以 X-Frame-Options 用 SAMEORIGIN
        config = SecurityHeadersConfig(
            env=env,
            frame_options_value="SAMEORIGIN",
            # 开发环境 CSP 更宽松（允许 inline 脚本和 eval，便于调试）
            csp_policy=None,  # 使用 SecurityHeadersConfig 中的默认策略
        )
        app.add_middleware(SecurityHeadersMiddleware, config=config)
        logger.info("安全响应头中间件已注册（shared 统一实现）")
        return True
    except ImportError:
        # 回退到本地简单实现
        return _setup_security_headers_fallback(app, settings, logger)


def _setup_security_headers_fallback(app: FastAPI, settings, logger) -> bool:
    """
    安全响应头中间件的本地回退实现（当 shared 不可用时）
    使用 Starlette 的 BaseHTTPMiddleware 简单实现
    """
    try:
        from starlette.middleware.base import BaseHTTPMiddleware

        class SimpleSecurityHeadersMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request, call_next):
                response = await call_next(request)
                # 跳过健康检查等路径
                path = request.url.path
                if path in ("/health", "/m8/health", "/m8/metrics"):
                    return response
                # 添加安全头
                response.headers["X-Content-Type-Options"] = "nosniff"
                response.headers["X-Frame-Options"] = "SAMEORIGIN"
                response.headers["X-XSS-Protection"] = "1; mode=block"
                response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
                response.headers["Permissions-Policy"] = (
                    "geolocation=(), microphone=(), camera=(), payment=()"
                )
                return response

        app.add_middleware(SimpleSecurityHeadersMiddleware)
        logger.info("安全响应头中间件已注册（本地回退实现）")
        return True
    except Exception as e:
        logger.warning(f"安全响应头中间件注册失败: {e}")
        return False


def setup_cors(app: FastAPI, settings, logger) -> None:
    """
    配置 CORS 中间件（统一安全策略：生产环境禁用通配符，开发环境默认localhost）
    
    优先使用 shared.core.cors_utils 的统一配置，
    不可用时回退到本地安全策略。
    """
    try:
        from shared.core.cors_utils import get_cors_middleware_kwargs
        cors_kwargs = get_cors_middleware_kwargs(
            configured_origins=settings.cors_origins,
            env=settings.env,
            module_name="m8",
            allow_credentials=True,
            logger=logger,
        )
        app.add_middleware(CORSMiddleware, **cors_kwargs)
    except ImportError:
        _setup_cors_fallback(app, settings, logger)


def _setup_cors_fallback(app: FastAPI, settings, logger) -> None:
    """shared 不可用时使用本地安全策略"""
    _env = os.environ.get("YUNXI_ENV", os.environ.get("ENV", "development")).lower()
    _is_prod = _env in ("production", "prod", "release")
    _cors_raw = settings.cors_origins
    _cors_list = [o.strip() for o in _cors_raw.split(",") if o.strip()]

    if _is_prod and (not _cors_list or _cors_raw == "*"):
        raise RuntimeError(
            "[CORS] 生产环境必须显式配置 ALLOWED_ORIGINS，禁止使用 '*'。"
            "请在 yunxi.env 中设置 CORS_ORIGINS 为具体域名列表。"
        )

    if not _cors_list or _cors_raw == "*":
        if not _is_prod:
            _dev_ports = [3000, 5173, 8080] + list(range(8000, 8013))
            _cors_list = [f"http://localhost:{p}" for p in _dev_ports] + \
                         [f"http://127.0.0.1:{p}" for p in _dev_ports]
            logger.warning(
                "[CORS] 开发环境使用默认 localhost 来源列表（%d 个）。"
                "生产环境请配置具体域名。", len(_cors_list)
            )
        else:
            _cors_list = []

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


def setup_distributed_cluster(app: FastAPI, logger) -> bool:
    """
    配置分布式集群管理
    
    Returns:
        bool: 是否成功启用分布式集群管理
    """
    try:
        from shared.business.distributed.api import router as cluster_router, init_services as init_cluster_services
        from shared.business.distributed import NodeConfig, NodeRegistry, MessageBus
    except ImportError:
        return False
    
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
    
    return True
