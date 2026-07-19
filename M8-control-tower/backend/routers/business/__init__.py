"""
business 子域路由
"""

from .growth_m5_proxy import router as growth_router
from .work_dev import router as work_dev_router
from .review import router as review_router
from .study_plan import router as study_plan_router
from .life_management import router as life_management_router
from .emotion_comfort import router as emotion_comfort_router
from .social_relation import router as social_relation_router
from .appearance import router as appearance_router
from .chat import router as chat_router
from .memory import router as memory_router
from .brain import router as brain_router
from .personalization import router as personalization_router
from .reminders import router as reminders_router
from .agents import router as agents_router
from .task import router as task_router
from .workflow import router as workflow_router
from .evolution_planner import router as evolution_planner_router
from .evolution_deployer import router as evolution_deployer_router
from .evolution_auditor import router as evolution_auditor_router
from .voice import router as voice_router
from .voice_presets import router as voice_presets_router
from .m6_devices import router as m6_devices_router
from .watch import router as watch_router

__all__ = [
    "growth_router",
    "work_dev_router",
    "review_router",
    "study_plan_router",
    "life_management_router",
    "emotion_comfort_router",
    "social_relation_router",
    "appearance_router",
    "chat_router",
    "memory_router",
    "brain_router",
    "personalization_router",
    "reminders_router",
    "agents_router",
    "task_router",
    "workflow_router",
    "evolution_planner_router",
    "evolution_deployer_router",
    "evolution_auditor_router",
    "voice_router",
    "voice_presets_router",
    "m6_devices_router",
    "watch_router",
]
