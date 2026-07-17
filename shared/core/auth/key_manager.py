"""
统一认证体系 - RSA 密钥管理模块

提供 RSA 密钥对的生成、加载、保存、轮换等功能，
用于 JWT RS256 非对称加密签名和验证。

核心特性：
- RSA 密钥对生成（2048/4096 位）
- PEM 格式密钥文件读写
- 密钥 ID（kid）管理，支持密钥轮换
- 多密钥并存（当前签名密钥 + 历史验证密钥）
- 从环境变量配置密钥路径
- 首次启动自动生成密钥
- 文件权限控制（600）

用法：
    from shared.core.auth.key_manager import RSAKeyManager

    # 基本用法
    manager = RSAKeyManager(key_dir="config/keys")
    manager.ensure_keys()  # 首次启动自动生成
    handler = manager.get_jwt_handler()

    # 密钥轮换
    new_kid = manager.rotate_keys()
"""

import os
import uuid
import stat
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from cryptography.hazmat.primitives import serialization, hashes
    from cryptography.hazmat.primitives.asymmetric import rsa, padding
    from cryptography.hazmat.backends import default_backend
    _crypto_available = True
except ImportError:  # pragma: no cover
    _crypto_available = False

logger = logging.getLogger(__name__)


def is_crypto_available() -> bool:
    """检查 cryptography 库是否可用

    Returns:
        True 表示 cryptography 已安装可用
    """
    return _crypto_available


# ===========================================================================
# 密钥信息数据类
# ===========================================================================

class RSAKeyPair:
    """RSA 密钥对信息

    Attributes:
        kid: 密钥 ID（用于 JWT kid 头）
        private_key: 私钥（PEM 格式字符串）
        public_key: 公钥（PEM 格式字符串）
        created_at: 创建时间
        expires_at: 过期时间（None 表示永不过期）
        is_active: 是否为当前活跃签名密钥
    """

    def __init__(
        self,
        kid: str,
        private_key: str,
        public_key: str,
        created_at: Optional[datetime] = None,
        expires_at: Optional[datetime] = None,
        is_active: bool = False,
    ):
        self.kid = kid
        self.private_key = private_key
        self.public_key = public_key
        self.created_at = created_at or datetime.now(tz=timezone.utc)
        self.expires_at = expires_at
        self.is_active = is_active

    @property
    def is_expired(self) -> bool:
        """密钥是否已过期"""
        if self.expires_at is None:
            return False
        return datetime.now(tz=timezone.utc) > self.expires_at

    def to_dict(self) -> Dict:
        """序列化为字典"""
        return {
            "kid": self.kid,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "is_active": self.is_active,
        }


# ===========================================================================
# RSA 密钥管理器
# ===========================================================================

