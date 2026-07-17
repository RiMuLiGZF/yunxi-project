"""
云汐统一认证体系 (shared.core.auth)
====================================

以 M12 安全盾的认证实现为基准，下沉到 shared/core/auth，
为所有模块提供统一的认证能力。

**向后兼容**：本模块同时导出原 shared.core.auth 单文件的所有 API，
旧代码无需修改即可继续使用。

子模块：
- password: 密码哈希与验证（bcrypt）
- jwt: JWT Token 签发与验证（HS256/RS256，access+refresh，密钥轮换）
- key_manager: RSA 密钥管理（生成、加载、轮换、kid 管理）
- api_key: API Key 管理与验证
- api_key_manager: API Key 统一管理中心（SC-010，分级/配额/轮换/存储）
- api_key_router: API Key 管理 FastAPI Router
- service_caller: 服务间调用 SDK（带 API Key 认证）
- rbac: 角色权限控制（RBAC）
- middleware: FastAPI 统一认证中间件
- dependencies: FastAPI Depends 认证依赖

快速开始：
    # JWT 认证
    from shared.core.auth import JWTHandler, JWTConfig
    handler = JWTHandler(JWTConfig(secret="your-secret"))
    token = handler.create_access_token({"sub": "user1"})

    # API Key 认证
    from shared.core.auth import ApiKeyValidator, InMemoryApiKeyStore, ApiKeyInfo
    store = InMemoryApiKeyStore()
    store.add_key(ApiKeyInfo(key_hash=..., key_name="test"))
    validator = ApiKeyValidator(store)

    # RBAC 权限检查
    from shared.core.auth import has_role, require_role, ROLE_ADMIN

    # FastAPI 中间件
    from shared.core.auth import UnifiedAuthMiddleware
    app.add_middleware(UnifiedAuthMiddleware, jwt_handler=handler)

    # FastAPI Depends
    from shared.core.auth import create_auth_dependency
    get_current_user = create_auth_dependency(jwt_handler=handler)

    # ===== 旧版 API（向后兼容）=====
    from shared.core.auth import hash_api_key, verify_api_key, is_public_path
    from shared.core.auth import SimpleRateLimiter, create_api_key_dependency
    from shared.core.auth import generate_api_key, mask_api_key, DEFAULT_PUBLIC_PATHS
"""

# ===========================================================================
# 密码模块
# ===========================================================================
from .password import (
    hash_password,
    verify_password,
    needs_update,
    is_bcrypt_available,
    is_insecure_fallback_mode,
)

# ===========================================================================
# JWT 模块
# ===========================================================================
from .jwt import (
    JWTHandler,
    JWTConfig,
    TokenBlacklistBackend,
    InMemoryTokenBlacklist,
    is_jwt_available,
    create_jwt_handler_from_key_manager,
)

# ===========================================================================
# RSA 密钥管理模块
# ===========================================================================
from .key_manager import (
    RSAKeyManager,
    RSAKeyPair,
    is_crypto_available,
    generate_rsa_keys,
    rotate_jwt_keys,
)

# ===========================================================================
# API Key 模块
# ===========================================================================
from .api_key import (
    generate_api_key,
    hash_api_key_sha256,
    verify_api_key_hash,
    mask_api_key,
    get_api_key_prefix,
    ApiKeyInfo,
    ApiKeyStore,
    InMemoryApiKeyStore,
    ApiKeyValidator,
)

# 为了向后兼容：旧版 hash_api_key 使用 SHA256（不是 bcrypt）
# 新版默认使用 bcrypt，旧版使用 SHA256
# 这里导出 hash_api_key 指向 SHA256 版本以保持兼容
def hash_api_key(key: str) -> str:
    """计算 API Key 的 SHA256 哈希值（向后兼容旧版 API）

    **注意**：这是旧版兼容函数，使用 SHA256 快速哈希。
    新代码建议使用：
    - hash_api_key_sha256(key) - SHA256 快速哈希（同此函数）
    - api_key.hash_api_key(key, use_bcrypt=True) - bcrypt 慢哈希

    Args:
        key: 原始 API Key 字符串

    Returns:
        64 位十六进制 SHA256 哈希字符串
    """
    return hash_api_key_sha256(key)


# 旧版 verify_api_key 函数（向后兼容）
from typing import List, Optional, Dict, Any, Union, Tuple


def verify_api_key(
    key: str,
    valid_keys: List[Union[str, Tuple[str, Dict[str, Any]]]],
) -> Optional[Dict[str, Any]]:
    """验证 API Key 是否有效（向后兼容旧版 API）

    valid_keys 支持两种格式：
    - 字符串列表：直接比对明文密钥
    - 元组列表：比对哈希值并返回对应的元数据字典

    Args:
        key: 待验证的 API Key
        valid_keys: 有效密钥列表

    Returns:
        验证成功返回密钥对应的元数据字典，失败返回 None
    """
    if not key or not valid_keys:
        return None

    key_hash = hash_api_key_sha256(key)

    for item in valid_keys:
        if isinstance(item, str):
            if item == key or item == key_hash:
                return {}
        elif isinstance(item, tuple) and len(item) >= 2:
            stored_hash, metadata = item[0], item[1]
            if stored_hash == key_hash or stored_hash == key:
                return dict(metadata) if isinstance(metadata, dict) else {}

    return None


# ===========================================================================
# API Key 统一管理中心（SC-010）
# ===========================================================================
from .api_key_manager import (
    ApiKeyLevel,
    QuotaConfig,
    QuotaUsage,
    QuotaManager,
    ApiKeyCache,
    SqliteApiKeyStore,
    ManagedApiKeyInfo,
    ApiKeyManager,
    get_api_key_manager,
    reset_api_key_manager,
)

# API Key 管理 Router
try:
    from .api_key_router import (
        create_api_key_router,
        is_fastapi_available as is_api_router_available,
    )
except ImportError:  # pragma: no cover
    create_api_key_router = None  # type: ignore
    is_fastapi_available = lambda: False  # noqa: E731

# 服务间调用 SDK
try:
    from .service_caller import (
        ServiceCaller,
        RetryConfig,
        CallStats,
        create_service_caller,
        is_httpx_available,
    )
except ImportError:  # pragma: no cover
    ServiceCaller = None  # type: ignore
    RetryConfig = None  # type: ignore
    CallStats = None  # type: ignore
    create_service_caller = None  # type: ignore
    is_httpx_available = lambda: False  # noqa: E731


# ===========================================================================
# RBAC 模块
# ===========================================================================
from .rbac import (
    # 角色常量
    ROLE_SUPER_ADMIN,
    ROLE_ADMIN,
    ROLE_OPERATOR,
    ROLE_VIEWER,
    ROLE_API,
    ROLE_HIERARCHY,
    ALL_ROLES,
    # 权限范围常量
    SCOPE_READ,
    SCOPE_WRITE,
    SCOPE_DELETE,
    SCOPE_ADMIN,
    SCOPE_ALL,
    # 角色检查函数
    has_role,
    has_any_role,
    has_all_roles,
    # 权限检查函数
    has_scope,
    has_any_scope,
    has_all_scopes,
    # FastAPI 依赖装饰器
    require_role,
    require_scope,
    require_any_scope,
)

# ===========================================================================
# 中间件模块（含向后兼容的 SimpleRateLimiter / is_public_path / DEFAULT_PUBLIC_PATHS
# ===========================================================================
from .middleware import (
    UnifiedAuthMiddleware,
    RateLimitBackend,
    SimpleMemoryRateLimiter,
    AuditLogger,
    is_public_path,
    extract_bearer_token,
    extract_api_key,
    DEFAULT_PUBLIC_PATHS,
)

# 向后兼容：旧版 SimpleRateLimiter 类名
SimpleRateLimiter = SimpleMemoryRateLimiter


