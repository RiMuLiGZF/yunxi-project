"""
统一认证体系 - API Key 管理模块

提供 API Key 的生成、哈希、验证等功能，支持：
- 安全随机 API Key 生成
- bcrypt 慢哈希存储（可选 SHA256 快速哈希）
- 可插拔的验证后端接口
- 密钥前缀与脱敏展示

用法：
    from shared.core.auth.api_key import (
        generate_api_key, hash_api_key, ApiKeyValidator,
        InMemoryApiKeyStore, ApiKeyInfo,
    )

    # 生成密钥
    api_key = generate_api_key(prefix="yx-")

    # 哈希存储
    key_hash = hash_api_key(api_key)

    # 使用验证器
    store = InMemoryApiKeyStore()
    store.add_key(ApiKeyInfo(
        key_hash=key_hash,
        key_name="test-key",
        roles=["admin"],
        scopes=["*"],
    ))
    validator = ApiKeyValidator(store)
    result = validator.validate(api_key)
"""

import secrets
import hashlib
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field

try:
    from passlib.context import CryptContext
    _pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    _bcrypt_available = True
except ImportError:  # pragma: no cover
    _pwd_context = None
    _bcrypt_available = False


def is_bcrypt_available() -> bool:
    """检查 bcrypt 是否可用"""
    return _bcrypt_available


# ===========================================================================
# API Key 生成与哈希
# ===========================================================================

def generate_api_key(prefix: str = "yx-", length: int = 32) -> str:
    """生成安全的随机 API Key

    使用加密安全的随机数生成器（secrets）生成指定长度的密钥，
    可选前缀便于识别和区分不同用途的密钥。

    Args:
        prefix: 密钥前缀，默认 "yx-"
        length: 密钥主体长度（字符数），默认 32，不含前缀

    Returns:
        生成的 API Key 字符串，格式为 {prefix}{random_base64url}

    示例：
        >>> key = generate_api_key(prefix="m10-", length=32)
        >>> key.startswith("m10-")
        True
    """
    if length <= 0:
        raise ValueError("length 必须为正整数")
    # 使用 URL-safe base64 编码，比 hex 更紧凑
    random_part = secrets.token_urlsafe(length)[:length]
    return f"{prefix}{random_part}"


def hash_api_key_sha256(api_key: str) -> str:
    """计算 API Key 的 SHA256 哈希（快速哈希）

    适用于需要高性能验证的场景（如 API 网关），
    安全性低于 bcrypt，但速度更快。

    Args:
        api_key: 明文 API Key

    Returns:
        64 位十六进制 SHA256 哈希字符串
    """
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def hash_api_key(api_key: str, use_bcrypt: bool = True) -> str:
    """哈希 API Key（默认使用 bcrypt 慢哈希）

    bcrypt 慢哈希可以抵御暴力破解和彩虹表攻击，
    但性能较低，适合用户量不大的场景。
    对于高吞吐量场景，建议使用 SHA256 + 加盐。

    Args:
        api_key: 明文 API Key
        use_bcrypt: 是否使用 bcrypt，默认 True

    Returns:
        哈希后的字符串

    Raises:
        RuntimeError: 当 use_bcrypt=True 但 bcrypt 不可用时
    """
    if use_bcrypt:
        if not _bcrypt_available:
            raise RuntimeError(
                "bcrypt 不可用，请安装 passlib[bcrypt] 或使用 use_bcrypt=False"
            )
        return _pwd_context.hash(api_key)
    return hash_api_key_sha256(api_key)


def verify_api_key_hash(
    api_key: str,
    key_hash: str,
    use_bcrypt: bool = True,
) -> bool:
    """验证 API Key 与哈希是否匹配

    Args:
        api_key: 明文 API Key
        key_hash: 存储的哈希值
        use_bcrypt: 是否使用 bcrypt 验证，默认 True

    Returns:
        True 表示匹配
    """
    if not api_key or not key_hash:
        return False

    if use_bcrypt and _bcrypt_available:
        try:
            return _pwd_context.verify(api_key, key_hash)
        except Exception:
            return False
    else:
        # SHA256 验证，使用恒定时间比较防止时序攻击
        import hmac
        computed = hash_api_key_sha256(api_key)
        return hmac.compare_digest(computed, key_hash)


