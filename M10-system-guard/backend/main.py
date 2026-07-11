"""
云汐 M10 系统卫士 - 主入口文件
FastAPI 应用主入口，负责初始化应用、注册路由、配置中间件
沙盒监控版 - 全部使用模拟数据，不调用真实系统API
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
from fastapi.responses import JSONResponse

# 导入配置和数据库
from config import get_settings
from database import init_db

# 导入路由
from routers.status import router as status_router
from routers.process import router as process_router
from routers.health import router as health_router
from routers.alerts import router as alerts_router


# ===== 初始化配置 =====
settings = get_settings()

# ===== 创建 FastAPI 应用 =====
app = FastAPI(
    title="云汐 M10 系统卫士 API",
    description="M10 系统卫士后端服务 - 系统资源监控、进程管理、健康评估、告警通知（沙盒监控版）",
    version="1.0.0 (Sandbox Phase 1)",
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

# ===== 注册路由 =====
# 注意：各路由文件内部已定义 prefix，这里直接包含即可
app.include_router(status_router)
app.include_router(process_router)
app.include_router(health_router)
app.include_router(alerts_router)


# ===== 启动事件 =====
@app.on_event("startup")
async def startup_event():
    """应用启动时的初始化操作"""
    # 1. 初始化数据库
    init_db()
    print("[M10] 数据库初始化完成")

    # 2. 初始化模拟数据引擎
    try:
        from mock_data_engine import get_mock_engine
        mock_engine = get_mock_engine()
        # 生成初始数据
        metrics = mock_engine.generate_system_metrics()
        print(f"[M10] 模拟数据引擎初始化完成 (CPU: {metrics['cpu']['percent']}%, MEM: {metrics['memory']['percent']}%)")
    except Exception as e:
        print(f"[M10] 模拟数据引擎初始化警告: {e}")

    # 3. 初始化系统监控服务
    try:
        from services.system_monitor import get_system_monitor
        monitor = get_system_monitor()
        print("[M10] 系统监控服务就绪")
    except Exception as e:
        print(f"[M10] 系统监控服务初始化警告: {e}")

    # 4. 初始化进程监控服务
    try:
        from services.process_monitor import get_process_monitor
        proc_monitor = get_process_monitor()
        procs = proc_monitor.get_process_list(limit=1)
        print(f"[M10] 进程监控服务就绪 (模拟进程数: 约50+)")
    except Exception as e:
        print(f"[M10] 进程监控服务初始化警告: {e}")

    # 5. 初始化健康评估服务
    try:
        from services.health_assessor import get_health_assessor
        assessor = get_health_assessor()
        score = assessor.get_health_score()
        print(f"[M10] 健康评估服务就绪 (当前评分: {score['total_score']} {score['level_text']})")
    except Exception as e:
        print(f"[M10] 健康评估服务初始化警告: {e}")

    # 6. 初始化告警管理服务
    try:
        from services.alert_manager import get_alert_manager
        alert_mgr = get_alert_manager()
        stats = alert_mgr.get_unresolved_count()
        print(f"[M10] 告警通知服务就绪 (未解决告警: {stats['total']}个)")
    except Exception as e:
        print(f"[M10] 告警通知服务初始化警告: {e}")

    # 7. 输出运行模式信息
    mode_text = "沙盒模式（模拟数据）" if settings.sandbox_mode else "真实模式"
    print(f"[M10] ========================================")
    print(f"[M10] M10 系统卫士启动完成")
    print(f"[M10] 运行模式: {mode_text}")
    print(f"[M10] 服务端口: {settings.port}")
    print(f"[M10] 采样间隔: {settings.sampling_interval}秒")
    print(f"[M10] 数据保留: {settings.data_retention_days}天")
    print(f"[M10] API文档: http://localhost:{settings.port}/docs")
    print(f"[M10] ========================================")


@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭时的清理操作"""
    print("[M10] 服务正在关闭...")
    # 预留清理逻辑
    print("[M10] 服务已关闭")


# ===== 健康检查接口 =====
@app.get("/health", summary="健康检查")
def health_check():
    """服务健康检查接口"""
    try:
        from services.system_monitor import get_system_monitor
        from services.health_assessor import get_health_assessor
        from services.alert_manager import get_alert_manager

        monitor = get_system_monitor()
        assessor = get_health_assessor()
        alert_mgr = get_alert_manager()

        status = monitor.get_realtime_status()
        score = assessor.get_health_score()
        alert_stats = alert_mgr.get_unresolved_count()

        return {
            "status": "healthy",
            "service": "yunxi-m10-system-guard",
            "version": "1.0.0",
            "sandbox_mode": settings.sandbox_mode,
            "health_score": score["total_score"],
            "health_level": score["level_text"],
            "cpu_percent": status["cpu"]["percent"],
            "memory_percent": status["memory"]["percent"],
            "unresolved_alerts": alert_stats["total"],
        }
    except Exception as e:
        return {
            "status": "degraded",
            "service": "yunxi-m10-system-guard",
            "version": "1.0.0",
            "sandbox_mode": settings.sandbox_mode,
            "error": str(e),
        }


# ===== API 信息接口 =====
@app.get("/api/info", summary="API 信息")
def api_info():
    """获取 API 基本信息"""
    return {
        "name": "云汐 M10 系统卫士 API",
        "version": "1.0.0 (Sandbox Phase 1)",
        "description": "系统资源监控、进程管理、健康评估、告警通知服务",
        "sandbox_mode": settings.sandbox_mode,
        "modules": [
            {"name": "A1 系统资源监控", "prefix": "/api/m10/status", "status": "active"},
            {"name": "A2 进程监控与画像", "prefix": "/api/m10/process", "status": "active"},
            {"name": "A3 启动安全检查", "prefix": "/api/m10/process/startup-check", "status": "active"},
            {"name": "A4 健康评估与风险预测", "prefix": "/api/m10/health", "status": "active"},
            {"name": "A5 告警通知系统", "prefix": "/api/m10/alerts", "status": "active"},
        ],
        "upcoming_modules": [
            {"name": "B1 三大运行模式", "status": "planned"},
            {"name": "B2 模式切换调度器", "status": "planned"},
            {"name": "B3 一键加速功能", "status": "planned"},
            {"name": "B4 自动调度策略", "status": "planned"},
            {"name": "B5 模块联动接口", "status": "planned"},
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
            "message": "云汐 M10 系统卫士 API 服务（沙盒监控版）",
            "sandbox_mode": settings.sandbox_mode,
            "version": "1.0.0",
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
