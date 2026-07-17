"""
云汐项目共享模块
================

shared 模块已重构为三层架构：
- shared.core:     基础工具层（config, logger, errors, auth, utils 等）
- shared.data:     数据基础设施层（cache, data_layer, data_governance 等）
- shared.business: 业务能力层（agent_engine, voice_engine, module_client 等）

旧的 import 路径（如 from shared.config import ...）仍然可用，
但建议逐步迁移到新路径以获得更好的代码组织。

示例：
    # 旧路径（仍可用，会有弃用警告）
    from shared.config import get_config

    # 新路径（推荐）
    from shared.core.config import get_config
"""

import warnings

# 导入三层子模块
from . import core
from . import data
from . import business

# 版本号
__version__ = "1.0.0"

# 从各层 re-export 常用符号，保持 `from shared import Xxx` 可用
# core 层
from .core import (
    YunxiConfig, get_config,
    get_logger,
    YunxiError, ConfigError, ModuleNotFoundError, ModuleCallError,
    ValidationError, AuthenticationError, AuthorizationError, error_to_dict,
    ApiResponse, SUCCESS, ERROR_INVALID_PARAMS, ERROR_UNAUTHORIZED,
    ERROR_FORBIDDEN, ERROR_NOT_FOUND, ERROR_INTERNAL, ERROR_MODULE_UNAVAILABLE,
    DEFAULT_PUBLIC_PATHS, hash_api_key, verify_api_key, is_public_path,
    SimpleRateLimiter, create_api_key_dependency, generate_api_key, mask_api_key,
    escape_html, sanitize_html, validate_input, validate_dict,
    safe_filename, safe_join_path, safe_shell_arg, truncate,
    strip_tags, normalize_whitespace, mask_sensitive_data, mask_dict_sensitive,
    mask_email, mask_phone, mask_string, INPUT_PATTERNS,
    resolve_cors_origins, validate_cors_config, get_cors_middleware_kwargs,
    DEFAULT_DEV_ORIGINS,
    generate_id, now_timestamp, now_iso, safe_get, truncate_text,
    format_file_size,
    SYSTEM_VERSION, BUILD_DATE, VERSION_CODE,
    WafMiddleware, WafEngineCore, register_waf_middleware, get_waf_middleware,
    create_waf_router, WAF_ENABLED, WAF_MODE,
    TracingMiddleware, get_trace_id, get_request_id,
    UnifiedLogger, TraceContext, Span, start_trace, end_trace,
    start_span, end_span, get_trace_headers, extract_trace_headers,
    MetricsCollector, Counter, Gauge, Histogram, get_metrics,
    ObservabilityMiddleware, MetricsEndpoint,
)

# data 层
from .data import (
    SimpleCache, CacheStats, get_cache_from_env, get_path_ttl,
    DEFAULT_PATH_TTL_MAP,
    DatabaseManager, get_db_manager,
    BackupManager, get_backup_manager,
    MigrationEngine, get_migration_engine,
    MigrationStats, TableMigrationStats, MigrationCheckpoint,
    ProgressTracker, format_duration, retry_with_backoff,
    RetryableError, CheckpointManager, row_to_dict, safe_str,
    parse_datetime, safe_json_loads, IdempotencyChecker, BaseDataMigrator,
    load_sovereignty, get_module_sovereignty, check_data_owner,
    list_overlapping_domains, get_deduplication_progress,
)

# business 层
from .business import (
    ModuleKey, ModuleCategory, ModuleInfo, ModuleClient,
    ModuleRegistry, ModuleStatus, get_registry, get_module_registry,
    DEFAULT_MODULE_CONFIGS,
    ProcessManager, ProcessInfo, ProcessStatus, MODULE_CONFIGS,
    get_process_manager,
    A2AClient, A2AError, A2AConnectionError, A2AResponseError,
)

__all__ = [
    "__version__",
    # core
    "YunxiConfig", "get_config", "get_logger",
    "YunxiError", "ConfigError", "ModuleNotFoundError", "ModuleCallError",
    "ValidationError", "AuthenticationError", "AuthorizationError", "error_to_dict",
    "ApiResponse", "SUCCESS", "ERROR_INVALID_PARAMS", "ERROR_UNAUTHORIZED",
    "ERROR_FORBIDDEN", "ERROR_NOT_FOUND", "ERROR_INTERNAL", "ERROR_MODULE_UNAVAILABLE",
    "DEFAULT_PUBLIC_PATHS", "hash_api_key", "verify_api_key", "is_public_path",
    "SimpleRateLimiter", "create_api_key_dependency", "generate_api_key", "mask_api_key",
    "escape_html", "sanitize_html", "validate_input", "validate_dict",
    "safe_filename", "safe_join_path", "safe_shell_arg", "truncate",
    "strip_tags", "normalize_whitespace", "mask_sensitive_data", "mask_dict_sensitive",
    "mask_email", "mask_phone", "mask_string", "INPUT_PATTERNS",
    "resolve_cors_origins", "validate_cors_config", "get_cors_middleware_kwargs",
    "DEFAULT_DEV_ORIGINS",
    "generate_id", "now_timestamp", "now_iso", "safe_get", "truncate_text",
    "format_file_size",
    "SYSTEM_VERSION", "BUILD_DATE", "VERSION_CODE",
    "WafMiddleware", "WafEngineCore", "register_waf_middleware", "get_waf_middleware",
    "create_waf_router", "WAF_ENABLED", "WAF_MODE",
    "TracingMiddleware", "get_trace_id", "get_request_id",
    "UnifiedLogger", "TraceContext", "Span", "start_trace", "end_trace",
    "start_span", "end_span", "get_trace_headers", "extract_trace_headers",
    "MetricsCollector", "Counter", "Gauge", "Histogram", "get_metrics",
    "ObservabilityMiddleware", "MetricsEndpoint",
    # data
    "SimpleCache", "CacheStats", "get_cache_from_env", "get_path_ttl",
    "DEFAULT_PATH_TTL_MAP",
    "DatabaseManager", "get_db_manager",
    "BackupManager", "get_backup_manager",
    "MigrationEngine", "get_migration_engine",
    "MigrationStats", "TableMigrationStats", "MigrationCheckpoint",
    "ProgressTracker", "format_duration", "retry_with_backoff",
    "RetryableError", "CheckpointManager", "row_to_dict", "safe_str",
    "parse_datetime", "safe_json_loads", "IdempotencyChecker", "BaseDataMigrator",
    "load_sovereignty", "get_module_sovereignty", "check_data_owner",
    "list_overlapping_domains", "get_deduplication_progress",
    # business
    "ModuleKey", "ModuleCategory", "ModuleInfo", "ModuleClient",
    "ModuleRegistry", "ModuleStatus", "get_registry", "get_module_registry",
    "DEFAULT_MODULE_CONFIGS",
    "ProcessManager", "ProcessInfo", "ProcessStatus", "MODULE_CONFIGS",
    "get_process_manager",
    "A2AClient", "A2AError", "A2AConnectionError", "A2AResponseError",
]