# 向后兼容：旧版 create_api_key_dependency 函数
def create_api_key_dependency(
    valid_keys: List[Union[str, Tuple[str, Dict[str, Any]]]],
    public_paths: Optional[List[str]] = None,
    rate_limiter: Optional[SimpleMemoryRateLimiter] = None,
    enabled: bool = True,
):
    """创建 FastAPI 依赖函数，用于 API Key 鉴权（向后兼容旧版 API）

    Args:
        valid_keys: 有效密钥列表
        public_paths: 公开路径列表
        rate_limiter: 限流器实例
        enabled: 是否启用鉴权

    Returns:
        FastAPI 依赖函数
    """
    if public_paths is None:
        public_paths = DEFAULT_PUBLIC_PATHS

    try:
        from fastapi import Header, HTTPException, Request, status
    except ImportError:
        def _dependency_placeholder(*args, **kwargs):
            raise RuntimeError("未安装 FastAPI，无法使用 create_api_key_dependency")
        return _dependency_placeholder

    async def api_key_dependency(
        request: Request,
        x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
        authorization: Optional[str] = Header(None, alias="Authorization"),
    ) -> Dict[str, Any]:
        if not enabled:
            return {"name": "dev", "permissions": ["*"]}

        path = request.url.path

        if is_public_path(path, public_paths):
            return {"name": "public", "permissions": []}

        api_key = x_api_key
        if not api_key and authorization:
            if authorization.lower().startswith("bearer "):
                api_key = authorization[7:].strip()

        if not api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="缺少 API Key，请在 X-API-Key 或 Authorization: Bearer 请求头中提供",
                headers={"WWW-Authenticate": "Bearer"},
            )

        metadata = verify_api_key(api_key, valid_keys)
        if metadata is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API Key 无效",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if rate_limiter is not None:
            rate_key = metadata.get("name", api_key[:8])
            allowed, remaining, window = rate_limiter.check(rate_key)
            if not allowed:
                raise HTTPException(
                    status_code=429,
                    detail=f"请求过于频繁，请 {window} 秒后重试",
                    headers={
                        "X-RateLimit-Limit": str(rate_limiter.default_limit),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Window": str(window),
                        "Retry-After": str(window),
                    },
                )

        return metadata

    return api_key_dependency


# ===========================================================================
# 依赖模块
# ===========================================================================
from .dependencies import (
    create_jwt_dependency,
    create_api_key_dependency as create_api_key_dependency_new,
    create_auth_dependency,
    create_token_header_dependency,
    is_fastapi_available,
)

# ===========================================================================
# 模块版本
# ===========================================================================

__version__ = "1.0.0"

__all__ = [
    # password
    "hash_password",
    "verify_password",
    "needs_update",
    "is_bcrypt_available",
    "is_insecure_fallback_mode",
    # jwt
    "JWTHandler",
    "JWTConfig",
    "TokenBlacklistBackend",
    "InMemoryTokenBlacklist",
    "is_jwt_available",
    "create_jwt_handler_from_key_manager",
    # key_manager (RSA 密钥管理)
    "RSAKeyManager",
    "RSAKeyPair",
    "is_crypto_available",
    "generate_rsa_keys",
    "rotate_jwt_keys",
    # api_key
    "generate_api_key",
    "hash_api_key",          # 旧版兼容名 (SHA256)
    "hash_api_key_sha256",  # 新版明确名
    "verify_api_key_hash",
    "verify_api_key",       # 旧版兼容函数
    "mask_api_key",
    "get_api_key_prefix",
    "ApiKeyInfo",
    "ApiKeyStore",
    "InMemoryApiKeyStore",
    "ApiKeyValidator",
    # api_key_manager (SC-010 统一管理中心)
    "ApiKeyLevel",
    "QuotaConfig",
    "QuotaUsage",
    "QuotaManager",
    "ApiKeyCache",
    "SqliteApiKeyStore",
    "ManagedApiKeyInfo",
    "ApiKeyManager",
    "get_api_key_manager",
    "reset_api_key_manager",
    # api_key_router
    "create_api_key_router",
    "is_api_router_available",
    # service_caller
    "ServiceCaller",
    "RetryConfig",
    "CallStats",
    "create_service_caller",
    "is_httpx_available",
    # rbac
    "ROLE_SUPER_ADMIN",
    "ROLE_ADMIN",
    "ROLE_OPERATOR",
    "ROLE_VIEWER",
    "ROLE_API",
    "ROLE_HIERARCHY",
    "ALL_ROLES",
    "SCOPE_READ",
    "SCOPE_WRITE",
    "SCOPE_DELETE",
    "SCOPE_ADMIN",
    "SCOPE_ALL",
    "has_role",
    "has_any_role",
    "has_all_roles",
    "has_scope",
    "has_any_scope",
    "has_all_scopes",
    "require_role",
    "require_scope",
    "require_any_scope",
    # middleware (含旧版兼容)
    "UnifiedAuthMiddleware",
    "RateLimitBackend",
    "SimpleMemoryRateLimiter",
    "SimpleRateLimiter",     # 旧版兼容名
    "AuditLogger",
    "is_public_path",
    "extract_bearer_token",
    "extract_api_key",
    "DEFAULT_PUBLIC_PATHS",
    # dependencies
    "create_jwt_dependency",
    "create_api_key_dependency",  # 旧版兼容函数
    "create_auth_dependency",
    "create_token_header_dependency",
    "is_fastapi_available",
    # version
    "__version__",
]