def mask_api_key(
    key: str,
    show_first: int = 6,
    show_last: int = 4,
) -> str:
    """脱敏显示 API Key（日志和界面中使用）

    只显示密钥的前后几位，中间用星号代替，
    避免泄露完整密钥。

    Args:
        key: 原始 API Key
        show_first: 显示前几位，默认 6
        show_last: 显示后几位，默认 4

    Returns:
        脱敏后的密钥字符串
    """
    if not key:
        return ""

    key_len = len(key)
    total_show = show_first + show_last

    if key_len <= total_show:
        # 密钥太短，全部隐藏
        return "*" * key_len

    return f"{key[:show_first]}{'*' * (key_len - total_show)}{key[-show_last:]}"


def get_api_key_prefix(api_key: str, prefix_len: int = 8) -> str:
    """获取 API Key 前缀（用于展示和快速查询）

    Args:
        api_key: 完整 API Key
        prefix_len: 前缀长度，默认 8

    Returns:
        前缀字符串
    """
    if not api_key:
        return ""
    return api_key[:prefix_len] if len(api_key) > prefix_len else api_key


# ===========================================================================
# API Key 信息数据类
# ===========================================================================

@dataclass
class ApiKeyInfo:
    """API Key 信息

    包含一个 API Key 的完整配置信息。
    """
    key_hash: str                           # 密钥哈希值
    key_name: str = ""                      # 密钥名称
    key_prefix: str = ""                    # 密钥前缀（用于展示）
    owner: str = ""                         # 所有者
    roles: List[str] = field(default_factory=list)     # 角色列表
    scopes: List[str] = field(default_factory=list)    # 权限范围列表
    rate_limit: int = 0                     # 自定义速率限制（0=使用默认）
    call_count: int = 0                     # 累计调用次数
    last_used_at: Optional[datetime] = None  # 最后使用时间
    expires_at: Optional[datetime] = None    # 过期时间（None=永不过期）
    is_active: bool = True                  # 是否启用
    created_by: str = "system"              # 创建人
    created_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )
    description: str = ""                   # 描述说明
    extra: Dict[str, Any] = field(default_factory=dict)  # 扩展字段

    def to_dict(self, include_hash: bool = False) -> Dict[str, Any]:
        """转换为字典

        Args:
            include_hash: 是否包含密钥哈希（默认不包含，安全考虑）

        Returns:
            密钥信息字典
        """
        result = {
            "key_name": self.key_name,
            "key_prefix": self.key_prefix,
            "owner": self.owner,
            "roles": self.roles,
            "scopes": self.scopes,
            "rate_limit": self.rate_limit,
            "call_count": self.call_count,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "is_active": self.is_active,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "description": self.description,
            "extra": self.extra,
        }
        if include_hash:
            result["key_hash"] = self.key_hash
        return result

    def is_expired(self) -> bool:
        """检查是否已过期

        Returns:
            True 表示已过期
        """
        if self.expires_at is None:
            return False
        return self.expires_at < datetime.now(tz=timezone.utc)


# ===========================================================================
# API Key 存储后端接口
# ===========================================================================

class ApiKeyStore:
    """API Key 存储后端接口（抽象基类）

    各模块可以实现自己的存储后端（内存、数据库、Redis 等）。
    """

    def get_all_active(self) -> List[ApiKeyInfo]:
        """获取所有活跃的 API Key

        Returns:
            活跃的 API Key 信息列表
        """
        raise NotImplementedError

    def find_by_hash(self, key_hash: str) -> Optional[ApiKeyInfo]:
        """根据哈希查找 API Key（可选，用于快速定位）

        Args:
            key_hash: 密钥哈希值

        Returns:
            API Key 信息，找不到返回 None
        """
        # 默认实现：遍历所有活跃密钥
        for key_info in self.get_all_active():
            if key_info.key_hash == key_hash:
                return key_info
        return None

    def increment_usage(self, key_info: ApiKeyInfo) -> None:
        """更新密钥使用统计（调用次数和最后使用时间）

        Args:
            key_info: API Key 信息对象（已更新状态）
        """
        # 默认空实现，各后端可按需实现
        pass


