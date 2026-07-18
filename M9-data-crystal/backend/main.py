"""
云汐 M9 数据水晶 - 主入口文件

P3 优化：数据采集管道 + 连接器生态
FastAPI 应用主入口，负责初始化应用、注册路由、配置中间件
"""

from __future__ import annotations

import os
import sys
import time
import threading
from pathlib import Path
from contextlib import asynccontextmanager

# 确保可以导入同级模块
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# 将项目根目录加入 path，以便导入 shared 模块
_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# 导入配置
from config import get_config

# 导入路由
from routers.connectors import router as connectors_router
from routers.pipelines import router as pipelines_router

# 导入连接器和管道模块（触发注册）
import connectors
import pipelines

# 版本号
APP_VERSION = "1.2.0"
MODULE_NAME = "m9-data-crystal"

# 请求统计
_request_count = 0
_request_error_count = 0
_request_total_time = 0.0
_request_lock = threading.Lock()

# 配置
settings = get_config()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # ---- 启动阶段 ----
    # 1. 初始化数据库
    try:
        from models import init_db
        init_db()
        logger.info("数据库初始化完成")
    except Exception as e:
        logger.warning(f"数据库初始化警告: {e}")

    # 2. 初始化连接器管理器
    try:
        from connectors.manager import get_connector_manager
        conn_mgr = get_connector_manager()
        conn_mgr.start_health_check_scheduler()
        logger.info("连接器管理器初始化完成")
    except Exception as e:
        logger.warning(f"连接器管理器初始化警告: {e}")

    # 3. 初始化管道管理器
    try:
        from pipelines.manager import get_pipeline_manager
        from connectors.manager import get_connector_manager
        pipe_mgr = get_pipeline_manager()
        pipe_mgr.set_connector_manager(get_connector_manager())
        logger.info("管道管理器初始化完成")
    except Exception as e:
        logger.warning(f"管道管理器初始化警告: {e}")

    logger.info(f"M9 数据水晶服务启动完成，版本: {APP_VERSION}")

    yield

    # ---- 关闭阶段 ----
    try:
        from connectors.manager import get_connector_manager
        from pipelines.manager import get_pipeline_manager
        pipe_mgr = get_pipeline_manager()
        pipe_mgr.shutdown()
        conn_mgr = get_connector_manager()
        conn_mgr.shutdown()
    except Exception:
        logger.debug("Resource cleanup failed during shutdown", exc_info=True)
    logger.info("服务已关闭")


# 创建 FastAPI 应用
app = FastAPI(
    title="云汐 M9 数据水晶 API",
    description="M9 数据水晶后端服务 - 数据采集管道 + 连接器生态",
    version=APP_VERSION,
    debug=getattr(settings, 'debug', True),
    lifespan=lifespan,
)

# 配置 CORS
_cors_origins = getattr(settings, 'cors_origins', [
    "http://localhost:3000", "http://localhost:5173",
    "http://127.0.0.1:3000", "http://127.0.0.1:5173",
])
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 请求统计中间件
@app.middleware("http")
async def request_stats_middleware(request, call_next):
    """请求统计中间件"""
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


# 注册路由
app.include_router(connectors_router)
app.include_router(pipelines_router)


# 健康检查
@app.get("/health", summary="健康检查")
def health_check():
    """服务健康检查接口"""
    return {
        "status": "healthy",
        "service": f"yunxi-{MODULE_NAME}",
        "version": APP_VERSION,
    }


# API 信息
@app.get("/api/info", summary="API 信息")
def api_info():
    """获取 API 基本信息"""
    return {
        "name": "云汐 M9 数据水晶 API",
        "version": APP_VERSION,
        "description": "数据采集管道 + 连接器生态",
        "modules": [
            {"name": "连接器管理", "prefix": "/api/v1/connectors", "status": "active"},
            {"name": "管道管理", "prefix": "/api/v1/pipelines", "status": "active"},
        ],
        "docs": "/docs",
        "redoc": "/redoc",
    }


# 根路径
@app.get("/", include_in_schema=False)
def root():
    """根路径重定向到 API 文档"""
    return JSONResponse(
        content={
            "message": "云汐 M9 数据水晶 API 服务",
            "docs": "/docs",
            "health": "/health",
            "api_info": "/api/info",
        }
    )


# 日志
import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("m9_data_crystal")


# 启动服务
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=getattr(settings, 'host', "0.0.0.0"),
        port=getattr(settings, 'port', 8019),
        reload=getattr(settings, 'debug', True),
    )
