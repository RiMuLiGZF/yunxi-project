"""
云汐 M9 开发者工坊 - 主入口文件
FastAPI 应用主入口，负责初始化应用、注册路由、配置中间件
"""

import os
import sys
import time
import threading
import psutil
from pathlib import Path

# 确保可以导入同级模块
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from fastapi import FastAPI, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, RedirectResponse

# 导入配置和模型
from config import get_settings
from models import init_db

# 导入路由
from routers.vscode import router as vscode_router
from routers.workspace import router as workspace_router
from routers.mcp import router as mcp_router
from routers.dashboard import router as dashboard_router
from routers.code import router as code_router

# 导入中间件
from core.auth_middleware import AuthMiddleware, RateLimitMiddleware

# 导入日志和错误处理
from core.logging_config import setup_logging, get_logger
from core.error_handler import global_exception_handler


# ===== 初始化配置 =====
settings = get_settings()

# ===== 版本号 =====
# P2优化后版本 - 可观测性/数据库/沙箱/MCP/配置中心
APP_VERSION = "1.3.0"

# ===== M8 标准接口启动时间（用于 uptime 计算） =====
_start_time_m8 = time.time()

# ===== P2-1: 请求统计计数器 =====
_request_count = 0
_request_error_count = 0
_request_total_time = 0.0
_request_lock = threading.Lock()

# ===== 创建 FastAPI 应用 =====
# 初始化日志系统
setup_logging(level="DEBUG" if settings.debug else "INFO", log_dir=str(settings.data_dir), log_file="m9.log")
logger = get_logger("main")

app = FastAPI(
    title="云汐 M9 开发者工坊 API",
    description="M9 开发者工坊后端服务 - VS Code 管理、工作区管理、MCP 桥接",
    version=APP_VERSION,
    debug=settings.debug,
)

# 注册全局异常处理器
app.add_exception_handler(Exception, global_exception_handler)

# ===== 配置 CORS 中间件 =====
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== 认证中间件 =====
# 全环境启用，保护除白名单外的所有 API 接口
app.add_middleware(AuthMiddleware)

# ===== 速率限制中间件 =====
# 全环境启用，防止 API 滥用（默认 100 次/分钟/IP）
app.add_middleware(RateLimitMiddleware)


# ===== 旧 API 路径兼容中间件 =====
# 将 /api/xxx/* 重定向到 /api/v1/xxx/*，保留请求方法和 body
# 使用 307/308 重定向，并添加 Deprecation 警告头
_DEPRECATED_PREFIXES = {
    "/api/workspace": "/api/v1/workspace",
    "/api/vscode": "/api/v1/vscode",
    "/api/mcp": "/api/v1/mcp",
    "/api/dashboard": "/api/v1/dashboard",
}


@app.middleware("http")
async def deprecated_api_redirect_middleware(request: Request, call_next):
    """旧 API 路径兼容中间件

    将 /api/xxx/* 的请求重定向到 /api/v1/xxx/*，
    同时在响应头中添加 Deprecation 警告，提示客户端迁移到新路径。

    - GET/HEAD 请求使用 308 永久重定向（保留方法）
    - 其他请求使用 307 临时重定向（保留方法和 body）
    """
    path = request.url.path

    # 跳过已经是 /api/v1/ 的路径和非匹配路径
    if path.startswith("/api/v1/"):
        return await call_next(request)

    # 检查是否匹配旧路径前缀
    for old_prefix, new_prefix in _DEPRECATED_PREFIXES.items():
        if path == old_prefix or path.startswith(old_prefix + "/"):
            # 构建新路径，保留查询参数
            new_path = new_prefix + path[len(old_prefix):]
            new_url = request.url.replace(path=new_path)

            # GET/HEAD 使用 308（永久重定向，保留方法），其他使用 307（临时重定向，保留方法和body）
            status_code = 308 if request.method in ("GET", "HEAD") else 307

            response = RedirectResponse(url=str(new_url), status_code=status_code)
            # 添加 Deprecation 警告头（RFC 8594 标准）
            response.headers["Deprecation"] = "true"
            response.headers["Warning"] = '299 - "Deprecated API path: use /api/v1/ prefix instead"'
            response.headers["X-Deprecated-Reason"] = f"Path {old_prefix} is deprecated, use {new_prefix} instead"
            return response

    return await call_next(request)


# ===== P2-1: 请求统计中间件 =====
@app.middleware("http")
async def request_stats_middleware(request: Request, call_next):
    """请求统计中间件 - 记录请求数、错误数和响应时间"""
    global _request_count, _request_error_count, _request_total_time
    start = time.time()
    response = await call_next(request)
    elapsed = time.time() - start
    with _request_lock:
        _request_count += 1
        _request_total_time += elapsed
        if response.status_code >= 400:
            _request_error_count += 1
    return response


# ===== 注册路由 =====
# 注意：各路由文件内部已定义 prefix，这里直接包含即可
app.include_router(vscode_router)
app.include_router(workspace_router)
app.include_router(mcp_router)
app.include_router(dashboard_router)
app.include_router(code_router)


# ===== 静态文件服务（前端页面） =====
# 前端构建产物目录（预留）
_frontend_dir = BASE_DIR.parent / "frontend" / "dist"
if _frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dir), html=True), name="frontend")
else:
    # 如果没有前端构建产物，挂载一个默认静态目录
    _static_dir = BASE_DIR / "static"
    _static_dir.mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")



# ===== M8 标准接口 - Token 验证辅助函数 =====
def _verify_m8_token(x_m8_token: str = Header(None)) -> bool:
    """验证 M8 标准接口的 x-m8-token Header.

    使用与认证中间件一致的 Token 获取逻辑，支持开发环境默认 Token。
    使用 hmac.compare_digest 防时序攻击。
    返回 True 表示验证通过。
    """
    # 使用与认证中间件一致的 Token 获取逻辑
    from core.auth_middleware import get_admin_token
    expected = get_admin_token()
    # 如果未配置 token，M8 接口也不可访问
    if not expected:
        return False
    # 使用安全的字符串比较（防时序攻击）
    import hmac
    return hmac.compare_digest(x_m8_token or "", expected)


# ===== M8 标准接口 - 健康检查 =====
@app.get("/m8/health", summary="M8 标准健康检查接口")
async def m8_health(x_m8_token: str = Header(None)):
    """M8 标准健康检查接口

    返回服务健康状态，包含深度探针信息：
    - DB 连通性
    - VSCode 状态
    - MCP 工具数
    - 服务运行时长

    需要 x-m8-token Header 验证。
    """
    # Token 验证
    if not _verify_m8_token(x_m8_token):
        return JSONResponse(
            status_code=401,
            content={"code": 40101, "message": "Unauthorized: Invalid or missing x-m8-token", "data": None},
        )

    # 深度探针：DB 连通性
    db_status = "unknown"
    try:
        from models import SessionLocal
        db = SessionLocal()
        db.execute("SELECT 1")
        db.close()
        db_status = "connected"
    except Exception:
        db_status = "disconnected"

    # 深度探针：VSCode 状态
    vscode_status = "unknown"
    vscode_installed = False
    vscode_running_count = 0
    try:
        from vscode_manager import get_vscode_manager
        vscode_mgr = get_vscode_manager()
        vscode_installed = vscode_mgr.is_installed()
        procs = vscode_mgr.get_running_processes()
        vscode_running_count = len(procs)
        if vscode_installed:
            vscode_status = "running" if vscode_running_count > 0 else "installed"
        else:
            vscode_status = "not_installed"
    except Exception:
        vscode_status = "error"

    # 深度探针：MCP 工具数
    mcp_tool_count = 0
    mcp_status = "unknown"
    try:
        from mcp_bridge import get_mcp_registry
        mcp_registry = get_mcp_registry()
        tools = mcp_registry.list_tools()
        mcp_tool_count = len(tools)
        mcp_status = "active"
    except Exception:
        mcp_status = "error"

    # 计算 uptime
    uptime_seconds = int(time.time() - _start_time_m8)
    uptime_str = f"{uptime_seconds // 3600}h {(uptime_seconds % 3600) // 60}m {uptime_seconds % 60}s"

    # 总体健康状态
    overall_status = "healthy"
    if db_status != "connected":
        overall_status = "degraded"
    if mcp_status == "error":
        overall_status = "degraded"

    return {
        "code": 0,
        "message": "ok",
        "data": {
            "status": overall_status,
            "service": "yunxi-m9-dev-workshop",
            "version": APP_VERSION,
            "uptime": uptime_seconds,
            "uptime_str": uptime_str,
            "probes": {
                "database": {
                    "status": db_status,
                },
                "vscode": {
                    "status": vscode_status,
                    "installed": vscode_installed,
                    "running_instances": vscode_running_count,
                },
                "mcp": {
                    "status": mcp_status,
                    "tool_count": mcp_tool_count,
                },
            },
        },
    }


