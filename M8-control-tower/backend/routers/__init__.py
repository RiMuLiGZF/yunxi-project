"""
路由包
"""

from .auth import router as auth_router
from .deploy import router as deploy_router
from .monitor import router as monitor_router
from .task import router as task_router
from .system import router as system_router
from .memory import router as memory_router
from .chat import router as chat_router
from .agents import router as agents_router
from .growth import router as growth_router
from .workflow import router as workflow_router
from .modules import router as modules_router
from .work_dev import router as work_dev_router
from .review import router as review_router
from .study_plan import router as study_plan_router
from .life_management import router as life_management_router
from .emotion_comfort import router as emotion_comfort_router
from .social_relation import router as social_relation_router
from .appearance import router as appearance_router
from .m6_devices import router as m6_devices_router
from .compute_sources import router as compute_sources_router
from .compute_groups import router as compute_groups_router
from .compute_models import router as compute_models_router
from .compute_routing import router as compute_routing_router
from .compute_monitor import router as compute_monitor_router
from .compute_config import router as compute_config_router
from .compute_skills import router as compute_skills_router
from .inspection_agents import router as inspection_agents_router
from .watch import router as watch_router
from .git_status import router as git_status_router
from .audit import router as audit_router
from .modes import router as modes_router
from .security import router as security_router
from .users import router as users_router
from .evolution_planner import router as evolution_planner_router
from .evolution_deployer import router as evolution_deployer_router
from .evolution_auditor import router as evolution_auditor_router
from .compute_gpu import router as compute_gpu_router
from .voice import router as voice_router
from .voice_presets import router as voice_presets_router
from .m4_gateway import router as m4_gateway_router
from .personalization import router as personalization_router
from .reminders import router as reminders_router

__all__ = [
    "auth_router",
    "deploy_router",
    "monitor_router",
    "task_router",
    "system_router",
    "memory_router",
    "chat_router",
    "agents_router",
    "growth_router",
    "workflow_router",
    "modules_router",
    "work_dev_router",
    "review_router",
    "study_plan_router",
    "life_management_router",
    "emotion_comfort_router",
    "social_relation_router",
    "appearance_router",
    "m6_devices_router",
    "compute_sources_router",
    "compute_groups_router",
    "compute_models_router",
    "compute_routing_router",
    "compute_monitor_router",
    "compute_config_router",
    "compute_skills_router",
    "inspection_agents_router",
    "watch_router",
    "git_status_router",
    "audit_router",
    "modes_router",
    "security_router",
    "users_router",
    "evolution_planner_router",
    "evolution_deployer_router",
    "evolution_auditor_router",
    "compute_gpu_router",
    "voice_router",
    "voice_presets_router",
    "m4_gateway_router",
    "personalization_router",
    "reminders_router",
]
