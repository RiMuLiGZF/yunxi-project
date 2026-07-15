"""
记忆共享池管理器

基于 SQLite 的共享包持久化管理器，支持：
- 共享包的保存、获取、删除
- 分页浏览与关键词搜索
- 导入次数记录
- 评分与平均分计算
- 统计信息

线程安全：使用 threading.Lock 保护写操作。
单例模式：通过 get_instance() 获取全局实例。
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import structlog

logger = structlog.get_logger(__name__)


class SharePoolManager:
    """记忆共享池管理器"""

    _instance: Optional["SharePoolManager"] = None
    _lock = threading.Lock()

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_path = os.path.join(
                os.path.expanduser("~"), ".yunxi", "memory", "share_pool.db"
            )
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self._write_lock = threading.Lock()
        self._init_db()

    @classmethod
    def get_instance(cls) -> "SharePoolManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ============================================================
    # 数据库初始化
    # ============================================================

    def _init_db(self):
        """初始化数据库

        表：
        - share_packages: 共享包（items 以 JSON 存储）
        - share_ratings: 评分记录
        - import_logs: 导入日志
        """
        with self._write_lock:
            conn = self._get_conn()
            try:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS share_packages (
                        share_id        TEXT PRIMARY KEY,
                        title           TEXT NOT NULL,
                        description     TEXT DEFAULT '',
                        author          TEXT DEFAULT 'anonymous',
                        items_json      TEXT DEFAULT '[]',
                        tags_json       TEXT DEFAULT '[]',
                        domain          TEXT DEFAULT 'shared',
                        classification_level TEXT DEFAULT 'INTERNAL',
                        checksum        TEXT DEFAULT '',
                        item_count      INTEGER DEFAULT 0,
                        import_count    INTEGER DEFAULT 0,
                        rating_sum      REAL DEFAULT 0.0,
                        rating_count    INTEGER DEFAULT 0,
                        created_at      TEXT,
                        updated_at      TEXT
                    );

                    CREATE TABLE IF NOT EXISTS share_ratings (
                        id          INTEGER PRIMARY KEY AUTOINCREMENT,
                        share_id    TEXT NOT NULL,
                        user_id     TEXT NOT NULL,
                        rating      INTEGER NOT NULL,
                        comment     TEXT DEFAULT '',
                        created_at  TEXT,
                        UNIQUE(share_id, user_id)
                    );

                    CREATE TABLE IF NOT EXISTS import_logs (
                        id          INTEGER PRIMARY KEY AUTOINCREMENT,
                        share_id    TEXT NOT NULL,
                        importer    TEXT DEFAULT 'anonymous',
                        imported_count INTEGER DEFAULT 0,
                        failed_count   INTEGER DEFAULT 0,
                        created_at  TEXT
                    );

                    CREATE INDEX IF NOT EXISTS idx_packages_created
                        ON share_packages(created_at DESC);
                    CREATE INDEX IF NOT EXISTS idx_packages_imports
                        ON share_packages(import_count DESC);
                    CREATE INDEX IF NOT EXISTS idx_ratings_share
                        ON share_ratings(share_id);
                    CREATE INDEX IF NOT EXISTS idx_imports_share
                        ON import_logs(share_id);
                    """
                )
                conn.commit()
            finally:
                conn.close()
        logger.info("share_pool_db_initialized", db_path=self.db_path)

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # ============================================================
    # 共享包 CRUD
    # ============================================================

    def save_package(self, package: Dict[str, Any]) -> bool:
        """保存共享包到池中

        如果 share_id 已存在则更新。
        """
        share_id = package.get("share_id", "")
        if not share_id:
            logger.warning("save_package_missing_share_id")
            return False

        now_iso = datetime.utcnow().isoformat()
        items = package.get("items", [])
        tags = package.get("tags", [])
        created_at = package.get("created_at", now_iso)
        if isinstance(created_at, datetime):
            created_at = created_at.isoformat()

        with self._write_lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    """
                    INSERT INTO share_packages
                        (share_id, title, description, author, items_json,
                         tags_json, domain, classification_level, checksum,
                         item_count, import_count, rating_sum, rating_count,
                         created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(share_id) DO UPDATE SET
                        title = excluded.title,
                        description = excluded.description,
                        author = excluded.author,
                        items_json = excluded.items_json,
                        tags_json = excluded.tags_json,
                        domain = excluded.domain,
                        classification_level = excluded.classification_level,
                        checksum = excluded.checksum,
                        item_count = excluded.item_count,
                        updated_at = excluded.updated_at
                    """,
                    (
                        share_id,
                        package.get("title", ""),
                        package.get("description", ""),
                        package.get("author", "anonymous"),
                        json.dumps(items, ensure_ascii=False, default=str),
                        json.dumps(tags, ensure_ascii=False, default=str),
                        package.get("domain", "shared"),
                        package.get("classification_level", "INTERNAL"),
                        package.get("checksum", ""),
                        package.get("item_count", len(items)),
                        package.get("import_count", 0),
                        package.get("rating_avg", 0.0)
                        * package.get("rating_count", 0),  # rating_sum
                        package.get("rating_count", 0),
                        created_at,
                        now_iso,
                    ),
                )
                conn.commit()
                logger.info("share_package_saved", share_id=share_id)
                return True
            except Exception as e:
                logger.error("save_package_failed", share_id=share_id, error=str(e))
                conn.rollback()
                return False
            finally:
                conn.close()

    def get_package(self, share_id: str) -> Optional[Dict[str, Any]]:
        """获取共享包完整数据（含 items）"""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM share_packages WHERE share_id = ?",
                (share_id,),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_package(row, include_items=True)
        finally:
            conn.close()

    def list_packages(
        self,
        tag: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """浏览共享池

        Args:
            tag: 按标签过滤（可选）
            page: 页码，从 1 开始
            size: 每页数量

        Returns:
            (列表项列表, 总数) — 列表项不含 items 详情
        """
        page = max(1, page)
        size = max(1, min(size, 100))
        offset = (page - 1) * size

        conn = self._get_conn()
        try:
            if tag:
                # 按标签过滤（tags_json 中包含该标签）
                like_pattern = f'%"{tag}"%'
                rows = conn.execute(
                    """
                    SELECT * FROM share_packages
                    WHERE tags_json LIKE ?
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (like_pattern, size, offset),
                ).fetchall()
                total_row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM share_packages WHERE tags_json LIKE ?",
                    (like_pattern,),
                ).fetchone()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM share_packages
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (size, offset),
                ).fetchall()
                total_row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM share_packages"
                ).fetchone()

            total = total_row["cnt"] if total_row else 0
            listings = [self._row_to_listing(row) for row in rows]
            return listings, total
        finally:
            conn.close()

    def search(
        self,
        query: str,
        page: int = 1,
        size: int = 20,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """搜索共享包

        在 title、description、tags_json 中进行 LIKE 搜索。
        """
        page = max(1, page)
        size = max(1, min(size, 100))
        offset = (page - 1) * size
        like_pattern = f"%{query}%"

        conn = self._get_conn()
        try:
            rows = conn.execute(
                """
                SELECT * FROM share_packages
                WHERE title LIKE ? OR description LIKE ? OR tags_json LIKE ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (like_pattern, like_pattern, like_pattern, size, offset),
            ).fetchall()
            total_row = conn.execute(
                """
                SELECT COUNT(*) as cnt FROM share_packages
                WHERE title LIKE ? OR description LIKE ? OR tags_json LIKE ?
                """,
                (like_pattern, like_pattern, like_pattern),
            ).fetchone()
            total = total_row["cnt"] if total_row else 0
            listings = [self._row_to_listing(row) for row in rows]
            return listings, total
        finally:
            conn.close()

    def delete_package(self, share_id: str) -> bool:
        """删除共享包"""
        with self._write_lock:
            conn = self._get_conn()
            try:
                cursor = conn.execute(
                    "DELETE FROM share_packages WHERE share_id = ?",
                    (share_id,),
                )
                # 同时删除相关评分和导入日志
                conn.execute("DELETE FROM share_ratings WHERE share_id = ?", (share_id,))
                conn.execute("DELETE FROM import_logs WHERE share_id = ?", (share_id,))
                conn.commit()
                deleted = cursor.rowcount > 0
                if deleted:
                    logger.info("share_package_deleted", share_id=share_id)
                return deleted
            except Exception as e:
                logger.error("delete_package_failed", share_id=share_id, error=str(e))
                conn.rollback()
                return False
            finally:
                conn.close()

    # ============================================================
    # 导入记录
    # ============================================================

    def record_import(
        self,
        share_id: str,
        importer: str = "anonymous",
        imported_count: int = 0,
        failed_count: int = 0,
    ) -> bool:
        """记录一次导入"""
        now_iso = datetime.utcnow().isoformat()
        with self._write_lock:
            conn = self._get_conn()
            try:
                # 插入导入日志
                conn.execute(
                    """
                    INSERT INTO import_logs
                        (share_id, importer, imported_count, failed_count, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (share_id, importer, imported_count, failed_count, now_iso),
                )
                # 增加包的导入计数
                conn.execute(
                    """
                    UPDATE share_packages
                    SET import_count = import_count + 1, updated_at = ?
                    WHERE share_id = ?
                    """,
                    (now_iso, share_id),
                )
                conn.commit()
                return True
            except Exception as e:
                logger.error("record_import_failed", share_id=share_id, error=str(e))
                conn.rollback()
                return False
            finally:
                conn.close()

    # ============================================================
    # 评分
    # ============================================================

    def rate(
        self,
        share_id: str,
        user_id: str,
        rating: int,
        comment: str = "",
    ) -> bool:
        """评分

        每个用户对每个包只能评分一次（UNIQUE 约束），重复评分会更新。
        """
        if not (1 <= rating <= 5):
            logger.warning("rate_invalid_rating", rating=rating)
            return False

        now_iso = datetime.utcnow().isoformat()
        with self._write_lock:
            conn = self._get_conn()
            try:
                # 检查包是否存在
                row = conn.execute(
                    "SELECT rating_sum, rating_count FROM share_packages WHERE share_id = ?",
                    (share_id,),
                ).fetchone()
                if row is None:
                    logger.warning("rate_package_not_found", share_id=share_id)
                    return False

                old_sum = row["rating_sum"]
                old_count = row["rating_count"]

                # 检查是否已评分
                existing = conn.execute(
                    "SELECT rating FROM share_ratings WHERE share_id = ? AND user_id = ?",
                    (share_id, user_id),
                ).fetchone()

                if existing:
                    # 更新已有评分
                    old_rating = existing["rating"]
                    new_sum = old_sum - old_rating + rating
                    conn.execute(
                        """
                        UPDATE share_ratings
                        SET rating = ?, comment = ?, created_at = ?
                        WHERE share_id = ? AND user_id = ?
                        """,
                        (rating, comment, now_iso, share_id, user_id),
                    )
                else:
                    # 新增评分
                    new_sum = old_sum + rating
                    new_count = old_count + 1
                    conn.execute(
                        """
                        INSERT INTO share_ratings (share_id, user_id, rating, comment, created_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (share_id, user_id, rating, comment, now_iso),
                    )
                    # 更新包的评分统计
                    conn.execute(
                        """
                        UPDATE share_packages
                        SET rating_sum = ?, rating_count = ?, updated_at = ?
                        WHERE share_id = ?
                        """,
                        (new_sum, new_count, now_iso, share_id),
                    )

                # 如果是更新已有评分，上面没更新 count，这里补上 sum
                if existing:
                    conn.execute(
                        """
                        UPDATE share_packages
                        SET rating_sum = ?, updated_at = ?
                        WHERE share_id = ?
                        """,
                        (new_sum, now_iso, share_id),
                    )

                conn.commit()
                return True
            except Exception as e:
                logger.error("rate_failed", share_id=share_id, error=str(e))
                conn.rollback()
                return False
            finally:
                conn.close()

    # ============================================================
    # 统计
    # ============================================================

    def get_stats(self) -> Dict[str, Any]:
        """获取共享池统计"""
        conn = self._get_conn()
        try:
            # 总包数
            total_row = conn.execute(
                "SELECT COUNT(*) as cnt, COALESCE(SUM(item_count), 0) as items, "
                "COALESCE(SUM(import_count), 0) as imports FROM share_packages"
            ).fetchone()

            total_packages = total_row["cnt"] if total_row else 0
            total_items = total_row["items"] if total_row else 0
            total_imports = total_row["imports"] if total_row else 0

            # 平均评分
            rating_row = conn.execute(
                "SELECT COALESCE(SUM(rating_sum), 0) as sum_ratings, "
                "COALESCE(SUM(rating_count), 0) as count_ratings "
                "FROM share_packages"
            ).fetchone()
            sum_ratings = rating_row["sum_ratings"] if rating_row else 0
            count_ratings = rating_row["count_ratings"] if rating_row else 0
            avg_rating = (sum_ratings / count_ratings) if count_ratings > 0 else 0.0

            # 导入次数最多的包
            top_rows = conn.execute(
                """
                SELECT * FROM share_packages
                ORDER BY import_count DESC
                LIMIT 5
                """
            ).fetchall()
            top_imported = [self._row_to_listing(row) for row in top_rows]

            return {
                "total_packages": total_packages,
                "total_imports": total_imports,
                "total_items": total_items,
                "avg_rating": round(avg_rating, 2),
                "top_imported": top_imported,
            }
        finally:
            conn.close()

    # ============================================================
    # 内部转换辅助
    # ============================================================

    def _row_to_listing(self, row: sqlite3.Row) -> Dict[str, Any]:
        """将数据库行转换为列表项（不含 items 详情）"""
        rating_count = row["rating_count"]
        rating_sum = row["rating_sum"]
        rating_avg = (rating_sum / rating_count) if rating_count > 0 else 0.0
        return {
            "share_id": row["share_id"],
            "title": row["title"],
            "description": row["description"],
            "author": row["author"],
            "tags": json.loads(row["tags_json"]) if row["tags_json"] else [],
            "item_count": row["item_count"],
            "import_count": row["import_count"],
            "rating_avg": round(rating_avg, 2),
            "rating_count": rating_count,
            "created_at": row["created_at"],
        }

    def _row_to_package(
        self, row: sqlite3.Row, include_items: bool = False
    ) -> Dict[str, Any]:
        """将数据库行转换为完整包数据"""
        rating_count = row["rating_count"]
        rating_sum = row["rating_sum"]
        rating_avg = (rating_sum / rating_count) if rating_count > 0 else 0.0
        package: Dict[str, Any] = {
            "share_id": row["share_id"],
            "title": row["title"],
            "description": row["description"],
            "author": row["author"],
            "tags": json.loads(row["tags_json"]) if row["tags_json"] else [],
            "domain": row["domain"],
            "classification_level": row["classification_level"],
            "checksum": row["checksum"],
            "item_count": row["item_count"],
            "import_count": row["import_count"],
            "rating_avg": round(rating_avg, 2),
            "rating_count": rating_count,
            "created_at": row["created_at"],
        }
        if include_items:
            package["items"] = (
                json.loads(row["items_json"]) if row["items_json"] else []
            )
        return package

# vim: set et ts=4 sw=4:
