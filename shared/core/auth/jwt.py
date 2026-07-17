"""
统一认证体系 - JWT Token 管理模块

提供 JSON Web Token（JWT）的签发与验证功能，支持：
- HS256 / RS256 算法
- Access Token + Refresh Token 双令牌机制
- Token 黑名单支持（接口抽象，由调用方实现存储）
- JTI（JWT ID）唯一标识
- 密钥安全校验

用法：
    from shared.core.auth.jwt import JWTHandler, JWTConfig

    config = JWTConfig(secret="your-secret-key", algorithm="HS256")
    handler = JWTHandler(config)

    # 签发 Token
    token = handler.create_access_token({"sub": "user123", "roles": ["admin"]})

    # 验证 Token
    payload = handler.decode_token(token)
    if payload:
        print("Token 有效")
"""

import uuid
import hashlib
import warnings
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List, Callable

try:
    from jose import JWTError, jwt as _jose_jwt
    _jose_available = True
except ImportError:  # pragma: no cover
    _jose_jwt = None
    _jose_available = False


def is_jwt_available() -> bool:
    """检查 JWT 库是否可用

    Returns:
        True 表示 python-jose 已安装可用
    """
    return _jose_available


# ===========================================================================
# JWT 配置类
# ===========================================================================

class JWTConfig:
    """JWT 配置类

    封装所有 JWT 相关的配置参数，支持通过环境变量或代码配置。

    Attributes:
        secret: JWT 签名密钥（HS256 使用）
        algorithm: 签名算法，默认 HS256
        access_token_expire_minutes: Access Token 过期时间（分钟）
        refresh_token_expire_days: Refresh Token 过期时间（天）
        issuer: Token 签发者（可选）
        audience: Token 受众（可选）
        require_secure_secret: 是否强制要求安全密钥
    """

    def __init__(
        self,
        secret: str = "",
        algorithm: str = "HS256",
        access_token_expire_minutes: int = 1440,  # 24 小时
        refresh_token_expire_days: int = 7,
        issuer: Optional[str] = None,
        audience: Optional[str] = None,
        require_secure_secret: bool = True,
        # RS256 相关
        private_key: Optional[str] = None,
        public_key: Optional[str] = None,
    ):
        self.secret = secret
        self.algorithm = algorithm
        self.access_token_expire_minutes = access_token_expire_minutes
        self.refresh_token_expire_days = refresh_token_expire_days
        self.issuer = issuer
        self.audience = audience
        self.require_secure_secret = require_secure_secret
        self.private_key = private_key
        self.public_key = public_key

    @property
    def is_default_secret(self) -> bool:
        """检查是否使用了不安全的默认密钥

        Returns:
            True 表示密钥不安全
        """
        if self.algorithm.startswith("RS"):
            # RS256 使用公私钥，检查私钥是否配置
            return not self.private_key or not self.public_key
        # HS256 使用对称密钥
        return not self.secret or len(self.secret) < 32

    def validate(self) -> None:
        """验证配置的安全性

        Raises:
            ValueError: 当配置不安全且 require_secure_secret=True 时
        """
        if not self.require_secure_secret:
            return

        if self.algorithm.startswith("RS"):
            if not self.private_key or not self.public_key:
                raise ValueError(
                    "JWT 配置不安全：使用 RS256 算法必须配置 private_key 和 public_key"
                )
        else:
            if not self.secret:
                raise ValueError(
                    "JWT 配置不安全：secret 不能为空。"
                    "请设置一个至少 32 字符的强密钥，"
                    "或设置 require_secure_secret=False 跳过检查（仅限开发环境）。"
                )
            if len(self.secret) < 32:
                raise ValueError(
                    f"JWT 配置不安全：secret 长度仅 {len(self.secret)} 字符，"
                    "建议至少 32 字符以确保安全。"
                )


# ===========================================================================
# JWT 处理器
# ===========================================================================

