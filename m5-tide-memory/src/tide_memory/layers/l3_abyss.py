"""L3 深海层 - 长期记忆（AES-256-GCM 加密文件存储）"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from typing import Dict, List, Optional

import structlog

from ..core.models import (
    ClassificationLevel,
    EmotionState,
    MemoryDomain,
    MemoryItem,
    MemoryLayer,
)
from ..db import DatabaseMigrator
from ..db.connection import get_connection
from ..common.constants import (
    L3_MAX_ITEMS,
    L3_RETENTION_DAYS,
    L3_ACCESS_PRIORITY,
    DEFAULT_L3_STORAGE_PATH,
    ENCRYPTION_KEY_SIZE,
    ENCRYPTION_SALT_SIZE,
    ENCRYPTION_NONCE_SIZE,
    ENCRYPTION_TAG_SIZE,
    PBKDF2_ITERATIONS,
    PBKDF2_DKLEN,
    QUALITY_SCORE_MAX,
    QUALITY_SCORE_DIVISOR,
    QUALITY_SCORE_DEFAULT,
    CONTENT_SANITIZED,
    CONTENT_ENCRYPTED,
    DEFAULT_TOP_K,
    FILTER_EXPAND_MULTIPLIER,
)

logger = structlog.get_logger(__name__)


class AbyssLayer:
    """
    L3 深海层 - 永久记忆

    特性：
    - 最大容量 100,000 条
    - 永久保留（retention_days = -1）
    - AES-256-GCM 加密文件存储（机密性 + 完整性校验）
    - 密钥派生：主密钥 + salt → PBKDF2-HMAC-SHA256 派生每条记忆的加密密钥
    - 每个记忆一个加密文件，文件名用 content_hash 的 SHA256
    - SQLite 索引（元数据，不含原文）
    - 支持主密钥用用户密码加密存储（可选）
    """

    def __init__(self, config: dict = None):
        config = config or {}
        self.max_items = config.get("max_items", L3_MAX_ITEMS)
        self.retention_days = config.get("retention_days", L3_RETENTION_DAYS)  # 永久
        self.access_priority = config.get("access_priority", L3_ACCESS_PRIORITY)
        self._storage_path = config.get("storage_path", DEFAULT_L3_STORAGE_PATH)
        self._db_path = os.path.join(self._storage_path, "index.db")
        self._vault_path = os.path.join(self._storage_path, "vault")
        self._master_key_path = os.path.join(self._storage_path, "master.key.enc")

        # 主密钥（内存中）
        self._master_key: bytes | None = None

        # 密码（可选，用于加密主密钥）
        self._password: str | None = config.get("password")

        # 加密后端标记
        self._use_cryptography: bool = False

        # 迁移系统开关（默认启用）
        self._use_migration = config.get("use_migration", True)

        # 初始化存储目录
        os.makedirs(self._storage_path, exist_ok=True)
        os.makedirs(self._vault_path, exist_ok=True)

        # 初始化加密后端
        self._init_crypto_backend()

        # 初始化主密钥
        self._init_master_key()

        # 初始化 SQLite 索引
        self._ensure_db()

    # ============================================================
    # 加密后端初始化
    # ============================================================

    def _init_crypto_backend(self) -> None:
        """检测可用的加密后端"""
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM

            self._use_cryptography = True
            logger.debug("加密后端: cryptography (AES-256-GCM)")
        except ImportError:
            self._use_cryptography = False
            logger.warning("cryptography 库未安装，使用降级加密方案")

    def _init_master_key(self) -> None:
        """
        初始化主密钥

        - 如果已有加密的主密钥文件，用密码解密加载
        - 如果没有，生成新的主密钥
        - 如果没有密码，明文保存主密钥（不推荐，但可用）
        """
        if os.path.exists(self._master_key_path):
            # 加载已有主密钥
            self._load_master_key()
        else:
            # 生成新主密钥
            self._master_key = os.urandom(ENCRYPTION_KEY_SIZE)  # 256 bits
            self._save_master_key()
            logger.info("生成新的 L3 主密钥")

    def _load_master_key(self) -> None:
        """从磁盘加载主密钥"""
        try:
            with open(self._master_key_path, "rb") as f:
                data = f.read()

            if self._password:
                # 用密码解密主密钥
                # 格式: salt(16) + nonce(12) + ciphertext + tag(16)
                if len(data) < ENCRYPTION_SALT_SIZE + ENCRYPTION_NONCE_SIZE + ENCRYPTION_TAG_SIZE:
                    raise ValueError("主密钥文件格式错误")

                salt = data[:ENCRYPTION_SALT_SIZE]
                nonce = data[ENCRYPTION_SALT_SIZE:ENCRYPTION_SALT_SIZE + ENCRYPTION_NONCE_SIZE]
                ciphertext_with_tag = data[ENCRYPTION_SALT_SIZE + ENCRYPTION_NONCE_SIZE:]

                # 派生解密密钥
                derived_key, _ = self._pbkdf2_derive(self._password, salt)

                # 解密主密钥
                if self._use_cryptography:
                    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

                    aesgcm = AESGCM(derived_key)
                    self._master_key = aesgcm.decrypt(nonce, ciphertext_with_tag, None)
                else:
                    # 降级方案：XOR 解密（不安全，仅用于无 cryptography 时）
                    self._master_key = self._simple_xor_decrypt(
                        ciphertext_with_tag, derived_key, nonce
                    )
            else:
                # 没有密码，直接加载（明文存储）
                self._master_key = data
                if len(self._master_key) != ENCRYPTION_KEY_SIZE:
                    logger.warning("主密钥长度异常，将重新生成")
                    self._master_key = os.urandom(ENCRYPTION_KEY_SIZE)
                    self._save_master_key()
        except Exception as e:
            logger.error(f"加载主密钥失败: {e}")
            # 失败时生成新密钥（会导致旧数据无法解密，但保证系统可用）
            self._master_key = os.urandom(ENCRYPTION_KEY_SIZE)
            self._save_master_key()

    def _save_master_key(self) -> None:
        """保存主密钥到磁盘"""
        if self._master_key is None:
            return

        try:
            if self._password:
                # 用密码加密主密钥后保存
                salt = os.urandom(ENCRYPTION_SALT_SIZE)
                nonce = os.urandom(ENCRYPTION_NONCE_SIZE)

                # 派生加密密钥
                derived_key, _ = self._pbkdf2_derive(self._password, salt)

                # 加密主密钥
                if self._use_cryptography:
                    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

                    aesgcm = AESGCM(derived_key)
                    ciphertext_with_tag = aesgcm.encrypt(nonce, self._master_key, None)
                else:
                    # 降级方案
                    ciphertext_with_tag = self._simple_xor_encrypt(
                        self._master_key, derived_key, nonce
                    )

                # 格式: salt(16) + nonce(12) + ciphertext+tag
                data = salt + nonce + ciphertext_with_tag
            else:
                # 无密码，明文保存（不推荐）
                data = self._master_key

            with open(self._master_key_path, "wb") as f:
                    f.write(data)
        except Exception as e:
            logger.error(f"保存主密钥失败: {e}")

    # ============================================================
    # SQLite 索引
    # ============================================================

    def _get_migrator(self) -> DatabaseMigrator:
        """
        获取 L3 索引数据库的迁移器

        注册 L3 层的迁移：
        - v1: 初始表结构 + 索引

        Returns:
            DatabaseMigrator 实例
        """
        migrator = DatabaseMigrator(self._db_path)

        # v1: 初始 schema（memories 表 + 索引）
        migrator.register(
            version=1,
            name="initial_schema",
            up_sql=[
                """
                CREATE TABLE IF NOT EXISTS memories (
                    memory_id TEXT PRIMARY KEY,
                    content_hash TEXT,
                    file_name TEXT,
                    layer TEXT,
                    domain TEXT,
                    owner_agent TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    last_accessed_at TEXT,
                    access_count INTEGER DEFAULT 0,
                    quality_score REAL DEFAULT 50,
                    quality_level TEXT DEFAULT 'normal',
                    retention_days INTEGER DEFAULT -1,
                    tags TEXT DEFAULT '[]',
                    metadata TEXT DEFAULT '{}',
                    sync_version INTEGER DEFAULT 0,
                    emotion_valence REAL DEFAULT 0,
                    emotion_arousal REAL DEFAULT 0,
                    emotion_ei REAL DEFAULT 0,
                    emotion_label TEXT DEFAULT 'neutral',
                    classification TEXT DEFAULT 'TOP_SECRET',
                    encryption_salt TEXT
                )
                """,
                "CREATE INDEX IF NOT EXISTS idx_domain ON memories(domain)",
                "CREATE INDEX IF NOT EXISTS idx_created ON memories(created_at)",
                "CREATE INDEX IF NOT EXISTS idx_quality ON memories(quality_score)",
                "CREATE INDEX IF NOT EXISTS idx_content_hash ON memories(content_hash)",
            ],
        )

        return migrator

    def _bootstrap_migration(self) -> bool:
        """
        引导 L3 迁移系统：检测现有数据库状态，初始化版本号

        Returns:
            是否成功引导
        """
        try:
            with get_connection(self._db_path, apply_pragmas=False) as conn:
                # 检查 memories 表是否存在
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name='memories'"
                )
                if not cursor.fetchone():
                    return False

                # L3 目前只有 v1，检测到表存在则为 v1
                detected_version = 1

                # 初始化版本表和日志表
                migrator = self._get_migrator()
                migrator._ensure_version_table(conn)
                migrator._ensure_migration_log_table(conn)
                migrator._set_version(conn, detected_version)

                # 记录迁移日志
                import time
                for v in range(1, detected_version + 1):
                    if v in migrator._migrations:
                        m = migrator._migrations[v]
                        migrator._log_migration(conn, v, m.name, 0.0)

                conn.commit()
                logger.info(
                    "migration.bootstrapped",
                    layer="L3_ABYSS",
                    db_path=self._db_path,
                    detected_version=detected_version,
                )
                return True
        except Exception as e:
            logger.warning("migration.bootstrap_failed", layer="L3_ABYSS", error=str(e))
            return False

    def _ensure_db(self) -> None:
        """确保 SQLite 索引表存在

        使用版本化迁移系统管理 schema，
        向后兼容：禁用迁移系统时回退到旧模式。
        """
        if self._use_migration:
            self._ensure_db_with_migration()
        else:
            self._ensure_db_legacy()

    def _ensure_db_with_migration(self) -> None:
        """使用版本化迁移系统初始化数据库"""
        migrator = self._get_migrator()

        # 检查迁移系统是否已初始化
        if not migrator.is_initialized():
            # 尝试引导
            bootstrapped = self._bootstrap_migration()
            if not bootstrapped:
                logger.debug("migration.new_database", layer="L3_ABYSS", db_path=self._db_path)

        # 执行迁移到最新版本
        try:
            result = migrator.migrate()
            if result["status"] == "success" and result["applied"]:
                logger.info(
                    "migration.layer_applied",
                    layer="L3_ABYSS",
                    from_version=result["from_version"],
                    to_version=result["to_version"],
                    applied_count=len(result["applied"]),
                )
        except Exception as e:
            logger.error("migration.layer_failed", layer="L3_ABYSS", error=str(e))
            # 迁移失败时回退到旧模式
            self._ensure_db_legacy()

    def _ensure_db_legacy(self) -> None:
        """旧模式：直接创建表和索引（向后兼容）"""
        with get_connection(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    memory_id TEXT PRIMARY KEY,
                    content_hash TEXT,
                    file_name TEXT,           -- 加密文件名
                    layer TEXT,
                    domain TEXT,
                    owner_agent TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    last_accessed_at TEXT,
                    access_count INTEGER DEFAULT 0,
                    quality_score REAL DEFAULT 50,
                    quality_level TEXT DEFAULT 'normal',
                    retention_days INTEGER DEFAULT -1,
                    tags TEXT DEFAULT '[]',
                    metadata TEXT DEFAULT '{}',
                    sync_version INTEGER DEFAULT 0,
                    emotion_valence REAL DEFAULT 0,
                    emotion_arousal REAL DEFAULT 0,
                    emotion_ei REAL DEFAULT 0,
                    emotion_label TEXT DEFAULT 'neutral',
                    classification TEXT DEFAULT 'TOP_SECRET',
                    encryption_salt TEXT        -- 用于派生密钥的 salt（每条记忆不同）
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_domain ON memories(domain)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_created ON memories(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_quality ON memories(quality_score)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_content_hash ON memories(content_hash)")
            conn.commit()

    # ============================================================
    # 密钥派生
    # ============================================================

    def _derive_key(self, content_hash: str, salt_hex: str = None) -> bytes:
        """
        派生单条记忆的加密密钥

        使用 PBKDF2-HMAC-SHA256：主密钥 + salt → 派生密钥

        Args:
            content_hash: 内容哈希（作为派生的一部分）
            salt_hex: 十六进制 salt，None 时用 content_hash 派生

        Returns:
            32 字节派生密钥
        """
        if self._master_key is None:
            raise RuntimeError("主密钥未初始化")

        if salt_hex:
            salt = bytes.fromhex(salt_hex)
        else:
            # 用 content_hash 作为 salt（每条记忆唯一）
            salt = hashlib.sha256(content_hash.encode("utf-8")).digest()[:ENCRYPTION_SALT_SIZE]

        # 将主密钥与 content_hash 混合，再做 PBKDF2
        mixed = self._master_key + content_hash.encode("utf-8")
        derived = hashlib.pbkdf2_hmac(
            "sha256",
            mixed,
            salt,
            PBKDF2_ITERATIONS,  # 迭代次数
            dklen=PBKDF2_DKLEN,  # 256 bits
        )
        return derived

    def _pbkdf2_derive(self, password: str, salt: bytes) -> tuple[bytes, bytes]:
        """从密码派生密钥（用于主密钥加密）"""
        key = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            PBKDF2_ITERATIONS * 10,  # 主密钥派生迭代次数更多
            dklen=PBKDF2_DKLEN,
        )
        return key, salt

    # ============================================================
    # 加密 / 解密
    # ============================================================

    def _encrypt_content(self, item: MemoryItem) -> tuple[bytes, str]:
        """
        加密记忆内容

        Args:
            item: 记忆项

        Returns:
            (加密数据 bytes, salt_hex)
            加密格式: [12 bytes nonce] + [ciphertext] + [16 bytes tag]
        """
        # 将记忆项序列化为 JSON
        item_dict = item.model_dump(mode="json")
        plaintext = json.dumps(item_dict, ensure_ascii=False).encode("utf-8")

        # 生成每条记忆唯一的 salt
        import secrets
        salt = secrets.token_bytes(16)
        salt_hex = salt.hex()

        # 派生加密密钥
        key = self._derive_key(item.content_hash, salt_hex)

        if self._use_cryptography:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM

            nonce = os.urandom(12)  # 96 bits (GCM 推荐)
            aesgcm = AESGCM(key)
            # associated_data = item.memory_id.encode("utf-8")  # 用 memory_id 作为 AAD
            ciphertext_with_tag = aesgcm.encrypt(nonce, plaintext, None)
            # 格式: nonce(12) + ciphertext+tag
            encrypted_data = nonce + ciphertext_with_tag
        else:
            # 降级方案：简单 XOR + 简单完整性校验
            nonce = os.urandom(12)
            encrypted_data = self._simple_stream_encrypt(plaintext, key, nonce)

        return encrypted_data, salt_hex

    def _decrypt_content(
        self, memory_id: str, encrypted_data: bytes, content_hash: str, salt_hex: str
    ) -> Optional[MemoryItem]:
        """
        解密记忆内容

        Args:
            memory_id: 记忆 ID
            encrypted_data: 加密数据
            content_hash: 内容哈希
            salt_hex: 盐值（十六进制）

        Returns:
            解密后的 MemoryItem，失败返回 None
        """
        try:
            # 派生解密密钥
            key = self._derive_key(content_hash, salt_hex)

            if self._use_cryptography:
                from cryptography.hazmat.primitives.ciphers.aead import AESGCM

                nonce = encrypted_data[:12]
                ciphertext_with_tag = encrypted_data[12:]
                aesgcm = AESGCM(key)
                plaintext = aesgcm.decrypt(nonce, ciphertext_with_tag, None)
            else:
                # 降级方案
                plaintext = self._simple_stream_decrypt(encrypted_data, key)
                if plaintext is None:
                    return None

            # 反序列化为 MemoryItem
            item_dict = json.loads(plaintext.decode("utf-8"))
            return MemoryItem(**item_dict)

        except Exception as e:
            logger.error(f"解密记忆失败 [{memory_id}]: {e}")
            return None

    # ============================================================
    # 降级加密方案（无 cryptography 库时）
    # ============================================================

    def _simple_stream_encrypt(self, plaintext: bytes, key: bytes, nonce: bytes) -> bytes:
        """
        简化的流加密（降级方案，仅用于无 cryptography 库时）

        格式: nonce(12) + ciphertext + checksum(16)
        用 SHA256 派生流密码 + 简单完整性校验
        """
        import hmac

        # 用 nonce + key 生成密钥流
        stream = b""
        counter = 0
        while len(stream) < len(plaintext):
            block = hashlib.sha256(key + nonce + counter.to_bytes(4, "big")).digest()
            stream += block
            counter += 1
        stream = stream[: len(plaintext)]

        # XOR 加密
        ciphertext = bytes([p ^ s for p, s in zip(plaintext, stream)])

        # 计算 HMAC 作为完整性校验
        checksum = hmac.new(key, nonce + ciphertext, hashlib.sha256).digest()[:16]

        return nonce + ciphertext + checksum

    def _simple_stream_decrypt(self, encrypted_data: bytes, key: bytes) -> Optional[bytes]:
        """简化流解密（降级方案）"""
        import hmac

        if len(encrypted_data) < 12 + 16:
            return None

        nonce = encrypted_data[:12]
        ciphertext = encrypted_data[12:-16]
        checksum = encrypted_data[-16:]

        # 校验完整性
        expected = hmac.new(key, nonce + ciphertext, hashlib.sha256).digest()[:16]
        if not hmac.compare_digest(checksum, expected):
            logger.warning("降级加密校验失败，数据可能被篡改")
            return None

        # 生成密钥流
        stream = b""
        counter = 0
        while len(stream) < len(ciphertext):
            block = hashlib.sha256(key + nonce + counter.to_bytes(4, "big")).digest()
            stream += block
            counter += 1
        stream = stream[: len(ciphertext)]

        # XOR 解密
        plaintext = bytes([c ^ s for c, s in zip(ciphertext, stream)])
        return plaintext

    def _simple_xor_encrypt(self, data: bytes, key: bytes, nonce: bytes) -> bytes:
        """简单 XOR 加密（用于主密钥加密降级）"""
        # 用 key + nonce 生成更长的密钥流
        stream = hashlib.sha256(key + nonce).digest()
        while len(stream) < len(data) + 16:
            stream += hashlib.sha256(key + nonce + stream).digest()
        encrypted = bytes([d ^ s for d, s in zip(data, stream[:len(data)])])
        # 追加简单校验
        checksum = hashlib.md5(data).digest()
        return encrypted + checksum

    def _simple_xor_decrypt(self, data: bytes, key: bytes, nonce: bytes) -> bytes:
        """简单 XOR 解密（用于主密钥加密降级）"""
        encrypted = data[:-16]
        checksum = data[-16:]
        stream = hashlib.sha256(key + nonce).digest()
        while len(stream) < len(encrypted) + 16:
            stream += hashlib.sha256(key + nonce + stream).digest()
        plaintext = bytes([e ^ s for e, s in zip(encrypted, stream[:len(encrypted)])])
        # 校验
        expected = hashlib.md5(plaintext).digest()
        if checksum != expected:
            raise ValueError("主密钥校验失败")
        return plaintext

    # ============================================================
    # 文件名计算
    # ============================================================

    def _get_file_name(self, content_hash: str) -> str:
        """根据 content_hash 计算加密文件名（SHA256）"""
        return hashlib.sha256(content_hash.encode("utf-8")).hexdigest()

    def _get_file_path(self, file_name: str) -> str:
        """获取加密文件完整路径"""
        return os.path.join(self._vault_path, file_name)

    # ============================================================
    # 核心 API
    # ============================================================

    def add(self, item: MemoryItem) -> bool:
        """
        添加记忆（加密存储 + 索引入库）

        Args:
            item: 记忆项

        Returns:
            是否成功
        """
        item.layer = MemoryLayer.L3_ABYSS

        try:
            # 加密内容
            encrypted_data, salt_hex = self._encrypt_content(item)

            # 计算文件名
            file_name = self._get_file_name(item.content_hash)
            file_path = self._get_file_path(file_name)

            # 写入加密文件
            with open(file_path, "wb") as f:
                f.write(encrypted_data)

            # 写入 SQLite 索引
            with get_connection(self._db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO memories
                    (memory_id, content_hash, file_name, layer, domain, owner_agent,
                     created_at, updated_at, last_accessed_at, access_count,
                     quality_score, quality_level, retention_days,
                     tags, metadata, sync_version,
                     emotion_valence, emotion_arousal, emotion_ei, emotion_label,
                     classification, encryption_salt)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    item.memory_id, item.content_hash, file_name,
                    item.layer.value, item.domain.value, item.owner_agent,
                    item.created_at.isoformat(), item.updated_at.isoformat(),
                    item.last_accessed_at.isoformat() if item.last_accessed_at else None,
                    item.access_count, item.quality_score, item.quality_level,
                    item.retention_days,
                    json.dumps(item.tags, ensure_ascii=False),
                    json.dumps(item.metadata, ensure_ascii=False),
                    item.sync_version,
                    item.emotion.valence, item.emotion.arousal,
                    item.emotion.ei_score, item.emotion.dominant_emotion,
                    item.classification.value,
                    salt_hex,
                ))
                conn.commit()

            return True
        except Exception as e:
            logger.error(f"L3 添加记忆失败 [{item.memory_id}]: {e}")
            return False

    def get(self, memory_id: str) -> Optional[MemoryItem]:
        """
        获取记忆（解密返回）

        Args:
            memory_id: 记忆 ID

        Returns:
            MemoryItem，不存在返回 None
        """
        try:
            with get_connection(self._db_path) as conn:
                row = conn.execute(
                    "SELECT content_hash, file_name, encryption_salt FROM memories WHERE memory_id = ?",
                    (memory_id,),
                ).fetchone()

            if not row:
                return None

            content_hash, file_name, salt_hex = row
            file_path = self._get_file_path(file_name)

            if not os.path.exists(file_path):
                logger.warning(f"L3 加密文件不存在: {file_name}")
                return None

            # 读取加密文件
            with open(file_path, "rb") as f:
                encrypted_data = f.read()

            # 解密
            item = self._decrypt_content(memory_id, encrypted_data, content_hash, salt_hex)
            if item is None:
                return None

            # 更新访问计数
            self._touch(memory_id)

            return item
        except Exception as e:
            logger.error(f"L3 获取记忆失败 [{memory_id}]: {e}")
            return None

    def _touch(self, memory_id: str) -> None:
        """更新访问时间和计数"""
        try:
            with get_connection(self._db_path) as conn:
                conn.execute(
                    "UPDATE memories SET access_count = access_count + 1, last_accessed_at = ? WHERE memory_id = ?",
                    (datetime.now().isoformat(), memory_id),
                )
                conn.commit()
        except Exception as e:
            logger.warning(f"更新访问计数失败 [{memory_id}]: {e}")

    def remove(self, memory_id: str) -> bool:
        """
        删除记忆（删除加密文件 + 索引）

        Args:
            memory_id: 记忆 ID

        Returns:
            是否成功
        """
        try:
            with get_connection(self._db_path) as conn:
                row = conn.execute(
                    "SELECT file_name FROM memories WHERE memory_id = ?",
                    (memory_id,),
                ).fetchone()

                if not row:
                    return False

                file_name = row[0]
                conn.execute("DELETE FROM memories WHERE memory_id = ?", (memory_id,))
                conn.commit()

            # 删除加密文件
            file_path = self._get_file_path(file_name)
            if os.path.exists(file_path):
                try:
                    # 安全删除（覆写后删除）
                    from ..utils.crypto import CryptoUtils
                    CryptoUtils.secure_delete(file_path)
                except Exception:
                    os.remove(file_path)

            return True
        except Exception as e:
            logger.error(f"L3 删除记忆失败 [{memory_id}]: {e}")
            return False

    def search(self, query: str, domain: str = None, top_k: int = DEFAULT_TOP_K) -> List[Dict]:
        """
        搜索（只搜元数据索引，内容不解密

        Args:
            query: 查询文本
            domain: 域过滤
            top_k: 返回数量

        Returns:
            [{memory_id, content_preview, layer, domain, similarity, created_at, emotion_tags, encrypted}]
        """
        try:
            with get_connection(self._db_path) as conn:
                query_cond = ""
                params: list = []
                if domain:
                    query_cond = "AND domain = ?"
                    params.append(domain)

                rows = conn.execute(f"""
                    SELECT memory_id, layer, domain, created_at, tags, quality_score,
                           emotion_ei, emotion_label
                    FROM memories WHERE 1=1 {query_cond}
                    ORDER BY quality_score DESC
                    LIMIT ?
                """, params + [top_k * FILTER_EXPAND_MULTIPLIER]).fetchall()

            results = []
            for row in rows:
                tags = json.loads(row[4]) if row[4] else []
                # 简单标签匹配计分
                score = sum(1 for tag in tags if tag in query)
                if score > 0 or not query:
                    results.append({
                        "memory_id": row[0],
                        "content_preview": CONTENT_ENCRYPTED,  # L3层内容加密
                        "layer": row[1],
                        "domain": row[2],
                        "similarity": min(1.0, (score + row[5] / QUALITY_SCORE_MAX) / QUALITY_SCORE_DIVISOR),
                        "created_at": row[3],
                        "emotion_tags": [row[7]] if row[7] else [],
                        "quality_score": row[5],
                        "encrypted": True,
                    })

            results.sort(key=lambda x: x["quality_score"], reverse=True)
            return results[:top_k]
        except Exception as e:
            logger.error(f"L3 搜索失败: {e}")
            return []

    def items(self) -> List[MemoryItem]:
        """
        遍历所有记忆（用于巩固引擎）

        注意：会解密所有记忆，可能较慢。
        """
        result = []
        try:
            with get_connection(self._db_path) as conn:
                rows = conn.execute(
                    "SELECT memory_id, content_hash, file_name, encryption_salt FROM memories"
                ).fetchall()

            for row in rows:
                memory_id, content_hash, file_name, salt_hex = row
                file_path = self._get_file_path(file_name)
                if not os.path.exists(file_path):
                    continue
                try:
                    with open(file_path, "rb") as f:
                        encrypted_data = f.read()
                    item = self._decrypt_content(memory_id, encrypted_data, content_hash, salt_hex)
                    if item:
                        result.append(item)
                except Exception:
                    continue
        except Exception as e:
            logger.error(f"L3 遍历失败: {e}")

        return result

    def count(self) -> int:
        """获取记忆数量"""
        try:
            with get_connection(self._db_path) as conn:
                row = conn.execute("SELECT COUNT(*) FROM memories").fetchone()
            return row[0] if row else 0
        except Exception:
            return 0

    def get_stats(self) -> Dict:
        """获取统计信息"""
        try:
            with get_connection(self._db_path) as conn:
                total = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]

                # 按域统计
                by_domain = {}
                rows = conn.execute(
                    "SELECT domain, COUNT(*) FROM memories GROUP BY domain"
                ).fetchall()
                for domain, cnt in rows:
                    by_domain[domain] = cnt

            # 加密文件总大小
            total_size = 0
            if os.path.exists(self._vault_path):
                for fname in os.listdir(self._vault_path):
                    fpath = os.path.join(self._vault_path, fname)
                    if os.path.isfile(fpath):
                        total_size += os.path.getsize(fpath)

            return {
                "total_memories": total,
                "by_domain": by_domain,
                "encryption_backend": "AES-256-GCM" if self._use_cryptography else "simple_stream",
                "vault_size_bytes": total_size,
                "master_key_encrypted": self._password is not None,
                "storage_path": self._storage_path,
            }
        except Exception as e:
            return {"error": str(e)}
# vim: set et ts=4 sw=4:
