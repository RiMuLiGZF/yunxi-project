"""
哈希工具类

用于内容哈希、同步比对等
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from typing import List


class HashUtils:
    """哈希工具类"""

    @staticmethod
    def sha256(text: str) -> str:
        """SHA-256哈希"""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def sha512(text: str) -> str:
        """SHA-512哈希"""
        return hashlib.sha512(text.encode("utf-8")).hexdigest()

    @staticmethod
    def md5(text: str) -> str:
        """MD5哈希（仅用于非安全场景）"""
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    @staticmethod
    def hmac_sha256(key: str, message: str) -> str:
        """HMAC-SHA256"""
        return hmac.new(
            key.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def generate_id(prefix: str = "") -> str:
        """生成唯一ID"""
        unique_id = uuid.uuid4().hex[:16]
        if prefix:
            return f"{prefix}_{unique_id}"
        return unique_id

    @staticmethod
    def content_hash(content: str) -> str:
        """
        计算内容哈希（用于同步比对）
        
        只存哈希，不存原文
        """
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def merkle_root(hashes: List[str]) -> str:
        """
        计算Merkle根哈希（用于批量校验）
        
        简化实现：两两组合哈希
        """
        if not hashes:
            return ""
        if len(hashes) == 1:
            return hashes[0]

        current = sorted(hashes)
        while len(current) > 1:
            next_level = []
            for i in range(0, len(current), 2):
                if i + 1 < len(current):
                    combined = current[i] + current[i + 1]
                else:
                    combined = current[i] + current[i]
                next_level.append(HashUtils.sha256(combined))
            current = next_level

        return current[0]

    @staticmethod
    def checksum(data: bytes) -> str:
        """计算数据校验和"""
        return hashlib.sha256(data).hexdigest()
