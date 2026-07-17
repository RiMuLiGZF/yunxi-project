"""
云汐共享核心层 (shared.core)
==============================

基础工具层，无业务依赖，提供系统级通用能力。

子模块：
- config: 全局配置管理
- module_registry: 模块注册表（配置外部化 / 动态注册 / 心跳检测）
- logger: 统一日志工具
- errors: 统一错误类型
- responses: 统一 API 响应格式
- auth: 认证工具（API Key / JWT / 限流）
- security: 安全工具（输入验证 / 输出编码 / 脱敏）
- cors_utils: CORS 配置工具
- utils: 通用工具函数
- version: 系统版本信息
- waf_middleware: WAF 防火墙中间件
- logger_redis: Redis 日志通道
- middleware: 中间件集合（链路追踪等）
- observability: 可观测性（统一日志 / 追踪 / 指标）
- audit_framework: 统一审计框架（SC-007 P1级，审计日志全覆盖）
- bounded_collections: 有界集合工具（防止内存无界增长）
"""

from .config import YunxiConfig, get_config
from .module_registry import (
    ModuleRegistry,
    ModuleInfo,
    ModuleCategory,
    ModuleStatus,
    HealthStatus,
    get_module_registry,
)
from .logger import get_logger
from .errors import (
    # 错误码枚举
    ErrorCategory,
    ModuleCode,
    # 通用错误码
    ErrorCode,
    # 错误码工具
    build_error_code,
    parse_error_code,
    module_error_range,
    normalize_error_code,
    get_default_message,
    get_http_status,
    ERROR_CODE_LEGACY_MAP,
    ERROR_MESSAGES,
    CATEGORY_HTTP_STATUS,
    # 异常基类
    YunxiError,
    # 异常子类
    ValidationError,
    AuthenticationError,
    AuthorizationError,
    NotFoundError,
    BusinessError,
    SystemError,
    ConfigError,
    ModuleNotFoundError,
    ModuleCallError,
    RateLimitError,
    ThirdPartyError,
    DataError,
    # 模块错误码基类
    ModuleErrorCode,
    # 工具函数
    error_to_dict,
    from_exception,
    raise_validation,
    raise_not_found,
    raise_auth,
    raise_permission,
)
from .responses import (
    ApiResponse,
    # 旧版错误码常量（向后兼容）
    SUCCESS,
    ERROR_INVALID_PARAMS,
    ERROR_UNAUTHORIZED,
    ERROR_FORBIDDEN,
    ERROR_NOT_FOUND,
    ERROR_INTERNAL,
    ERROR_MODULE_UNAVAILABLE,
    # 便捷响应函数
    ok,
    fail,
    paginated,
    # 全局异常处理器
    GlobalExceptionHandler,
    register_global_exception_handler,
)
from .auth import (
    DEFAULT_PUBLIC_PATHS,
    hash_api_key,
    verify_api_key,
    is_public_path,
    SimpleRateLimiter,
    create_api_key_dependency,
    generate_api_key,
    mask_api_key,
)
from .security import (
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
from .cors_utils import (
    resolve_cors_origins,
    validate_cors_config,
    get_cors_middleware_kwargs,
    DEFAULT_DEV_ORIGINS,
)
from .utils import (
    generate_id,
    now_timestamp,
    now_iso,
    safe_get,
    truncate_text,
    format_file_size,
)
from .version import SYSTEM_VERSION, BUILD_DATE, VERSION_CODE
from .waf_middleware import (
    WafMiddleware,
    WafEngineCore,
    register_waf_middleware,
    get_waf_middleware,
    create_waf_router,
    WAF_ENABLED,
    WAF_MODE,
)

# 中间件子模块
from .middleware import TracingMiddleware, get_trace_id, get_request_id

# 可观测性子模块
from .observability import (
    UnifiedLogger,
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

# 统一审计框架（SC-007 P1级）
from .audit_framework import (
    AuditCategory,
    AuditLevel,
    AuditResult,
    AuditEvent,
    AuditStorageBackend,
    MemoryAuditStorage,
    JsonFileAuditStorage,
    AuditLogger,
    audit_log,
    AuditMiddleware,
    AuthAuditHook,
    get_audit_logger,
    set_audit_logger,
    audit_event,
)

# 有界集合工具（内存无界增长防护）
from .bounded_collections import (
    BoundedList,
    LRUDict,
    BoundedSet,
    EvictionReason,
)

__version__ = "1.0.1"
"""shared.core 版本号"""

__all__ = [
    "__version__",
    # Config
    "YunxiConfig", "get_config",
    # Module Registry (CQ-001)
    "ModuleRegistry", "ModuleInfo", "ModuleCategory", "ModuleStatus",
    "HealthStatus", "get_module_registry",
    # Logger
    "get_logger",
    # Errors - 枚举
    "ErrorCategory", "ModuleCode",
    # Errors - 通用错误码
    "ErrorCode",
    # Errors - 工具
    "build_error_code", "parse_error_code", "module_error_range",
    "normalize_error_code", "get_default_message", "get_http_status",
    "ERROR_CODE_LEGACY_MAP", "ERROR_MESSAGES", "CATEGORY_HTTP_STATUS",
    # Errors - 异常类
    "YunxiError", "ValidationError", "AuthenticationError", "AuthorizationError",
    "NotFoundError", "BusinessError", "SystemError", "ConfigError",
    "ModuleNotFoundError", "ModuleCallError", "RateLimitError",
    "ThirdPartyError", "DataError",
    # Errors - 模块错误码基类
    "ModuleErrorCode",
    # Errors - 工具函数
    "error_to_dict", "from_exception",
    "raise_validation", "raise_not_found", "raise_auth", "raise_permission",
    # Responses
    "ApiResponse", "SUCCESS", "ERROR_INVALID_PARAMS", "ERROR_UNAUTHORIZED",
    "ERROR_FORBIDDEN", "ERROR_NOT_FOUND", "ERROR_INTERNAL", "ERROR_MODULE_UNAVAILABLE",
    "ok", "fail", "paginated",
    "GlobalExceptionHandler", "register_global_exception_handler",
    # Auth
    "DEFAULT_PUBLIC_PATHS", "hash_api_key", "verify_api_key", "is_public_path",
    "SimpleRateLimiter", "create_api_key_dependency", "generate_api_key", "mask_api_key",
    # Security
    "escape_html", "sanitize_html", "validate_input", "validate_dict",
    "safe_filename", "safe_join_path", "safe_shell_arg", "truncate",
    "strip_tags", "normalize_whitespace", "mask_sensitive_data", "mask_dict_sensitive",
    "mask_email", "mask_phone", "mask_string", "INPUT_PATTERNS",
    # CORS
    "resolve_cors_origins", "validate_cors_config", "get_cors_middleware_kwargs",
    "DEFAULT_DEV_ORIGINS",
    # Utils
    "generate_id", "now_timestamp", "now_iso", "safe_get", "truncate_text",
    "format_file_size",
    # Version
    "SYSTEM_VERSION", "BUILD_DATE", "VERSION_CODE",
    # WAF
    "WafMiddleware", "WafEngineCore", "register_waf_middleware", "get_waf_middleware",
    "create_waf_router", "WAF_ENABLED", "WAF_MODE",
    # Middleware
    "TracingMiddleware", "get_trace_id", "get_request_id",
    # Observability
    "UnifiedLogger", "TraceContext", "Span", "start_trace", "end_trace",
    "start_span", "end_span", "get_trace_headers", "extract_trace_headers",
    "MetricsCollector", "Counter", "Gauge", "Histogram", "get_metrics",
    "ObservabilityMiddleware", "MetricsEndpoint",
    # Audit Framework (SC-007 P1级)
    "AuditCategory", "AuditLevel", "AuditResult", "AuditEvent",
    "AuditStorageBackend", "MemoryAuditStorage", "JsonFileAuditStorage",
    "AuditLogger", "audit_log", "AuditMiddleware", "AuthAuditHook",
    "get_audit_logger", "set_audit_logger", "audit_event",
    # Bounded Collections (内存防护)
    "BoundedList", "LRUDict", "BoundedSet", "EvictionReason",
]
