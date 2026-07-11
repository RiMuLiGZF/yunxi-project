"""L2 深水层 - 中期记忆（SQLite持久化）"""

from __future__ import annotations

import sqlite3
import json
import os
from datetime import datetime
from typing import Dict, List, Optional

from ..core.models import MemoryItem, MemoryLayer, MemoryDomain, ClassificationLevel, EmotionState


class DeepLayer:
    """
    L2 深水层 - 中期记忆
    - 大容量 (max_items=10000)
    - 保留时间：天~月
    - SQLite 持久化存储
    - 支持语义蒸馏和冗余合并
    """

    def __init__(self, config: dict = None):
        config = config or {}
        self.max_items = config.get("max_items", 10000)
        self.retention_days = config.get("retention_days", 30)
        self.access_priority = config.get("access_priority", 4)
        self._db_path = config.get("db_path", "./data/memory/l2_deep.db")
        self._ensure_db()

    def _ensure_db(self) -> None:
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.execute("""
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
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_domain ON memories(domain)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_created ON memories(created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_quality ON memories(quality_score)")
        conn.commit()
        conn.close()

    def add(self, item: MemoryItem) -> bool:
        item.layer = MemoryLayer.L2_DEEP
        conn = sqlite3.connect(self._db_path)
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
        conn.close()
        return True

    def get(self, memory_id: str) -> Optional[MemoryItem]:
        conn = sqlite3.connect(self._db_path)
        row = conn.execute(
            "SELECT * FROM memories WHERE memory_id = ?", (memory_id,)
        ).fetchone()
        conn.close()
        if row:
            item = self._row_to_item(row)
            # 更新访问计数
            self._touch(memory_id)
            return item
        return None

    def _touch(self, memory_id: str) -> None:
        """更新访问时间和计数"""
        conn = sqlite3.connect(self._db_path)
        conn.execute(
            "UPDATE memories SET access_count = access_count + 1, last_accessed_at = ? WHERE memory_id = ?",
            (datetime.now().isoformat(), memory_id)
        )
        conn.commit()
        conn.close()

    def search(self, query: str, domain: str = None, top_k: int = 10) -> List[Dict]:
        """关键词搜索（标签匹配+质量分排序）"""
        conn = sqlite3.connect(self._db_path)
        query_cond = ""
        params = []
        if domain:
            query_cond = "AND domain = ?"
            params.append(domain)
        rows = conn.execute(f"""
            SELECT memory_id, layer, domain, created_at, tags, quality_score,
                   emotion_ei, emotion_label
            FROM memories WHERE 1=1 {query_cond}
            ORDER BY quality_score DESC
            LIMIT ?
        """, params + [top_k * 10]).fetchall()  # 多取一些做标签匹配
        conn.close()

        results = []
        for row in rows:
            tags = json.loads(row[4]) if row[4] else []
            score = sum(1 for tag in tags if tag in query)
            if score > 0 or not query:
                results.append({
                    "memory_id": row[0],
                    "content_preview": "[SANITIZED]",
                    "layer": row[1],
                    "domain": row[2],
                    "similarity": min(1.0, (score + row[5] / 100) / 6),
                    "created_at": row[3],
                    "emotion_tags": [row[7]] if row[7] else [],
                    "quality_score": row[5],
                })
        results.sort(key=lambda x: x["quality_score"], reverse=True)
        return results[:top_k]

    def compress(self) -> Dict:
        """执行语义蒸馏（简化版：标记低质量记忆为可压缩）"""
        conn = sqlite3.connect(self._db_path)
        low_quality_rows = conn.execute(
            "SELECT memory_id FROM memories WHERE quality_score < 30"
        ).fetchall()
        compressed = len(low_quality_rows)
        for row in low_quality_rows:
            conn.execute(
                "UPDATE memories SET quality_level = 'compressed' WHERE memory_id = ?",
                (row[0],)
            )
        conn.commit()
        total = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        conn.close()
        return {
            "compressed_count": compressed,
            "remaining_count": total - compressed,
        }

    def count(self) -> int:
        conn = sqlite3.connect(self._db_path)
        row = conn.execute("SELECT COUNT(*) FROM memories").fetchone()
        conn.close()
        return row[0]

    def items(self) -> List[MemoryItem]:
        """返回所有记忆项（用于巩固引擎遍历）"""
        conn = sqlite3.connect(self._db_path)
        rows = conn.execute("SELECT * FROM memories").fetchall()
        conn.close()
        return [self._row_to_item(row) for row in rows]

    def remove(self, memory_id: str) -> bool:
        """删除指定记忆（巩固引擎迁移时需要从源层删除）"""
        conn = sqlite3.connect(self._db_path)
        cursor = conn.execute("DELETE FROM memories WHERE memory_id = ?", (memory_id,))
        conn.commit()
        conn.close()
        return cursor.rowcount > 0

    def _row_to_item(self, row) -> MemoryItem:
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
