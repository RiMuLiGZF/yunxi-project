"""
云汐 M9 开发者工坊 - 主入口文件
FastAPI 应用主入口，负责初始化应用、注册路由、配置中间件
"""

import os
import sys
from pathlib import Path

# 确保可以导入同级模块
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from fastapi import FastAPI, Request
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


# ===== 初始化配置 =====
settings = get_settings()

# ===== 创建 FastAPI 应用 =====
app = FastAPI(
    title="云汐 M9 开发者工坊 API",
    description="M9 开发者工坊后端服务 - VS Code 管理、工作区管理、MCP 桥接",
    version="1.0.0",
    debug=settings.debug,
)

# ===== 配置 CORS 中间件 =====
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


# ===== 注册路由 =====
# 注意：各路由文件内部已定义 prefix，这里直接包含即可
app.include_router(vscode_router)
app.include_router(workspace_router)
app.include_router(mcp_router)
app.include_router(dashboard_router)


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


# ===== 启动事件 =====
@app.on_event("startup")
async def startup_event():
    """应用启动时的初始化操作"""
    # 1. 初始化数据库
    init_db()
    print("[M9] 数据库初始化完成")

    # 2. 自动检测 VS Code
    vscode_path = settings.vscode_path
    if vscode_path:
        print(f"[M9] VS Code 已检测: {vscode_path}")
    else:
        print("[M9] 警告: 未检测到 VS Code 安装")

    # 3. 初始化 MCP 注册中心（触发内置工具注册）
    try:
        from mcp_bridge import get_mcp_registry
        registry = get_mcp_registry()
        tools = registry.list_tools()
        print(f"[M9] MCP 工具注册完成，共 {len(tools)} 个工具")
    except Exception as e:
        print(f"[M9] MCP 初始化警告: {e}")

    # 4. 初始化工作区
    try:
        from workspace_manager import get_workspace_manager
        ws_mgr = get_workspace_manager()
        stats = ws_mgr.get_statistics()
        print(f"[M9] 工作区管理就绪，共 {stats['total_projects']} 个项目")
    except Exception as e:
        print(f"[M9] 工作区初始化警告: {e}")

    print(f"[M9] 开发者工坊服务启动完成，监听端口: {settings.port}")


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
    print("[M9] 服务已关闭")


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
        "version": "1.0.0",
        "vscode_installed": vscode_mgr.is_installed(),
        "mcp_tools": len(mcp_registry.list_tools()),
    }


@app.get("/api/info", summary="API 信息")
def api_info():
    """获取 API 基本信息"""
    return {
        "name": "云汐 M9 开发者工坊 API",
        "version": "1.0.0",
        "description": "VS Code 管理、工作区管理、MCP 桥接服务",
        "modules": [
            {"name": "VS Code 管理", "prefix": "/api/v1/vscode", "status": "active"},
            {"name": "工作区管理", "prefix": "/api/v1/workspace", "status": "active"},
            {"name": "MCP 桥接", "prefix": "/api/v1/mcp", "status": "active"},
            {"name": "仪表盘", "prefix": "/api/v1/dashboard", "status": "active"},
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
