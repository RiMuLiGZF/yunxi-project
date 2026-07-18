"""
M8 路由配置清单（ARC-005 重构）

将所有 router 的注册信息集中管理，通过配置列表 + 循环方式
在 main.py 中统一注册，减少 main.py 代码量。

使用方式：
    from .routers.router_config import ROUTER_CONFIGS
    for router, prefix, tags in ROUTER_CONFIGS:
        app.include_router(router, prefix=prefix, tags=tags)
"""

from .routers import (
    auth_router,
    deploy_router,
    monitor_router,
    task_router,
    system_router,
    memory_router,
    chat_router,
    agents_router,
    growth_router,
    workflow_router,
    modules_router,
    work_dev_router,
    review_router,
    study_plan_router,
    life_management_router,
    emotion_comfort_router,
    social_relation_router,
    appearance_router,
    m6_devices_router,
    compute_sources_router,
    compute_groups_router,
    compute_models_router,
    compute_routing_router,
    compute_monitor_router,
    compute_config_router,
    compute_skills_router,
    compute_gpu_router,
    inspection_agents_router,
    watch_router,
    git_status_router,
    audit_router,
    modes_router,
    security_router,
    users_router,
    evolution_planner_router,
    evolution_deployer_router,
    evolution_auditor_router,
    voice_router,
    voice_presets_router,
    m4_gateway_router,
    personalization_router,
    reminders_router,
    brain_router,
    backup_scheduler_router,
    config_center_router,
    registry_router,
    data_access_router,
    ops_dashboard_router,
    performance_router,
    i18n_router,
)

#: 路由配置列表：(router 实例, URL 前缀, 标签列表)
#: 按业务领域分组，方便查阅和维护
ROUTER_CONFIGS = [
    # ---- 认证与基础 ----
    (auth_router, "/api/auth", ["认证"]),
    (users_router, "/api/users", ["用户管理"]),
    
    # ---- 系统管理 ----
    (system_router, "/api/system", ["系统管理"]),
    (deploy_router, "/api/deploy", ["部署中心"]),
    (monitor_router, "/api/monitor", ["监控中心"]),
    (modules_router, "/api/modules", ["模块管理"]),
    (audit_router, "/api/audit", ["审计日志"]),
    (security_router, "/api/security", ["安全管理"]),
    (modes_router, "/api/modes", ["模式管理"]),
    
    # ---- 业务模式（已迁移到 M4，本地保留回退） ----
    (growth_router, "/api/growth", ["成长中心"]),
    (work_dev_router, "/api/work-dev", ["工作开发"]),
    (review_router, "/api/review", ["复盘总结"]),
    (study_plan_router, "/api/study-plan", ["学业规划"]),
    (life_management_router, "/api/life-management", ["生活管理"]),
    (emotion_comfort_router, "/api/emotion-comfort", ["情绪陪伴"]),
    (social_relation_router, "/api/social-relation", ["人际关系"]),
    (appearance_router, "/api/appearance", ["形象工坊"]),
    
    # ---- 对话与记忆 ----
    (chat_router, "/api/chat", ["云汐聊天"]),
    (memory_router, "/api/memory", ["潮汐记忆-M5"]),
    (brain_router, "/api/brain", ["云汐大脑"]),
    (personalization_router, "/api/personalization", ["个性化设置"]),
    (reminders_router, "/api/reminders", ["主动提醒"]),
    
    # ---- Agent 与任务 ----
    (agents_router, "/api/agents", ["Agent管理"]),
    (task_router, "/api/tasks", ["汐舷-任务"]),
    (workflow_router, "/api/workflows", ["积木平台"]),
    (inspection_agents_router, "/api/inspection", ["巡检Agent"]),
    
    # ---- 算力调度中台 (M8-CS) ----
    (compute_sources_router, "/api/compute/sources", ["算力调度-算力源"]),
    (compute_gpu_router, "/api/compute/gpu", ["GPU算力管理"]),
    (compute_groups_router, "/api/compute/groups", ["算力调度-密钥分组"]),
    (compute_models_router, "/api/compute/models", ["算力调度-模型绑定"]),
    (compute_routing_router, "/api/compute/routing", ["算力调度-路由调度"]),
    (compute_monitor_router, "/api/compute/monitor", ["算力调度-监控大盘"]),
    (compute_config_router, "/api/compute/config", ["算力调度-配置管理"]),
    (compute_skills_router, "/api/compute/skills", ["算力调度-技能绑定"]),
    
    # ---- 自进化 ----
    (evolution_planner_router, "/api/evolution/planner", ["自进化-规划器"]),
    (evolution_deployer_router, "/api/evolution/deployer", ["自进化-部署治理"]),
    (evolution_auditor_router, "/api/evolution/auditor", ["自进化-安全审计"]),
    
    # ---- 语音服务 ----
    (voice_router, "/api/voice", ["语音服务"]),
    (voice_presets_router, "/api/voice/presets", ["音色管理"]),
    
    # ---- 设备与穿戴 ----
    (m6_devices_router, "/api/v1/m6", ["M6穿戴设备"]),
    (watch_router, "/api/watch", ["手表交互"]),
    
    # ---- 运维管理 ----
    (ops_dashboard_router, "/api/ops", ["运维仪表盘"]),
    (performance_router, "/api/performance", ["性能监控"]),
    
    # ---- 国际化 ----
    (i18n_router, "/api/i18n", ["国际化"]),
    
    # ---- 其他 ----
    (git_status_router, "/api/git", ["Git状态看板"]),
    (m4_gateway_router, "/api/m4-gateway", ["M4代理网关"]),
    (backup_scheduler_router, "/api/v1/backup-scheduler", ["备份调度中心"]),
    (config_center_router, "/api/config", ["配置中心"]),
    (registry_router, "/registry", ["服务注册中心"]),
    (data_access_router, "/api/data", ["数据访问层"]),
]


def register_all_routers(app):
    """将所有配置的路由注册到 FastAPI 应用"""
    for router, prefix, tags in ROUTER_CONFIGS:
        app.include_router(router, prefix=prefix, tags=tags)
