"""M11 MCP Bus - 安全层 - API Key 认证.

核心认证逻辑从 middleware/auth.py 抽离，
提供不依赖 FastAPI 的纯逻辑层，便于复用和测试。

middleware/auth.py 保留为薄适配层，将 FastAPI 请求转换为
对本模块核心函数的调用。
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from fnmatch import fnmatch
from typing import List, Optional

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
    "/",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/favicon.ico",
]


# ============================================================
# 工具函数
# ============================================================

def hash_key(key: str) -> str:
    """对 API Key 进行 SHA256 哈希.

    Args:
        key: 明文密钥

    Returns:
        哈希后的十六进制字符串
    """
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def is_public_path(path: str, public_paths: Optional[List[str]] = None) -> bool:
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
# API Key 查找与验证（核心逻辑）
# ============================================================

def find_api_key_by_value(key_value: str) -> Optional[ApiKey]:
    """根据明文 Key 查找数据库中的 API Key 记录.

    Args:
        key_value: 明文 API Key

    Returns:
        ApiKey 对象，未找到或已过期返回 None
    """
    key_hash = hash_key(key_value)
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


def find_api_key_by_id(key_id: int) -> Optional[ApiKey]:
    """根据 ID 查找 API Key 记录.

    Args:
        key_id: API Key ID

    Returns:
        ApiKey 对象，未找到或已过期返回 None
    """
    db = get_session()
    try:
        api_key = db.query(ApiKey).filter(ApiKey.id == key_id).first()
        if not api_key:
            return None

        if api_key.expires_at and api_key.expires_at < datetime.utcnow():
            return None

        return api_key
    finally:
        db.close()


def update_last_used(api_key: ApiKey) -> None:
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
# 认证服务
# ============================================================

class AuthResult:
    """认证结果."""

    def __init__(
        self,
        success: bool,
        api_key: Optional[ApiKey] = None,
        error_code: str = "",
        error_message: str = "",
    ) -> None:
        self.success = success
        self.api_key = api_key
        self.error_code = error_code
        self.error_message = error_message

    def __bool__(self) -> bool:
        return self.success


class AuthService:
    """API Key 认证服务.

    提供纯逻辑的认证功能，不依赖任何 Web 框架，
    可在 FastAPI、CLI、内部服务等多种场景中复用。

    功能:
    - API Key 验证（数据库查找 + 过期检查）
    - 速率限制检查
    - 使用时间更新
    - 公开路径判断
    """

    def __init__(
        self,
        public_paths: Optional[List[str]] = None,
        rate_limit_window: int = 60,
    ) -> None:
        """初始化认证服务.

        Args:
            public_paths: 公开路径列表，支持通配符
            rate_limit_window: 限流窗口大小（秒），默认 60 秒
        """
        self._public_paths = public_paths or DEFAULT_PUBLIC_PATHS
        self._rate_limit_window = rate_limit_window

    # --------------------------------------------------------
    # 路径检查
    # --------------------------------------------------------

    def is_public_path(self, path: str) -> bool:
        """判断路径是否为公开路径.

        Args:
            path: 请求路径

        Returns:
            True 表示不需要鉴权
        """
        return is_public_path(path, self._public_paths)

    # --------------------------------------------------------
    # 认证
    # --------------------------------------------------------

    def authenticate(self, key_value: str) -> AuthResult:
        """验证 API Key.

        Args:
            key_value: 明文 API Key

        Returns:
            AuthResult 认证结果
        """
        if not key_value:
            return AuthResult(
                success=False,
                error_code="missing_key",
                error_message="缺少 API Key",
            )

        api_key = find_api_key_by_value(key_value)
        if not api_key:
            return AuthResult(
                success=False,
                error_code="invalid_key",
                error_message="API Key 无效或已过期",
            )

        return AuthResult(success=True, api_key=api_key)

    # --------------------------------------------------------
    # 速率限制
    # --------------------------------------------------------

    def check_rate_limit(self, api_key: ApiKey) -> tuple[bool, int]:
        """检查速率限制.

        Args:
            api_key: API Key 对象

        Returns:
            (是否允许, 剩余次数) 元组
        """
        allowed = rate_limiter.check_rate(
            f"apikey:{api_key.id}",
            api_key.rate_limit,
            self._rate_limit_window,
        )
        remaining = rate_limiter.get_remaining(
            f"apikey:{api_key.id}",
            api_key.rate_limit,
            self._rate_limit_window,
        )
        return allowed, remaining

    # --------------------------------------------------------
    # 完整认证流程
    # --------------------------------------------------------

    def authenticate_full(
        self,
        path: str,
        key_value: str,
        auth_enabled: Optional[bool] = None,
    ) -> AuthResult:
        """完整的认证流程（公开路径判断 + Key 验证 + 限流）.

        Args:
            path: 请求路径
            key_value: API Key 值（空字符串表示未提供）
            auth_enabled: 是否启用鉴权，为 None 则从配置读取

        Returns:
            AuthResult 认证结果
        """
        # 1. 公开路径直接放行
        if self.is_public_path(path):
            return AuthResult(success=True, api_key=None)

        # 2. 检查鉴权是否启用
        if auth_enabled is None:
            settings = get_settings()
            auth_enabled = settings.api_key_auth_enabled

        if not auth_enabled:
            # 鉴权被禁用，返回匿名通过
            return AuthResult(success=True, api_key=None)

        # 3. 验证 API Key
        if not key_value:
            return AuthResult(
                success=False,
                error_code="missing_key",
                error_message="缺少 API Key，请通过 X-API-Key 或 Authorization: Bearer 提供",
            )

        auth_result = self.authenticate(key_value)
        if not auth_result.success:
            return auth_result

        # 4. 检查速率限制
        api_key = auth_result.api_key
        assert api_key is not None

        allowed, remaining = self.check_rate_limit(api_key)
        if not allowed:
            return AuthResult(
                success=False,
                error_code="rate_limited",
                error_message=f"超过速率限制（每分钟 {api_key.rate_limit} 次）",
            )

        # 5. 更新最后使用时间
        update_last_used(api_key)

        return auth_result

    # --------------------------------------------------------
    # 从请求头提取 Key
    # --------------------------------------------------------

    @staticmethod
    def extract_key_from_headers(headers: dict) -> Optional[str]:
        """从请求头字典中提取 API Key.

        支持两种方式（按优先级）：
        1. X-API-Key 头
        2. Authorization: Bearer 头

        Args:
            headers: 请求头字典（大小写不敏感）

        Returns:
            API Key 字符串，未找到返回 None
        """
        # 尝试各种大小写形式的 X-API-Key
        for header_name in ("X-API-Key", "x-api-key", "X-Api-Key"):
            value = headers.get(header_name)
            if value:
                return value

        # 尝试 Authorization: Bearer
        auth = headers.get("Authorization") or headers.get("authorization")
        if auth and auth.lower().startswith("bearer "):
            return auth[7:].strip()

        return None


# ============================================================
# 全局单例
# ============================================================

_auth_service: Optional[AuthService] = None


def get_auth_service() -> AuthService:
    """获取全局认证服务单例.

    Returns:
        AuthService 实例
    """
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService()
    return _auth_service


__all__ = [
    # 常量
    "DEFAULT_PUBLIC_PATHS",
    # 工具函数
    "hash_key",
    "is_public_path",
    "find_api_key_by_value",
    "find_api_key_by_id",
    "update_last_used",
    # 服务类
    "AuthResult",
    "AuthService",
    # 全局单例
    "get_auth_service",
]
