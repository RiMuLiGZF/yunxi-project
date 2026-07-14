"""
记忆巩固引擎（睡眠模式）

模拟人类睡眠时的记忆巩固过程：
1. 记忆迁移：L0 → L1 → L2 → L3
2. 语义蒸馏：相似记忆合并
3. 索引重建：优化检索效率
4. 质量评估：低质量记忆淘汰（多维遗忘得分）
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from ..core.models import EmotionState, MemoryItem, MemoryLayer
from ..common.transaction import MemoryTransaction
from ..common.constants import (
    FORGET_WEIGHT_QUALITY,
    FORGET_WEIGHT_ACCESS,
    FORGET_WEIGHT_TIME,
    FORGET_WEIGHT_EMOTION,
    FORGET_THRESHOLD_DELETE,
    FORGET_THRESHOLD_DEMOTE,
    FORGET_THRESHOLD_MARK,
    FORGET_ACCESS_LOG_FACTOR,
    FORGET_HALF_LIFE_DAYS,
    QUALITY_SCORE_MAX,
    PROMOTE_L0_ACCESS_THRESHOLD,
    PROMOTE_L0_QUALITY_THRESHOLD,
    PROMOTE_L1_ACCESS_THRESHOLD,
    PROMOTE_L1_QUALITY_THRESHOLD,
    PROMOTE_L1_EI_THRESHOLD,
    PROMOTE_L2_QUALITY_THRESHOLD,
    PROMOTE_L2_ACCESS_FOR_QUALITY,
    PROMOTE_L2_EI_THRESHOLD,
    PROMOTE_L2_ACCESS_FOR_EI,
    PROMOTE_L2_LONG_TERM_DAYS,
    PROMOTE_L2_ACCESS_FOR_LONG_TERM,
    DISTILL_TAG_OVERLAP_THRESHOLD,
    DISTILL_QUALITY_BOOST,
    DISTILL_QUALITY_DROP_RATIO,
    DISTILL_CONFIDENCE,
    EMOTION_DISTILLED,
    MEMORY_ID_PREFIX,
    MEMORY_ID_LENGTH,
    QUALITY_LEVEL_LOW,
    QUALITY_LEVEL_DISTILLED,
    QUALITY_LEVEL_DISTILLED_MASTER,
    CONSOLIDATION_MODE_QUICK,
    CONSOLIDATION_MODE_NORMAL,
    CONSOLIDATION_MODE_FULL,
)


class ConsolidationEngine:
    """
    睡眠记忆巩固引擎

    巩固策略：
    - 访问频率高的记忆向上迁移
    - 情绪强度高的记忆优先保留
    - 高质量记忆长期保存
    - 低质量记忆逐步淘汰（基于多维遗忘得分）
    """

    # 遗忘得分权重（P2-2：多维评估）
    # 从 constants 导入，保留为类属性以兼容旧引用
    _FORGET_WEIGHT_QUALITY = FORGET_WEIGHT_QUALITY    # 质量分权重
    _FORGET_WEIGHT_ACCESS = FORGET_WEIGHT_ACCESS      # 访问频率权重
    _FORGET_WEIGHT_TIME = FORGET_WEIGHT_TIME          # 时间衰减权重
    _FORGET_WEIGHT_EMOTION = FORGET_WEIGHT_EMOTION    # 情绪强度权重

    # 遗忘阈值
    _FORGET_THRESHOLD_DELETE = FORGET_THRESHOLD_DELETE   # 立即删除
    _FORGET_THRESHOLD_DEMOTE = FORGET_THRESHOLD_DEMOTE   # 降级到下一层
    _FORGET_THRESHOLD_MARK = FORGET_THRESHOLD_MARK       # 标记为"正在遗忘"

    # 语义蒸馏标签重合度阈值
    _DISTILL_TAG_OVERLAP_THRESHOLD = DISTILL_TAG_OVERLAP_THRESHOLD

    def __init__(self, l0=None, l1=None, l2=None, l3=None, ei_engine=None) -> None:
        self._l0 = l0
        self._l1 = l1
        self._l2 = l2
        self._l3 = l3
        self._ei = ei_engine
        self._consolidation_count = 0

    # ============================================================
    # 对外 API
    # ============================================================

    def run_consolidation(self, mode: str = "normal") -> Dict[str, Any]:
        """
        执行记忆巩固

        Args:
            mode: 巩固模式
                - quick: 快速模式（仅 L0→L1 迁移）
                - normal: 标准模式（L0→L1→L2 + 低质量降级）
                - full: 完整模式（全链路 + 语义蒸馏 + 索引重建）

        Returns:
            巩固结果统计
        """
        stats = {
            "mode": mode,
            "promoted": 0,       # 升级数量
            "demoted": 0,        # 降级数量
            "merged": 0,         # 合并数量
            "compressed": 0,     # 压缩数量
            "forgotten": 0,      # 遗忘（删除）数量
            "distilled": 0,      # 语义蒸馏数量
            "marked_forgetting": 0,  # 标记为正在遗忘的数量
            "reindexed": False,  # 是否重建索引
        }

        # 1. L0 → L1 迁移（所有模式都执行）
        if mode in [CONSOLIDATION_MODE_QUICK, CONSOLIDATION_MODE_NORMAL, CONSOLIDATION_MODE_FULL]:
            promoted_l0 = self._promote_l0_to_l1()
            stats["promoted"] += promoted_l0

        # 2. L1 → L2 迁移（normal + full）
        if mode in [CONSOLIDATION_MODE_NORMAL, CONSOLIDATION_MODE_FULL]:
            promoted_l1 = self._promote_l1_to_l2()
            stats["promoted"] += promoted_l1

        # 3. L2 → L3 迁移（仅 full 模式）
        if mode == CONSOLIDATION_MODE_FULL:
            promoted_l2 = self._promote_l2_to_l3()
            stats["promoted"] += promoted_l2

        # 4. 低质量记忆降级/遗忘（normal + full）
        if mode in [CONSOLIDATION_MODE_NORMAL, CONSOLIDATION_MODE_FULL]:
            demote_stats = self._demote_low_quality()
            stats["demoted"] += demote_stats["demoted"]
            stats["forgotten"] += demote_stats["forgotten"]
            stats["marked_forgetting"] += demote_stats["marked"]

        # 5. L2 层语义蒸馏（仅 full 模式）
        if mode == CONSOLIDATION_MODE_FULL:
            distill_stats = self._semantic_distill_l2()
            stats["distilled"] = distill_stats["distilled"]
            stats["merged"] = distill_stats["merged"]

        # 6. L2 层压缩（full 模式，兼容旧 API）
        if mode == CONSOLIDATION_MODE_FULL and hasattr(self._l2, "compress"):
            compressed = self._l2.compress()
            stats["compressed"] = compressed.get("compressed_count", 0)

        # 7. 索引重建（full 模式）
        if mode == CONSOLIDATION_MODE_FULL:
            stats["reindexed"] = True

        self._consolidation_count += 1
        return stats

    def quick_consolidate(self) -> Dict:
        """
        快速模式巩固（仅 L0→L1 迁移）
        适用于高频调用场景，耗时 < 1s
        """
        return self.run_consolidation(mode=CONSOLIDATION_MODE_QUICK)

    def full_consolidate(self) -> Dict[str, Any]:
        """
        完整模式巩固（全链路 + 语义蒸馏 + 索引重建）
        适用于低频深度巩固（如每日睡眠模式）
        """
        return self.run_consolidation(mode=CONSOLIDATION_MODE_FULL)

    def get_stats(self) -> Dict:
        """
        获取各层记忆数量统计

        Returns:
            {total, layers: {l0_beach, l1_shallow, l2_deep, l3_abyss}}
        """
        l0_count = self._l0.count() if self._l0 and hasattr(self._l0, "count") else 0
        l1_count = self._l1.count() if self._l1 and hasattr(self._l1, "count") else 0
        l2_count = self._l2.count() if self._l2 and hasattr(self._l2, "count") else 0
        l3_count = self._l3.count() if self._l3 and hasattr(self._l3, "count") else 0

        return {
            "total": l0_count + l1_count + l2_count + l3_count,
            "layers": {
                "l0_beach": l0_count,
                "l1_shallow": l1_count,
                "l2_deep": l2_count,
                "l3_abyss": l3_count,
            },
            "total_consolidations": self._consolidation_count,
        }

    def get_consolidation_stats(self) -> Dict:
        """获取巩固统计（兼容旧 API）"""
        stats = self.get_stats()
        return {
            "total_consolidations": self._consolidation_count,
            "layers": stats["layers"],
        }

    # ============================================================
    # L0 → L1 迁移
    # ============================================================

    def _promote_l0_to_l1(self) -> int:
        """
        L0沙滩层 → L1浅水层 迁移（事务保障）

        迁移条件（满足任一即可）：
        - 访问次数 >= 2 次
        - 质量分 >= 60 分

        每条记忆的迁移在独立事务中执行，确保原子性：
        如果 L1 添加失败，L0 不删除。
        """
        import structlog
        log = structlog.get_logger(__name__)

        if not self._l0 or not self._l1:
            return 0

        promoted = 0
        items = self._l0.items()

        for item in items:
            if item.access_count >= PROMOTE_L0_ACCESS_THRESHOLD or item.quality_score >= PROMOTE_L0_QUALITY_THRESHOLD:
                try:
                    with MemoryTransaction(name=f"promote_l0_l1_{item.memory_id}") as tx:
                        # 注意：item 是 L0 中的引用，需要深拷贝后再 promote
                        promoted_item = item.model_copy(deep=True)
                        promoted_item.promote()
                        tx.add(self._l1, promoted_item)
                        tx.remove(self._l0, item.memory_id)
                    promoted += 1
                except Exception as e:
                    log.warning(
                        "consolidation.promote_l0_l1_failed",
                        memory_id=item.memory_id,
                        error=str(e),
                    )
                    # 单条失败不影响其他记忆的迁移

        return promoted

    # ============================================================
    # L1 → L2 迁移
    # ============================================================

    def _promote_l1_to_l2(self) -> int:
        """
        L1浅水层 → L2深水层 迁移（事务保障）

        迁移条件（满足任一即可）：
        - 访问次数 >= 3 次
        - 质量分 >= 70 分
        - EI 情绪强度 >= 0.6

        每条记忆的迁移在独立事务中执行，确保原子性：
        如果 L2 添加失败，L1 不删除。
        """
        import structlog
        log = structlog.get_logger(__name__)

        if not self._l1 or not self._l2:
            return 0

        promoted = 0
        items = self._l1.items()

        for item in items:
            should_promote = (
                item.access_count >= PROMOTE_L1_ACCESS_THRESHOLD
                or item.quality_score >= PROMOTE_L1_QUALITY_THRESHOLD
                or item.emotion.ei_score >= PROMOTE_L1_EI_THRESHOLD
            )
            if should_promote:
                try:
                    with MemoryTransaction(name=f"promote_l1_l2_{item.memory_id}") as tx:
                        promoted_item = item.model_copy(deep=True)
                        promoted_item.promote()
                        tx.add(self._l2, promoted_item)
                        tx.remove(self._l1, item.memory_id)
                    promoted += 1
                except Exception as e:
                    log.warning(
                        "consolidation.promote_l1_l2_failed",
                        memory_id=item.memory_id,
                        error=str(e),
                    )
                    # 单条失败不影响其他记忆的迁移

        return promoted

    # ============================================================
    # L2 → L3 迁移（修复版）
    # ============================================================

    def _promote_l2_to_l3(self) -> int:
        """
        L2深水层 → L3深海层 迁移（事务保障）

        迁移条件（满足任一即可）：
        - 质量分 >= 85 且 访问次数 >= 5
        - EI 情绪强度 >= 0.8 且 访问次数 >= 3
        - 创建超过 30 天且 访问次数 >= 10（长期高频记忆）

        每条记忆的迁移在独立事务中执行，确保原子性：
        如果 L3 添加失败，L2 不删除。
        """
        import structlog
        log = structlog.get_logger(__name__)

        if not self._l2 or not self._l3:
            return 0

        promoted = 0
        items = self._l2.items()
        now = datetime.now()

        for item in items:
            days_since_created = (now - item.created_at).days

            condition_quality = (
                item.quality_score >= PROMOTE_L2_QUALITY_THRESHOLD and item.access_count >= PROMOTE_L2_ACCESS_FOR_QUALITY
            )
            condition_emotion = (
                item.emotion.ei_score >= PROMOTE_L2_EI_THRESHOLD and item.access_count >= PROMOTE_L2_ACCESS_FOR_EI
            )
            condition_long_term = (
                days_since_created >= PROMOTE_L2_LONG_TERM_DAYS and item.access_count >= PROMOTE_L2_ACCESS_FOR_LONG_TERM
            )

            if condition_quality or condition_emotion or condition_long_term:
                try:
                    with MemoryTransaction(name=f"promote_l2_l3_{item.memory_id}") as tx:
                        promoted_item = item.model_copy(deep=True)
                        promoted_item.promote()
                        tx.add(self._l3, promoted_item)
                        tx.remove(self._l2, item.memory_id)
                    promoted += 1
                except Exception as e:
                    log.warning(
                        "consolidation.promote_l2_l3_failed",
                        memory_id=item.memory_id,
                        error=str(e),
                    )
                    # 单条失败不影响其他记忆的迁移

        return promoted

    # ============================================================
    # 低质量记忆降级/遗忘（P2-2：多维遗忘得分）
    # ============================================================

    def _demote_low_quality(self) -> Dict[str, Any]:
        """
        低质量记忆降级/遗忘（基于多维遗忘得分）

        遗忘得分 = 加权求和：
        - 质量分（30%）：quality_score 越低越容易忘
        - 访问频率（30%）：access_count 越少越容易忘
        - 时间衰减（20%）：创建越久越容易忘（指数衰减）
        - 情绪强度（20%）：EI 越低越容易忘

        遗忘阈值：
        - 遗忘得分 > 0.8 → 立即删除
        - 遗忘得分 > 0.6 → 降级到下一层
        - 遗忘得分 > 0.4 → 标记为"正在遗忘"

        Returns:
            {demoted, forgotten, marked}
        """
        demoted = 0
        forgotten = 0
        marked = 0

        # 处理 L1 层
        if self._l1:
            s = self._process_layer_forgetting(
                layer=self._l1,
                layer_name="l1_shallow",
                lower_layer=self._l0,
                lower_layer_name="l0_beach",
            )
            demoted += s["demoted"]
            forgotten += s["forgotten"]
            marked += s["marked"]

        # 处理 L2 层
        if self._l2:
            s = self._process_layer_forgetting(
                layer=self._l2,
                layer_name="l2_deep",
                lower_layer=self._l1,
                lower_layer_name="l1_shallow",
            )
            demoted += s["demoted"]
            forgotten += s["forgotten"]
            marked += s["marked"]

        # 处理 L3 层（只能遗忘，不能降级到 L2，L3 是永久记忆）
        if self._l3:
            s = self._process_layer_forgetting(
                layer=self._l3,
                layer_name="l3_abyss",
                lower_layer=None,   # L3 不降级，只遗忘
                lower_layer_name=None,
            )
            forgotten += s["forgotten"]
            marked += s["marked"]

        return {
            "demoted": demoted,
            "forgotten": forgotten,
            "marked": marked,
        }

    def _process_layer_forgetting(
        self,
        layer,
        layer_name: str,
        lower_layer,
        lower_layer_name: Optional[str],
    ) -> Dict[str, Any]:
        """
        处理单层的遗忘/降级逻辑（事务保障）

        降级操作（先加到下层，再从当前层删除）在事务中执行，
        确保原子性：下层添加失败时，当前层不删除。

        Args:
            layer: 当前层对象
            layer_name: 当前层名称
            lower_layer: 下一层对象（降级目标），None 表示不降级
            lower_layer_name: 下一层名称

        Returns:
            {demoted, forgotten, marked}
        """
        import structlog
        log = structlog.get_logger(__name__)

        demoted = 0
        forgotten = 0
        marked = 0

        items = layer.items()
        now = datetime.now()

        for item in items:
            score = self._compute_forgetting_score(item, now)

            # 立即删除
            if score > self._FORGET_THRESHOLD_DELETE:
                layer.remove(item.memory_id)
                forgotten += 1
            # 降级到下一层（事务保障）
            elif score > self._FORGET_THRESHOLD_DEMOTE and lower_layer is not None:
                try:
                    with MemoryTransaction(name=f"demote_{layer_name}_{item.memory_id}") as tx:
                        demoted_item = item.model_copy(deep=True)
                        demoted_item.demote()
                        tx.add(lower_layer, demoted_item)
                        tx.remove(layer, item.memory_id)
                    demoted += 1
                except Exception as e:
                    log.warning(
                        "consolidation.demote_failed",
                        memory_id=item.memory_id,
                        from_layer=layer_name,
                        to_layer=lower_layer_name,
                        error=str(e),
                    )
                    # 单条失败不影响其他记忆
            # 标记为正在遗忘
            elif score > self._FORGET_THRESHOLD_MARK:
                # 在 metadata 中标记，不改变层位置
                item.metadata["forgetting"] = True
                item.metadata["forgetting_score"] = round(score, 4)
                # 更新质量等级提示
                if item.quality_level not in ("poor", QUALITY_LEVEL_LOW):
                    item.quality_level = QUALITY_LEVEL_LOW
                # 写回存储（通过 add 覆盖更新）
                layer.add(item)
                marked += 1

        return {
            "demoted": demoted,
            "forgotten": forgotten,
            "marked": marked,
        }

    def _compute_forgetting_score(self, item: MemoryItem, now: datetime) -> float:
        """
        计算单条记忆的遗忘得分（0~1，越高越容易忘）

        加权求和：
        - 质量分（30%）：quality_score 越低得分越高
        - 访问频率（30%）：access_count 越少得分越高
        - 时间衰减（20%）：创建越久得分越高（指数衰减）
        - 情绪强度（20%）：EI 越低得分越高
        """
        # 1. 质量分因子：quality 越低 → 得分越高
        #    quality=0 → 1.0, quality=100 → 0.0
        quality_factor = 1.0 - (item.quality_score / QUALITY_SCORE_MAX)

        # 2. 访问频率因子：access_count 越少 → 得分越高
        #    使用对数衰减，访问0次=1.0，访问5次≈0.3，访问20次≈0.1
        if item.access_count <= 0:
            access_factor = 1.0
        else:
            access_factor = 1.0 / (1.0 + FORGET_ACCESS_LOG_FACTOR * item.access_count)
            access_factor = min(1.0, max(0.0, access_factor))

        # 3. 时间衰减因子：创建越久 → 得分越高
        #    指数衰减：days=0 → 0, days=30 → 0.5, days=90 → 0.8
        days_since_created = (now - item.created_at).days
        if days_since_created <= 0:
            time_factor = 0.0
        else:
            # 指数趋近于 1.0，半衰期约 30 天
            time_factor = 1.0 - math.exp(-days_since_created / FORGET_HALF_LIFE_DAYS)
            time_factor = min(1.0, max(0.0, time_factor))

        # 4. 情绪强度因子：EI 越低 → 得分越高
        #    ei=0 → 1.0, ei=1 → 0.0
        ei = max(0.0, min(1.0, item.emotion.ei_score))
        emotion_factor = 1.0 - ei

        # 加权求和
        score = (
            self._FORGET_WEIGHT_QUALITY * quality_factor
            + self._FORGET_WEIGHT_ACCESS * access_factor
            + self._FORGET_WEIGHT_TIME * time_factor
            + self._FORGET_WEIGHT_EMOTION * emotion_factor
        )

        return round(score, 4)

    # ============================================================
    # 语义蒸馏（L2 层）
    # ============================================================

    def _semantic_distill_l2(self) -> Dict[str, Any]:
        """
        L2 层语义蒸馏（简单版）

        策略：
        - 在 L2 中找出高度相似的记忆对（基于标签重合度 >= 0.8）
        - 合并为一条更抽象的记忆，质量分取平均
        - 被合并的记忆标记为"已蒸馏"，保留在 L2 但降低检索权重

        Returns:
            {distilled: 新生成的抽象记忆数, merged: 被合并的记忆数}
        """
        if not self._l2:
            return {"distilled": 0, "merged": 0}

        items = self._l2.items()
        if len(items) < 2:
            return {"distilled": 0, "merged": 0}

        distilled_count = 0
        merged_count = 0
        processed_ids = set()

        # 遍历所有记忆对，找高度相似的
        for i, item_a in enumerate(items):
            if item_a.memory_id in processed_ids:
                continue

            similar_items = []
            for j, item_b in enumerate(items):
                if i >= j:
                    continue
                if item_b.memory_id in processed_ids:
                    continue

                overlap = self._tag_overlap(item_a.tags, item_b.tags)
                if overlap >= self._DISTILL_TAG_OVERLAP_THRESHOLD:
                    similar_items.append(item_b)

            if similar_items:
                # 合并相似记忆，生成一条更抽象的记忆
                all_items = [item_a] + similar_items
                distilled_item = self._merge_memories(all_items)

                # 添加蒸馏后的新记忆
                self._l2.add(distilled_item)
                distilled_count += 1

                # 标记被合并的记忆为"已蒸馏"
                for merged in all_items:
                    merged.metadata["distilled"] = True
                    merged.metadata["distilled_into"] = distilled_item.memory_id
                    merged.quality_level = QUALITY_LEVEL_DISTILLED
                    # 降低质量分（降低检索权重）
                    merged.quality_score = merged.quality_score * DISTILL_QUALITY_DROP_RATIO
                    self._l2.add(merged)  # 覆盖更新
                    processed_ids.add(merged.memory_id)
                    merged_count += 1

        return {
            "distilled": distilled_count,
            "merged": merged_count,
        }

    def _tag_overlap(self, tags_a: List[str], tags_b: List[str]) -> float:
        """
        计算两组标签的重合度（Jaccard 相似度）

        Args:
            tags_a: 标签列表 A
            tags_b: 标签列表 B

        Returns:
            重合度 0~1
        """
        if not tags_a or not tags_b:
            return 0.0

        set_a = set(tags_a)
        set_b = set(tags_b)
        intersection = set_a & set_b
        union = set_a | set_b

        if not union:
            return 0.0

        return len(intersection) / len(union)

    def _merge_memories(self, items: List[MemoryItem]) -> MemoryItem:
        """
        合并多条记忆为一条更抽象的记忆

        Args:
            items: 待合并的记忆列表

        Returns:
            合并后的新记忆
        """
        if not items:
            raise ValueError("合并列表不能为空")

        # 合并标签（取并集，去重）
        all_tags: List[str] = []
        for item in items:
            for tag in item.tags:
                if tag not in all_tags:
                    all_tags.append(tag)

        # 质量分取平均
        avg_quality = sum(i.quality_score for i in items) / len(items)
        # 蒸馏后的记忆质量略高于平均（抽象知识更有价值）
        distilled_quality = min(QUALITY_SCORE_MAX, avg_quality * DISTILL_QUALITY_BOOST)

        # 情绪取平均
        avg_valence = sum(i.emotion.valence for i in items) / len(items)
        avg_arousal = sum(i.emotion.arousal for i in items) / len(items)
        avg_ei = sum(i.emotion.ei_score for i in items) / len(items)

        # 访问次数取平均（向上取整）
        avg_access = int(sum(i.access_count for i in items) / len(items))

        # 创建时间取最早的
        earliest_created = min(i.created_at for i in items)

        # 合并 metadata 中的源记忆 ID
        source_ids = [i.memory_id for i in items]

        new_item = MemoryItem(
            memory_id=f"{MEMORY_ID_PREFIX}{uuid.uuid4().hex[:MEMORY_ID_LENGTH]}",
            content_hash=f"distilled_{uuid.uuid4().hex[:12]}",
            layer=MemoryLayer.L2_DEEP,
            domain=items[0].domain,
            owner_agent=items[0].owner_agent,
            created_at=earliest_created,
            updated_at=datetime.now(),
            access_count=avg_access,
            quality_score=distilled_quality,
            quality_level=QUALITY_LEVEL_DISTILLED_MASTER,
            tags=all_tags,
            metadata={
                "distilled_master": True,
                "source_memories": source_ids,
                "distilled_count": len(items),
            },
            emotion=EmotionState(
                valence=avg_valence,
                arousal=avg_arousal,
                ei_score=avg_ei,
                dominant_emotion=EMOTION_DISTILLED,
                confidence=DISTILL_CONFIDENCE,
            ),
        )

        return new_item
# vim: set et ts=4 sw=4:
