"""
云汐系统共享模块
提供全局配置、模块注册、进程管理等共享功能
"""

from shared.config import YunxiConfig, get_config
from shared.module_client import ModuleRegistry, ModuleInfo, get_registry
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

__all__ = [
    # 原有导出（保持向后兼容）
    "YunxiConfig",
    "get_config",
    "ModuleRegistry",
    "ModuleInfo",
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
]
