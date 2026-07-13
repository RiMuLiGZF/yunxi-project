"""
SQLite 记忆层基类

L1 浅水层和 L2 深水层的公共基类，抽取两者共有的 SQLite 操作逻辑。
表结构、增删改查、搜索、计数等通用方法均在此实现，
子类通过属性和钩子方法定制各自的行为。

P2-任务1: 可选原文加密存储
- 新增 original_encrypted 列，存储 AES-256-GCM 加密的原文
- 默认关闭，通过 store_original 配置开启
- 密钥与 L3 主密钥同源（从 encryption_key 配置派生）
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import structlog

from ..core.models import (
    ClassificationLevel,
    EmotionState,
    MemoryDomain,
    MemoryItem,
    MemoryLayer,
)
from ..db import DatabaseMigrator, Migration


class BaseSQLLayer:
    """
    SQLite 记忆层基类

    子类需要设置：
    - _layer_enum: MemoryLayer 枚举值，标识当前层级
    - _db_path: 数据库文件路径
    - max_items / retention_days / access_priority: 层配置参数

    子类可覆盖：
    - _get_extra_indexes(): 返回额外的索引 SQL 列表
    - _get_search_columns(): 返回搜索时 SELECT 的列名列表
    - _build_search_result(row, tags, score): 构建单条搜索结果
    - _sort_search_results(results): 对搜索结果排序
    """

    # 子类必须在 __init__ 中设置
    _layer_enum: MemoryLayer = None  # type: ignore
    _db_path: str = ""

    # 表结构 SQL（L1/L2 完全一致）
    _TABLE_SQL = """
        CREATE TABLE IF NOT EXISTS memories (
            memory_id TEXT PRIMARY KEY,
            content_hash TEXT,
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
            original_encrypted TEXT  -- P2-任务1: AES-256-GCM 加密的原文（可选）
        )
    """

    # 基础索引（所有层都有）
    _BASE_INDEXES = [
        "CREATE INDEX IF NOT EXISTS idx_domain ON memories(domain)",
        "CREATE INDEX IF NOT EXISTS idx_created ON memories(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_last_accessed ON memories(last_accessed_at)",
        "CREATE INDEX IF NOT EXISTS idx_quality ON memories(quality_score)",
    ]

    def __init__(self, config: dict = None):
        """
        初始化记忆层

        Args:
            config: 配置字典，支持 max_items / retention_days / access_priority / db_path
                    store_original / original_encryption / encryption_key
        """
        config = config or {}
        self.max_items = config.get("max_items", 1000)
        self.retention_days = config.get("retention_days", 1)
        self.access_priority = config.get("access_priority", 7)
        self._db_path = config.get("db_path", "./data/memory/layer.db")

        # P2-任务1: 原文存储配置
        self._store_original = config.get("store_original", False)
        self._original_encryption = config.get("original_encryption", True)
        self._encryption_key = config.get("encryption_key")

        # P2-任务3: 长连接 + 线程锁
        self._conn: Optional[sqlite3.Connection] = None
        self._conn_lock = threading.Lock()

        # 迁移系统开关（默认启用，可通过配置关闭以使用旧的自动检测模式）
        self._use_migration = config.get("use_migration", True)

        self._ensure_db()

    # ============================================================
    # 子类可覆盖的钩子方法
    # ============================================================

    def _get_extra_indexes(self) -> List[str]:
        """
        返回额外的索引 SQL 列表（子类可覆盖）

        例如 L2 层返回 quality_score 索引。
        """
        return []

    def _get_layer_migration_name(self) -> str:
        """
        返回当前层的迁移标识名（用于日志）

        子类可覆盖，默认返回类名。
        """
        return self.__class__.__name__

    # ============================================================
    # 迁移系统
    # ============================================================

    def _get_migrator(self) -> DatabaseMigrator:
        """
        获取当前层数据库的迁移器

        注册 L1/L2 层通用的迁移：
        - v1: 初始表结构 + 基础索引（不含 original_encrypted）
        - v2: 添加 original_encrypted 列（P2-任务1）

        Returns:
            DatabaseMigrator 实例
        """
        migrator = DatabaseMigrator(self._db_path)

        # v1: 初始 schema（不含 original_encrypted 列）
        migrator.register(
            version=1,
            name="initial_schema",
            up_sql=[
                """
        CREATE TABLE IF NOT EXISTS memories (
            memory_id TEXT PRIMARY KEY,
            content_hash TEXT,
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
            classification TEXT DEFAULT 'TOP_SECRET'
        )
                """,
            ] + self._BASE_INDEXES + self._get_extra_indexes(),
        )

        # v2: 添加 original_encrypted 列（P2-任务1）
        migrator.register(
            version=2,
            name="add_original_encrypted_column",
            up_sql=[
                "ALTER TABLE memories ADD COLUMN original_encrypted TEXT",
            ],
        )

        return migrator

    def _bootstrap_migration(self) -> bool:
        """
        引导迁移系统：检测现有数据库状态，初始化版本号

        当数据库已存在（通过旧方式创建）但迁移系统未初始化时，
        检测当前 schema 状态并设置对应的版本号。

        Returns:
            是否成功引导
        """
        log = structlog.get_logger(__name__)
        try:
            conn = sqlite3.connect(self._db_path)
            try:
                # 检查 memories 表是否存在
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name='memories'"
                )
                if not cursor.fetchone():
                    # 表不存在，无需引导，全新数据库
                    return False

                # 检测列，判断当前版本
                cursor = conn.execute("PRAGMA table_info(memories)")
                columns = [row[1] for row in cursor.fetchall()]

                # 确定版本：有 original_encrypted 则为 v2，否则为 v1
                if "original_encrypted" in columns:
                    detected_version = 2
                else:
                    detected_version = 1

                # 初始化版本表和日志表
                migrator = self._get_migrator()
                migrator._ensure_version_table(conn)
                migrator._ensure_migration_log_table(conn)

                # 设置版本号
                migrator._set_version(conn, detected_version)

                # 记录已应用的迁移日志（从 v1 到 detected_version）
                import time
                for v in range(1, detected_version + 1):
                    if v in migrator._migrations:
                        m = migrator._migrations[v]
                        migrator._log_migration(conn, v, m.name, 0.0)

                conn.commit()

                log.info(
                    "migration.bootstrapped",
                    layer=self._get_layer_migration_name(),
                    db_path=self._db_path,
                    detected_version=detected_version,
                )
                return True
            finally:
                conn.close()
        except Exception as e:
            log.warning(
                "migration.bootstrap_failed",
                layer=self._get_layer_migration_name(),
                error=str(e),
            )
            return False

    def _get_search_columns(self) -> List[str]:
        """
        返回搜索时 SELECT 的列名列表（子类可覆盖）

        列顺序需与 _build_search_result 中 row 索引对应。
        """
        return [
            "memory_id", "layer", "domain", "created_at", "tags",
            "quality_score", "emotion_ei", "emotion_label",
        ]

    def _build_search_result(self, row: Tuple, tags: List[str], score: int) -> Dict:
        """
        构建单条搜索结果字典（子类可覆盖）

        Args:
            row: 数据库行（列顺序与 _get_search_columns 一致）
            tags: 解析后的标签列表
            score: 标签匹配得分

        Returns:
            搜索结果字典
        """
        return {
            "memory_id": row[0],
            "content_preview": "[SANITIZED]",
            "layer": row[1],
            "domain": row[2],
            "similarity": min(1.0, (score + row[5] / 100) / 6),
            "created_at": row[3],
            "emotion_tags": [row[7]] if row[7] else [],
        }

    def _sort_search_results(self, results: List[Dict]) -> List[Dict]:
        """
        对搜索结果排序（子类可覆盖）

        默认按 similarity 降序。
        """
        results.sort(key=lambda x: x.get("similarity", 0), reverse=True)
        return results

    # ============================================================
    # 数据库初始化
    # ============================================================

    def _ensure_db(self) -> None:
        """初始化数据库表和索引

        P2-任务3: 启用 WAL 模式 + 长连接 + 性能优化 PRAGMA
        P2-任务1: 自动迁移添加 original_encrypted 列

        使用版本化迁移系统管理 schema：
        - 如果启用了迁移系统且数据库已初始化，使用 DatabaseMigrator
        - 如果迁移系统未初始化（旧数据库），先引导再迁移
        - 如果禁用迁移系统，回退到原有的自动检测模式（向后兼容）
        """
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)

        with self._conn_lock:
            # P2-任务3: 使用 check_same_thread=False + 锁的长连接模式
            self._conn = sqlite3.connect(
                self._db_path,
                check_same_thread=False,
                timeout=30.0,
            )

            # P2-任务3: WAL 模式 + 性能优化
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA synchronous=NORMAL;")
            self._conn.execute("PRAGMA cache_size=-20000;")  # 20MB 页缓存
            self._conn.execute("PRAGMA temp_store=MEMORY;")
            self._conn.execute("PRAGMA mmap_size=268435456;")  # 256MB 内存映射

            if self._use_migration:
                self._ensure_db_with_migration()
            else:
                # 向后兼容：使用旧的自动检测模式
                self._ensure_db_legacy()

    def _ensure_db_with_migration(self) -> None:
        """
        使用版本化迁移系统初始化数据库

        1. 如果迁移系统未初始化，先引导（检测现有 schema 状态）
        2. 执行迁移到最新版本
        """
        log = structlog.get_logger(__name__)
        migrator = self._get_migrator()

        # 检查迁移系统是否已初始化
        if not migrator.is_initialized():
            # 尝试引导（从旧数据库状态迁移到版本化管理）
            bootstrapped = self._bootstrap_migration()
            if not bootstrapped:
                log.debug(
                    "migration.new_database",
                    layer=self._get_layer_migration_name(),
                    db_path=self._db_path,
                )

        # 执行迁移到最新版本
        try:
            result = migrator.migrate()
            if result["status"] == "success" and result["applied"]:
                log.info(
                    "migration.layer_applied",
                    layer=self._get_layer_migration_name(),
                    from_version=result["from_version"],
                    to_version=result["to_version"],
                    applied_count=len(result["applied"]),
                )
        except Exception as e:
            log.error(
                "migration.layer_failed",
                layer=self._get_layer_migration_name(),
                error=str(e),
            )
            # 迁移失败时回退到旧模式，保证可用性
            self._ensure_db_legacy()

    def _ensure_db_legacy(self) -> None:
        """
        旧模式：直接创建表和索引（向后兼容）

        当迁移系统禁用或失败时使用。
        """
        # 创建表
        self._conn.execute(self._TABLE_SQL)

        # P2-任务1: 迁移 - 如果没有 original_encrypted 列则添加
        self._migrate_add_column("original_encrypted", "TEXT")

        # 创建基础索引
        for idx_sql in self._BASE_INDEXES:
            self._conn.execute(idx_sql)
        # 创建子类额外索引
        for idx_sql in self._get_extra_indexes():
            self._conn.execute(idx_sql)
        self._conn.commit()

    def _migrate_add_column(self, column_name: str, column_type: str) -> None:
        """
        安全地添加列（如果列不存在）

        Args:
            column_name: 列名
            column_type: 列类型
        """
        try:
            cursor = self._conn.execute("PRAGMA table_info(memories)")
            columns = [row[1] for row in cursor.fetchall()]
            if column_name not in columns:
                self._conn.execute(
                    f"ALTER TABLE memories ADD COLUMN {column_name} {column_type}"
                )
                logger = structlog.get_logger(__name__)
                logger.info("迁移: 添加列", column_name=column_name, column_type=column_type)
        except Exception as e:
            logger = structlog.get_logger(__name__)
            logger.warning("迁移列失败", column_name=column_name, error_type=type(e).__name__, exc_info=True)

    # ============================================================
    # 连接管理（P2-任务3: 长连接模式）
    # ============================================================

    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接（长连接，线程安全）"""
        if self._conn is None:
            with self._conn_lock:
                if self._conn is None:
                    self._ensure_db()
        return self._conn

    def close(self) -> None:
        """关闭数据库连接"""
        with self._conn_lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None

    def __del__(self):
        """析构时关闭连接"""
        try:
            self.close()
        except Exception:
            pass

    # ============================================================
    # P2-任务1: 原文加密存储辅助方法
    # ============================================================

    def _get_original_encryption_key(self) -> bytes:
        """
        获取原文加密密钥

        优先使用配置的 encryption_key，否则从 L3 主密钥派生。
        降级方案：使用 content_hash 派生的简单密钥。

        Returns:
            32 字节密钥
        """
        import hashlib
        if self._encryption_key:
            # 从配置的密钥字符串派生 32 字节密钥
            if isinstance(self._encryption_key, str):
                return hashlib.sha256(self._encryption_key.encode("utf-8")).digest()
            return self._encryption_key[:32].ljust(32, b"\x00")
        # 没有配置密钥时，使用派生密钥（基于 db_path，保证同库一致）
        base = f"tide_memory_original_{self._db_path}"
        return hashlib.sha256(base.encode("utf-8")).digest()

    def _encrypt_original(self, content: str, memory_id: str = "") -> str:
        """
        加密原文内容

        Args:
            content: 原文内容
            memory_id: 记忆ID（作为关联认证数据）

        Returns:
            Base64 编码的密文，加密失败返回空字符串
        """
        if not content:
            return ""
        try:
            from ..utils.crypto import CryptoUtils
            key = self._get_original_encryption_key()
            return CryptoUtils.encrypt(content, key, memory_id)
        except Exception:
            # 加密失败则不存储原文
            return ""

    def _decrypt_original(self, encrypted: str, memory_id: str = "") -> Optional[str]:
        """
        解密原文内容

        Args:
            encrypted: Base64 编码的密文
            memory_id: 记忆ID（作为关联认证数据）

        Returns:
            原文内容，解密失败返回 None
        """
        if not encrypted:
            return None
        try:
            from ..utils.crypto import CryptoUtils
            key = self._get_original_encryption_key()
            return CryptoUtils.decrypt(encrypted, key, memory_id)
        except Exception:
            return None

    # ============================================================
    # 基础 CRUD
    # ============================================================

    def add(self, item: MemoryItem) -> bool:
        """
        添加/更新记忆

        自动设置 item.layer 为当前层的枚举值。
        P2-任务1: 如果 store_original=True 且 item.original_content 有值，加密后存入 original_encrypted 列。

        Args:
            item: 记忆项

        Returns:
            是否成功
        """
        item.layer = self._layer_enum

        # P2-任务1: 处理原文加密存储
        original_encrypted = ""
        if self._store_original and item.original_content:
            if self._original_encryption:
                original_encrypted = self._encrypt_original(
                    item.original_content, item.memory_id
                )
            else:
                original_encrypted = item.original_content

        with self._conn_lock:
            conn = self._get_conn()
            try:
                conn.execute("""
                    INSERT OR REPLACE INTO memories
                    (memory_id, content_hash, layer, domain, owner_agent, created_at, updated_at,
                     last_accessed_at, access_count, quality_score, quality_level, retention_days,
                     tags, metadata, sync_version, emotion_valence, emotion_arousal,
                     emotion_ei, emotion_label, classification, original_encrypted)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    item.memory_id, item.content_hash, item.layer.value, item.domain.value,
                    item.owner_agent, item.created_at.isoformat(), item.updated_at.isoformat(),
                    item.last_accessed_at.isoformat() if item.last_accessed_at else None,
                    item.access_count, item.quality_score, item.quality_level,
                    item.retention_days, json.dumps(item.tags, ensure_ascii=False),
                    json.dumps(item.metadata, ensure_ascii=False), item.sync_version,
                    item.emotion.valence, item.emotion.arousal,
                    item.emotion.ei_score, item.emotion.dominant_emotion,
                    item.classification.value,
                    original_encrypted,
                ))
                conn.commit()
                return True
            except Exception:
                conn.rollback()
                return False

    def get(self, memory_id: str) -> Optional[MemoryItem]:
        """
        获取单条记忆，并自动更新访问计数

        P2-任务1: 如果存储了原文，解密后填充到 item.original_content

        Args:
            memory_id: 记忆ID

        Returns:
            记忆项，不存在返回 None
        """
        with self._conn_lock:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT * FROM memories WHERE memory_id = ?", (memory_id,)
            ).fetchone()

        if row:
            item = self._row_to_item(row)
            self._touch(memory_id)
            return item
        return None

    def _touch(self, memory_id: str) -> None:
        """
        更新访问时间和计数

        Args:
            memory_id: 记忆ID
        """
        with self._conn_lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    "UPDATE memories SET access_count = access_count + 1, last_accessed_at = ? WHERE memory_id = ?",
                    (datetime.now().isoformat(), memory_id)
                )
                conn.commit()
            except Exception:
                conn.rollback()

    def count(self) -> int:
        """
        返回记忆总数

        Returns:
            记忆条数
        """
        with self._conn_lock:
            conn = self._get_conn()
            row = conn.execute("SELECT COUNT(*) FROM memories").fetchone()
            return row[0]

    def items(self) -> List[MemoryItem]:
        """
        返回所有记忆项（用于巩固引擎遍历）

        Returns:
            全部记忆项列表
        """
        with self._conn_lock:
            conn = self._get_conn()
            rows = conn.execute("SELECT * FROM memories").fetchall()
            return [self._row_to_item(row) for row in rows]

    def remove(self, memory_id: str) -> bool:
        """
        删除指定记忆

        Args:
            memory_id: 记忆ID

        Returns:
            是否删除了记录
        """
        with self._conn_lock:
            conn = self._get_conn()
            try:
                cursor = conn.execute("DELETE FROM memories WHERE memory_id = ?", (memory_id,))
                conn.commit()
                return cursor.rowcount > 0
            except Exception:
                conn.rollback()
                return False

    # ============================================================
    # 搜索
    # ============================================================

    def search(self, query: str, domain: str = None, top_k: int = 10) -> List[Dict]:
        """
        关键词搜索（基础版，基于标签匹配 + 质量分排序）

        Args:
            query: 查询关键词
            domain: 按域过滤（可选）
            top_k: 返回数量

        Returns:
            搜索结果列表，按相似度降序
        """
        with self._conn_lock:
            conn = self._get_conn()
            query_cond = ""
            params = []
            if domain:
                query_cond = "AND domain = ?"
                params.append(domain)

            columns = ", ".join(self._get_search_columns())
            rows = conn.execute(f"""
                SELECT {columns}
                FROM memories WHERE 1=1 {query_cond}
                ORDER BY quality_score DESC
                LIMIT ?
            """, params + [top_k * 10]).fetchall()  # 多取一些做标签匹配

        results = []
        for row in rows:
            # 找到 tags 列的索引
            tags_idx = self._get_search_columns().index("tags")
            tags = json.loads(row[tags_idx]) if row[tags_idx] else []
            score = sum(1 for tag in tags if tag in query)
            if score > 0 or not query:
                result = self._build_search_result(row, tags, score)
                results.append(result)

        results = self._sort_search_results(results)
        return results[:top_k]

    # ============================================================
    # 批量操作
    # ============================================================

    def batch_add(self, items: List[MemoryItem]) -> Dict:
        """
        批量添加记忆

        Args:
            items: 记忆项列表

        Returns:
            {"success_count": n, "failed": [memory_ids]}
        """
        success_count = 0
        failed = []
        with self._conn_lock:
            conn = self._get_conn()
            try:
                for item in items:
                    try:
                        item.layer = self._layer_enum

                        # P2-任务1: 处理原文加密存储
                        original_encrypted = ""
                        if self._store_original and item.original_content:
                            if self._original_encryption:
                                original_encrypted = self._encrypt_original(
                                    item.original_content, item.memory_id
                                )
                            else:
                                original_encrypted = item.original_content

                        conn.execute("""
                            INSERT OR REPLACE INTO memories
                            (memory_id, content_hash, layer, domain, owner_agent, created_at, updated_at,
                             last_accessed_at, access_count, quality_score, quality_level, retention_days,
                             tags, metadata, sync_version, emotion_valence, emotion_arousal,
                             emotion_ei, emotion_label, classification, original_encrypted)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            item.memory_id, item.content_hash, item.layer.value, item.domain.value,
                            item.owner_agent, item.created_at.isoformat(), item.updated_at.isoformat(),
                            item.last_accessed_at.isoformat() if item.last_accessed_at else None,
                            item.access_count, item.quality_score, item.quality_level,
                            item.retention_days, json.dumps(item.tags, ensure_ascii=False),
                            json.dumps(item.metadata, ensure_ascii=False), item.sync_version,
                            item.emotion.valence, item.emotion.arousal,
                            item.emotion.ei_score, item.emotion.dominant_emotion,
                            item.classification.value,
                            original_encrypted,
                        ))
                        success_count += 1
                    except Exception:
                        failed.append(item.memory_id)
                conn.commit()
            except Exception:
                conn.rollback()
        return {"success_count": success_count, "failed": failed}

    def batch_remove(self, memory_ids: List[str]) -> int:
        """
        批量删除记忆

        Args:
            memory_ids: 记忆ID列表

        Returns:
            实际删除的数量
        """
        if not memory_ids:
            return 0
        with self._conn_lock:
            conn = self._get_conn()
            try:
                placeholders = ",".join(["?"] * len(memory_ids))
                cursor = conn.execute(
                    f"DELETE FROM memories WHERE memory_id IN ({placeholders})",
                    tuple(memory_ids)
                )
                conn.commit()
                return cursor.rowcount
            except Exception:
                conn.rollback()
                return 0

    # ============================================================
    # 分页查询
    # ============================================================

    def list_items(
        self,
        page_size: int = 20,
        cursor: Optional[str] = None,
        domain: Optional[str] = None,
        sort_by: str = "created_at",
        order: str = "desc",
    ) -> Dict:
        """
        游标分页查询记忆列表

        Args:
            page_size: 每页数量，默认 20
            cursor: 游标值（下一页的起点），None 表示第一页
            domain: 按域过滤（可选）
            sort_by: 排序字段：created_at / quality_score / access_count
            order: 排序方向：desc / asc

        Returns:
            {"items": [...], "next_cursor": "...", "has_more": true/false, "total": n}
        """
        # 校验排序字段
        allowed_sort = {"created_at", "quality_score", "access_count"}
        if sort_by not in allowed_sort:
            sort_by = "created_at"
        if order not in ("desc", "asc"):
            order = "desc"

        with self._conn_lock:
            conn = self._get_conn()
            # 先算总数
            count_sql = "SELECT COUNT(*) FROM memories WHERE 1=1"
            count_params: List = []
            if domain:
                count_sql += " AND domain = ?"
                count_params.append(domain)
            total = conn.execute(count_sql, count_params).fetchone()[0]

            # 构建查询 SQL
            where_clauses = []
            params: List = []
            if domain:
                where_clauses.append("domain = ?")
                params.append(domain)

            # 游标条件
            if cursor:
                op = "<" if order == "desc" else ">"
                where_clauses.append(f"{sort_by} {op} ?")
                params.append(cursor)

            where_sql = ""
            if where_clauses:
                where_sql = "WHERE " + " AND ".join(where_clauses)

            # 多取一条判断是否有下一页
            fetch_size = page_size + 1
            sql = f"""
                SELECT * FROM memories
                {where_sql}
                ORDER BY {sort_by} {order.upper()}
                LIMIT ?
            """
            rows = conn.execute(sql, params + [fetch_size]).fetchall()

        items = [self._row_to_item(row) for row in rows[:page_size]]
        has_more = len(rows) > page_size
        next_cursor = None

        if has_more and items:
            # 游标值 = 最后一条记录的排序字段值
            col_index_map = {
                "created_at": 5,    # created_at 在 SELECT * 中的索引
                "quality_score": 9,
                "access_count": 8,
            }
            idx = col_index_map.get(sort_by, 5)
            next_cursor = str(rows[page_size - 1][idx])

        return {
            "items": items,
            "next_cursor": next_cursor,
            "has_more": has_more,
            "total": total,
        }

    # ============================================================
    # 行转 MemoryItem
    # ============================================================

    def _row_to_item(self, row) -> MemoryItem:
        """
        将数据库行转换为 MemoryItem 对象

        列顺序与 _TABLE_SQL 定义一致：
        0:memory_id, 1:content_hash, 2:layer, 3:domain, 4:owner_agent,
        5:created_at, 6:updated_at, 7:last_accessed_at, 8:access_count,
        9:quality_score, 10:quality_level, 11:retention_days,
        12:tags, 13:metadata, 14:sync_version,
        15:emotion_valence, 16:emotion_arousal, 17:emotion_ei, 18:emotion_label,
        19:classification,
        20:original_encrypted (P2-任务1新增)
        """
        item = MemoryItem(
            memory_id=row[0],
            content_hash=row[1],
            layer=MemoryLayer(row[2]),
            domain=MemoryDomain(row[3]),
            owner_agent=row[4],
            created_at=datetime.fromisoformat(row[5]),
            updated_at=datetime.fromisoformat(row[6]),
            last_accessed_at=datetime.fromisoformat(row[7]) if row[7] else None,
            access_count=row[8],
            quality_score=row[9],
            quality_level=row[10],
            retention_days=row[11],
            tags=json.loads(row[12]) if row[12] else [],
            metadata=json.loads(row[13]) if row[13] else {},
            sync_version=row[14],
            emotion=EmotionState(
                valence=row[15],
                arousal=row[16],
                ei_score=row[17],
                dominant_emotion=row[18],
            ),
            classification=ClassificationLevel(row[19]),
        )

        # P2-任务1: 如果有加密原文，解密后填充
        if len(row) > 20 and row[20]:
            if self._original_encryption:
                decrypted = self._decrypt_original(row[20], row[0])
                if decrypted is not None:
                    item.original_content = decrypted
            else:
                item.original_content = row[20]

        return item
# vim: set et ts=4 sw=4:
