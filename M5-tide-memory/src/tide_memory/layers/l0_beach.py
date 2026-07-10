"""L0 沙滩层 - 瞬时/短期记忆"""

from __future__ import annotations

from collections import OrderedDict
from typing import Dict, List, Optional

from ..core.models import MemoryItem, MemoryLayer


class BeachLayer:
    """
    L0 沙滩层 - 瞬时记忆
    - 容量小，速度最快
    - 保留时间最短（分钟~小时级）
    - 内存存储
    """

    def __init__(self, config: dict = None):
        config = config or {}
        self.max_items = config.get("max_items", 100)
        self.retention_hours = config.get("retention_hours", 1)
        self.access_priority = config.get("access_priority", 10)
        self._items: "OrderedDict[str, MemoryItem]" = OrderedDict()

    def add(self, item: MemoryItem) -> bool:
        """添加记忆，超出容量时淘汰最旧的"""
        item.layer = MemoryLayer.L0_BEACH
        self._items[item.memory_id] = item
        self._items.move_to_end(item.memory_id)
        # 超出容量淘汰最旧的
        while len(self._items) > self.max_items:
            self._items.popitem(last=False)
        return True

    def get(self, memory_id: str) -> Optional[MemoryItem]:
        if memory_id in self._items:
            item = self._items[memory_id]
            item.touch()
            self._items.move_to_end(memory_id)
            return item
        return None

    def search(self, query: str, top_k: int = 10) -> List[Dict]:
        """简单关键词搜索"""
        results = []
        for item in self._items.values():
            # L0层只做简单标签匹配（不存原文，用标签）
            score = sum(1 for tag in item.tags if tag in query)
            if score > 0:
                results.append({
                    "memory_id": item.memory_id,
                    "layer": "l0_beach",
                    "score": score,
                    "tags": item.tags,
                    "created_at": item.created_at.isoformat(),
                })
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def items(self) -> List[MemoryItem]:
        return list(self._items.values())

    def count(self) -> int:
        return len(self._items)

    def remove(self, memory_id: str) -> bool:
        if memory_id in self._items:
            del self._items[memory_id]
            return True
        return False

    def pop_oldest(self) -> Optional[MemoryItem]:
        """取出最旧的记忆（用于沉降）"""
        if self._items:
            _, item = self._items.popitem(last=False)
            return item
        return None
