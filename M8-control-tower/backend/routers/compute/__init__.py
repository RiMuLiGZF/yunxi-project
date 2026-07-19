"""
compute 子域路由
"""

from .compute_sources import router as compute_sources_router
from .compute_gpu import router as compute_gpu_router
from .compute_groups import router as compute_groups_router
from .compute_models import router as compute_models_router
from .compute_routing import router as compute_routing_router
from .compute_monitor import router as compute_monitor_router
from .compute_config import router as compute_config_router
from .compute_skills import router as compute_skills_router

__all__ = [
    "compute_sources_router",
    "compute_gpu_router",
    "compute_groups_router",
    "compute_models_router",
    "compute_routing_router",
    "compute_monitor_router",
    "compute_config_router",
    "compute_skills_router",
]
