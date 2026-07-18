"""
M8 控制塔 - Schemas 层

按领域划分的 Pydantic 模型集合：
- common: 通用响应、分页、排序、健康检查、代理状态
- auth: 登录、注册、Token、密码管理
- user: 用户管理、用户偏好、个人中心
- module: 模块管理、健康检查、模块操作

所有 router 应从 schemas 包导入模型，
不要在 router 文件内联定义 Pydantic 模型。
"""

# 通用模型（兼容旧的 ApiResponse 导入方式）
from .common import (
    ApiResponse,
    PaginatedResponse,
    PaginationParams,
    SortParams,
    FilterParams,
    ListQueryParams,
    OperationResult,
    BulkOperationResult,
    HealthStatus,
    ModuleHealthInfo,
    ProxyStatusInfo,
    DegradedResponse,
)

# 认证模型
from .auth import (
    LoginRequest,
    LoginResponseData,
    LoginResponse,
    RegisterRequest,
    RegisterResponseData,
    TokenRefreshRequest,
    TokenRefreshResponseData,
    TokenInfo,
    LogoutRequest,
    ChangePasswordRequest,
    ResetPasswordRequest,
    PasswordStrengthCheckRequest,
    PasswordStrengthInfo,
    UserInfo,
    CaptchaResponseData,
    CaptchaVerifyRequest,
)

# 用户模型
from .user import (
    UserBase,
    UserCreate,
    UserUpdate,
    UserResponse,
    UserDetailResponse,
    UserListItem,
    UserListResponse,
    UserPreferencesUpdate,
    UserPreferencesResponse,
    UserStatusUpdate,
    UserRoleUpdate,
    BatchUserOperationRequest,
    CurrentUserResponse,
    ProfileUpdate,
)

# 模块模型
from .module import (
    ModuleStatus,
    ModuleCategory,
    HealthStatus,
    ModuleBase,
    ModuleInfo,
    ModuleListItem,
    ModuleListResponse,
    ModuleStatusSummary,
    ModuleOperationRequest,
    ModuleOperationResult,
    BatchModuleOperationRequest,
    BatchModuleOperationResult,
    ModuleHealthCheckRequest,
    ModuleHealthDetail,
    ModuleConfigUpdate,
    ModuleConfigResponse,
    ModuleRegisterRequest,
    ModuleRegisterResponse,
    ModuleProxyRequest,
    ModuleProxyResponse,
)

__all__ = [
    # common
    "ApiResponse",
    "PaginatedResponse",
    "PaginationParams",
    "SortParams",
    "FilterParams",
    "ListQueryParams",
    "OperationResult",
    "BulkOperationResult",
    "HealthStatus",
    "ModuleHealthInfo",
    "ProxyStatusInfo",
    "DegradedResponse",
    # auth
    "LoginRequest",
    "LoginResponseData",
    "LoginResponse",
    "RegisterRequest",
    "RegisterResponseData",
    "TokenRefreshRequest",
    "TokenRefreshResponseData",
    "TokenInfo",
    "LogoutRequest",
    "ChangePasswordRequest",
    "ResetPasswordRequest",
    "PasswordStrengthCheckRequest",
    "PasswordStrengthInfo",
    "UserInfo",
    "CaptchaResponseData",
    "CaptchaVerifyRequest",
    # user
    "UserBase",
    "UserCreate",
    "UserUpdate",
    "UserResponse",
    "UserDetailResponse",
    "UserListItem",
    "UserListResponse",
    "UserPreferencesUpdate",
    "UserPreferencesResponse",
    "UserStatusUpdate",
    "UserRoleUpdate",
    "BatchUserOperationRequest",
    "CurrentUserResponse",
    "ProfileUpdate",
    # module
    "ModuleStatus",
    "ModuleCategory",
    "HealthStatus",
    "ModuleBase",
    "ModuleInfo",
    "ModuleListItem",
    "ModuleListResponse",
    "ModuleStatusSummary",
    "ModuleOperationRequest",
    "ModuleOperationResult",
    "BatchModuleOperationRequest",
    "BatchModuleOperationResult",
    "ModuleHealthCheckRequest",
    "ModuleHealthDetail",
    "ModuleConfigUpdate",
    "ModuleConfigResponse",
    "ModuleRegisterRequest",
    "ModuleRegisterResponse",
    "ModuleProxyRequest",
    "ModuleProxyResponse",
]