class JWTHandler:
    """JWT Token 处理器

    提供 Token 的签发、验证、刷新等核心功能。
    支持 HS256（对称加密）和 RS256（非对称加密）两种算法。

    Args:
        config: JWTConfig 配置对象

    用法：
        handler = JWTHandler(config)
        token = handler.create_access_token({"sub": "user1"})
        payload = handler.decode_token(token)
    """

    def __init__(self, config: JWTConfig):
        if not _jose_available:
            raise RuntimeError(
                "python-jose 不可用，请先安装: pip install python-jose[cryptography]"
            )
        self.config = config
        # 首次使用时验证配置安全性（警告模式，不抛出异常以免影响启动）
        if config.is_default_secret and config.require_secure_secret:
            warnings.warn(
                "【安全警告】JWT 密钥不安全！生产环境请配置强密钥。",
                UserWarning,
                stacklevel=2,
            )

    def _get_signing_key(self) -> str:
        """获取签名密钥"""
        if self.config.algorithm.startswith("RS"):
            return self.config.private_key or ""
        return self.config.secret

    def _get_verification_key(self) -> str:
        """获取验证密钥"""
        if self.config.algorithm.startswith("RS"):
            return self.config.public_key or ""
        return self.config.secret

    def create_access_token(
        self,
        data: Dict[str, Any],
        expires_delta: Optional[timedelta] = None,
    ) -> str:
        """创建访问令牌（Access Token）

        Args:
            data: 要编码到 Token 中的数据（如 sub, username, roles, scopes）
            expires_delta: 过期时间增量，不传则使用默认配置

        Returns:
            JWT Token 字符串
        """
        to_encode = data.copy()

        if expires_delta:
            expire = datetime.now(tz=timezone.utc) + expires_delta
        else:
            expire = datetime.now(tz=timezone.utc) + timedelta(
                minutes=self.config.access_token_expire_minutes
            )

        to_encode.update({
            "exp": expire,
            "iat": datetime.now(tz=timezone.utc),
            "type": "access",
            "jti": uuid.uuid4().hex,
        })

        if self.config.issuer:
            to_encode["iss"] = self.config.issuer

        encoded_jwt = _jose_jwt.encode(
            to_encode,
            self._get_signing_key(),
            algorithm=self.config.algorithm,
        )
        return encoded_jwt

    def create_refresh_token(
        self,
        data: Dict[str, Any],
        expires_delta: Optional[timedelta] = None,
    ) -> str:
        """创建刷新令牌（Refresh Token）

        Refresh Token 通常只包含用户标识，不包含权限信息，
        用于换取新的 Access Token。

        Args:
            data: 要编码到 Token 中的数据（通常只有 sub）
            expires_delta: 过期时间增量，不传则使用默认配置

        Returns:
            JWT Refresh Token 字符串
        """
        to_encode = data.copy()

        if expires_delta:
            expire = datetime.now(tz=timezone.utc) + expires_delta
        else:
            expire = datetime.now(tz=timezone.utc) + timedelta(
                days=self.config.refresh_token_expire_days
            )

        to_encode.update({
            "exp": expire,
            "iat": datetime.now(tz=timezone.utc),
            "type": "refresh",
            "jti": uuid.uuid4().hex,
        })

        if self.config.issuer:
            to_encode["iss"] = self.config.issuer

        encoded_jwt = _jose_jwt.encode(
            to_encode,
            self._get_signing_key(),
            algorithm=self.config.algorithm,
        )
        return encoded_jwt

    def decode_token(
        self,
        token: str,
        token_type: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """解码并验证 JWT Token

        Args:
            token: JWT Token 字符串
            token_type: 可选，指定 Token 类型（"access" / "refresh"）

        Returns:
            解码后的 payload 字典，无效返回 None
        """
        try:
            decode_options = {}
            if self.config.audience:
                decode_options["audience"] = self.config.audience

            payload = _jose_jwt.decode(
                token,
                self._get_verification_key(),
                algorithms=[self.config.algorithm],
                options=decode_options if decode_options else None,
                audience=self.config.audience if self.config.audience else None,
                issuer=self.config.issuer if self.config.issuer else None,
            )

            # 验证 Token 类型
            if token_type and payload.get("type") != token_type:
                return None

            return payload
        except JWTError:
            return None

    def is_access_token_valid(self, token: str) -> bool:
        """检查 Access Token 是否有效

        Args:
            token: JWT Token 字符串

        Returns:
            True 表示有效
        """
        payload = self.decode_token(token, token_type="access")
        return payload is not None

    def is_refresh_token_valid(self, token: str) -> bool:
        """检查 Refresh Token 是否有效

        Args:
            token: JWT Token 字符串

        Returns:
            True 表示有效
        """
        payload = self.decode_token(token, token_type="refresh")
        return payload is not None

    def refresh_access_token(
        self,
        refresh_token: str,
        additional_data: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """使用 Refresh Token 刷新 Access Token

        Args:
            refresh_token: Refresh Token 字符串
            additional_data: 额外添加到新 Access Token 中的数据

        Returns:
            包含新 access_token 和 refresh_token 的字典，失败返回 None
        """
        payload = self.decode_token(refresh_token, token_type="refresh")
        if not payload:
            return None

        # 构造新 Token 的数据（保留 sub 等核心字段）
        token_data = {"sub": payload.get("sub", "")}
        if additional_data:
            token_data.update(additional_data)

        new_access_token = self.create_access_token(token_data)
        new_refresh_token = self.create_refresh_token(
            {"sub": payload.get("sub", "")}
        )

        return {
            "access_token": new_access_token,
            "refresh_token": new_refresh_token,
            "token_type": "bearer",
            "expires_in": self.config.access_token_expire_minutes * 60,
        }

    @staticmethod
    def hash_token(token: str) -> str:
        """计算 Token 的 SHA256 哈希（用于存储和黑名单比对）

        Args:
            token: JWT Token 字符串

        Returns:
            64 位十六进制哈希字符串
        """
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def get_jti(token: str) -> Optional[str]:
        """从 Token 中提取 JTI（不验证签名，仅解码 payload）

        警告：此方法不验证签名，仅用于在验证失败前提取 JTI。
        正式验证请使用 decode_token()。

        Args:
            token: JWT Token 字符串

        Returns:
            JTI 字符串，提取失败返回 None
        """
        try:
            # 不安全解码，仅提取 JTI
            payload = _jose_jwt.get_unverified_claims(token)
            return payload.get("jti")
        except Exception:
            return None


# ===========================================================================
# Token 黑名单接口
# ===========================================================================

class TokenBlacklistBackend:
    """Token 黑名单存储后端接口（抽象基类）

    各模块可以实现自己的存储后端（内存、数据库、Redis 等）。
    """

    def is_blacklisted(self, token_jti: str) -> bool:
        """检查 Token JTI 是否在黑名单中

        Args:
            token_jti: Token 的 JTI 标识

        Returns:
            True 表示在黑名单中
        """
        raise NotImplementedError

    def add(self, token_jti: str, token_hash: str, expired_at: datetime) -> None:
        """将 Token 加入黑名单

        Args:
            token_jti: Token 的 JTI 标识
            token_hash: Token 的 SHA256 哈希
            expired_at: Token 过期时间
        """
        raise NotImplementedError

    def clean_expired(self) -> int:
        """清理已过期的黑名单 Token

        Returns:
            清理的记录数量
        """
        raise NotImplementedError


class InMemoryTokenBlacklist(TokenBlacklistBackend):
    """内存版 Token 黑名单实现

    适用于单进程场景，进程重启后数据丢失。
    生产环境建议使用数据库或 Redis 后端。
    """

    def __init__(self):
        self._blacklist: Dict[str, datetime] = {}  # jti -> expired_at

    def is_blacklisted(self, token_jti: str) -> bool:
        if not token_jti:
            return False
        if token_jti in self._blacklist:
            # 检查是否已过期
            if self._blacklist[token_jti] < datetime.now(tz=timezone.utc):
                # 已过期，移除
                del self._blacklist[token_jti]
                return False
            return True
        return False

    def add(self, token_jti: str, token_hash: str, expired_at: datetime) -> None:
        if token_jti:
            self._blacklist[token_jti] = expired_at

    def clean_expired(self) -> int:
        now = datetime.now(tz=timezone.utc)
        expired_jtis = [
            jti for jti, exp in self._blacklist.items() if exp < now
        ]
        for jti in expired_jtis:
            del self._blacklist[jti]
        return len(expired_jtis)
