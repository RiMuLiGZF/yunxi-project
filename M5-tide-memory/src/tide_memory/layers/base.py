"""
SQLite 记忆层基类

L1 浅水层和 L2 深水层的公共基类，抽取两者共有的 SQLite 操作逻辑。
表结构、增删改查、搜索、计数等通用方法均在此实现，
子类通过属性和钩子方法定制各自的行为。
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from ..core.models import (
    ClassificationLevel,
    EmotionState,
    MemoryDomain,
    MemoryItem,
    MemoryLayer,
)


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
            classification TEXT DEFAULT 'TOP_SECRET'
        )
    """

    # 基础索引（所有层都有）
    _BASE_INDEXES = [
        "CREATE INDEX IF NOT EXISTS idx_domain ON memories(domain)",
        "CREATE INDEX IF NOT EXISTS idx_created ON memories(created_at)",
    ]

    def __init__(self, config: dict = None):
        """
        初始化记忆层

        Args:
            config: 配置字典，支持 max_items / retention_days / access_priority / db_path
        """
        config = config or {}
        self.max_items = config.get("max_items", 1000)
        self.retention_days = config.get("retention_days", 1)
        self.access_priority = config.get("access_priority", 7)
        self._db_path = config.get("db_path", "./data/memory/layer.db")
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
        """初始化数据库表和索引"""
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute(self._TABLE_SQL)
            # 创建基础索引
            for idx_sql in self._BASE_INDEXES:
                conn.execute(idx_sql)
            # 创建子类额外索引
            for idx_sql in self._get_extra_indexes():
                conn.execute(idx_sql)
            conn.commit()
        finally:
            conn.close()

    # ============================================================
    # 基础 CRUD
    # ============================================================

    def add(self, item: MemoryItem) -> bool:
        """
        添加/更新记忆

        自动设置 item.layer 为当前层的枚举值。

        Args:
            item: 记忆项

        Returns:
            是否成功
        """
        item.layer = self._layer_enum
        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute("""
                INSERT OR REPLACE INTO memories
                (memory_id, content_hash, layer, domain, owner_agent, created_at, updated_at,
                 last_accessed_at, access_count, quality_score, quality_level, retention_days,
                 tags, metadata, sync_version, emotion_valence, emotion_arousal,
                 emotion_ei, emotion_label, classification)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            ))
            conn.commit()
            return True
        finally:
            conn.close()

    def get(self, memory_id: str) -> Optional[MemoryItem]:
        """
        获取单条记忆，并自动更新访问计数

        Args:
            memory_id: 记忆ID

        Returns:
            记忆项，不存在返回 None
        """
        conn = sqlite3.connect(self._db_path)
        try:
            row = conn.execute(
                "SELECT * FROM memories WHERE memory_id = ?", (memory_id,)
            ).fetchone()
        finally:
            conn.close()

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
        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute(
                "UPDATE memories SET access_count = access_count + 1, last_accessed_at = ? WHERE memory_id = ?",
                (datetime.now().isoformat(), memory_id)
            )
            conn.commit()
        finally:
            conn.close()

    def count(self) -> int:
        """
        返回记忆总数

        Returns:
            记忆条数
        """
        conn = sqlite3.connect(self._db_path)
        try:
            row = conn.execute("SELECT COUNT(*) FROM memories").fetchone()
            return row[0]
        finally:
            conn.close()

    def items(self) -> List[MemoryItem]:
        """
        返回所有记忆项（用于巩固引擎遍历）

        Returns:
            全部记忆项列表
        """
        conn = sqlite3.connect(self._db_path)
        try:
            rows = conn.execute("SELECT * FROM memories").fetchall()
            return [self._row_to_item(row) for row in rows]
        finally:
            conn.close()

    def remove(self, memory_id: str) -> bool:
        """
        删除指定记忆

        Args:
            memory_id: 记忆ID

        Returns:
            是否删除了记录
        """
        conn = sqlite3.connect(self._db_path)
        try:
            cursor = conn.execute("DELETE FROM memories WHERE memory_id = ?", (memory_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

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
        conn = sqlite3.connect(self._db_path)
        try:
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
        finally:
            conn.close()

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
        conn = sqlite3.connect(self._db_path)
        try:
            for item in items:
                try:
                    item.layer = self._layer_enum
                    conn.execute("""
                        INSERT OR REPLACE INTO memories
                        (memory_id, content_hash, layer, domain, owner_agent, created_at, updated_at,
                         last_accessed_at, access_count, quality_score, quality_level, retention_days,
                         tags, metadata, sync_version, emotion_valence, emotion_arousal,
                         emotion_ei, emotion_label, classification)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    ))
                    success_count += 1
                except Exception:
                    failed.append(item.memory_id)
            conn.commit()
        finally:
            conn.close()
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
        conn = sqlite3.connect(self._db_path)
        try:
            placeholders = ",".join(["?"] * len(memory_ids))
            cursor = conn.execute(
                f"DELETE FROM memories WHERE memory_id IN ({placeholders})",
                tuple(memory_ids)
            )
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()

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

        conn = sqlite3.connect(self._db_path)
        try:
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
        finally:
            conn.close()

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
        19:classification
        """
        return MemoryItem(
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
# vim: set et ts=4 sw=4:
