"""
云汐共享核心层 (shared.core)
==============================

基础工具层，无业务依赖，提供系统级通用能力。

子模块：
- config: 全局配置管理
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
"""

from .config import YunxiConfig, get_config
from .logger import get_logger
from .errors import (
    YunxiError,
    ConfigError,
    ModuleNotFoundError,
    ModuleCallError,
    ValidationError,
    AuthenticationError,
    AuthorizationError,
    error_to_dict,
)
from .responses import (
    ApiResponse,
    SUCCESS,
    ERROR_INVALID_PARAMS,
    ERROR_UNAUTHORIZED,
    ERROR_FORBIDDEN,
    ERROR_NOT_FOUND,
    ERROR_INTERNAL,
    ERROR_MODULE_UNAVAILABLE,
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

__version__ = "1.0.0"
"""shared.core 版本号"""

__all__ = [
    "__version__",
    # Config
    "YunxiConfig", "get_config",
    # Logger
    "get_logger",
    # Errors
    "YunxiError", "ConfigError", "ModuleNotFoundError", "ModuleCallError",
    "ValidationError", "AuthenticationError", "AuthorizationError", "error_to_dict",
    # Responses
    "ApiResponse", "SUCCESS", "ERROR_INVALID_PARAMS", "ERROR_UNAUTHORIZED",
    "ERROR_FORBIDDEN", "ERROR_NOT_FOUND", "ERROR_INTERNAL", "ERROR_MODULE_UNAVAILABLE",
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
]
