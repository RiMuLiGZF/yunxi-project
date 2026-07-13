"""
L0-L1 缓存协调器 - KV 缓存联动

P2-任务4: 实现 L0→L1 沉降机制和 L1→L0 预加载机制，
提升高频访问记忆的读取速度，优化整体缓存命中率。

功能：
1. L0→L1 沉降：L0 中访问次数 ≥ 阈值的记忆，自动沉降到 L1
2. L1→L0 预加载：检索结果中 top_k 的前 N 个自动预加载到 L0
3. 缓存统计：记录 L0 命中率、沉降次数、预加载次数
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Optional

import structlog

from ..core.models import MemoryItem

logger = structlog.get_logger(__name__)


class CacheCoordinator:
    """
    L0-L1 缓存协调器

    管理 L0 沙滩层（热缓存）和 L1 浅水层（温缓存）之间的智能数据流动：
    - 沉降（settle）：L0 → L1，高频访问记忆持久化
    - 预加载（preload）：L1 → L0，热门记忆加速访问
    """

    def __init__(
        self,
        l0_layer=None,
        l1_layer=None,
        settle_threshold_access: int = 2,
        preload_top_k: int = 3,
    ):
        """
        初始化缓存协调器

        Args:
            l0_layer: L0 沙滩层实例
            l1_layer: L1 浅水层实例
            settle_threshold_access: L0→L1 沉降的访问次数阈值
            preload_top_k: recall 结果中前 N 个预加载到 L0
        """
        self._l0 = l0_layer
        self._l1 = l1_layer
        self._settle_threshold = settle_threshold_access
        self._preload_top_k = preload_top_k

        # 统计信息
        self._stats = {
            "l0_hits": 0,           # L0 命中次数
            "l0_misses": 0,         # L0 未命中次数
            "settle_count": 0,      # 沉降次数
            "preload_count": 0,     # 预加载次数
            "preload_skipped": 0,   # 预加载跳过（已在L0）次数
        }

    # ============================================================
    # L0→L1 沉降机制
    # ============================================================

    def check_and_settle(self, memory_id: str) -> bool:
        """
        检查 L0 中的记忆是否满足沉降条件，满足则沉降到 L1

        沉降条件：
        - 记忆在 L0 中
        - 访问次数 >= settle_threshold_access

        沉降操作：
        - 写入 L1
        - 从 L0 删除
        - 保留 access_count 等统计信息

        Args:
            memory_id: 记忆 ID

        Returns:
            是否执行了沉降
        """
        if self._l0 is None or self._l1 is None:
            return False

        # 从 L0 获取（注意：get 会增加 access_count，所以用 items 查找）
        item = self._l0_get_without_touch(memory_id)
        if item is None:
            return False

        # 检查沉降条件
        if item.access_count < self._settle_threshold:
            return False

        # 执行沉降
        try:
            # 写入 L1（保留所有属性，包括 access_count）
            self._l1.add(item)
            # 从 L0 删除
            self._l0.remove(memory_id)
            self._stats["settle_count"] += 1
            logger.debug(f"沉降: {memory_id} L0→L1 (access_count={item.access_count})")
            return True
        except Exception as e:
            logger.warning(f"沉降失败 [{memory_id}]: {e}")
            return False

    def settle_all_eligible(self) -> int:
        """
        扫描 L0，将所有满足沉降条件的记忆沉降到 L1

        Returns:
            沉降的记忆数量
        """
        if self._l0 is None or self._l1 is None:
            return 0

        settled = 0
        # 先收集所有满足条件的 ID（避免遍历时修改）
        eligible_ids = []
        for item in self._l0.items():
            if item.access_count >= self._settle_threshold:
                eligible_ids.append(item.memory_id)

        for mid in eligible_ids:
            if self.check_and_settle(mid):
                settled += 1

        return settled

    def _l0_get_without_touch(self, memory_id: str) -> Optional[MemoryItem]:
        """
        从 L0 获取记忆但不增加访问计数（用于沉降检查）

        Args:
            memory_id: 记忆 ID

        Returns:
            MemoryItem，不存在返回 None
        """
        if self._l0 is None:
            return None
        # 直接访问内部字典（BeachLayer 的 _items）
        if hasattr(self._l0, '_items') and memory_id in self._l0._items:
            return self._l0._items[memory_id]
        return None

    # ============================================================
    # L1→L0 预加载机制
    # ============================================================

    def preload_to_l0(self, memory_ids: List[str]) -> Dict:
        """
        将指定的记忆从 L1 预加载到 L0

        预加载策略：
        - 只加载前 preload_top_k 个
        - 已在 L0 中的跳过
        - 不在 L1 中的跳过

        Args:
            memory_ids: 记忆 ID 列表（按相关性排序，前 N 个优先加载）

        Returns:
            {"preloaded": n, "skipped": n, "failed": n}
        """
        if self._l0 is None or self._l1 is None:
            return {"preloaded": 0, "skipped": 0, "failed": 0}

        preloaded = 0
        skipped = 0
        failed = 0

        # 只取前 N 个
        target_ids = memory_ids[:self._preload_top_k]

        for mid in target_ids:
            # 检查是否已在 L0
            if self._l0_get_without_touch(mid) is not None:
                skipped += 1
                continue

            # 从 L1 加载
            try:
                item = self._l1.get(mid)
                if item is not None:
                    # 添加到 L0（注意：L0 的 add 会设置 layer 为 L0_BEACH）
                    # 保留 access_count 等统计信息
                    self._l0.add(item)
                    preloaded += 1
                    self._stats["preload_count"] += 1
                    logger.debug(f"预加载: {mid} L1→L0")
                else:
                    failed += 1
            except Exception as e:
                logger.warning(f"预加载失败 [{mid}]: {e}")
                failed += 1

        self._stats["preload_skipped"] += skipped
        return {
            "preloaded": preloaded,
            "skipped": skipped,
            "failed": failed,
        }

    def preload_hot_from_l1(
        self,
        min_access_count: int = 2,
        within_hours: int = 1,
        max_items: int = 10,
    ) -> int:
        """
        从 L1 预加载热门记忆到 L0

        预加载条件：
        - 最近 within_hours 小时内有访问
        - 访问次数 >= min_access_count

        Args:
            min_access_count: 最小访问次数
            within_hours: 最近多少小时内有访问
            max_items: 最大预加载数量

        Returns:
            预加载的记忆数量
        """
        if self._l0 is None or self._l1 is None:
            return 0

        try:
            cutoff_time = datetime.now() - timedelta(hours=within_hours)
            hot_items: List[MemoryItem] = []

            for item in self._l1.items():
                if (
                    item.access_count >= min_access_count
                    and item.last_accessed_at is not None
                    and item.last_accessed_at >= cutoff_time
                ):
                    hot_items.append(item)

            # 按访问次数降序，取前 max_items 个
            hot_items.sort(key=lambda x: x.access_count, reverse=True)
            hot_items = hot_items[:max_items]

            preloaded = 0
            for item in hot_items:
                if self._l0_get_without_touch(item.memory_id) is None:
                    self._l0.add(item)
                    preloaded += 1
                    self._stats["preload_count"] += 1

            logger.debug(f"热门预加载: {preloaded} 条记忆 L1→L0")
            return preloaded
        except Exception as e:
            logger.warning(f"热门预加载失败: {e}")
            return 0

    # ============================================================
    # 缓存访问（带命中统计）
    # ============================================================

    def get_with_stats(self, memory_id: str) -> Optional[MemoryItem]:
        """
        获取记忆，同时更新缓存命中率统计

        查找顺序：L0 → L1

        Args:
            memory_id: 记忆 ID

        Returns:
            MemoryItem，不存在返回 None
        """
        # 先查 L0
        if self._l0 is not None:
            item = self._l0.get(memory_id)
            if item is not None:
                self._stats["l0_hits"] += 1
                # L0 命中后检查沉降
                self.check_and_settle(memory_id)
                return item

        # L0 未命中，查 L1
        self._stats["l0_misses"] += 1
        if self._l1 is not None:
            item = self._l1.get(memory_id)
            if item is not None:
                return item

        return None

    # ============================================================
    # 统计信息
    # ============================================================

    def get_stats(self) -> Dict:
        """
        获取缓存协调器统计信息

        Returns:
            统计字典
        """
        total_l0_accesses = self._stats["l0_hits"] + self._stats["l0_misses"]
        hit_rate = (
            round(self._stats["l0_hits"] / total_l0_accesses, 4)
            if total_l0_accesses > 0
            else 0.0
        )

        l0_count = self._l0.count() if self._l0 and hasattr(self._l0, 'count') else 0
        l1_count = self._l1.count() if self._l1 and hasattr(self._l1, 'count') else 0

        return {
            "l0_hit_rate": hit_rate,
            "l0_hits": self._stats["l0_hits"],
            "l0_misses": self._stats["l0_misses"],
            "settle_count": self._stats["settle_count"],
            "preload_count": self._stats["preload_count"],
            "preload_skipped": self._stats["preload_skipped"],
            "settle_threshold": self._settle_threshold,
            "preload_top_k": self._preload_top_k,
            "l0_size": l0_count,
            "l1_size": l1_count,
        }

    def reset_stats(self) -> None:
        """重置统计计数器"""
        self._stats = {
            "l0_hits": 0,
            "l0_misses": 0,
            "settle_count": 0,
            "preload_count": 0,
            "preload_skipped": 0,
        }
# vim: set et ts=4 sw=4:
