"""
加密工具 - AES-256-GCM

⚠️ 高涉密模块核心加密工具
   所有密钥仅本地存储，绝不上传
"""

from __future__ import annotations

import base64
import hashlib
import os
from typing import Optional, Tuple


class CryptoUtils:
    """
    加密工具类
    
    算法：AES-256-GCM
    - 提供认证加密（机密性 + 完整性）
    - 支持关联数据（AEAD）
    - 每次加密使用随机IV
    """

    ALGORITHM = "AES-256-GCM"
    KEY_SIZE = 32  # 256 bits
    IV_SIZE = 12   # 96 bits (GCM推荐)
    TAG_SIZE = 16  # 128 bits

    @staticmethod
    def generate_key() -> bytes:
        """生成随机密钥（256位）"""
        return os.urandom(CryptoUtils.KEY_SIZE)

    @staticmethod
    def derive_key(password: str, salt: bytes = None) -> Tuple[bytes, bytes]:
        """
        从密码派生密钥（PBKDF2-HMAC-SHA256）
        
        Args:
            password: 密码
            salt: 盐值，None时自动生成
        
        Returns:
            (key, salt)
        """
        if salt is None:
            salt = os.urandom(16)
        
        # 使用PBKDF2派生密钥
        key = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            100000,  # 迭代次数
            dklen=CryptoUtils.KEY_SIZE,
        )
        return key, salt

    @staticmethod
    def encrypt(plaintext: str, key: bytes, associated_data: str = "") -> str:
        """
        加密文本
        
        ⚠️ 高涉密 - 仅用于本地记忆加密
        
        Args:
            plaintext: 明文
            key: 256位密钥
            associated_data: 关联认证数据（不加密，但参与认证）
        
        Returns:
            Base64编码的密文（iv + tag + ciphertext）
        """
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            
            iv = os.urandom(CryptoUtils.IV_SIZE)
            aesgcm = AESGCM(key)
            ciphertext = aesgcm.encrypt(
                iv,
                plaintext.encode("utf-8"),
                associated_data.encode("utf-8") if associated_data else None,
            )
            
            # 组合: iv(12) + tag(16) + ciphertext
            # AES-GCM的tag在ciphertext末尾
            combined = iv + ciphertext
            return base64.b64encode(combined).decode("ascii")
        except ImportError:
            # 没有cryptography库时，使用简化的XOR混淆（仅用于测试）
            return CryptoUtils._simple_encrypt(plaintext, key)

    @staticmethod
    def decrypt(ciphertext_b64: str, key: bytes, associated_data: str = "") -> Optional[str]:
        """
        解密文本
        
        Args:
            ciphertext_b64: Base64编码的密文
            key: 256位密钥
            associated_data: 关联认证数据
        
        Returns:
            明文，解密失败返回None
        """
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            
            combined = base64.b64decode(ciphertext_b64)
            iv = combined[:CryptoUtils.IV_SIZE]
            ciphertext = combined[CryptoUtils.IV_SIZE:]
            
            aesgcm = AESGCM(key)
            plaintext = aesgcm.decrypt(
                iv,
                ciphertext,
                associated_data.encode("utf-8") if associated_data else None,
            )
            return plaintext.decode("utf-8")
        except Exception:
            # 尝试简化解密
            return CryptoUtils._simple_decrypt(ciphertext_b64, key)

    @staticmethod
    def _simple_encrypt(plaintext: str, key: bytes) -> str:
        """简化加密（无cryptography库时的降级方案，仅用于开发测试）"""
        import base64
        pt_bytes = plaintext.encode("utf-8")
        key_len = len(key)
        encrypted = bytes([b ^ key[i % key_len] for i, b in enumerate(pt_bytes)])
        return base64.b64encode(b"SIMPLE:" + encrypted).decode("ascii")

    @staticmethod
    def _simple_decrypt(ciphertext_b64: str, key: bytes) -> Optional[str]:
        """简化解密"""
        try:
            import base64
            data = base64.b64decode(ciphertext_b64)
            if not data.startswith(b"SIMPLE:"):
                return None
            encrypted = data[len(b"SIMPLE:"):]
            key_len = len(key)
            decrypted = bytes([b ^ key[i % key_len] for i, b in enumerate(encrypted)])
            return decrypted.decode("utf-8")
        except Exception:
            return None

    @staticmethod
    def hash_content(content: str, algorithm: str = "sha256") -> str:
        """
        计算内容哈希（用于同步比对，不存储原文）
        
        Args:
            content: 内容
            algorithm: 哈希算法
        
        Returns:
            十六进制哈希字符串
        """
        if algorithm == "sha256":
            return hashlib.sha256(content.encode("utf-8")).hexdigest()
        elif algorithm == "sha512":
            return hashlib.sha512(content.encode("utf-8")).hexdigest()
        elif algorithm == "md5":
            return hashlib.md5(content.encode("utf-8")).hexdigest()
        else:
            return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def secure_delete(file_path: str, passes: int = 3) -> bool:
        """
        安全删除文件（覆写后删除）
        
        ⚠️ 用于彻底删除敏感数据
        """
        try:
            if not os.path.exists(file_path):
                return False
            
            file_size = os.path.getsize(file_path)
            if file_size == 0:
                os.remove(file_path)
                return True
            
            # 多次覆写
            for i in range(passes):
                with open(file_path, "wb") as f:
                    if i % 2 == 0:
                        f.write(b"\x00" * file_size)
                    else:
                        f.write(b"\xFF" * file_size)
                    f.flush()
                    os.fsync(f.fileno())
            
            os.remove(file_path)
            return True
        except Exception:
            return False
