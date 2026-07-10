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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

# 导入配置和模型
from config import get_settings
from models import init_db

# 导入路由
from routers.vscode import router as vscode_router
from routers.workspace import router as workspace_router
from routers.mcp import router as mcp_router
from routers.dashboard import router as dashboard_router
from routers.compat import router as compat_router

# 统一错误处理（从shared共享库导入，兼容本地路径）
try:
    from shared.error_handler import register_exception_handlers
except ImportError:
    import sys as _sys
    from pathlib import Path as _Path
    _shared_path = _Path(__file__).resolve().parent.parent.parent / "shared"
    if str(_shared_path) not in _sys.path:
        _sys.path.insert(0, str(_shared_path))
    from error_handler import register_exception_handlers  # type: ignore
from routers.compat import router as compat_router


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

# ===== 注册全局异常处理器 =====
register_exception_handlers(app)
# 保存debug状态供错误处理器使用
app.state.debug = settings.debug

# ===== 注册路由 =====
# 注意：各路由文件内部已定义 prefix，这里直接包含即可
# compat 路由需放在前面，确保前端兼容路径优先匹配
app.include_router(compat_router)
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
            {"name": "前端兼容", "prefix": "/api/stats, /api/projects, /api/activities", "status": "active"},
            {"name": "VS Code 管理", "prefix": "/api/vscode", "status": "active"},
            {"name": "工作区管理", "prefix": "/api/workspace", "status": "active"},
            {"name": "MCP 桥接", "prefix": "/api/mcp", "status": "active"},
            {"name": "仪表盘", "prefix": "/api/dashboard", "status": "active"},
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
