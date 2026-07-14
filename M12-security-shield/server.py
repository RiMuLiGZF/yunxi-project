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

import os
import sys
import time
import uuid
from pathlib import Path
from contextlib import asynccontextmanager

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
    print("\n" + "=" * 60)
    print("  M12 安全盾服务 - 启动中...")
    print("=" * 60)

    # 初始化 WAF 引擎
    waf = get_waf_engine()
    rule_count = waf.get_rule_count()
    print(f"  WAF 引擎: 已就绪 (防护规则 {rule_count} 条)")

    # 初始化速率限制器
    rl = get_rate_limiter()
    print(f"  速率限制: 已就绪 (默认 {rl.default_rate} 次/分钟)")

    # 初始化 IP 过滤器
    ipf = get_ip_filter()
    bl_count, wl_count = ipf.get_counts()
    print(f"  IP 过滤: 已就绪 (黑名单 {bl_count} 条, 白名单 {wl_count} 条)")

    # 初始化审计服务
    audit = get_audit_service()
    print(f"  审计服务: 已就绪")

    print("-" * 60)
    print(f"  服务端口: {settings.port}")
    print(f"  数据库:   {settings.db_path}")
    print("=" * 60 + "\n")

    yield

    # 关闭时清理
    print("\n正在关闭 M12 安全盾服务...")
    print("M12 安全盾服务已关闭\n")


# ---------------------------------------------------------------------------
# FastAPI 应用
# ---------------------------------------------------------------------------
app = create_app(lifespan=lifespan)

# ---------------------------------------------------------------------------
# CORS 中间件
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
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

    # WAF 检测（仅对 API 路径）
    if request.url.path.startswith("/api/"):
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

    print("\n" + "=" * 60)
    print("  M12 安全盾服务")
    print("  M12 Security Shield Service")
    print("=" * 60)
    print(f"  版本:        {settings.version}")
    print(f"  模块名:      {settings.module_name}")
    print(f"  监听地址:    {host}:{port}")
    print(f"  WAF 防护:    {'开启' if settings.waf_enabled else '关闭'}")
    print(f"  速率限制:    {'开启' if settings.rate_limit_enabled else '关闭'}")
    print(f"  文档地址:    http://localhost:{port}/docs")
    print(f"  健康检查:    http://localhost:{port}/health")
    print("=" * 60)
    print()

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level=settings.log_level,
    )


if __name__ == "__main__":
    main()
