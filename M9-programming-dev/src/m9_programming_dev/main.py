"""M9 Programming Dev - FastAPI 入口"""

from fastapi import FastAPI
from .config import settings
from .routers import vscode, code, projects
from .auth_middleware import AuthMiddleware, RateLimitMiddleware

app = FastAPI(
    title="M9 Programming Dev API",
    description="云汐系统编程开发模块 - VSCode管理、代码执行、项目管理",
    version="0.1.0"
)

# P2-23: 注册安全中间件（生产环境启用认证）
import os
import hmac
if os.environ.get("YUNXI_ENV", "development") == "production":
    app.add_middleware(AuthMiddleware)

# P2-23: 速率限制中间件
app.add_middleware(RateLimitMiddleware)

# 注册路由
app.include_router(vscode.router, prefix="/api/v1/vscode", tags=["VSCode管理"])
app.include_router(code.router, prefix="/api/v1/code", tags=["代码执行"])
app.include_router(projects.router, prefix="/api/v1/projects", tags=["项目管理"])


from fastapi import Header, HTTPException
import time
import os

# M8 标准接口 - 启动时间记录（用于 uptime_seconds 统计）
_start_time_m8 = time.time()


# M8 标准接口 - Token 验证
def _verify_m8_token(x_m8_token: str = "") -> bool:
    """验证 M8 token."""
    expected = os.environ.get("M9_ADMIN_TOKEN", "")
    if not expected:
        return True
    return hmac.compare_digest(x_m8_token, expected)


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "healthy", "module": "m9_programming_dev"}


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
            "module": "m9",
            "module_name": "编程开发",
            "version": "0.1.0",
            "uptime_seconds": int(time.time() - _start_time_m8),
        },
    }


@app.get("/m8/metrics", tags=["M8-标准接口"], summary="M8标准性能指标")
async def m8_std_metrics(x_m8_token: str = Header(default="")):
    """M8 标准性能指标接口."""
    if not _verify_m8_token(x_m8_token):
        raise HTTPException(status_code=401, detail="Invalid M8 token")
    try:
        import psutil
        cpu_usage = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        mem_usage = mem.percent
        mem_mb = mem.used / (1024 * 1024)
    except Exception:
        cpu_usage = 0.0
        mem_usage = 0.0
        mem_mb = 0
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "cpu_usage": cpu_usage,
            "memory_usage": mem_usage,
            "memory_mb": round(mem_mb, 2),
            "vscode_instances": 0,
            "active_projects": 0,
        },
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
            "module": "m9",
            "version": "0.1.0",
            "env": os.environ.get("YUNXI_ENV", "development"),
            "sandbox_enabled": True,
            "code_exec_timeout": 30,
            "vscode_port_range_start": 8080,
        },
    }


@app.get("/")
async def root():
    return {
        "module": "M9-programming-dev",
        "name": "编程开发模块",
        "version": "0.1.0",
        "endpoints": [
            "/api/v1/vscode/*",
            "/api/v1/code/*",
            "/api/v1/projects/*",
        ]
    }
