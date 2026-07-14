"""
M10 系统卫士 - API 路由包

系统状态、进程管理、防护策略、启动检查、审计日志、报告生成等 API。
"""

from fastapi import APIRouter

from .status import router as status_router
from .process import router as process_router
from .guard import router as guard_router
from .startup_check import router as startup_check_router
from .audit import router as audit_router
from .report import router as report_router
from .response import success, error

# 主 API 路由
api_router = APIRouter(prefix="/api/v1")
api_router.include_router(status_router, prefix="/status", tags=["系统状态"])
api_router.include_router(process_router, prefix="/process", tags=["进程管理"])
api_router.include_router(guard_router, prefix="/guard", tags=["防护策略"])
api_router.include_router(startup_check_router, prefix="/startup-check", tags=["启动安全检查"])
api_router.include_router(audit_router, prefix="/audit", tags=["审计日志"])
api_router.include_router(report_router, prefix="/report", tags=["报告生成"])

__all__ = ["api_router"]
