"""
M8 控制塔路由包（结构重组版）

所有路由按业务域拆分到子目录：
  - core/      核心控制（模块、系统、部署、模式、注册、网关）
  - compute/   算力调度中台
  - ops/       运维监控
  - security/  安全管理
  - config/    配置管理
  - data/      数据服务
  - business/  业务服务（对话、Agent、语音、设备、自进化等）

向后兼容：所有旧的 from routers.xxx import router 仍然有效，
但会发出 DeprecationWarning。
"""

from .core.modules import router as modules_router
from .core.system import router as system_router
from .core.deploy import router as deploy_router
from .core.modes import router as modes_router
from .core.registry import router as registry_router
from .core.m4_gateway import router as m4_gateway_router
from .compute.compute_sources import router as compute_sources_router
from .compute.compute_gpu import router as compute_gpu_router
from .compute.compute_groups import router as compute_groups_router
from .compute.compute_models import router as compute_models_router
from .compute.compute_routing import router as compute_routing_router
from .compute.compute_monitor import router as compute_monitor_router
from .compute.compute_config import router as compute_config_router
from .compute.compute_skills import router as compute_skills_router
from .ops.monitor import router as monitor_router
from .ops.ops_dashboard import router as ops_dashboard_router
from .ops.performance import router as performance_router
from .ops.inspection_agents import router as inspection_agents_router
from .ops.git_status import router as git_status_router
from .security.auth import router as auth_router
from .security.users import router as users_router
from .security.security import router as security_router
from .security.audit import router as audit_router
from .config.config_center import router as config_center_router
from .config.i18n import router as i18n_router
from .data.backup_scheduler import router as backup_scheduler_router
from .data.data_access import router as data_access_router
from .business.growth_m5_proxy import router as growth_router
from .business.work_dev import router as work_dev_router
from .business.review import router as review_router
from .business.study_plan import router as study_plan_router
from .business.life_management import router as life_management_router
from .business.emotion_comfort import router as emotion_comfort_router
from .business.social_relation import router as social_relation_router
from .business.appearance import router as appearance_router
from .business.chat import router as chat_router
from .business.memory import router as memory_router
from .business.brain import router as brain_router
from .business.personalization import router as personalization_router
from .business.reminders import router as reminders_router
from .business.agents import router as agents_router
from .business.task import router as task_router
from .business.workflow import router as workflow_router
from .business.evolution_planner import router as evolution_planner_router
from .business.evolution_deployer import router as evolution_deployer_router
from .business.evolution_auditor import router as evolution_auditor_router
from .business.voice import router as voice_router
from .business.voice_presets import router as voice_presets_router
from .business.m6_devices import router as m6_devices_router
from .business.watch import router as watch_router

__all__ = [
    "modules_router",
    "system_router",
    "deploy_router",
    "modes_router",
    "registry_router",
    "m4_gateway_router",
    "compute_sources_router",
    "compute_gpu_router",
    "compute_groups_router",
    "compute_models_router",
    "compute_routing_router",
    "compute_monitor_router",
    "compute_config_router",
    "compute_skills_router",
    "monitor_router",
    "ops_dashboard_router",
    "performance_router",
    "inspection_agents_router",
    "git_status_router",
    "auth_router",
    "users_router",
    "security_router",
    "audit_router",
    "config_center_router",
    "i18n_router",
    "backup_scheduler_router",
    "data_access_router",
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