class InMemoryApiKeyStore(ApiKeyStore):
    """内存版 API Key 存储

    适用于单进程场景，进程重启后数据丢失。
    生产环境建议使用数据库后端。
    """

    def __init__(self):
        self._keys: List[ApiKeyInfo] = []
        self._hash_index: Dict[str, ApiKeyInfo] = {}  # 哈希 -> key_info

    def get_all_active(self) -> List[ApiKeyInfo]:
        return [k for k in self._keys if k.is_active]

    def find_by_hash(self, key_hash: str) -> Optional[ApiKeyInfo]:
        return self._hash_index.get(key_hash)

    def add_key(self, key_info: ApiKeyInfo) -> None:
        """添加一个 API Key

        Args:
            key_info: API Key 信息
        """
        self._keys.append(key_info)
        self._hash_index[key_info.key_hash] = key_info

    def remove_key(self, key_hash: str) -> bool:
        """移除一个 API Key

        Args:
            key_hash: 密钥哈希值

        Returns:
            True 表示成功移除
        """
        key_info = self._hash_index.pop(key_hash, None)
        if key_info:
            self._keys = [k for k in self._keys if k.key_hash != key_hash]
            return True
        return False

    def increment_usage(self, key_info: ApiKeyInfo) -> None:
        key_info.call_count += 1
        key_info.last_used_at = datetime.now(tz=timezone.utc)


# ===========================================================================
# API Key 验证器
# ===========================================================================

class ApiKeyValidator:
    """API Key 验证器

    结合存储后端，验证 API Key 的有效性并返回对应的密钥信息。

    Args:
        store: API Key 存储后端
        use_bcrypt: 是否使用 bcrypt 验证，默认 True

    用法：
        validator = ApiKeyValidator(store)
        result = validator.validate(api_key)
        if result:
            print(f"验证通过: {result.key_name}")
    """

    def __init__(self, store: ApiKeyStore, use_bcrypt: bool = True):
        self.store = store
        self.use_bcrypt = use_bcrypt

    def validate(self, api_key: str) -> Optional[ApiKeyInfo]:
        """验证 API Key 是否有效

        验证步骤：
        1. 检查密钥是否为空
        2. 遍历所有活跃密钥进行哈希比对
        3. 检查密钥是否已过期
        4. 更新使用统计

        Args:
            api_key: 明文 API Key

        Returns:
            验证通过返回 ApiKeyInfo，失败返回 None
        """
        if not api_key:
            return None

        active_keys = self.store.get_all_active()
        if not active_keys:
            return None

        # 遍历比对（bcrypt 必须逐一比对，因为每次哈希结果不同）
        for key_info in active_keys:
            if verify_api_key_hash(api_key, key_info.key_hash, self.use_bcrypt):
                # 检查是否过期
                if key_info.is_expired():
                    return None
                # 更新使用统计
                try:
                    self.store.increment_usage(key_info)
                except Exception:
                    pass  # 统计更新失败不影响主流程
                return key_info

        return None

    def validate_sha256_fast(self, api_key: str) -> Optional[ApiKeyInfo]:
        """快速验证（仅 SHA256，支持哈希索引）

        当存储后端支持 find_by_hash 时，此方法比遍历验证快得多。
        适用于高吞吐量场景。

        Args:
            api_key: 明文 API Key

        Returns:
            验证通过返回 ApiKeyInfo，失败返回 None
        """
        if not api_key:
            return None

        key_hash = hash_api_key_sha256(api_key)
        key_info = self.store.find_by_hash(key_hash)

        if key_info and key_info.is_active and not key_info.is_expired():
            try:
                self.store.increment_usage(key_info)
            except Exception:
                pass
            return key_info

        return None
