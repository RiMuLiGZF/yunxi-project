"""
云汐 M12 安全盾 - 状态/健康检查 API
提供服务状态、健康检查、模块信息等接口

第三阶段增强：接入 shared.core.observability 标准化健康检查，
支持 deep 深度检查、Prometheus 指标输出。
"""

import time
from fastapi import APIRouter, Depends, Query
from typing import Optional

# 兼容相对导入和直接运行
try:
    from ..schemas.common import make_response, make_error_response
    from ..services.waf_engine import get_waf_engine
    from ..services.rate_limiter import get_rate_limiter
    from ..services.ip_filter import get_ip_filter
    from ..services.audit_service import get_audit_service
    from ..config import get_settings
    from ..auth import require_role, ROLE_ADMIN, ROLE_VIEWER
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from schemas.common import make_response, make_error_response
    from services.waf_engine import get_waf_engine
    from services.rate_limiter import get_rate_limiter
    from services.ip_filter import get_ip_filter
    from services.audit_service import get_audit_service
    from config import get_settings
    from auth import require_role, ROLE_ADMIN, ROLE_VIEWER

router = APIRouter(prefix="/api/m12/status", tags=["M12-状态检查"])


# ===========================================================================
# 标准化健康检查器（懒加载）
# ===========================================================================

_m12_health_checker = None
_m12_obs_available = None


def _get_obs_available() -> bool:
    """检查标准化可观测性是否可用."""
    global _m12_obs_available
    if _m12_obs_available is not None:
        return _m12_obs_available

    try:
        from shared.core.observability import HealthChecker  # noqa: F401
        _m12_obs_available = True
    except ImportError:
        _m12_obs_available = False

    return _m12_obs_available


def _get_health_checker():
    """获取或创建 M12 标准化健康检查器."""
    global _m12_health_checker
    if _m12_health_checker is not None:
        return _m12_health_checker

    if not _get_obs_available():
        return None

    try:
        from shared.core.observability import HealthChecker
        from shared.core.observability.health import CheckResult

        settings = get_settings()
        checker = HealthChecker(
            module_name="m12",
            version=settings.version,
            module_display_name="安全盾",
        )

        # 注册轻量检查：内存
        checker.register_memory_check(threshold_percent=90.0, lightweight=True)

        # 注册轻量检查：磁盘
        checker.register_disk_check(
            path=".",
            threshold_percent=90.0,
            lightweight=True,
        )

        # 注册深度检查：数据库（核心）
        def _check_db() -> CheckResult:
            start_t = time.time()
            try:
                from ..database import SessionLocal
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

        checker.register_check("database", _check_db, critical=True, lightweight=False)

        # 注册深度检查：WAF 引擎（M12 特有）
        def _check_waf() -> CheckResult:
            start_t = time.time()
            try:
                waf = get_waf_engine()
                status = waf.get_status()
                resp_ms = (time.time() - start_t) * 1000
                return CheckResult.healthy(
                    enabled=status.get("enabled", False),
                    total_rules=status.get("total_rules", 0),
                    active_rules=status.get("active_rules", 0),
                    response_time_ms=resp_ms,
                )
            except Exception as e:
                resp_ms = (time.time() - start_t) * 1000
                return CheckResult.degraded(
                    error=str(e),
                    response_time_ms=resp_ms,
                )

        checker.register_check("waf", _check_waf, critical=False, lightweight=False)

        # 注册深度检查：速率限制器（M12 特有）
        def _check_rate_limiter() -> CheckResult:
            start_t = time.time()
            try:
                rl = get_rate_limiter()
                resp_ms = (time.time() - start_t) * 1000
                return CheckResult.healthy(
                    active=rl.is_active(),
                    default_rate=rl.default_rate,
                    response_time_ms=resp_ms,
                )
            except Exception as e:
                resp_ms = (time.time() - start_t) * 1000
                return CheckResult.degraded(
                    error=str(e),
                    response_time_ms=resp_ms,
                )

        checker.register_check("rate_limiter", _check_rate_limiter, critical=False, lightweight=False)

        # 注册深度检查：IP 过滤器（M12 特有）
        def _check_ip_filter() -> CheckResult:
            start_t = time.time()
            try:
                ipf = get_ip_filter()
                bl_count, wl_count = ipf.get_counts()
                resp_ms = (time.time() - start_t) * 1000
                return CheckResult.healthy(
                    blacklist_count=bl_count,
                    whitelist_count=wl_count,
                    response_time_ms=resp_ms,
                )
            except Exception as e:
                resp_ms = (time.time() - start_t) * 1000
                return CheckResult.degraded(
                    error=str(e),
                    response_time_ms=resp_ms,
                )

        checker.register_check("ip_filter", _check_ip_filter, critical=False, lightweight=False)

        # 注册深度检查：审计服务（M12 特有）
        def _check_audit() -> CheckResult:
            start_t = time.time()
            try:
                audit = get_audit_service()
                stats = audit.get_recent_stats()
                resp_ms = (time.time() - start_t) * 1000
                return CheckResult.healthy(
                    events_today=stats.get("events_today", 0),
                    total_events=stats.get("total_events", 0),
                    response_time_ms=resp_ms,
                )
            except Exception as e:
                resp_ms = (time.time() - start_t) * 1000
                return CheckResult.degraded(
                    error=str(e),
                    response_time_ms=resp_ms,
                )

        checker.register_check("audit", _check_audit, critical=False, lightweight=False)

        _m12_health_checker = checker
        return checker

    except Exception:
        return None


# ===========================================================================
# 根路径健康检查（标准化格式）
# ===========================================================================

@router.get("/health", summary="健康检查")
async def health_check(
    deep: bool = Query(default=False, description="是否执行深度检查（检查所有依赖）"),
):
    """
    服务健康检查接口（标准化格式）

    - 轻量检查（默认）：内存、磁盘等基础指标
    - 深度检查（deep=true）：数据库、WAF、速率限制、IP 过滤、审计等所有依赖
    """
    checker = _get_health_checker()
    if checker is not None:
        result = await checker.async_check(deep=deep)
        return make_response(data=result.to_dict())

    # 回退到旧版实现
    try:
        settings = get_settings()
        waf = get_waf_engine()
        rl = get_rate_limiter()
        ipf = get_ip_filter()

        waf_status = waf.get_status()
        bl_count, wl_count = ipf.get_counts()

        return make_response(data={
            "status": "healthy",
            "module": "m12-security-shield",
            "module_name": "安全盾",
            "version": settings.version,
            "env": settings.env,
            "timestamp": time.time(),
            "components": {
                "waf": {
                    "status": "ok",
                    "enabled": waf_status["enabled"],
                    "rules": waf_status["total_rules"],
                },
                "rate_limiter": {
                    "status": "ok",
                    "enabled": rl.is_active(),
                    "default_rate": rl.default_rate,
                },
                "ip_filter": {
                    "status": "ok",
                    "blacklist_count": bl_count,
                    "whitelist_count": wl_count,
                },
                "audit": {
                    "status": "ok",
                },
            },
        })
    except Exception as e:
        return make_error_response(f"健康检查失败: {str(e)}")


# ===========================================================================
# 模块信息
# ===========================================================================

@router.get("/info", summary="模块信息")
def module_info():
    """
    获取 M12 安全盾模块的基本信息
    """
    try:
        settings = get_settings()
        return make_response(data={
            "module": "m12-security-shield",
            "module_name": settings.module_name_cn,
            "module_code": "M12",
            "version": settings.version,
            "description": "云汐系统安全防护核心模块，提供 WAF 防护墙、API 密钥管理、IP 黑白名单、速率限制、安全审计等全方位安全防护能力。",
            "port": settings.port,
            "env": settings.env,
            "debug": settings.debug,
            "features": [
                {"name": "WAF 防护墙", "enabled": settings.waf_enabled, "description": "SQL注入/XSS/CSRF/命令注入检测"},
                {"name": "速率限制", "enabled": settings.rate_limit_enabled, "description": "令牌桶算法，按IP/API Key限流"},
                {"name": "IP 访问控制", "enabled": True, "description": "黑白名单管理，支持CIDR段"},
                {"name": "API 密钥管理", "enabled": True, "description": "密钥生成、吊销、权限分配"},
                {"name": "JWT 认证", "enabled": True, "description": "基于角色的访问控制"},
                {"name": "安全审计", "enabled": True, "description": "事件记录、查询、统计"},
            ],
            "api_prefix": "/api/m12",
            "docs_url": "/docs",
        })
    except Exception as e:
        return make_error_response(f"获取模块信息失败: {str(e)}")


# ===========================================================================
# 服务状态概览
# ===========================================================================

@router.get("/overview", summary="服务状态概览")
def service_overview(
    current_user: dict = Depends(require_role(ROLE_VIEWER)),
):
    """
    获取服务状态总览，包括各组件运行状态和关键指标
    """
    try:
        waf = get_waf_engine()
        rl = get_rate_limiter()
        ipf = get_ip_filter()
        audit = get_audit_service()

        waf_status = waf.get_status()
        bl_count, wl_count = ipf.get_counts()
        audit_stats = audit.get_recent_stats()

        return make_response(data={
            "uptime": "running",
            "waf": {
                "enabled": waf_status["enabled"],
                "total_rules": waf_status["total_rules"],
                "active_rules": waf_status["active_rules"],
                "today_blocks": waf_status["today_blocks"],
            },
            "rate_limit": {
                "enabled": rl.is_active(),
                "default_rate_per_minute": rl.default_rate,
                "burst_size": rl.default_burst,
            },
            "ip_control": {
                "blacklist_count": bl_count,
                "whitelist_count": wl_count,
            },
            "audit": {
                "events_today": audit_stats.get("events_today", 0),
                "waf_blocks_today": audit_stats.get("waf_blocks_today", 0),
                "total_events": audit_stats.get("total_events", 0),
            },
        })
    except Exception as e:
        return make_error_response(f"获取状态概览失败: {str(e)}")


# ===========================================================================
# 配置信息
# ===========================================================================

@router.get("/config", summary="系统配置信息")
def system_config(
    current_user: dict = Depends(require_role(ROLE_ADMIN)),
):
    """
    获取当前运行配置（敏感信息已脱敏）
    """
    try:
        settings = get_settings()
        return make_response(data={
            "module_name": settings.module_name,
            "version": settings.version,
            "env": settings.env,
            "debug": settings.debug,
            "host": settings.host,
            "port": settings.port,
            "log_level": settings.log_level,
            "waf": {
                "enabled": settings.waf_enabled,
                "sql_injection": settings.waf_sql_injection,
                "xss": settings.waf_xss,
                "csrf": settings.waf_csrf,
                "command_injection": settings.waf_command_injection,
                "path_traversal": settings.waf_path_traversal,
            },
            "rate_limit": {
                "enabled": settings.rate_limit_enabled,
                "default_rate_per_minute": settings.default_rate_per_minute,
                "burst_size": settings.rate_limit_burst,
            },
            "jwt": {
                "algorithm": settings.jwt_algorithm,
                "expire_minutes": settings.jwt_expire_minutes,
                "secret_set": bool(settings.jwt_secret),
            },
            "audit": {
                "retention_days": settings.audit_retention_days,
                "log_all_requests": settings.audit_log_all_requests,
            },
            "auto_ban": {
                "failures_threshold": settings.auto_ban_failures,
                "ban_minutes": settings.auto_ban_minutes,
            },
        })
    except Exception as e:
        return make_error_response(f"获取配置信息失败: {str(e)}")