# ===== M8 标准接口 - 指标接口 =====
@app.get("/m8/metrics", summary="M8 标准指标接口")
async def m8_metrics(x_m8_token: str = Header(None)):
    """M8 标准指标接口

    返回服务运行指标（P2-1 扩展至 ≥15 个）：
    - 系统指标：CPU/内存/磁盘/文件描述符
    - API 指标：请求数/错误数/平均响应时间/端点数
    - VSCode 实例数
    - 项目数
    - MCP 工具数
    - 代码执行：总次数/成功/失败/平均耗时

    需要 x-m8-token Header 验证。
    """
    # Token 验证
    if not _verify_m8_token(x_m8_token):
        return JSONResponse(
            status_code=401,
            content={"code": 40101, "message": "Unauthorized: Invalid or missing x-m8-token", "data": None},
        )

    # 系统指标：CPU/内存/磁盘/文件描述符
    cpu_percent = 0.0
    memory_percent = 0.0
    memory_used_mb = 0.0
    memory_total_mb = 0.0
    disk_usage = 0.0
    open_fds = 0
    try:
        cpu_percent = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        memory_percent = mem.percent
        memory_used_mb = round(mem.used / (1024 * 1024), 2)
        memory_total_mb = round(mem.total / (1024 * 1024), 2)
        # P2-1 新增：磁盘使用率
        disk = psutil.disk_usage("/")
        disk_usage = round((disk.used / disk.total) * 100, 2)
        # P2-1 新增：打开的文件描述符/句柄数
        proc = psutil.Process()
        try:
            open_fds = proc.num_fds()
        except AttributeError:
            # Windows 使用 num_handles()
            open_fds = proc.num_handles()
    except Exception:
        pass

    # API 请求统计
    with _request_lock:
        total_requests = _request_count
        error_requests = _request_error_count
        avg_resp_ms = round((_request_total_time / max(_request_count, 1)) * 1000, 3)

    # 端点数
    endpoints_count = 0
    try:
        endpoints_count = len(app.openapi()["paths"].keys())
    except Exception:
        pass

    # VSCode 实例数
    vscode_instances = 0
    try:
        from vscode_manager import get_vscode_manager
        vscode_mgr = get_vscode_manager()
        vscode_instances = len(vscode_mgr.get_running_processes())
    except Exception:
        pass

    # 项目数
    total_projects = 0
    try:
        from workspace_manager import get_workspace_manager
        ws_mgr = get_workspace_manager()
        stats = ws_mgr.get_statistics()
        total_projects = stats.get("total_projects", 0)
    except Exception:
        pass

    # MCP 工具数
    mcp_tool_count = 0
    try:
        from mcp_bridge import get_mcp_registry
        mcp_registry = get_mcp_registry()
        mcp_tool_count = len(mcp_registry.list_tools())
    except Exception:
        pass

    # 代码执行统计（P2-1 扩展）
    code_exec_count = 0
    code_exec_success = 0
    code_exec_failed = 0
    code_avg_time = 0.0
    try:
        from core.code_executor import code_executor
        code_exec_count = code_executor.exec_count
        code_exec_success = code_executor.exec_success_count
        code_exec_failed = code_executor.exec_failed_count
        code_avg_time = code_executor.avg_exec_time
    except Exception:
        pass

    # 运行时长
    uptime_seconds = int(time.time() - _start_time_m8)

    return {
        "code": 0,
        "message": "ok",
        "data": {
            "service": "yunxi-m9-dev-workshop",
            "version": APP_VERSION,
            "uptime": uptime_seconds,
            "system": {
                "cpu_percent": cpu_percent,
                "memory_percent": memory_percent,
                "memory_used_mb": memory_used_mb,
                "memory_total_mb": memory_total_mb,
                "disk_usage_percent": disk_usage,
                "open_file_descriptors": open_fds,
            },
            "api": {
                "total_requests": total_requests,
                "error_requests": error_requests,
                "avg_response_time_ms": avg_resp_ms,
                "endpoints_count": endpoints_count,
            },
            "vscode": {
                "running_instances": vscode_instances,
            },
            "workspace": {
                "total_projects": total_projects,
            },
            "mcp": {
                "tool_count": mcp_tool_count,
            },
            "code_execution": {
                "total_executions": code_exec_count,
                "success_count": code_exec_success,
                "failed_count": code_exec_failed,
                "avg_exec_time_s": code_avg_time,
            },
        },
    }


