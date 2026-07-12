"""M11 MCP Bus - Redis 客户端封装.

提供 Redis 单例客户端封装，支持可选的 Redis 集成。
当 Redis 未配置或不可用时，所有操作自动降级为返回 None，
不阻塞主业务流程。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ..config import get_settings

# 尝试导入 redis-py 库，未安装也不报错
try:
    import redis
    from redis.exceptions import RedisError

    _REDIS_AVAILABLE = True
except ImportError:
    redis = None  # type: ignore[assignment]
    RedisError = Exception  # type: ignore[assignment,misc]
    _REDIS_AVAILABLE = False


logger = logging.getLogger(__name__)


class RedisClient:
    """Redis 客户端单例.

    封装常用 Redis 操作，自动处理连接管理和异常降级。
    Redis 不可用时所有方法返回 None 或空值，不抛出异常。
    """

    _instance: Optional["RedisClient"] = None

    def __new__(cls) -> "RedisClient":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """初始化 Redis 客户端（不自动连接）."""
        if hasattr(self, "_initialized") and self._initialized:
            return
        self._initialized = True
        self._client: Optional[Any] = None
        self._connected = False
        self._prefix = "m11:"
        self._timeout = 5

    # --------------------------------------------------------
    # 连接管理
    # --------------------------------------------------------

    def connect(self) -> bool:
        """连接 Redis.

        Returns:
            True 表示连接成功，False 表示连接失败或未配置
        """
        settings = get_settings()

        if not settings.use_redis:
            logger.info("[Redis] 未配置 redis_url，跳过 Redis 连接")
            return False

        if not _REDIS_AVAILABLE:
            logger.warning("[Redis] redis-py 库未安装，无法连接 Redis")
            return False

        self._prefix = settings.redis_prefix
        self._timeout = settings.redis_timeout

        try:
            self._client = redis.from_url(
                settings.redis_url,
                socket_connect_timeout=settings.redis_timeout,
                socket_timeout=settings.redis_timeout,
                decode_responses=True,
            )
            # 测试连接
            self._client.ping()
            self._connected = True
            logger.info("[Redis] 连接成功 (prefix=%s)", self._prefix)
            return True
        except Exception as e:
            logger.error("[Redis] 连接失败: %s", e)
            self._client = None
            self._connected = False
            return False

    def disconnect(self) -> None:
        """断开 Redis 连接."""
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
            self._connected = False
            logger.info("[Redis] 连接已关闭")

    def is_available(self) -> bool:
        """检查 Redis 是否可用.

        Returns:
            True 表示 Redis 已连接且可用
        """
        if not self._connected or self._client is None:
            return False
        try:
            self._client.ping()
            return True
        except Exception:
            self._connected = False
            return False

    # --------------------------------------------------------
    # 工具方法
    # --------------------------------------------------------

    def _make_key(self, key: str) -> str:
        """生成带前缀的 Redis Key.

        Args:
            key: 原始键名

        Returns:
            带前缀的键名
        """
        return f"{self._prefix}{key}"

    def _safe_call(self, func, *args, **kwargs) -> Any:
        """安全执行 Redis 操作，捕获所有异常.

        Args:
            func: Redis 操作方法
            *args: 位置参数
            **kwargs: 关键字参数

        Returns:
            操作结果，失败时返回 None
        """
        if not self._connected or self._client is None:
            return None
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.debug("[Redis] 操作失败: %s", e)
            return None

    # --------------------------------------------------------
    # 常用操作封装
    # --------------------------------------------------------

    def get(self, key: str) -> Optional[str]:
        """获取字符串值.

        Args:
            key: 键名

        Returns:
            字符串值，不存在或失败时返回 None
        """
        return self._safe_call(self._client.get, self._make_key(key))

    def set(
        self,
        key: str,
        value: str,
        ex: Optional[int] = None,
    ) -> bool:
        """设置字符串值.

        Args:
            key: 键名
            value: 值
            ex: 过期时间（秒）

        Returns:
            True 表示成功
        """
        result = self._safe_call(
            self._client.set,
            self._make_key(key),
            value,
            ex=ex,
        )
        return result is not None and result is not False

    def incr(self, key: str, amount: int = 1) -> Optional[int]:
        """递增计数器.

        Args:
            key: 键名
            amount: 递增量

        Returns:
            递增后的值，失败时返回 None
        """
        return self._safe_call(self._client.incr, self._make_key(key), amount)

    def expire(self, key: str, seconds: int) -> bool:
        """设置过期时间.

        Args:
            key: 键名
            seconds: 过期秒数

        Returns:
            True 表示成功
        """
        result = self._safe_call(
            self._client.expire, self._make_key(key), seconds
        )
        return bool(result)

    def delete(self, key: str) -> bool:
        """删除键.

        Args:
            key: 键名

        Returns:
            True 表示成功删除
        """
        result = self._safe_call(self._client.delete, self._make_key(key))
        return result is not None and result > 0

    # --------------------------------------------------------
    # Hash 操作
    # --------------------------------------------------------

    def hget(self, key: str, field: str) -> Optional[str]:
        """获取 Hash 字段值.

        Args:
            key: Hash 键名
            field: 字段名

        Returns:
            字段值，不存在或失败时返回 None
        """
        return self._safe_call(
            self._client.hget, self._make_key(key), field
        )

    def hset(self, key: str, field: str, value: str) -> bool:
        """设置 Hash 字段值.

        Args:
            key: Hash 键名
            field: 字段名
            value: 值

        Returns:
            True 表示成功
        """
        result = self._safe_call(
            self._client.hset, self._make_key(key), field, value
        )
        return result is not None

    def hset_dict(self, key: str, mapping: Dict[str, str]) -> bool:
        """批量设置 Hash 字段.

        Args:
            key: Hash 键名
            mapping: 字段-值映射

        Returns:
            True 表示成功
        """
        result = self._safe_call(
            self._client.hset, self._make_key(key), mapping=mapping
        )
        return result is not None

    def hgetall(self, key: str) -> Optional[Dict[str, str]]:
        """获取 Hash 所有字段.

        Args:
            key: Hash 键名

        Returns:
            所有字段字典，失败时返回 None
        """
        return self._safe_call(self._client.hgetall, self._make_key(key))

    # --------------------------------------------------------
    # Sorted Set 操作
    # --------------------------------------------------------

    def zadd(self, key: str, mapping: Dict[str, float]) -> Optional[int]:
        """添加成员到有序集合.

        Args:
            key: 有序集合键名
            mapping: 成员-分数映射

        Returns:
            新添加的成员数，失败时返回 None
        """
        return self._safe_call(
            self._client.zadd, self._make_key(key), mapping
        )

    def zrange(
        self,
        key: str,
        start: int = 0,
        end: int = -1,
        desc: bool = False,
    ) -> Optional[List[str]]:
        """获取有序集合的成员范围.

        Args:
            key: 有序集合键名
            start: 起始索引
            end: 结束索引
            desc: 是否按分数降序

        Returns:
            成员列表，失败时返回 None
        """
        return self._safe_call(
            self._client.zrange,
            self._make_key(key),
            start,
            end,
            desc=desc,
        )

    # --------------------------------------------------------
    # 键管理
    # --------------------------------------------------------

    def exists(self, key: str) -> bool:
        """检查键是否存在.

        Args:
            key: 键名

        Returns:
            True 表示存在
        """
        result = self._safe_call(self._client.exists, self._make_key(key))
        return result is not None and result > 0

    def keys(self, pattern: str = "*") -> List[str]:
        """按模式获取键列表（慎用，生产环境建议用 scan）.

        Args:
            pattern: 匹配模式（不含前缀，内部自动添加）

        Returns:
            键名列表（已去除前缀），失败时返回空列表
        """
        result = self._safe_call(
            self._client.keys, self._make_key(pattern)
        )
        if not result:
            return []
        prefix_len = len(self._prefix)
        return [k[prefix_len:] for k in result]


# ============================================================
# 单例实例
# ============================================================

redis_client = RedisClient()
