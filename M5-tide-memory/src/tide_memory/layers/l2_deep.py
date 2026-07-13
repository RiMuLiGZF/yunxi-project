"""L2 深水层 - 中期记忆（SQLite持久化）"""

from __future__ import annotations

import sqlite3
from typing import Dict, List, Tuple

from ..core.models import MemoryLayer
from ..common.constants import (
    L2_MAX_ITEMS,
    L2_RETENTION_DAYS,
    L2_ACCESS_PRIORITY,
    DEFAULT_L2_DB_PATH,
    QUALITY_SCORE_MAX,
    QUALITY_SCORE_DIVISOR,
    LOW_QUALITY_THRESHOLD,
    QUALITY_LEVEL_COMPRESSED,
    CONTENT_SANITIZED,
)
from .base import BaseSQLLayer


class DeepLayer(BaseSQLLayer):
    """
    L2 深水层 - 中期记忆
    - 大容量 (max_items=10000)
    - 保留时间：天~月
    - SQLite 持久化存储
    - 支持语义蒸馏和冗余合并
    """

    _layer_enum = MemoryLayer.L2_DEEP

    def __init__(self, config: dict = None):
        config = config or {}
        # L2 默认配置
        config.setdefault("max_items", L2_MAX_ITEMS)
        config.setdefault("retention_days", L2_RETENTION_DAYS)
        config.setdefault("access_priority", L2_ACCESS_PRIORITY)
        config.setdefault("db_path", DEFAULT_L2_DB_PATH)
        super().__init__(config)

    # ============================================================
    # 基类钩子覆盖
    # ============================================================

    def _get_extra_indexes(self) -> List[str]:
        """L2 额外的 quality_score 索引"""
        return [
            "CREATE INDEX IF NOT EXISTS idx_quality ON memories(quality_score)",
        ]

    def _get_search_columns(self) -> List[str]:
        """L2 搜索返回的列（比基类多一列 quality_score 用于结果排序）"""
        return [
            "memory_id", "layer", "domain", "created_at", "tags",
            "quality_score", "emotion_ei", "emotion_label",
        ]

    def _build_search_result(self, row: Tuple, tags: list, score: int) -> Dict:
        """L2 搜索结果额外包含 quality_score 字段"""
        return {
            "memory_id": row[0],
            "content_preview": CONTENT_SANITIZED,
            "layer": row[1],
            "domain": row[2],
            "similarity": min(1.0, (score + row[5] / QUALITY_SCORE_MAX) / QUALITY_SCORE_DIVISOR),
            "created_at": row[3],
            "emotion_tags": [row[7]] if row[7] else [],
            "quality_score": row[5],
        }

    def _sort_search_results(self, results: List[Dict]) -> List[Dict]:
        """L2 按 quality_score 降序排序"""
        results.sort(key=lambda x: x.get("quality_score", 0), reverse=True)
        return results

    # ============================================================
    # L2 独有方法
    # ============================================================

    def compress(self) -> Dict:
        """
        执行语义蒸馏（简化版：标记低质量记忆为可压缩）

        Returns:
            {"compressed_count": n, "remaining_count": m}
        """
        conn = sqlite3.connect(self._db_path)
        try:
            low_quality_rows = conn.execute(
                "SELECT memory_id FROM memories WHERE quality_score < ?",
                (LOW_QUALITY_THRESHOLD,),
            ).fetchall()
            compressed = len(low_quality_rows)
            for row in low_quality_rows:
                conn.execute(
                    "UPDATE memories SET quality_level = ? WHERE memory_id = ?",
                    (QUALITY_LEVEL_COMPRESSED, row[0]),
                )
            conn.commit()
            total = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        finally:
            conn.close()
        return {
            "compressed_count": compressed,
            "remaining_count": total - compressed,
        }
# vim: set et ts=4 sw=4:
