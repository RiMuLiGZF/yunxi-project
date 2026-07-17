"""
M12 安全盾服务 - FastAPI 启动入口

云汐系统模块十二：安全盾（Security Shield）
提供 WAF 防护墙、API 密钥管理、IP 黑白名单、速率限制、
安全审计、威胁检测等全方位安全防护能力。

运行方式:
    python server.py

默认端口: 8012 (通过环境变量 M12_PORT 配置)
"""

from __future__ import annotations

import logging
import os
import sys
import time
import uuid
from pathlib import Path
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

import uvicorn
from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

# ---------------------------------------------------------------------------
# 路径配置
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = BASE_DIR / "backend"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
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
# 导入 M12 核心组件
# ---------------------------------------------------------------------------
from backend.config import get_settings
from backend.main import create_app
from backend.services.waf_engine import get_waf_engine
from backend.services.rate_limiter import get_rate_limiter
from backend.services.ip_filter import get_ip_filter
from backend.services.audit_service import get_audit_service

# ---------------------------------------------------------------------------
# 加载配置
# ---------------------------------------------------------------------------
settings = get_settings()

# ---------------------------------------------------------------------------
# 生命周期管理
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理."""
    logger.info("=" * 60)
    logger.info("  M12 安全盾服务 - 启动中...")
    logger.info("=" * 60)

    # 初始化 WAF 引擎
    waf = get_waf_engine()
    rule_count = waf.get_rule_count()
    logger.info("  WAF 引擎: 已就绪 (防护规则 %d 条)", rule_count)

    # 初始化速率限制器
    rl = get_rate_limiter()
    logger.info("  速率限制: 已就绪 (默认 %d 次/分钟)", rl.default_rate)

    # 初始化 IP 过滤器
    ipf = get_ip_filter()
    bl_count, wl_count = ipf.get_counts()
    logger.info("  IP 过滤: 已就绪 (黑名单 %d 条, 白名单 %d 条)", bl_count, wl_count)

    # 初始化审计服务
    audit = get_audit_service()
    logger.info("  审计服务: 已就绪")

    logger.info("-" * 60)
    logger.info("  服务端口: %d", settings.port)
    logger.info("  数据库:   %s", settings.db_path)
    logger.info("=" * 60)

    yield

    # 关闭时清理
    logger.info("正在关闭 M12 安全盾服务...")
    logger.info("M12 安全盾服务已关闭")


# ---------------------------------------------------------------------------
# FastAPI 应用
# ---------------------------------------------------------------------------
app = create_app(lifespan=lifespan)

# ---------------------------------------------------------------------------
# CORS 中间件（统一安全策略：生产环境禁用通配符，开发环境默认localhost）
# ---------------------------------------------------------------------------
_cors_env = os.environ.get("YUNXI_ENV", os.environ.get("ENV", "development")).lower()
_cors_is_prod = _cors_env in ("production", "prod", "release")
_cors_origins = settings.cors_origins
_cors_has_wildcard = any(o == "*" for o in _cors_origins)

if _cors_is_prod and (not _cors_origins or _cors_has_wildcard):
    raise RuntimeError(
        "[CORS] 生产环境安全校验失败：M12 安全盾的 CORS origins "
        f"包含通配符或为空。生产环境必须显式配置具体的允许来源，"
        "禁止使用通配符 '*'。请设置 M12_CORS_ORIGINS 环境变量。"
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# 请求中间件：request_id 注入 + WAF 检测 + 速率限制
# ---------------------------------------------------------------------------
@app.middleware("http")
async def security_middleware(request: Request, call_next):
    """安全中间件：request_id注入、WAF检测、速率限制、响应时间记录."""
    start_time = time.time()
    request_id = uuid.uuid4().hex[:16]
    request.state.request_id = request_id

    # 获取客户端 IP
    client_ip = request.client.host if request.client else "unknown"
    request.state.client_ip = client_ip

    # 速率限制检查（仅对 API 路径）
    if request.url.path.startswith("/api/"):
        try:
            rl = get_rate_limiter()
            if not rl.allow_request(client_ip):
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    status_code=429,
                    content={
                        "code": 429,
                        "message": "请求过于频繁，请稍后再试",
                        "data": {"retry_after": rl.get_retry_after(client_ip)},
                        "request_id": request_id,
                    },
                )
        except Exception as e:
            logger.error("Rate limiter error, fail-open: %s", e, exc_info=True)

    # WAF 检测（仅对 API 路径）
    if request.url.path.startswith("/api/"):
        try:
            waf = get_waf_engine()
            check_result = waf.check_request(
                method=request.method,
                path=request.url.path,
                query=request.url.query,
                headers=dict(request.headers),
                client_ip=client_ip,
            )
            if not check_result["passed"]:
                # 记录安全事件
                audit = get_audit_service()
                audit.log_security_event(
                    event_type="waf_block",
                    severity="high",
                    source_ip=client_ip,
                    description=f"WAF拦截: {check_result['rule_name']}",
                    details=check_result,
                )
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    status_code=403,
                    content={
                        "code": 403,
                        "message": f"请求被安全策略拦截: {check_result['rule_name']}",
                        "data": check_result,
                        "request_id": request_id,
                    },
                )
        except Exception as e:
            logger.error("WAF check error, fail-open: %s", e, exc_info=True)

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
    waf = get_waf_engine()
    waf_status = waf.get_status()

    return {
        "name": "M12 安全盾服务",
        "module": "m12-security-shield",
        "version": settings.version,
        "status": "running",
        "docs": "/docs",
        "openapi": "/openapi.json",
        "waf_rules": waf_status["total_rules"],
        "waf_enabled": waf_status["enabled"],
        "endpoints": {
            "status": "/api/m12/status",
            "waf": "/api/m12/waf",
            "auth": "/api/m12/auth",
            "ip_control": "/api/m12/ip",
            "audit": "/api/m12/audit",
            "dashboard": "/api/m12/dashboard",
        },
    }


# ---------------------------------------------------------------------------
# 健康检查（标准端点）
# ---------------------------------------------------------------------------
@app.get("/health", tags=["Health"], summary="健康检查")
async def health():
    """标准健康检查端点."""
    waf = get_waf_engine()
    waf_status = waf.get_status()
    rl = get_rate_limiter()

    return {
        "code": 0,
        "message": "ok",
        "data": {
            "status": "healthy",
            "module": "m12-security-shield",
            "version": settings.version,
            "waf_enabled": waf_status["enabled"],
            "waf_rules": waf_status["total_rules"],
            "rate_limiter_active": rl.is_active(),
        },
        "request_id": uuid.uuid4().hex[:16],
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# M8 标准对接接口
# ---------------------------------------------------------------------------
_start_time_m8 = time.time()


def _verify_m8_token(x_m8_token: str = "") -> bool:
    """验证 M8 管控塔身份令牌"""
    import hmac
    expected = os.environ.get("M12_ADMIN_TOKEN", "")
    if not expected:
        return False  # 环境变量未设置时，拒绝所有请求（安全默认）
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
            "module": "m12",
            "module_name": "安全盾",
            "version": settings.version,
            "uptime_seconds": int(time.time() - _start_time_m8),
        }
    }


@app.get("/m8/metrics", tags=["M8-标准接口"], summary="M8标准性能指标")
async def m8_std_metrics(x_m8_token: str = Header(default="")):
    """M8 标准性能指标接口."""
    if not _verify_m8_token(x_m8_token):
        raise HTTPException(status_code=401, detail="Invalid M8 token")
    waf = get_waf_engine()
    waf_status = waf.get_status()
    ipf = get_ip_filter()
    bl_count, wl_count = ipf.get_counts()
    audit = get_audit_service()
    stats = audit.get_recent_stats()
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "waf_rules": waf_status["total_rules"],
            "waf_enabled": waf_status["enabled"],
            "waf_blocks_today": stats.get("waf_blocks_today", 0),
            "ip_blacklist_count": bl_count,
            "ip_whitelist_count": wl_count,
            "security_events_today": stats.get("events_today", 0),
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
            "module": "m12",
            "version": settings.version,
            "env": os.environ.get("YUNXI_ENV", "development"),
            "waf_enabled": settings.waf_enabled,
            "rate_limit_enabled": settings.rate_limit_enabled,
            "default_rate_per_minute": settings.default_rate_per_minute,
        }
    }


# ---------------------------------------------------------------------------
# 启动入口
# ---------------------------------------------------------------------------
def main() -> None:
    """启动 FastAPI 服务."""
    port = settings.port
    host = settings.host

    logger.info("=" * 60)
    logger.info("  M12 安全盾服务")
    logger.info("  M12 Security Shield Service")
    logger.info("=" * 60)
    logger.info("  版本:        %s", settings.version)
    logger.info("  模块名:      %s", settings.module_name)
    logger.info("  监听地址:    %s:%d", host, port)
    logger.info("  WAF 防护:    %s", "开启" if settings.waf_enabled else "关闭")
    logger.info("  速率限制:    %s", "开启" if settings.rate_limit_enabled else "关闭")
    logger.info("  文档地址:    http://localhost:%d/docs", port)
    logger.info("  健康检查:    http://localhost:%d/health", port)
    logger.info("=" * 60)

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level=settings.log_level,
    )


if __name__ == "__main__":
    main()
