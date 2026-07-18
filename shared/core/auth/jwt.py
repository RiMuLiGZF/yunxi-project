"""
统一认证体系 - JWT Token 管理模块

提供 JSON Web Token（JWT）的签发与验证功能，支持：
- HS256 / RS256 / RS384 / RS512 算法
- Access Token + Refresh Token 双令牌机制
- Token 黑名单支持（接口抽象，由调用方实现存储）
- JTI（JWT ID）唯一标识
- 密钥 ID（kid）用于密钥轮换
- 多密钥验证（密钥轮换时旧 Token 仍可验证）
- 从文件加载 RSA 密钥
- 密钥安全校验

用法：
    from shared.core.auth.jwt import JWTHandler, JWTConfig

    # HS256 对称加密
    config = JWTConfig(secret="your-secret-key", algorithm="HS256")
    handler = JWTHandler(config)

    # RS256 非对称加密
    config = JWTConfig(
        algorithm="RS256",
        private_key=private_key_pem,
        public_key=public_key_pem,
    )
    handler = JWTHandler(config)

    # 签发 Token
    token = handler.create_access_token({"sub": "user123", "roles": ["admin"]})

    # 验证 Token
    payload = handler.decode_token(token)
    if payload:
        print("Token 有效")
"""

import os
import uuid
import hashlib
import warnings
import logging
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List, Callable

try:
    from jose import JWTError, jwt as _jose_jwt
    from jose.backends import RSAKey
    _jose_available = True
except ImportError:  # pragma: no cover
    _jose_jwt = None
    _jose_available = False

