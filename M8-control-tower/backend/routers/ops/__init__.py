"""
ops 子域路由
"""

from .monitor import router as monitor_router
from .ops_dashboard import router as ops_dashboard_router
from .performance import router as performance_router
from .inspection_agents import router as inspection_agents_router
from .git_status import router as git_status_router

__all__ = [
    "monitor_router",
    "ops_dashboard_router",
    "performance_router",
    "inspection_agents_router",
    "git_status_router",
]
