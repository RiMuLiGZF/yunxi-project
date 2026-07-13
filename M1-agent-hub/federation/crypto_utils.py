"""
加密工具模块 — CryptoUtils

提供 API Key 加密存储、主密钥管理、密钥轮换等功能。
基于 cryptography.Fernet (AES-128-CBC + HMAC-SHA256)。
"""

from __future__ import annotations

import os
import base64
import hashlib
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

try:
    from cryptography.fernet import Fernet, InvalidToken
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    _CRYPTO_AVAILABLE = True
except ImportError:
    _CRYPTO_AVAILABLE = False


# 主密钥环境变量名
MASTER_KEY_ENV = "FEDERATION_MASTER_KEY"

# 受信任的内部组件 ID 列表（可以读取明文 Key 的组件）
TRUSTED_INTERNAL_CALLERS = {
    "federation.adapter.base",
    "federation.adapter.openai",
    "federation.adapter.anthropic",
    "federation.adapter.gemini",
    "federation.adapter.local_model",
    "federation.adapter.codex_agent",
    "federation.adapter.hermes_agent",
    "federation.registry",
    "federation.scheduler",
    "federation.key_manager",
    "m8.agents.router",
}


class CryptoManager:
    """加密管理器

    职责：
    - 主密钥管理（从环境变量读取或自动生成）
    - API Key 加密/解密
    - 密钥轮换
    - 调用者鉴权
    """

    def __init__(self) -> None:
        self._fernet: Any = None
        self._master_key: bytes = b""
        self._logger = logger.bind(component="crypto_manager")
        self._init_crypto()

    def _init_crypto(self) -> None:
        """初始化加密组件"""
        if not _CRYPTO_AVAILABLE:
            self._logger.warning(
                "cryptography library not available, using fallback base64 encoding"
            )
            return

        # 从环境变量读取主密钥
        key_str = os.environ.get(MASTER_KEY_ENV, "")

        if key_str:
            try:
                # 验证 key 格式是否正确（Fernet key 是 32 bytes base64）
                self._fernet = Fernet(key_str.encode())
                self._master_key = key_str.encode()
                self._logger.info("master_key_loaded_from_env")
            except Exception as exc:
                self._logger.warning(
                    "invalid_master_key_in_env",
                    error=str(exc),
                )
                # 生成新的
                self._generate_and_log_key()
        else:
            # 未配置，自动生成
            self._generate_and_log_key()

    def _generate_and_log_key(self) -> None:
        """生成新的主密钥并记录"""
        if not _CRYPTO_AVAILABLE:
            return

        key = Fernet.generate_key()
        self._fernet = Fernet(key)
        self._master_key = key

        self._logger.warning(
            "master_key_auto_generated",
            key_preview=key.decode()[:8] + "****",
            instruction=(
                f"请设置环境变量 {MASTER_KEY_ENV} 以确保密钥持久化。"
                f"当前生成的 Key 将在进程重启后失效。"
            ),
        )

    # ── 加密/解密 ─────────────────────────────────────

    def encrypt(self, plaintext: str) -> str:
        """加密明文

        Args:
            plaintext: 待加密的明文字符串

        Returns:
            加密后的 base64 字符串
        """
        if not plaintext:
            return ""

        if not _CRYPTO_AVAILABLE or self._fernet is None:
            # Fallback: base64 编码（仅开发模式，不安全）
            return base64.b64encode(plaintext.encode()).decode()

        token = self._fernet.encrypt(plaintext.encode())
        return token.decode()

    def decrypt(self, ciphertext: str, caller_id: str = "") -> str:
        """解密密文

        Args:
            ciphertext: 加密后的字符串
            caller_id: 调用者 ID（用于鉴权日志）

        Returns:
            解密后的明文字符串

        Raises:
            ValueError: 解密失败
        """
        if not ciphertext:
            return ""

        if not _CRYPTO_AVAILABLE or self._fernet is None:
            # Fallback: base64 解码
            try:
                return base64.b64decode(ciphertext.encode()).decode()
            except Exception:
                return ciphertext

        try:
            plaintext = self._fernet.decrypt(ciphertext.encode()).decode()
            if caller_id:
                self._logger.debug(
                    "api_key_decrypted",
                    caller=caller_id,
                    key_preview=mask_api_key(plaintext),
                )
            return plaintext
        except InvalidToken:
            raise ValueError("解密失败：无效的加密 token 或密钥不匹配")
        except Exception as exc:
            raise ValueError(f"解密失败：{exc}")

    # ── 密钥轮换 ─────────────────────────────────────

    def rotate_master_key(self, new_key: str | None = None) -> dict[str, Any]:
        """轮换主密钥

        Args:
            new_key: 新的主密钥（Fernet 格式），不提供则自动生成

        Returns:
            轮换结果
        """
        if not _CRYPTO_AVAILABLE or self._fernet is None:
            return {
                "success": False,
                "error": "cryptography library not available",
            }

        old_fernet = self._fernet

        if new_key:
            self._fernet = Fernet(new_key.encode())
            self._master_key = new_key.encode()
        else:
            key = Fernet.generate_key()
            self._fernet = Fernet(key)
            self._master_key = key
            new_key = key.decode()

        self._logger.info(
            "master_key_rotated",
            new_key_preview=new_key[:8] + "****",
        )

        return {
            "success": True,
            "new_key_preview": mask_api_key(new_key) if new_key else "",
            "note": "需要调用方使用新密钥重新加密所有现有数据",
        }

    # ── 鉴权辅助 ─────────────────────────────────────

    def is_trusted_caller(self, caller_id: str) -> bool:
        """检查调用者是否为受信任的内部组件

        Args:
            caller_id: 调用者标识

        Returns:
            是否受信任
        """
        return caller_id in TRUSTED_INTERNAL_CALLERS

    @property
    def is_crypto_available(self) -> bool:
        """加密库是否可用"""
        return _CRYPTO_AVAILABLE and self._fernet is not None


# ── 工具函数 ────────────────────────────────────────

def mask_api_key(api_key: str, keep_prefix: int = 4, keep_suffix: int = 4) -> str:
    """脱敏 API Key（只显示前后几位）

    Args:
        api_key: 原始 API Key
        keep_prefix: 保留前几位
        keep_suffix: 保留后几位

    Returns:
        脱敏后的 Key
    """
    if not api_key:
        return ""
    if len(api_key) <= keep_prefix + keep_suffix:
        return "*" * len(api_key)
    return api_key[:keep_prefix] + "****" + api_key[-keep_suffix:]


def content_hash(content: str) -> str:
    """计算内容的 SHA-256 哈希

    Args:
        content: 内容字符串

    Returns:
        十六进制哈希字符串
    """
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


# 全局单例
_crypto_manager: CryptoManager | None = None


def get_crypto_manager() -> CryptoManager:
    """获取加密管理器单例"""
    global _crypto_manager
    if _crypto_manager is None:
        _crypto_manager = CryptoManager()
    return _crypto_manager
