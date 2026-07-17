"""
M8 前端静态文件挂载（ARC-005 重构）

将 main.py 中的静态文件挂载逻辑抽离到独立模块，保持功能不变。

使用方式：
    from .static_files import mount_frontend_static
    mount_frontend_static(app, project_root, settings, logger)
"""

from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse


def mount_frontend_static(app: FastAPI, project_root: Path, settings, logger) -> None:
    """
    挂载前端静态文件服务
    
    按路径深度从深到浅排列，避免路由覆盖问题。
    挂载目录包括：m8, m7, m9, modes, xian, startup, watch, common, shared, user, master
    """
    frontend_dir = project_root / "frontend"
    if not frontend_dir.exists():
        # 没有前端目录时返回 API 信息
        @app.get("/", tags=["系统"])
        async def root():
            return {
                "code": 0,
                "message": "ok",
                "data": {
                    "name": settings.app_name,
                    "version": settings.version,
                    "docs": "/docs",
                },
            }
        return

    # 挂载各子目录（按路径深度从深到浅排列，避免路由覆盖问题）
    # M8 工作台
    if (frontend_dir / "m8").exists():
        app.mount("/m8", StaticFiles(directory=str(frontend_dir / "m8"), html=True), name="m8-frontend")
        app.mount("/m8-ui", StaticFiles(directory=str(frontend_dir / "m8"), html=True), name="m8-ui-frontend")
    # M7 积木平台
    if (frontend_dir / "m7").exists():
        app.mount("/m7", StaticFiles(directory=str(frontend_dir / "m7"), html=True), name="m7-frontend")
    # M9 开发工坊
    if (frontend_dir / "m9").exists():
        app.mount("/m9", StaticFiles(directory=str(frontend_dir / "m9"), html=True), name="m9-frontend")
    # 业务模式
    if (frontend_dir / "modes").exists():
        app.mount("/modes", StaticFiles(directory=str(frontend_dir / "modes"), html=True), name="modes-frontend")
    # 汐舷
    if (frontend_dir / "xian").exists():
        app.mount("/xian", StaticFiles(directory=str(frontend_dir / "xian"), html=True), name="xian-frontend")
    # 启动引导
    if (frontend_dir / "startup").exists():
        app.mount("/startup", StaticFiles(directory=str(frontend_dir / "startup"), html=True), name="startup-frontend")
    # 手表交互
    if (frontend_dir / "watch").exists():
        app.mount("/watch", StaticFiles(directory=str(frontend_dir / "watch"), html=True), name="watch-frontend")
    # 公共资源
    if (frontend_dir / "common").exists():
        app.mount("/common", StaticFiles(directory=str(frontend_dir / "common"), html=True), name="common-frontend")
    # 共享资源
    if (frontend_dir / "shared").exists():
        app.mount("/shared", StaticFiles(directory=str(frontend_dir / "shared"), html=True), name="shared-frontend")
    # 用户中心
    if (frontend_dir / "user").exists():
        app.mount("/user", StaticFiles(directory=str(frontend_dir / "user"), html=True), name="user-frontend")
    # 主控台
    if (frontend_dir / "master").exists():
        app.mount("/master", StaticFiles(directory=str(frontend_dir / "master"), html=True), name="master-frontend")

    # 根路径特殊文件（owner.html 等）
    @app.get("/owner.html", tags=["系统"])
    async def owner_page():
        owner_path = frontend_dir / "owner.html"
        if owner_path.exists():
            return FileResponse(str(owner_path))
        raise HTTPException(status_code=404, detail="Not Found")

    # 根路径返回统一入口页
    @app.get("/", tags=["系统"])
    async def root():
        index_path = frontend_dir / "index.html"
        if index_path.exists():
            return FileResponse(str(index_path))
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "name": settings.app_name,
                "version": settings.version,
                "docs": "/docs",
            },
        }

    logger.info(f"Frontend static files mounted from {frontend_dir}")
