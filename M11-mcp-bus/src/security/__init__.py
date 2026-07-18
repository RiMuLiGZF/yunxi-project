"""M11 MCP Bus - Security 安全层.

统一的安全层模块，整合认证、权限和审计功能。
核心逻辑从 middleware/ 和 services/ 中抽离，
形成独立的安全层，便于复用和维护。

架构定位:
    Security 层位于 Transport 层和 Services 层之间，
    提供认证、授权、审计三大安全功能。
    middleware/ 保留为薄适配层，将 Web 请求转换为
    对 Security 层的调用。

使用方式:
    from src.security import AuthService, PermissionChecker, AuditLogger
    from src.security import get_auth_service, get_permission_checker, get_audit_logger

    # 认证
    auth_service = get_auth_service()
    result = auth_service.authenticate(key_value)

    # 权限检查
    checker = get_permission_checker()
    if checker.has_permission(api_key, "servers:read"):
        ...

    # 审计日志
    audit = get_audit_logger()
    audit.log_event("tool_call", actor="user1", ...)
"""

from .auth import (
    AuthResult,
    AuthService,
    DEFAULT_PUBLIC_PATHS,
    find_api_key_by_id,
    find_api_key_by_value,
    get_auth_service,
    hash_key,
    is_public_path,
    update_last_used,
)
from .audit import (
    ALL_AUDIT_EVENT_TYPES,
    AuditEventType,
    AuditLogEntry,
    AuditLogger,
    get_audit_logger,
)
from .permission import (
    ACTION_CALL,
    ACTION_DELETE,
    ACTION_MANAGE,
    ACTION_READ,
    ACTION_WRITE,
    COMMON_PERMISSIONS,
    PermissionChecker,
    RESOURCE_ADMIN,
    RESOURCE_AUDIT,
    RESOURCE_MCP,
    RESOURCE_SERVERS,
    RESOURCE_TOOLS,
    SUPER_PERMISSION,
    get_permission_checker,
)
from .sandbox import (
    COMMAND_INJECTION_PATTERNS,
    DANGEROUS_FUNCTIONS,
    DEFAULT_MAX_OUTPUT_SIZE,
    DEFAULT_SANDBOX_LEVEL,
    DEFAULT_TIMEOUT,
    DangerDetector,
    FileSystemIsolator,
    ParameterValidator,
    SANDBOX_LEVEL_BASIC,
    SANDBOX_LEVEL_MAXIMUM,
    SANDBOX_LEVEL_STRICT,
    SANDBOX_LEVEL_UNLIMITED,
    SandboxConfig,
    SandboxedExecutor,
    SandboxExecutionContext,
    SandboxManager,
    SandboxRateLimiter,
    SandboxResult,
    SENSITIVE_PATH_PATTERNS,
    SSRF_BLOCKED_PATTERNS,
    execute_in_sandbox,
    get_sandbox_manager,
)

__all__ = [
    # 认证
    "AuthService",
    "AuthResult",
    "get_auth_service",
    "hash_key",
    "is_public_path",
    "find_api_key_by_value",
    "find_api_key_by_id",
    "update_last_used",
    "DEFAULT_PUBLIC_PATHS",
    # 权限
    "PermissionChecker",
    "get_permission_checker",
    "SUPER_PERMISSION",
    "RESOURCE_SERVERS",
    "RESOURCE_TOOLS",
    "RESOURCE_ADMIN",
    "RESOURCE_MCP",
    "RESOURCE_AUDIT",
    "ACTION_READ",
    "ACTION_WRITE",
    "ACTION_CALL",
    "ACTION_DELETE",
    "ACTION_MANAGE",
    "COMMON_PERMISSIONS",
    # 审计
    "AuditLogger",
    "AuditLogEntry",
    "AuditEventType",
    "ALL_AUDIT_EVENT_TYPES",
    "get_audit_logger",
    # 沙箱
    "SandboxedExecutor",
    "SandboxManager",
    "SandboxConfig",
    "SandboxResult",
    "SandboxExecutionContext",
    "SandboxRateLimiter",
    "ParameterValidator",
    "DangerDetector",
    "FileSystemIsolator",
    "get_sandbox_manager",
    "execute_in_sandbox",
    "SANDBOX_LEVEL_UNLIMITED",
    "SANDBOX_LEVEL_BASIC",
    "SANDBOX_LEVEL_STRICT",
    "SANDBOX_LEVEL_MAXIMUM",
    "DEFAULT_SANDBOX_LEVEL",
    "DEFAULT_TIMEOUT",
    "DEFAULT_MAX_OUTPUT_SIZE",
    "DANGEROUS_FUNCTIONS",
    "SENSITIVE_PATH_PATTERNS",
    "COMMAND_INJECTION_PATTERNS",
    "SSRF_BLOCKED_PATTERNS",
]