class RSAKeyManager:
    """RSA 密钥管理器

    管理 JWT RS256 签名所需的 RSA 密钥对，支持：
    - 密钥对生成和保存
    - 从文件加载密钥
    - 密钥轮换（保留旧密钥用于验证）
    - 根据 kid 查找密钥
    - 活跃密钥管理

    Args:
        key_dir: 密钥文件存放目录
        key_size: RSA 密钥位数（2048 或 4096）
        private_key_file: 私钥文件名
        public_key_file: 公钥文件名
        key_rotation_days: 密钥轮换周期（天），0 表示不自动轮换
        old_key_retention_days: 旧密钥保留天数（用于验证未过期 Token）
    """

    # 密钥元数据文件名
    METADATA_FILE = "keys_metadata.json"

    def __init__(
        self,
        key_dir: str = "config/keys",
        key_size: int = 2048,
        private_key_file: str = "jwt_private.pem",
        public_key_file: str = "jwt_public.pem",
        key_rotation_days: int = 0,
        old_key_retention_days: int = 30,
    ):
        if not _crypto_available:
            raise RuntimeError(
                "cryptography 库不可用，请先安装: pip install cryptography"
            )

        self.key_dir = Path(key_dir)
        self.key_size = key_size
        self.private_key_file = private_key_file
        self.public_key_file = public_key_file
        self.key_rotation_days = key_rotation_days
        self.old_key_retention_days = old_key_retention_days

        # 密钥存储：kid -> RSAKeyPair
        self._keys: Dict[str, RSAKeyPair] = {}
        # 当前活跃签名密钥的 kid
        self._active_kid: Optional[str] = None

        # 校验密钥大小
        if key_size not in (2048, 4096):
            raise ValueError(f"不支持的密钥长度: {key_size}，仅支持 2048 或 4096")

    # ============================================================
    # 密钥生成
    # ============================================================

    @staticmethod
    def generate_keypair(key_size: int = 2048) -> Tuple[str, str]:
        """生成 RSA 密钥对

        Args:
            key_size: 密钥位数，默认 2048

        Returns:
            (private_key_pem, public_key_pem) 元组
        """
        if not _crypto_available:
            raise RuntimeError("cryptography 库不可用")

        # 生成私钥
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=key_size,
            backend=default_backend(),
        )

        # 私钥 PEM 格式
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("utf-8")

        # 公钥 PEM 格式
        public_key = private_key.public_key()
        public_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")

        return private_pem, public_pem

    # ============================================================
    # 密钥文件读写
    # ============================================================

    def _ensure_key_dir(self) -> None:
        """确保密钥目录存在"""
        self.key_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _set_secure_permissions(filepath: Path) -> None:
        """设置文件权限为 600（仅所有者可读可写）

        注意：Windows 上权限模型不同，此操作可能是 no-op
        """
        try:
            if os.name == "posix":
                os.chmod(filepath, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
        except Exception as e:
            logger.warning("设置密钥文件权限失败 %s: %s", filepath, e)

    def _save_key_file(self, filename: str, content: str) -> Path:
        """保存密钥到文件

        Args:
            filename: 文件名
            content: 密钥内容

        Returns:
            文件路径
        """
        self._ensure_key_dir()
        filepath = self.key_dir / filename
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        self._set_secure_permissions(filepath)
        return filepath

    def _load_key_file(self, filename: str) -> Optional[str]:
        """从文件加载密钥

        Args:
            filename: 文件名

        Returns:
            密钥内容，文件不存在返回 None
        """
        filepath = self.key_dir / filename
        if not filepath.exists():
            return None
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()

    # ============================================================
    # 元数据管理
    # ============================================================

    def _load_metadata(self) -> None:
        """从元数据文件加载密钥列表"""
        import json

        meta_path = self.key_dir / self.METADATA_FILE
        if not meta_path.exists():
            return

        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            for kid, key_info in data.get("keys", {}).items():
                # 加载对应的密钥文件
                priv_file = key_info.get("private_key_file", f"{kid}_private.pem")
                pub_file = key_info.get("public_key_file", f"{kid}_public.pem")

                private_pem = self._load_key_file(priv_file)
                public_pem = self._load_key_file(pub_file)

                if private_pem and public_pem:
                    created_at = None
                    if key_info.get("created_at"):
                        created_at = datetime.fromisoformat(key_info["created_at"])
                    expires_at = None
                    if key_info.get("expires_at"):
                        expires_at = datetime.fromisoformat(key_info["expires_at"])

                    key_pair = RSAKeyPair(
                        kid=kid,
                        private_key=private_pem,
                        public_key=public_pem,
                        created_at=created_at,
                        expires_at=expires_at,
                        is_active=key_info.get("is_active", False),
                    )
                    self._keys[kid] = key_pair

                    if key_pair.is_active:
                        self._active_kid = kid

        except Exception as e:
            logger.warning("加载密钥元数据失败: %s", e)

    def _save_metadata(self) -> None:
        """保存密钥元数据到文件"""
        import json

        self._ensure_key_dir()
        meta_path = self.key_dir / self.METADATA_FILE

        data = {"keys": {}}
        for kid, key_pair in self._keys.items():
            data["keys"][kid] = {
                "private_key_file": f"{kid}_private.pem",
                "public_key_file": f"{kid}_public.pem",
                "created_at": key_pair.created_at.isoformat() if key_pair.created_at else None,
                "expires_at": key_pair.expires_at.isoformat() if key_pair.expires_at else None,
                "is_active": key_pair.is_active,
            }

        try:
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            self._set_secure_permissions(meta_path)
        except Exception as e:
            logger.warning("保存密钥元数据失败: %s", e)

    # ============================================================
    # 密钥生命周期管理
    # ============================================================

    def ensure_keys(self) -> bool:
        """确保密钥存在，不存在则自动生成

        首次启动时调用此方法，会：
        1. 尝试加载已有密钥
        2. 如果没有密钥，生成新的密钥对
        3. 设置默认密钥为活跃状态

        Returns:
            True 表示密钥已就绪，False 表示失败
        """
        try:
            # 先尝试加载已有密钥
            self._load_metadata()

            # 如果已经有活跃密钥，直接返回
            if self._active_kid and self._active_kid in self._keys:
                active_key = self._keys[self._active_kid]
                if not active_key.is_expired:
                    logger.info("JWT RS256 密钥已就绪，kid=%s", self._active_kid)
                    return True

            # 检查默认位置是否有密钥（旧版格式，无元数据）
            default_priv = self._load_key_file(self.private_key_file)
            default_pub = self._load_key_file(self.public_key_file)

            if default_priv and default_pub:
                # 迁移旧格式密钥
                kid = self._generate_kid()
                key_pair = RSAKeyPair(
                    kid=kid,
                    private_key=default_priv,
                    public_key=default_pub,
                    is_active=True,
                )
                self._keys[kid] = key_pair
                self._active_kid = kid

                # 保存为带 kid 的格式
                self._save_key_file(f"{kid}_private.pem", default_priv)
                self._save_key_file(f"{kid}_public.pem", default_pub)
                self._save_metadata()

                logger.info("已迁移旧格式 JWT 密钥，kid=%s", kid)
                return True

            # 生成新密钥
            logger.info("未找到 JWT 密钥，正在生成新的 RSA 密钥对 (%d 位)...", self.key_size)
            kid = self._generate_kid()
            private_pem, public_pem = self.generate_keypair(self.key_size)

            key_pair = RSAKeyPair(
                kid=kid,
                private_key=private_pem,
                public_key=public_pem,
                is_active=True,
            )

            # 计算过期时间
            if self.key_rotation_days > 0:
                key_pair.expires_at = datetime.now(tz=timezone.utc) + timedelta(
                    days=self.key_rotation_days
                )

            self._keys[kid] = key_pair
            self._active_kid = kid

            # 保存密钥文件
            self._save_key_file(f"{kid}_private.pem", private_pem)
            self._save_key_file(f"{kid}_public.pem", public_pem)

            # 同时保存默认文件名的副本（兼容旧代码）
            self._save_key_file(self.private_key_file, private_pem)
            self._save_key_file(self.public_key_file, public_pem)

            self._save_metadata()

            logger.info("JWT RS256 密钥生成完成，kid=%s", kid)
            return True

        except Exception as e:
            logger.error("确保 JWT 密钥失败: %s", e, exc_info=True)
            return False

    def rotate_keys(self) -> Optional[str]:
        """执行密钥轮换

        生成新的密钥对并设为活跃签名密钥，
        旧密钥保留用于验证尚未过期的 Token。

        Returns:
            新密钥的 kid，失败返回 None
        """
        try:
            # 确保有当前密钥
            if not self._active_kid:
                self.ensure_keys()
                if not self._active_kid:
                    return None

            old_kid = self._active_kid
            old_key = self._keys.get(old_kid)

            # 生成新密钥
            new_kid = self._generate_kid()
            private_pem, public_pem = self.generate_keypair(self.key_size)

            new_key = RSAKeyPair(
                kid=new_kid,
                private_key=private_pem,
                public_key=public_pem,
                is_active=True,
            )

            if self.key_rotation_days > 0:
                new_key.expires_at = datetime.now(tz=timezone.utc) + timedelta(
                    days=self.key_rotation_days
                )

            # 设置旧密钥为非活跃状态，设置保留期过期时间
            if old_key:
                old_key.is_active = False
                if self.old_key_retention_days > 0:
                    old_key.expires_at = datetime.now(tz=timezone.utc) + timedelta(
                        days=self.old_key_retention_days
                    )

            self._keys[new_kid] = new_key
            self._active_kid = new_kid

            # 保存文件
            self._save_key_file(f"{new_kid}_private.pem", private_pem)
            self._save_key_file(f"{new_kid}_public.pem", public_pem)

            # 更新默认文件指向新密钥
            self._save_key_file(self.private_key_file, private_pem)
            self._save_key_file(self.public_key_file, public_pem)

            self._save_metadata()

            # 清理过期密钥
            self._cleanup_expired_keys()

            logger.info(
                "JWT 密钥轮换完成：旧 kid=%s → 新 kid=%s",
                old_kid, new_kid,
            )
            return new_kid

        except Exception as e:
            logger.error("密钥轮换失败: %s", e, exc_info=True)
            return None

    def _cleanup_expired_keys(self) -> int:
        """清理已过期的旧密钥

        Returns:
            清理的密钥数量
        """
        expired_kids = [
            kid for kid, key_pair in self._keys.items()
            if key_pair.is_expired and not key_pair.is_active
        ]

        for kid in expired_kids:
            # 删除密钥文件
            for suffix in ["_private.pem", "_public.pem"]:
                filepath = self.key_dir / f"{kid}{suffix}"
                try:
                    if filepath.exists():
                        filepath.unlink()
                except Exception as e:
                    logger.warning("删除过期密钥文件失败 %s: %s", filepath, e)

            del self._keys[kid]
            logger.info("已清理过期密钥: kid=%s", kid)

        if expired_kids:
            self._save_metadata()

        return len(expired_kids)

    # ============================================================
    # 密钥查询
    # ============================================================

    def get_active_key(self) -> Optional[RSAKeyPair]:
        """获取当前活跃的签名密钥

        Returns:
            活跃密钥对，没有则返回 None
        """
        if not self._active_kid:
            return None
        return self._keys.get(self._active_kid)

    def get_key_by_kid(self, kid: str) -> Optional[RSAKeyPair]:
        """根据 kid 查找密钥

        Args:
            kid: 密钥 ID

        Returns:
            对应的密钥对，找不到返回 None
        """
        return self._keys.get(kid)

    def get_all_verification_keys(self) -> Dict[str, str]:
        """获取所有可用于验证的公钥

        包含活跃密钥和未过期的旧密钥。

        Returns:
            {kid: public_key_pem} 字典
        """
        result = {}
        for kid, key_pair in self._keys.items():
            if not key_pair.is_expired:
                result[kid] = key_pair.public_key
        return result

    def get_all_keys_info(self) -> List[Dict]:
        """获取所有密钥的基本信息（不含密钥内容）

        Returns:
            密钥信息列表
        """
        return [key_pair.to_dict() for key_pair in self._keys.values()]

    @property
    def active_kid(self) -> Optional[str]:
        """当前活跃密钥的 kid"""
        return self._active_kid

    @property
    def key_count(self) -> int:
        """密钥总数"""
        return len(self._keys)

    # ============================================================
    # 辅助方法
    # ============================================================

    @staticmethod
    def _generate_kid() -> str:
        """生成密钥 ID"""
        return f"key-{uuid.uuid4().hex[:12]}"

    # ============================================================
    # JWT Handler 集成
    # ============================================================

    def get_jwt_config(
        self,
        access_token_expire_minutes: int = 1440,
        refresh_token_expire_days: int = 7,
        issuer: Optional[str] = None,
        audience: Optional[str] = None,
    ) -> Optional["JWTConfig"]:
        """基于当前密钥生成 JWTConfig

        Args:
            access_token_expire_minutes: Access Token 有效期（分钟）
            refresh_token_expire_days: Refresh Token 有效期（天）
            issuer: Token 签发者
            audience: Token 受众

        Returns:
            JWTConfig 实例，密钥未就绪返回 None
        """
        from .jwt import JWTConfig

        active_key = self.get_active_key()
        if not active_key:
            return None

        return JWTConfig(
            algorithm="RS256",
            private_key=active_key.private_key,
            public_key=active_key.public_key,
            access_token_expire_minutes=access_token_expire_minutes,
            refresh_token_expire_days=refresh_token_expire_days,
            issuer=issuer,
            audience=audience,
            require_secure_secret=False,  # RS256 使用密钥文件，已有安全保障
        )

    def get_jwt_handler(
        self,
        access_token_expire_minutes: int = 1440,
        refresh_token_expire_days: int = 7,
        issuer: Optional[str] = None,
        audience: Optional[str] = None,
    ) -> Optional["JWTHandler"]:
        """基于当前密钥创建 JWTHandler

        Args:
            access_token_expire_minutes: Access Token 有效期（分钟）
            refresh_token_expire_days: Refresh Token 有效期（天）
            issuer: Token 签发者
            audience: Token 受众

        Returns:
            JWTHandler 实例，密钥未就绪返回 None
        """
        from .jwt import JWTHandler

        config = self.get_jwt_config(
            access_token_expire_minutes=access_token_expire_minutes,
            refresh_token_expire_days=refresh_token_expire_days,
            issuer=issuer,
            audience=audience,
        )
        if config is None:
            return None
        return JWTHandler(config)


# ===========================================================================
# 便捷函数
# ===========================================================================

def generate_rsa_keys(
    key_size: int = 2048,
    output_dir: str = "config/keys",
    private_key_name: str = "jwt_private.pem",
    public_key_name: str = "jwt_public.pem",
) -> Tuple[str, str]:
    """生成 RSA 密钥对并保存到文件（便捷函数）

    Args:
        key_size: 密钥位数
        output_dir: 输出目录
        private_key_name: 私钥文件名
        public_key_name: 公钥文件名

    Returns:
        (private_key_path, public_key_path) 元组
    """
    manager = RSAKeyManager(
        key_dir=output_dir,
        key_size=key_size,
        private_key_file=private_key_name,
        public_key_file=public_key_name,
    )
    manager.ensure_keys()

    priv_path = manager.key_dir / private_key_name
    pub_path = manager.key_dir / public_key_name
    return str(priv_path), str(pub_path)


def rotate_jwt_keys(
    key_dir: str = "config/keys",
    key_size: int = 2048,
) -> Optional[str]:
    """执行 JWT 密钥轮换（便捷函数）

    Args:
        key_dir: 密钥目录
        key_size: 新密钥位数

    Returns:
        新密钥 kid，失败返回 None
    """
    manager = RSAKeyManager(key_dir=key_dir, key_size=key_size)
    manager.ensure_keys()
    return manager.rotate_keys()


# ===========================================================================
# 命令行入口
# ===========================================================================

def main():
    """命令行工具入口

    用法：
        python -m shared.core.auth.key_manager generate [--key-size 2048] [--key-dir config/keys]
        python -m shared.core.auth.key_manager rotate [--key-dir config/keys]
        python -m shared.core.auth.key_manager list [--key-dir config/keys]
    """
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="JWT RSA 密钥管理工具")
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # generate 命令
    gen_parser = subparsers.add_parser("generate", help="生成 RSA 密钥对")
    gen_parser.add_argument("--key-size", type=int, default=2048, choices=[2048, 4096],
                            help="密钥位数（默认 2048）")
    gen_parser.add_argument("--key-dir", default="config/keys",
                            help="密钥文件目录（默认 config/keys）")

    # rotate 命令
    rot_parser = subparsers.add_parser("rotate", help="执行密钥轮换")
    rot_parser.add_argument("--key-dir", default="config/keys",
                            help="密钥文件目录（默认 config/keys）")

    # list 命令
    list_parser = subparsers.add_parser("list", help="列出所有密钥")
    list_parser.add_argument("--key-dir", default="config/keys",
                             help="密钥文件目录（默认 config/keys）")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if not _crypto_available:
        print("错误：cryptography 库未安装，请运行: pip install cryptography")
        sys.exit(1)

    if args.command == "generate":
        manager = RSAKeyManager(key_dir=args.key_dir, key_size=args.key_size)
        if manager.ensure_keys():
            active = manager.get_active_key()
            print(f"密钥已就绪")
            print(f"  目录: {manager.key_dir}")
            print(f"  活跃 kid: {active.kid if active else 'N/A'}")
            print(f"  密钥总数: {manager.key_count}")
        else:
            print("密钥生成失败")
            sys.exit(1)

    elif args.command == "rotate":
        manager = RSAKeyManager(key_dir=args.key_dir)
        manager.ensure_keys()
        new_kid = manager.rotate_keys()
        if new_kid:
            print(f"密钥轮换成功")
            print(f"  新 kid: {new_kid}")
            print(f"  密钥总数: {manager.key_count}")
        else:
            print("密钥轮换失败")
            sys.exit(1)

    elif args.command == "list":
        manager = RSAKeyManager(key_dir=args.key_dir)
        manager.ensure_keys()
        keys = manager.get_all_keys_info()
        if not keys:
            print("没有找到密钥")
        else:
            print(f"密钥列表（共 {len(keys)} 个）：")
            for key_info in keys:
                status = "活跃" if key_info["is_active"] else "历史"
                print(f"  - kid: {key_info['kid']} [{status}]")
                print(f"    创建时间: {key_info['created_at']}")
                print(f"    过期时间: {key_info['expires_at'] or '永不过期'}")


if __name__ == "__main__":
    main()
