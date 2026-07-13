from __future__ import annotations

"""Cache Repository - L2 磁盘缓存 Repository（SQLite 实现）.

使用 SQLite 替代原来的文件系统存储作为 L2 缓存后端，优势：
- 按标签批量失效（无需扫描所有文件）
- 更快的统计查询
- 支持更复杂的查询模式
- 更好的并发安全性

skill_cache.py 中的 L2DiskCache 保留（向后兼容），
同时提供 SQLiteL2Cache 作为高性能替代方案。
"""

import json
import os
import time
from typing import Any

import structlog

from skill_cluster.db.base import BaseRepository, SQLiteDatabase

logger = structlog.get_logger()


class CacheRepository(BaseRepository):
    """缓存 Repository - 基于 SQLite 的 L2 磁盘缓存.

    表结构：
    - cache_entries: 缓存条目主表
    - cache_tags: 标签关联表（用于快速按标签失效）

    Args:
        db: SQLiteDatabase 实例
    """

    table_name = "cache_entries"
    primary_key = "cache_key"

    def _create_tables(self) -> None:
        """创建缓存表与标签表."""
        # 主表
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS cache_entries (
                cache_key TEXT PRIMARY KEY,
                value_json TEXT,
                created_at REAL,
                ttl REAL,
                cache_scope TEXT DEFAULT 'public'
            )
            """
        )
        # 标签关联表
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS cache_tags (
                cache_key TEXT,
                tag TEXT,
                PRIMARY KEY (cache_key, tag),
                FOREIGN KEY (cache_key) REFERENCES cache_entries(cache_key) ON DELETE CASCADE
            )
            """
        )

    def _create_indexes(self) -> None:
        """创建索引."""
        self._ensure_index("created_at")
        self._ensure_index("cache_scope")
        # 标签表索引
        self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_cache_tags_tag ON cache_tags(tag)"
        )
        self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_cache_tags_key ON cache_tags(cache_key)"
        )

    # ------------------------------------------------------------------
    # 写入操作
    # ------------------------------------------------------------------

    def set(
        self,
        key: str,
        value: Any,
        ttl: float | None = None,
        tags: set[str] | None = None,
        cache_scope: str = "public",
    ) -> None:
        """设置缓存条目.

        Args:
            key: 缓存键
            value: 缓存值（需可 JSON 序列化）
            ttl: 过期时间（秒），None 表示永不过期
            tags: 标签集合
            cache_scope: 缓存作用域（public/private）
        """
        value_json = json.dumps(value, ensure_ascii=False)
        now = time.time()

        with self._db.transaction() as conn:
            # 插入或替换主条目
            conn.execute(
                """
                INSERT OR REPLACE INTO cache_entries
                (cache_key, value_json, created_at, ttl, cache_scope)
                VALUES (?, ?, ?, ?, ?)
                """,
                (key, value_json, now, ttl, cache_scope),
            )
            # 删除旧标签
            conn.execute("DELETE FROM cache_tags WHERE cache_key = ?", (key,))
            # 插入新标签
            if tags:
                conn.executemany(
                    "INSERT INTO cache_tags (cache_key, tag) VALUES (?, ?)",
                    [(key, tag) for tag in tags],
                )

    # ------------------------------------------------------------------
    # 读取操作
    # ------------------------------------------------------------------

    def get(self, key: str) -> Any | None:
        """获取缓存值（自动检查过期）.

        Args:
            key: 缓存键

        Returns:
            缓存值或 None（未命中或已过期）
        """
        row = self._db.fetchone(
            "SELECT value_json, created_at, ttl FROM cache_entries WHERE cache_key = ?",
            (key,),
        )
        if row is None:
            return None

        # 检查 TTL
        ttl = row["ttl"]
        if ttl is not None:
            now = time.time()
            if now - row["created_at"] > ttl:
                # 已过期，删除并返回 None
                self._db.execute(
                    "DELETE FROM cache_entries WHERE cache_key = ?", (key,)
                )
                return None

        try:
            return json.loads(row["value_json"])
        except (json.JSONDecodeError, TypeError):
            logger.warning("cache_value_corrupted", key=key)
            self._db.execute(
                "DELETE FROM cache_entries WHERE cache_key = ?", (key,)
            )
            return None

    def get_tags(self, key: str) -> set[str]:
        """获取缓存条目的所有标签.

        Args:
            key: 缓存键

        Returns:
            标签集合
        """
        rows = self._db.fetchall(
            "SELECT tag FROM cache_tags WHERE cache_key = ?",
            (key,),
        )
        return {row["tag"] for row in rows}

    # ------------------------------------------------------------------
    # 删除操作
    # ------------------------------------------------------------------

    def delete(self, key: str) -> bool:
        """删除缓存条目.

        Args:
            key: 缓存键

        Returns:
            True 表示成功删除
        """
        # 先检查是否存在
        row = self._db.fetchone(
            "SELECT 1 FROM cache_entries WHERE cache_key = ?", (key,)
        )
        if row is None:
            return False

        with self._db.transaction() as conn:
            conn.execute("DELETE FROM cache_tags WHERE cache_key = ?", (key,))
            conn.execute("DELETE FROM cache_entries WHERE cache_key = ?", (key,))
        return True

    def invalidate_by_tag(self, tag: str) -> int:
        """按标签批量失效缓存.

        比文件系统实现高效得多：一条 SQL 即可完成。

        Args:
            tag: 标签

        Returns:
            失效的缓存条目数
        """
        with self._db.transaction() as conn:
            # 找出匹配的 key
            rows = conn.execute(
                "SELECT DISTINCT cache_key FROM cache_tags WHERE tag = ?",
                (tag,),
            ).fetchall()
            keys = [r["cache_key"] for r in rows]
            if not keys:
                return 0

            # 删除标签和条目
            placeholders = ",".join("?" * len(keys))
            conn.execute(
                f"DELETE FROM cache_tags WHERE cache_key IN ({placeholders})",
                keys,
            )
            conn.execute(
                f"DELETE FROM cache_entries WHERE cache_key IN ({placeholders})",
                keys,
            )
        return len(keys)

    def clear(self) -> None:
        """清空所有缓存."""
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM cache_tags")
            conn.execute("DELETE FROM cache_entries")

    def cleanup_expired(self) -> int:
        """清理所有过期的缓存条目.

        Returns:
            清理的条目数
        """
        now = time.time()
        # 找出过期的 key（有 TTL 且已过期）
        rows = self._db.fetchall(
            """
            SELECT cache_key FROM cache_entries
            WHERE ttl IS NOT NULL AND (created_at + ttl) < ?
            """,
            (now,),
        )
        if not rows:
            return 0

        keys = [r["cache_key"] for r in rows]
        placeholders = ",".join("?" * len(keys))

        with self._db.transaction() as conn:
            conn.execute(
                f"DELETE FROM cache_tags WHERE cache_key IN ({placeholders})",
                keys,
            )
            conn.execute(
                f"DELETE FROM cache_entries WHERE cache_key IN ({placeholders})",
                keys,
            )
        return len(keys)

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        """获取缓存统计信息.

        Returns:
            统计信息字典
        """
        total_row = self._db.fetchone("SELECT COUNT(*) as cnt FROM cache_entries")
        total = total_row["cnt"] if total_row else 0

        scope_rows = self._db.fetchall(
            "SELECT cache_scope, COUNT(*) as cnt FROM cache_entries GROUP BY cache_scope"
        )
        scope_counts = {r["cache_scope"]: r["cnt"] for r in scope_rows}

        # 过期数量
        now = time.time()
        expired_row = self._db.fetchone(
            """
            SELECT COUNT(*) as cnt FROM cache_entries
            WHERE ttl IS NOT NULL AND (created_at + ttl) < ?
            """,
            (now,),
        )
        expired = expired_row["cnt"] if expired_row else 0

        # 总大小（估算：value_json 长度之和）
        size_row = self._db.fetchone(
            "SELECT COALESCE(SUM(LENGTH(value_json)), 0) as total FROM cache_entries"
        )
        total_bytes = size_row["total"] if size_row else 0

        return {
            "size": total,
            "expired": expired,
            "total_bytes": total_bytes,
            "scope_distribution": scope_counts,
            "backend": "sqlite",
        }


def get_cache_repository(db_path: str | None = None) -> CacheRepository:
    """便捷函数：创建 CacheRepository 实例.

    Args:
        db_path: 数据库文件路径，默认 ~/.yunxi/cache/skill_cache.db

    Returns:
        CacheRepository 实例
    """
    path = db_path or os.path.expanduser("~/.yunxi/cache/skill_cache.db")
    db = SQLiteDatabase(path)
    return CacheRepository(db)
