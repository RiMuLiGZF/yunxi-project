"""
云汐项目共享模块
================

shared 模块三层架构：
- shared.core:     基础工具层（config, logger, errors, auth, utils 等）
- shared.data:     数据基础设施层（cache, data_layer, data_governance 等）
- shared.business: 业务能力层（agent_engine, voice_engine, module_client 等）

推荐用法（显式导入）：
    from shared.core.config import get_config
    from shared.core.errors import YunxiError
    from shared.core.responses import ApiResponse

为了向后兼容，部分常用符号仍可通过 `from shared import Xxx` 导入，
但建议逐步迁移到子模块路径以获得更好的代码组织和 IDE 支持。

瘦身计划:
    第一步 (v1.3.0): 归档无人引用的顶层存根模块，精简 __all__
    第二步 (v1.4.0): 逐步移除非常用符号的顶层 re-export
    第三步 (v2.0.0): 彻底移除顶层存根模块
"""

import warnings

# 导入三层子模块
from . import core
from . import data
from . import business

# 版本号
__version__ = "1.2.0"

# ============================================================================
# 推荐导入（核心基础 - 5+ 外部引用）
# 这些符号在 __all__ 中，推荐通过 `from shared import Xxx` 使用
# ============================================================================

# --- 错误与异常 (core.errors) ---
from .core import (
    YunxiError,
    ConfigError,
    ModuleNotFoundError,
    ModuleCallError,
    ValidationError,
    AuthenticationError,
    AuthorizationError,
    error_to_dict,
)

# --- 配置 (core.config) ---
from .core import YunxiConfig, get_config

# --- 日志 (core.observability) ---
from .core import get_logger, UnifiedLogger

# --- API 响应 (core.responses) ---
from .core import (
    ApiResponse,
    SUCCESS,
    ERROR_INVALID_PARAMS,
    ERROR_UNAUTHORIZED,
    ERROR_FORBIDDEN,
    ERROR_NOT_FOUND,
    ERROR_INTERNAL,
    ERROR_MODULE_UNAVAILABLE,
)

# --- 版本信息 (core.version) ---
from .core import SYSTEM_VERSION, BUILD_DATE, VERSION_CODE

# --- 模块客户端 (business.module_client) ---
from .business import (
    ModuleKey,
    ModuleCategory,
    ModuleInfo,
    ModuleClient,
    ModuleRegistry,
    ModuleStatus,
    get_registry,
    get_module_registry,
    DEFAULT_MODULE_CONFIGS,
)

# --- 通用工具 (core.utils) ---
from .core import (
    generate_id,
    now_timestamp,
    now_iso,
    safe_get,
    truncate_text,
    format_file_size,
)

# ============================================================================
# 兼容导入（保留但不推荐 - 建议从子模块显式导入）
# 这些符号不在 __all__ 中，但仍可导入以保持向后兼容
# 未来版本将逐步移除，请尽快迁移到子模块路径
# ============================================================================

# --- 认证相关 (core.auth) ---
# 推荐: from shared.core.auth import ...
from .core import (
    DEFAULT_PUBLIC_PATHS,
    hash_api_key,
    verify_api_key,
    is_public_path,
    SimpleRateLimiter,
    create_api_key_dependency,
    generate_api_key,
    mask_api_key,
)

# --- 安全相关 (core.security) ---
# 推荐: from shared.core.security import ...
from .core import (
    escape_html,
    sanitize_html,
    validate_input,
    validate_dict,
    safe_filename,
    safe_join_path,
    safe_shell_arg,
    truncate,
    strip_tags,
    normalize_whitespace,
    mask_sensitive_data,
    mask_dict_sensitive,
    mask_email,
    mask_phone,
    mask_string,
    INPUT_PATTERNS,
)

# --- CORS (core.cors_utils) ---
# 推荐: from shared.core.cors_utils import ...
from .core import (
    resolve_cors_origins,
    validate_cors_config,
    get_cors_middleware_kwargs,
    DEFAULT_DEV_ORIGINS,
)

# --- WAF (core.waf_middleware) ---
# 推荐: from shared.core.waf_middleware import ...
from .core import (
    WafMiddleware,
    WafEngineCore,
    register_waf_middleware,
    get_waf_middleware,
    create_waf_router,
    WAF_ENABLED,
    WAF_MODE,
)

# --- 链路追踪 (core.observability) ---
# 推荐: from shared.core.observability import ...
from .core import (
    TracingMiddleware,
    get_trace_id,
    get_request_id,
    TraceContext,
    Span,
    start_trace,
    end_trace,
    start_span,
    end_span,
    get_trace_headers,
    extract_trace_headers,
    MetricsCollector,
    Counter,
    Gauge,
    Histogram,
    get_metrics,
    ObservabilityMiddleware,
    MetricsEndpoint,
)

# --- 数据层 (data) ---
# 推荐: from shared.data.cache import ... 或 from shared.data.data_layer import ...
from .data import (
    SimpleCache,
    CacheStats,
    get_cache_from_env,
    get_path_ttl,
    DEFAULT_PATH_TTL_MAP,
    DatabaseManager,
    get_db_manager,
    BackupManager,
    get_backup_manager,
    MigrationEngine,
    get_migration_engine,
    MigrationStats,
    TableMigrationStats,
    MigrationCheckpoint,
    ProgressTracker,
    format_duration,
    retry_with_backoff,
    RetryableError,
    CheckpointManager,
    row_to_dict,
    safe_str,
    parse_datetime,
    safe_json_loads,
    IdempotencyChecker,
    BaseDataMigrator,
    load_sovereignty,
    get_module_sovereignty,
    check_data_owner,
    list_overlapping_domains,
    get_deduplication_progress,
)

# --- 进程管理 (business.process_manager) ---
# 推荐: from shared.business.process_manager import ...
from .business import (
    ProcessManager,
    ProcessInfo,
    ProcessStatus,
    MODULE_CONFIGS,
    get_process_manager,
)

# --- A2A 客户端 (business.a2a_client) ---
# 推荐: from shared.business.a2a_client import ...
from .business import (
    A2AClient,
    A2AError,
    A2AConnectionError,
    A2AResponseError,
)

# ============================================================================
# __all__ - 仅包含推荐使用的核心符号
# 其他兼容导入的符号不在 __all__ 中，但仍可显式导入
# ============================================================================

__all__ = [
    # 版本
    "__version__",
    # 配置
    "YunxiConfig", "get_config",
    # 日志
    "get_logger", "UnifiedLogger",
    # 错误与异常
    "YunxiError", "ConfigError", "ModuleNotFoundError", "ModuleCallError",
    "ValidationError", "AuthenticationError", "AuthorizationError", "error_to_dict",
    # API 响应
    "ApiResponse",
    "SUCCESS", "ERROR_INVALID_PARAMS", "ERROR_UNAUTHORIZED",
    "ERROR_FORBIDDEN", "ERROR_NOT_FOUND", "ERROR_INTERNAL", "ERROR_MODULE_UNAVAILABLE",
    # 版本信息
    "SYSTEM_VERSION", "BUILD_DATE", "VERSION_CODE",
    # 模块客户端
    "ModuleKey", "ModuleCategory", "ModuleInfo", "ModuleClient",
    "ModuleRegistry", "ModuleStatus", "get_registry", "get_module_registry",
    "DEFAULT_MODULE_CONFIGS",
    # 通用工具
    "generate_id", "now_timestamp", "now_iso", "safe_get", "truncate_text",
    "format_file_size",
]
