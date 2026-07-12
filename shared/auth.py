"""
云汐系统轻量级鉴权工具模块
提供 API Key 管理、路径白名单、令牌桶限流、FastAPI 适配等通用鉴权能力，
不依赖数据库，仅使用 Python 标准库 + FastAPI（适配部分可选）
"""

import hashlib
import secrets
import threading
import time
from fnmatch import fnmatch
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

# ==================== 默认公开路径 ====================

DEFAULT_PUBLIC_PATHS: List[str] = [
    "/",
    "/health",
    "/m8/*",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/favicon.ico",
]
"""默认公开路径列表，支持通配符 * 匹配"""


# ==================== API Key 管理 ====================

def hash_api_key(key: str) -> str:
    """计算 API Key 的 SHA256 哈希值

    用于存储和比对密钥，避免明文保存。

    Args:
        key: 原始 API Key 字符串

    Returns:
        64 位十六进制 SHA256 哈希字符串

    Examples:
        >>> hash_api_key("my-secret-key")
        '2d3c4f5a6b...'
    """
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def verify_api_key(
    key: str,
    valid_keys: List[Union[str, Tuple[str, Dict[str, Any]]]],
) -> Optional[Dict[str, Any]]:
    """验证 API Key 是否有效

    valid_keys 支持两种格式：
    - 字符串列表：``["key1", "key2"]``，直接比对明文密钥
    - 元组列表：``[("key_hash", {"name": "admin", "permissions": ["*"]})]``，
      比对哈希值并返回对应的元数据字典

    两种格式可以混合使用。

    Args:
        key: 待验证的 API Key
        valid_keys: 有效密钥列表，支持字符串或（哈希值, 元数据）元组

    Returns:
        验证成功返回密钥对应的元数据字典（纯字符串密钥返回空字典 ``{}``），
        验证失败返回 ``None``

    Examples:
        >>> # 纯字符串密钥
        >>> verify_api_key("secret", ["secret", "other"])
        {}

        >>> # 带元数据的哈希密钥
        >>> keys = [(hash_api_key("admin-key"), {"name": "admin", "permissions": ["*"]})]
        >>> verify_api_key("admin-key", keys)
        {'name': 'admin', 'permissions': ['*']}

        >>> # 验证失败
        >>> verify_api_key("wrong", ["secret"]) is None
        True
    """
    if not key or not valid_keys:
        return None

    key_hash = hash_api_key(key)

    for item in valid_keys:
        if isinstance(item, str):
            # 字符串格式：同时支持明文比对和哈希比对
            if item == key or item == key_hash:
                return {}
        elif isinstance(item, tuple) and len(item) >= 2:
            # 元组格式：(key_hash, metadata_dict)
            stored_hash, metadata = item[0], item[1]
            if stored_hash == key_hash or stored_hash == key:
                return dict(metadata) if isinstance(metadata, dict) else {}

    return None


# ==================== 路径白名单 ====================

def is_public_path(path: str, public_paths: List[str]) -> bool:
    """判断路径是否在公开路径列表中

    支持通配符 ``*`` 匹配，例如 ``/m8/*`` 可以匹配 ``/m8/health``、``/m8/status`` 等。

    Args:
        path: 待检查的请求路径，如 ``/api/v1/users``
        public_paths: 公开路径列表，支持通配符

    Returns:
        ``True`` 表示该路径为公开路径，无需鉴权

    Examples:
        >>> is_public_path("/health", ["/health", "/docs"])
        True
        >>> is_public_path("/m8/health", ["/m8/*"])
        True
        >>> is_public_path("/api/users", ["/health"])
        False
    """
    if not path or not public_paths:
        return False

    for pattern in public_paths:
        if fnmatch(path, pattern):
            return True
        # 兼容不带通配符的前缀匹配（如 /docs 匹配 /docs/xxx）
        # 排除根路径 "/"，避免匹配所有路径
        stripped = pattern.rstrip("/")
        if stripped and not pattern.endswith("*") and path.startswith(stripped + "/"):
            return True

    return False


# ==================== 令牌桶限流 ====================

