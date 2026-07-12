"""M11 MCP Bus - API 鉴权中间件.

提供 API Key 鉴权、速率限制、权限检查等安全功能。
通过 FastAPI 依赖注入方式集成，无需修改 main.py。
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from fnmatch import fnmatch
from typing import List, Optional

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..config import get_settings
from ..db import get_session
from ..models_db import ApiKey
from ..services.rate_limiter import rate_limiter


# ============================================================
# 配置：不需要鉴权的路径
# ============================================================

# 默认跳过鉴权的路径模式（支持通配符 *）
DEFAULT_PUBLIC_PATHS: List[str] = [
    "/health",
    "/m8/*",
    "/mcp",
    "/",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/favicon.ico",
]


def _hash_key(key: str) -> str:
    """对 API Key 进行 SHA256 哈希.

    Args:
        key: 明文密钥

    Returns:
        哈希后的十六进制字符串
    """
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _is_public_path(path: str, public_paths: Optional[List[str]] = None) -> bool:
    """判断路径是否为公开路径（不需要鉴权）.

    支持通配符匹配，如 /m8/* 匹配所有 /m8/ 开头的路径。

    Args:
        path: 请求路径
        public_paths: 公开路径列表，为 None 则使用默认配置

    Returns:
        True 表示该路径不需要鉴权
    """
    if public_paths is None:
        public_paths = DEFAULT_PUBLIC_PATHS

    for pattern in public_paths:
        if fnmatch(path, pattern):
            return True

    return False


# ============================================================
# API Key 查找与验证
# ============================================================

def _find_api_key(key_value: str) -> Optional[ApiKey]:
    """根据明文 Key 查找数据库中的 API Key 记录.

    Args:
        key_value: 明文 API Key

    Returns:
        ApiKey 对象，未找到或已过期返回 None
    """
    key_hash = _hash_key(key_value)
    db = get_session()
    try:
        api_key = db.query(ApiKey).filter(ApiKey.key_hash == key_hash).first()
        if not api_key:
            return None

        # 检查是否已过期
        if api_key.expires_at and api_key.expires_at < datetime.utcnow():
            return None

        return api_key
    finally:
        db.close()


def _update_last_used(api_key: ApiKey) -> None:
    """更新 API Key 的最后使用时间.

    Args:
        api_key: API Key 对象
    """
    db = get_session()
    try:
        # 重新查询以确保在当前 session 中
        key = db.query(ApiKey).filter(ApiKey.id == api_key.id).first()
        if key:
            key.last_used_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


# ============================================================
# FastAPI 依赖：提取 API Key
# ============================================================

# HTTP Bearer 鉴权方案（用于 OpenAPI 文档）
security = HTTPBearer(auto_error=False)


async def get_current_api_key(
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key", description="API Key"),
    authorization: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[ApiKey]:
    """FastAPI 依赖：获取当前请求的 API Key 对象.

    支持两种方式传递 API Key：
    1. 请求头 X-API-Key: <key>
    2. 请求头 Authorization: Bearer <key>

    如果路径为公开路径或未提供 API Key，则返回 None。

    Args:
        request: FastAPI 请求对象
        x_api_key: X-API-Key 请求头
        authorization: Authorization Bearer 请求头

    Returns:
        ApiKey 对象（验证通过），None（公开路径或未提供 Key）

    Raises:
        HTTPException: 401 - API Key 无效或已过期
        HTTPException: 429 - 超过速率限制
    """
    path = request.url.path

    # 公开路径直接放行
    if _is_public_path(path):
        return None

    # 从配置读取是否启用鉴权（开发环境默认关闭）
    settings = get_settings()
    if settings.is_development and not settings.admin_token:
        # 开发环境且未配置 admin_token 时，跳过鉴权
        return None

    # 提取 API Key 值
    key_value = None
    if x_api_key:
        key_value = x_api_key
    elif authorization and authorization.scheme.lower() == "bearer":
        key_value = authorization.credentials

    if not key_value:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少 API Key，请通过 X-API-Key 或 Authorization: Bearer 提供",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 查找并验证 API Key
    api_key = _find_api_key(key_value)
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key 无效或已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 速率限制检查
    # 窗口大小：60 秒（每分钟）
    window_seconds = 60
    limit = api_key.rate_limit

    if not rate_limiter.check_rate(f"apikey:{api_key.id}", limit, window_seconds):
        remaining = rate_limiter.get_remaining(f"apikey:{api_key.id}", limit, window_seconds)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"超过速率限制（每分钟 {limit} 次）",
            headers={
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": str(remaining),
                "Retry-After": str(window_seconds),
            },
        )

    # 更新最后使用时间（异步后台处理可优化，此处直接更新）
    _update_last_used(api_key)

    return api_key


# ============================================================
# FastAPI 依赖：强制鉴权
# ============================================================

async def require_authenticated(
    api_key: Optional[ApiKey] = Depends(get_current_api_key),
) -> ApiKey:
    """FastAPI 依赖：强制要求鉴权通过.

    与 get_current_api_key（可选）不同，本依赖在未提供有效 API Key 时
    会抛出 401 异常，确保接口必须鉴权才能访问。

    适用于管理接口、控制台接口等需要保护的端点。

    Returns:
        ApiKey 对象（验证通过）

    Raises:
        HTTPException: 401 - 未提供有效 API Key
    """
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="需要鉴权才能访问此接口，请通过 X-API-Key 或 Authorization: Bearer 提供有效 API Key",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return api_key


# ============================================================
# FastAPI 依赖：权限检查工厂
# ============================================================

def require_permission(permission: str):
    """权限检查依赖工厂.

    返回一个 FastAPI 依赖函数，检查当前 API Key 是否拥有指定权限。

    使用方式：
        @router.get("/admin/servers")
        async def list_servers(
            api_key: ApiKey = Depends(require_permission("admin:servers:read"))
        ):
            ...

    Args:
        permission: 需要的权限标识（如 "admin:servers:read"）

    Returns:
        FastAPI 依赖函数
    """

    async def _check_permission(
        api_key: Optional[ApiKey] = Depends(get_current_api_key),
    ) -> ApiKey:
        """检查当前 API Key 是否拥有指定权限.

        Args:
            api_key: 当前请求的 API Key 对象

        Returns:
            ApiKey 对象（验证通过）

        Raises:
            HTTPException: 401 - 未提供有效 API Key
            HTTPException: 403 - 权限不足
        """
        if api_key is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="需要鉴权才能访问此接口",
                headers={"WWW-Authenticate": "Bearer"},
            )

        permissions = api_key.permissions or []

        # 超级权限 "*" 表示拥有所有权限
        if "*" in permissions:
            return api_key

        # 支持通配符匹配，如 "admin:*" 匹配所有 admin 开头的权限
        for perm in permissions:
            if perm == permission:
                return api_key
            if "*" in perm and fnmatch(permission, perm):
                return api_key

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"权限不足，需要: {permission}",
        )

    return _check_permission


# ============================================================
# 中间件类（可选：用于全局限流统计等）
# ============================================================

class ApiKeyAuthMiddleware:
    """API Key 鉴权中间件类.

    提供类形式的封装，便于在其他场景中复用。
    主要功能：
    - 从请求头提取 API Key
    - 验证 Key 有效性和过期时间
    - 基于 API Key 的速率限制
    - 权限检查

    注意：FastAPI 推荐使用依赖注入（Depends）方式进行鉴权，
    本类主要用于非路由场景的鉴权封装。
    """

    def __init__(
        self,
        public_paths: Optional[List[str]] = None,
        rate_limit_window: int = 60,
    ) -> None:
        """初始化鉴权中间件.

        Args:
            public_paths: 公开路径列表，支持通配符
            rate_limit_window: 限流窗口大小（秒），默认 60 秒
        """
        self._public_paths = public_paths or DEFAULT_PUBLIC_PATHS
        self._rate_limit_window = rate_limit_window

    def extract_key_from_headers(self, headers: dict) -> Optional[str]:
        """从请求头中提取 API Key.

        Args:
            headers: 请求头字典

        Returns:
            API Key 字符串，未找到返回 None
        """
        # 优先使用 X-API-Key
        api_key = headers.get("X-API-Key") or headers.get("x-api-key")
        if api_key:
            return api_key

        # 其次使用 Authorization: Bearer
        auth = headers.get("Authorization") or headers.get("authorization")
        if auth and auth.lower().startswith("bearer "):
            return auth[7:].strip()

        return None

    def authenticate(self, key_value: str) -> Optional[ApiKey]:
        """验证 API Key.

        Args:
            key_value: 明文 API Key

        Returns:
            ApiKey 对象，验证失败返回 None
        """
        return _find_api_key(key_value)

    def check_rate_limit(self, api_key: ApiKey) -> bool:
        """检查速率限制.

        Args:
            api_key: API Key 对象

        Returns:
            True 表示未超限，False 表示已超限
        """
        return rate_limiter.check_rate(
            f"apikey:{api_key.id}",
            api_key.rate_limit,
            self._rate_limit_window,
        )

    def is_public_path(self, path: str) -> bool:
        """判断路径是否为公开路径.

        Args:
            path: 请求路径

        Returns:
            True 表示不需要鉴权
        """
        return _is_public_path(path, self._public_paths)
