"""
云汐系统共享模块
提供全局配置、模块注册、进程管理等共享功能
"""

from shared.config import YunxiConfig, get_config
from shared.module_client import ModuleRegistry, ModuleInfo, ModuleKey, ModuleCategory, get_registry, DEFAULT_MODULE_CONFIGS
from shared.process_manager import ProcessManager, ProcessInfo, get_process_manager

# ===== 统一错误处理 =====
from shared.errors import (
    YunxiError,
    ConfigError,
    ModuleNotFoundError,
    ModuleCallError,
    ValidationError,
    AuthenticationError,
    AuthorizationError,
    error_to_dict,
)

# ===== 统一 API 响应 =====
from shared.responses import (
    ApiResponse,
    SUCCESS,
    ERROR_INVALID_PARAMS,
    ERROR_UNAUTHORIZED,
    ERROR_FORBIDDEN,
    ERROR_NOT_FOUND,
    ERROR_INTERNAL,
    ERROR_MODULE_UNAVAILABLE,
)

# ===== 通用工具函数 =====
from shared.utils import (
    generate_id,
    now_timestamp,
    now_iso,
    safe_get,
    truncate_text,
    format_file_size,
)

# ===== 轻量级鉴权工具 =====
from shared.auth import (
    hash_api_key,
    verify_api_key,
    is_public_path,
    DEFAULT_PUBLIC_PATHS,
    SimpleRateLimiter,
    create_api_key_dependency,
    generate_api_key,
    mask_api_key,
)

# ===== 角色与权限 =====
from shared.roles import (
    SystemRole,
    ROLE_HIERARCHY,
    ROLE_DISPLAY_NAMES,
    get_role_level,
    has_min_role,
    is_owner,
    is_admin,
    is_operator,
    is_viewer,
    get_role_display_name,
    get_all_roles,
    get_role_info,
)

__all__ = [
    # 原有导出（保持向后兼容）
    "YunxiConfig",
    "get_config",
    "ModuleRegistry",
    "ModuleInfo",
    "ModuleKey",
    "ModuleCategory",
    "DEFAULT_MODULE_CONFIGS",
    "get_registry",
    "ProcessManager",
    "ProcessInfo",
    "get_process_manager",
    # 错误处理
    "YunxiError",
    "ConfigError",
    "ModuleNotFoundError",
    "ModuleCallError",
    "ValidationError",
    "AuthenticationError",
    "AuthorizationError",
    "error_to_dict",
    # API 响应
    "ApiResponse",
    "SUCCESS",
    "ERROR_INVALID_PARAMS",
    "ERROR_UNAUTHORIZED",
    "ERROR_FORBIDDEN",
    "ERROR_NOT_FOUND",
    "ERROR_INTERNAL",
    "ERROR_MODULE_UNAVAILABLE",
    # 工具函数
    "generate_id",
    "now_timestamp",
    "now_iso",
    "safe_get",
    "truncate_text",
    "format_file_size",
    # 鉴权工具
    "hash_api_key",
    "verify_api_key",
    "is_public_path",
    "DEFAULT_PUBLIC_PATHS",
    "SimpleRateLimiter",
    "create_api_key_dependency",
    "generate_api_key",
    "mask_api_key",
    # 角色与权限
    "SystemRole",
    "ROLE_HIERARCHY",
    "ROLE_DISPLAY_NAMES",
    "get_role_level",
    "has_min_role",
    "is_owner",
    "is_admin",
    "is_operator",
    "is_viewer",
    "get_role_display_name",
    "get_all_roles",
    "get_role_info",
]