class SimpleRateLimiter:
    """简单内存令牌桶限流实现

    线程安全，支持按 key 分别限流，适用于单进程内的轻量级限流场景。
    不依赖外部存储，进程重启后计数清零。

    限流算法：滑动窗口计数。在每个时间窗口内，最多允许 ``limit`` 次请求。

    Attributes:
        default_limit: 默认每个窗口允许的请求次数
        window_seconds: 时间窗口大小（秒）

    Examples:
        >>> limiter = SimpleRateLimiter(default_limit=60, window_seconds=60)
        >>> allowed, remaining, window = limiter.check("user-123")
        >>> if allowed:
        ...     # 处理请求
        ...     pass
    """

    def __init__(self, default_limit: int = 60, window_seconds: int = 60):
        """初始化限流器

        Args:
            default_limit: 默认每个窗口允许的请求次数，默认 60
            window_seconds: 时间窗口大小（秒），默认 60
        """
        self.default_limit = default_limit
        self.window_seconds = window_seconds
        self._lock = threading.Lock()
        # key -> (count, window_start_time)
        self._buckets: Dict[str, Tuple[int, float]] = {}

    def _get_window_key(self, now: float) -> int:
        """计算当前时间所在的窗口编号"""
        return int(now // self.window_seconds)

    def check(
        self,
        key: str,
        limit: Optional[int] = None,
    ) -> Tuple[bool, int, int]:
        """检查是否超过限流

        如果未超过限流，会消耗一个令牌（计数 +1）。

        Args:
            key: 限流键，如用户 ID、IP 地址、API Key 等
            limit: 本次请求使用的限流阈值，不传则使用默认值

        Returns:
            三元组 ``(是否允许, 剩余次数, 窗口大小)``：
            - 是否允许：``True`` 表示可以通过，``False`` 表示已超限
            - 剩余次数：当前窗口内还剩多少次
            - 窗口大小：窗口总秒数

        Examples:
            >>> limiter = SimpleRateLimiter(default_limit=10, window_seconds=60)
            >>> allowed, remaining, window = limiter.check("user-1")
            >>> allowed
            True
            >>> remaining
            9
        """
        if limit is None:
            limit = self.default_limit

        now = time.time()
        window_id = self._get_window_key(now)

        with self._lock:
            count, start_time = self._buckets.get(key, (0, 0.0))
            current_window_id = self._get_window_key(start_time)

            # 窗口已过期，重置计数
            if current_window_id != window_id:
                count = 0
                start_time = now

            if count >= limit:
                # 已超限
                self._buckets[key] = (count, start_time)
                return False, 0, self.window_seconds

            # 允许通过，消耗一个令牌
            count += 1
            self._buckets[key] = (count, start_time)
            remaining = limit - count
            return True, remaining, self.window_seconds

    def remaining(self, key: str, limit: Optional[int] = None) -> int:
        """查询当前剩余次数（不消耗令牌）

        Args:
            key: 限流键
            limit: 限流阈值，不传则使用默认值

        Returns:
            当前窗口内的剩余请求次数
        """
        if limit is None:
            limit = self.default_limit

        now = time.time()
        window_id = self._get_window_key(now)

        with self._lock:
            count, start_time = self._buckets.get(key, (0, 0.0))
            current_window_id = self._get_window_key(start_time)

            if current_window_id != window_id:
                return limit

            return max(0, limit - count)

    def reset(self, key: str) -> None:
        """重置指定 key 的限流计数

        Args:
            key: 限流键
        """
        with self._lock:
            self._buckets.pop(key, None)

    def clear(self) -> None:
        """清空所有限流计数"""
        with self._lock:
            self._buckets.clear()


# ==================== FastAPI 适配 ====================

def create_api_key_dependency(
    valid_keys: List[Union[str, Tuple[str, Dict[str, Any]]]],
    public_paths: Optional[List[str]] = None,
    rate_limiter: Optional[SimpleRateLimiter] = None,
    enabled: bool = True,
) -> Callable:
    """创建 FastAPI 依赖函数，用于 API Key 鉴权

    支持多种鉴权方式：
    - ``X-API-Key`` 请求头
    - ``Authorization: Bearer <key>`` 请求头
    - 公开路径自动放行
    - 可选速率限制（按 API Key 或 IP 限流）
    - ``enabled=False`` 时完全关闭鉴权（开发环境用）

    Args:
        valid_keys: 有效密钥列表，支持字符串或（哈希值, 元数据）元组格式
        public_paths: 公开路径列表，不传则使用 ``DEFAULT_PUBLIC_PATHS``
        rate_limiter: 限流器实例，不传则不启用限流
        enabled: 是否启用鉴权，默认 ``True``。设为 ``False`` 时所有请求直接放行

    Returns:
        FastAPI 依赖函数，可直接用于 ``Depends()``

    Raises:
        HTTPException: 认证失败或超时时抛出，状态码 401 / 429

    Examples:
        >>> from fastapi import Depends, FastAPI
        >>> app = FastAPI()
        >>> get_api_key = create_api_key_dependency(valid_keys=["my-secret-key"])
        >>>
        >>> @app.get("/protected")
        ... async def protected(api_key=Depends(get_api_key)):
        ...     return {"message": "ok"}
    """
    if public_paths is None:
        public_paths = DEFAULT_PUBLIC_PATHS

    # 延迟导入，避免未安装 FastAPI 时无法使用纯函数接口
    try:
        from fastapi import Header, HTTPException, Request, status
    except ImportError:  # pragma: no cover
        # 如果未安装 FastAPI，提供一个简单的占位实现，纯函数接口仍可使用
        def _dependency_placeholder(*args, **kwargs):
            raise RuntimeError("未安装 FastAPI，无法使用 create_api_key_dependency")

        return _dependency_placeholder

    async def api_key_dependency(
        request: Request,
        x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
        authorization: Optional[str] = Header(None, alias="Authorization"),
    ) -> Dict[str, Any]:
        """API Key 鉴权依赖函数

        Args:
            request: FastAPI 请求对象
            x_api_key: X-API-Key 请求头
            authorization: Authorization 请求头

        Returns:
            验证成功返回密钥元数据字典

        Raises:
            HTTPException: 401 未认证 / 429 请求过于频繁
        """
        # 完全关闭鉴权（开发模式）
        if not enabled:
            return {"name": "dev", "permissions": ["*"]}

        path = request.url.path

        # 公开路径直接放行
        if is_public_path(path, public_paths):
            return {"name": "public", "permissions": []}

        # 提取 API Key
        api_key = x_api_key
        if not api_key and authorization:
            # 支持 Bearer 格式
            if authorization.lower().startswith("bearer "):
                api_key = authorization[7:].strip()

        if not api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="缺少 API Key，请在 X-API-Key 或 Authorization: Bearer 请求头中提供",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # 验证 API Key
        metadata = verify_api_key(api_key, valid_keys)
        if metadata is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API Key 无效",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # 速率限制（按 API Key 限流）
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


# ==================== 实用工具函数 ====================

def generate_api_key(prefix: str = "yx_", length: int = 32) -> str:
    """生成安全的随机 API Key

    使用加密安全的随机数生成器，生成指定长度的 API Key，
    可选前缀便于识别和区分不同用途的密钥。

    Args:
        prefix: 密钥前缀，默认 ``"yx_"``
        length: 密钥主体长度（字符数），默认 32，不含前缀

    Returns:
        生成的 API Key 字符串，格式为 ``{prefix}{random_hex}``

    Examples:
        >>> key = generate_api_key(prefix="yx_", length=32)
        >>> key.startswith("yx_")
        True
        >>> len(key) == len("yx_") + 32
        True
    """
    if length <= 0:
        raise ValueError("length 必须为正整数")
    # token_hex(n) 生成 2*n 个字符的十六进制字符串
    num_bytes = (length + 1) // 2
    random_part = secrets.token_hex(num_bytes)[:length]
    return f"{prefix}{random_part}"


def mask_api_key(key: str, show_first: int = 4, show_last: int = 4) -> str:
    """脱敏显示 API Key（日志中使用）

    只显示密钥的前后几位，中间用星号代替，避免日志中泄露完整密钥。

    Args:
        key: 原始 API Key
        show_first: 显示前几位，默认 4
        show_last: 显示后几位，默认 4

    Returns:
        脱敏后的密钥字符串

    Examples:
        >>> mask_api_key("yx_abcdefghijklmnop")
        'yx_a**********mnop'
        >>> mask_api_key("short", show_first=2, show_last=1)
        'sh***t'
    """
    if not key:
        return ""

    key_len = len(key)
    total_show = show_first + show_last

    if key_len <= total_show:
        # 密钥太短，全部隐藏
        return "*" * key_len

    return f"{key[:show_first]}{'*' * (key_len - total_show)}{key[-show_last:]}"