logger = logging.getLogger(__name__)


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
        algorithm: 签名算法，默认 RS256
        access_token_expire_minutes: Access Token 过期时间（分钟）
        refresh_token_expire_days: Refresh Token 过期时间（天）
        issuer: Token 签发者（可选）
        audience: Token 受众（可选）
        require_secure_secret: 是否强制要求安全密钥
        private_key: RSA 私钥（PEM 格式字符串，RS256 使用）
        public_key: RSA 公钥（PEM 格式字符串，RS256 使用）
        private_key_path: RSA 私钥文件路径（从文件加载）
        public_key_path: RSA 公钥文件路径（从文件加载）
        kid: 密钥 ID（用于密钥轮换，留空则自动生成）
        verification_keys: 额外的验证公钥字典 {kid: public_key_pem}
            用于密钥轮换时验证用旧密钥签发的 Token
    """

    def __init__(
        self,
        secret: str = "",
        algorithm: str = "RS256",
        access_token_expire_minutes: int = 120,  # SEC-011: 默认 2 小时（生产环境）
        refresh_token_expire_days: int = 7,
        issuer: Optional[str] = None,
        audience: Optional[str] = None,
        require_secure_secret: bool = True,
        # RS256 相关
        private_key: Optional[str] = None,
        public_key: Optional[str] = None,
        private_key_path: Optional[str] = None,
        public_key_path: Optional[str] = None,
        kid: Optional[str] = None,
        verification_keys: Optional[Dict[str, str]] = None,
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
        self.private_key_path = private_key_path
        self.public_key_path = public_key_path
        self.kid = kid
        self.verification_keys = verification_keys or {}

        # 向后兼容：如果配置了 secret 但没配置 RSA 密钥，且算法为 RS256，
        # 自动 fallback 到 HS256，避免破坏旧代码
        if (
            self._is_rsa_algorithm()
            and not private_key
            and not public_key
            and not private_key_path
            and not public_key_path
            and secret
        ):
            logger.info(
                "检测到仅配置了 JWT_SECRET 但未配置 RSA 密钥，"
                "自动从 %s 降级到 HS256（向后兼容模式）",
                algorithm,
            )
            self.algorithm = "HS256"

        # 如果配置了文件路径，自动加载密钥
        if self._is_rsa_algorithm() and not (private_key and public_key):
            self._load_keys_from_files()

    def _is_rsa_algorithm(self) -> bool:
        """检查是否为 RSA 非对称算法"""
        return self.algorithm.upper().startswith("RS") or self.algorithm.upper().startswith("PS")

    def _load_keys_from_files(self) -> None:
        """从文件加载 RSA 密钥对"""
        if self.private_key_path:
            priv_path = Path(self.private_key_path)
            if priv_path.exists():
                try:
                    with open(priv_path, "r", encoding="utf-8") as f:
                        self.private_key = f.read()
                    logger.debug("已从文件加载 RSA 私钥: %s", priv_path)
                except Exception as e:
                    logger.warning("加载 RSA 私钥文件失败 %s: %s", priv_path, e)

        if self.public_key_path:
            pub_path = Path(self.public_key_path)
            if pub_path.exists():
                try:
                    with open(pub_path, "r", encoding="utf-8") as f:
                        self.public_key = f.read()
                    logger.debug("已从文件加载 RSA 公钥: %s", pub_path)
                except Exception as e:
                    logger.warning("加载 RSA 公钥文件失败 %s: %s", pub_path, e)

    @property
    def is_default_secret(self) -> bool:
        """检查是否使用了不安全的默认密钥

        Returns:
            True 表示密钥不安全
        """
        if self._is_rsa_algorithm():
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

        if self._is_rsa_algorithm():
            if not self.private_key or not self.public_key:
                raise ValueError(
                    "JWT 配置不安全：使用 RS256 算法必须配置 private_key 和 public_key，"
                    "或配置 private_key_path / public_key_path"
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
    支持 HS256（对称加密）和 RS256/RS384/RS512（非对称加密）算法。
    支持密钥 ID（kid）和多密钥验证（密钥轮换场景）。

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
        if self.config._is_rsa_algorithm():
            return self.config.private_key or ""
        return self.config.secret

    def _get_verification_key(self) -> str:
        """获取默认验证密钥"""
        if self.config._is_rsa_algorithm():
            return self.config.public_key or ""
        return self.config.secret

    def _get_signing_headers(self) -> Dict[str, str]:
        """获取签名时的额外 JWT 头（如 kid）"""
        headers = {}
        if self.config._is_rsa_algorithm() and self.config.kid:
            headers["kid"] = self.config.kid
        return headers

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
            headers=self._get_signing_headers() or None,
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
            headers=self._get_signing_headers() or None,
        )
        return encoded_jwt

    def _get_verification_key_for_token(self, token: str) -> Optional[str]:
        """根据 Token 的 kid 头选择对应的验证公钥

        支持密钥轮换场景：
        1. 先从 Token 头中提取 kid
        2. 如果 kid 存在且在 verification_keys 中找到，使用对应的公钥
        3. 否则使用默认的 public_key

        Args:
            token: JWT Token 字符串

        Returns:
            验证用的公钥/密钥，找不到返回 None
        """
        # 如果没有配置额外验证密钥，直接使用默认密钥
        if not self.config.verification_keys:
            return self._get_verification_key()

        try:
            # 不安全解码，仅提取 header 中的 kid
            headers = _jose_jwt.get_unverified_header(token)
            kid = headers.get("kid")

            if kid and kid in self.config.verification_keys:
                return self.config.verification_keys[kid]
        except Exception:
            pass

        # 没找到 kid 或 kid 不在验证密钥列表中，使用默认公钥
        return self._get_verification_key()

    def decode_token(
        self,
        token: str,
        token_type: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """解码并验证 JWT Token

        支持密钥轮换：如果 Token 包含 kid 头，会尝试从
        verification_keys 中查找对应的公钥进行验证。

        Args:
            token: JWT Token 字符串
            token_type: 可选，指定 Token 类型（"access" / "refresh"）

        Returns:
            解码后的 payload 字典，无效返回 None
        """
        if not token or not isinstance(token, str):
            return None

        try:
            decode_options = {}
            if self.config.audience:
                decode_options["audience"] = self.config.audience

            # 获取对应的验证密钥
            verify_key = self._get_verification_key_for_token(token)
            if not verify_key:
                return None

            payload = _jose_jwt.decode(
                token,
                verify_key,
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

    def decode_token_with_kid(
        self,
        token: str,
        token_type: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """解码并验证 JWT Token，返回 kid 信息

        Args:
            token: JWT Token 字符串
            token_type: 可选，指定 Token 类型

        Returns:
            包含 payload 和 kid 的字典，失败返回 None
            格式: {"payload": {...}, "kid": "key-xxx"}
        """
        kid = self.get_kid(token)
        payload = self.decode_token(token, token_type)
        if payload is None:
            return None
        return {"payload": payload, "kid": kid}

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

    @staticmethod
    def get_kid(token: str) -> Optional[str]:
        """从 Token 中提取 kid（密钥 ID，不验证签名）

        警告：此方法不验证签名，仅用于在验证前提取 kid。

        Args:
            token: JWT Token 字符串

        Returns:
            kid 字符串，提取失败或没有 kid 返回 None
        """
        try:
            headers = _jose_jwt.get_unverified_header(token)
            return headers.get("kid")
        except Exception:
            return None

    @staticmethod
    def get_unverified_claims(token: str) -> Optional[Dict[str, Any]]:
        """不安全地提取 Token 的 payload（不验证签名）

        警告：此方法不验证签名，返回的数据不可信！
        仅用于在验证前快速查看 Token 内容。

        Args:
            token: JWT Token 字符串

        Returns:
            payload 字典，失败返回 None
        """
        try:
            return _jose_jwt.get_unverified_claims(token)
        except Exception:
            return None

    @staticmethod
    def get_unverified_header(token: str) -> Optional[Dict[str, Any]]:
        """不安全地提取 Token 的 header（不验证签名）

        Args:
            token: JWT Token 字符串

        Returns:
            header 字典，失败返回 None
        """
        try:
            return _jose_jwt.get_unverified_header(token)
        except Exception:
            return None

    def add_verification_key(self, kid: str, public_key: str) -> None:
        """添加额外的验证公钥（用于密钥轮换）

        Args:
            kid: 密钥 ID
            public_key: 公钥 PEM 字符串
        """
        if self.config.verification_keys is None:
            self.config.verification_keys = {}
        self.config.verification_keys[kid] = public_key

    def remove_verification_key(self, kid: str) -> None:
        """移除验证公钥

        Args:
            kid: 密钥 ID
        """
        if self.config.verification_keys and kid in self.config.verification_keys:
            del self.config.verification_keys[kid]


# ===========================================================================
# 便捷函数：从密钥管理器创建 JWT Handler
# ===========================================================================

def create_jwt_handler_from_key_manager(
    key_manager,
    access_token_expire_minutes: int = 120,  # SEC-011: 默认 2 小时
    refresh_token_expire_days: int = 7,
    issuer: Optional[str] = None,
    audience: Optional[str] = None,
) -> Optional[JWTHandler]:
    """从 RSAKeyManager 创建支持密钥轮换的 JWTHandler

    会自动将所有未过期的公钥添加到 verification_keys 中，
    以便验证用旧密钥签发的 Token。

    Args:
        key_manager: RSAKeyManager 实例
        access_token_expire_minutes: Access Token 有效期（分钟）
        refresh_token_expire_days: Refresh Token 有效期（天）
        issuer: Token 签发者
        audience: Token 受众

    Returns:
        JWTHandler 实例，密钥未就绪返回 None
    """
    active_key = key_manager.get_active_key()
    if not active_key:
        return None

    # 获取所有验证密钥
    verification_keys = key_manager.get_all_verification_keys()

    config = JWTConfig(
        algorithm="RS256",
        private_key=active_key.private_key,
        public_key=active_key.public_key,
        kid=active_key.kid,
        verification_keys=verification_keys,
        access_token_expire_minutes=access_token_expire_minutes,
        refresh_token_expire_days=refresh_token_expire_days,
        issuer=issuer,
        audience=audience,
        require_secure_secret=False,
    )

    return JWTHandler(config)


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