# ===== M8 标准接口 - 配置接口 =====
@app.get("/m8/config", summary="M8 标准配置接口")
async def m8_config(x_m8_token: str = Header(None)):
    """M8 标准配置接口

    返回服务配置信息（敏感信息已脱敏）。
    需要 x-m8-token Header 验证。
    """
    # Token 验证
    if not _verify_m8_token(x_m8_token):
        return JSONResponse(
            status_code=401,
            content={"code": 40101, "message": "Unauthorized: Invalid or missing x-m8-token", "data": None},
        )

    return {
        "code": 0,
        "message": "ok",
        "data": {
            "service": "yunxi-m9-dev-workshop",
            "version": APP_VERSION,
            "config": {
                # 服务配置
                "host": settings.host,
                "port": settings.port,
                "debug": settings.debug,
                # 工作区配置（脱敏）
                "workspace_root": settings.workspace_root,
                "scan_dirs_count": len(settings.scan_dirs) if settings.scan_dirs else 0,
                # VSCode 配置
                "vscode_installed": bool(settings.vscode_path),
                "vscode_path": settings.vscode_path or "",
                # MCP 配置
                "mcp_enabled": settings.mcp_enabled,
                "mcp_port": settings.mcp_port,
                # 安全配置（脱敏）
                "admin_token_configured": bool(settings.admin_token),
                # 代码执行配置
                "code_exec_timeout": settings.code_exec_timeout,
                "code_exec_sandbox_enabled": settings.code_exec_sandbox_enabled,
            },
        },
    }

# ===== M8 标准接口 - 配置热更新 =====
@app.post("/m8/config/reload", summary="M8 配置热更新接口")
async def m8_config_reload(x_m8_token: str = Header(None)):
    """重新加载环境变量配置（P2-5）"""
    if not _verify_m8_token(x_m8_token):
        return JSONResponse(status_code=401, content={"code": 40101, "message": "Unauthorized", "data": None})

    changes = settings.reload_config()
    logger.info(f"配置热更新: {changes}")
    return {"code": 0, "message": "ok", "data": {"changes": changes, "version": APP_VERSION}}


# ===== 启动事件 =====
@app.on_event("startup")
async def startup_event():
    """应用启动时的初始化操作"""
    # 1. 初始化数据库
    init_db()
    logger.info("数据库初始化完成")

    # 2. 自动检测 VS Code
    vscode_path = settings.vscode_path
    if vscode_path:
        logger.info(f"VS Code 已检测: {vscode_path}")
    else:
        logger.warning("未检测到 VS Code 安装")

    # 3. 初始化 MCP 注册中心（触发内置工具注册）
    try:
        from mcp_bridge import get_mcp_registry
        registry = get_mcp_registry()
        tools = registry.list_tools()
        logger.info(f"MCP 工具注册完成，共 {len(tools)} 个工具")
    except Exception as e:
        logger.warning(f"MCP 初始化警告: {e}")

    # 4. 初始化工作区
    try:
        from workspace_manager import get_workspace_manager
        ws_mgr = get_workspace_manager()
        stats = ws_mgr.get_statistics()
        logger.info(f"工作区管理就绪，共 {stats['total_projects']} 个项目")
    except Exception as e:
        logger.warning(f"工作区初始化警告: {e}")

    # 5. 认证中间件已启用（全环境生效）
    logger.info("认证中间件已启用（全环境生效）")
    logger.info(f"速率限制中间件已启用（默认 100次/分钟/IP）")

    logger.info(f"开发者工坊服务启动完成，版本: {APP_VERSION}，监听端口: {settings.port}")


@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭时的清理操作"""
    try:
        from vscode_manager import _vscode_manager
        from workspace_manager import _workspace_manager
        from mcp_bridge import _mcp_registry

        if _vscode_manager:
            _vscode_manager.close_db()
        if _workspace_manager:
            _workspace_manager.close()
        if _mcp_registry:
            _mcp_registry.close()
    except Exception:
        pass
    logger.info("服务已关闭")


# ===== 健康检查接口 =====
@app.get("/health", summary="健康检查")
def health_check():
    """服务健康检查接口"""
    from vscode_manager import get_vscode_manager
    from mcp_bridge import get_mcp_registry

    vscode_mgr = get_vscode_manager()
    mcp_registry = get_mcp_registry()

    return {
        "status": "healthy",
        "service": "yunxi-m9-dev-workshop",
        "version": APP_VERSION,
        "vscode_installed": vscode_mgr.is_installed(),
        "mcp_tools": len(mcp_registry.list_tools()),
    }


@app.get("/api/info", summary="API 信息")
def api_info():
    """获取 API 基本信息"""
    return {
        "name": "云汐 M9 开发者工坊 API",
        "version": APP_VERSION,
        "description": "VS Code 管理、工作区管理、MCP 桥接服务",
        "modules": [
            {"name": "VS Code 管理", "prefix": "/api/v1/vscode", "status": "active"},
            {"name": "工作区管理", "prefix": "/api/v1/workspace", "status": "active"},
            {"name": "MCP 桥接", "prefix": "/api/v1/mcp", "status": "active"},
            {"name": "仪表盘", "prefix": "/api/v1/dashboard", "status": "active"},
            {"name": "代码执行", "prefix": "/api/v1/code", "status": "active"},
        ],
        "deprecated_prefixes": [
            "/api/vscode",
            "/api/workspace",
            "/api/mcp",
            "/api/dashboard",
        ],
        "docs": "/docs",
        "redoc": "/redoc",
    }


# ===== 根路径 =====
@app.get("/", include_in_schema=False)
def root():
    """根路径重定向到 API 文档"""
    return JSONResponse(
        content={
            "message": "云汐 M9 开发者工坊 API 服务",
            "docs": "/docs",
            "health": "/health",
            "api_info": "/api/info",
            "m8_health": "/m8/health",
            "m8_metrics": "/m8/metrics",
            "m8_config": "/m8/config",
        }
    )


# ===== 启动服务 =====
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
