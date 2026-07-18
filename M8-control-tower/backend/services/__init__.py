"""
M8 控制塔 - 服务层 (Service Layer)

所有业务逻辑应封装在 service 层，router 只负责：
1. 参数校验（通过 Pydantic schemas）
2. 调用 service 层方法
3. 构造响应返回

Service 分层架构：
- auth_service: 认证相关（登录、登出、Token、密码）
- user_service: 用户管理（CRUD、状态、角色、偏好）
- module_service: 模块管理（注册、健康检查、操作、代理）
- monitor_service: 监控中心（指标采集、告警、历史数据）
- gpu_compute_service: GPU 算力管理（设备、任务、配额）
- backup_scheduler: 备份调度（模块备份、编排）
- health_service: 健康检查（系统健康、模块状态）

新增 service 时请在此导出，保持统一入口。
"""

# 认证服务
from .auth_service import (
    AuthService,
    TokenManager,
    get_auth_service,
    get_token_manager,
    get_password_hash,
    verify_password,
    check_password_strength,
)

# 用户服务
from .user_service import (
    UserService,
    get_user_service,
)

# 模块服务
from .module_service import (
    ModuleService,
    get_module_service,
)

# 监控服务
from .monitor_service import (
    MonitorService,
    get_monitor_service,
)

# GPU 算力服务
from .gpu_compute_service import (
    GPUDeviceStatus,
    GPUTask,
    GPUComputeSource,
    GPUComputeManager,
)

# 备份调度服务
from .backup_scheduler import (
    BackupOrchestratorService,
    ModuleBackupScheduler,
    get_backup_orchestrator_service,
)

# 代理降级服务
from .proxy_fallback_service import (
    ProxyFallbackService,
    ModuleProxyState,
    ProxyMode,
    HealthStatus,
    CircuitState,
    get_proxy_fallback_service,
)

__all__ = [
    # auth_service
    "AuthService",
    "TokenManager",
    "get_auth_service",
    "get_token_manager",
    "get_password_hash",
    "verify_password",
    "check_password_strength",
    # user_service
    "UserService",
    "get_user_service",
    # module_service
    "ModuleService",
    "get_module_service",
    # monitor_service
    "MonitorService",
    "get_monitor_service",
    # gpu_compute_service
    "GPUDeviceStatus",
    "GPUTask",
    "GPUComputeSource",
    "GPUComputeManager",
    # backup_scheduler
    "BackupOrchestratorService",
    "ModuleBackupScheduler",
    "get_backup_orchestrator_service",
    # proxy_fallback_service
    "ProxyFallbackService",
    "ModuleProxyState",
    "ProxyMode",
    "HealthStatus",
    "CircuitState",
    "get_proxy_fallback_service",
]
