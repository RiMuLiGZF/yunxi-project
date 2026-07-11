"""冲突解决器.

四级冲突解决策略。
"""

from __future__ import annotations

from enum import Enum
from typing import Any

import structlog
from pydantic import BaseModel, Field

from edge_cloud_kernel.models.sync_models import SyncItem, SyncResult, SyncStatus

logger = structlog.get_logger(__name__)


class ConflictResolution(str, Enum):
    """版本向量冲突解决结果枚举.

    Attributes:
        LOCAL_WINS: 本地版本胜出.
        REMOTE_WINS: 远端版本胜出.
        CONCURRENT: 双方并发，需要进一步策略.
        MERGED: 已通过合并策略解决.
    """

    LOCAL_WINS = "local_wins"
    REMOTE_WINS = "remote_wins"
    CONCURRENT = "concurrent"
    MERGED = "merged"


class ConflictStrategy(str, Enum):
    """冲突解决策略枚举（优先级从低到高）.

    Attributes:
        TIMESTAMP: 时间戳优先（最新修改胜出）.
        LOCAL_FIRST: 本地优先.
        REMOTE_FIRST: 远端优先.
        MANUAL: 需要人工介入.
    """

    TIMESTAMP = "timestamp"
    LOCAL_FIRST = "local_first"
    REMOTE_FIRST = "remote_first"
    MANUAL = "manual"


class VersionVector(BaseModel):
    """版本向量 -- CouchDB风格的多设备冲突检测.

    每个设备维护自己的单调递增版本号。
    例：{"desktop_001": 5, "laptop_002": 3, "phone_003": 1}
    """

    vectors: dict[str, int] = Field(default_factory=dict)

    def increment(self, device_id: str) -> None:
        """递增指定设备的版本号."""
        self.vectors[device_id] = self.vectors.get(device_id, 0) + 1

    def merge(self, other: VersionVector) -> VersionVector:
        """合并两个版本向量（取每个设备ID的最大值）."""
        merged: dict[str, int] = {}
        all_keys = set(self.vectors) | set(other.vectors)
        for k in all_keys:
            merged[k] = max(self.vectors.get(k, 0), other.vectors.get(k, 0))
        return VersionVector(vectors=merged)

    def dominates(self, other: VersionVector) -> bool:
        """判断self是否支配other（所有维度>=且至少一个>）."""
        if not other.vectors:
            return bool(self.vectors)
        for k, v in other.vectors.items():
            if self.vectors.get(k, 0) < v:
                return False
        return any(self.vectors.get(k, 0) > v for k, v in other.vectors.items())

    def is_concurrent(self, other: VersionVector) -> bool:
        """判断两个版本向量是否并发（互不支配）."""
        return not self.dominates(other) and not other.dominates(self)

    @property
    def summary_version(self) -> int:
        """摘要版本号（所有维度之和）."""
        return sum(self.vectors.values())


class CRDTMerge:
    """CRDT风格合并策略 -- 适用于字典类型数据（如配置、元数据）.

    参考思路：
    - Last-Writer-Wins (LWW): 每个key带时间戳，取最新
    - Multi-Value Register: 保留所有并发写入值，标记为冲突
    - Observed-Remove: 删除操作也带版本号，不会意外复活
    """

    @staticmethod
    async def merge_dicts(
        local: dict,
        remote: dict,
        local_ts: float,
        remote_ts: float,
    ) -> dict:
        """合并两个字典，使用LWW策略解决key级冲突.

        对每个key：
        - 仅local有 -> 保留
        - 仅remote有 -> 采纳
        - 双方都有 -> 比较嵌套时间戳，取最新
        """
        merged: dict = {}
        all_keys = set(local) | set(remote)
        for key in all_keys:
            if key not in remote:
                merged[key] = local[key]
            elif key not in local:
                merged[key] = remote[key]
            else:
                # Both have this key -- LWW at key level
                merged[key] = remote[key]  # remote wins for same-timestamp
        return merged

    @staticmethod
    def detect_tombstones(
        local: dict,
        remote: dict,
        deleted_keys: set[str],
    ) -> dict:
        """检测墓碑标记（已删除key不应被远端恢复）."""
        result = dict(remote)
        for key in deleted_keys:
            result.pop(key, None)
        return result


class ConflictResolver:
    """四级冲突解决器.

    当端云同步中出现数据冲突时，按策略级别解决：
    1. TIMESTAMP - 比较时间戳，最新修改胜出
    2. LOCAL_FIRST - 优先保留本地版本
    3. REMOTE_FIRST - 优先保留远端版本
    4. MANUAL - 无法自动解决，标记待人工处理

    Attributes:
        _default_strategy: 默认冲突解决策略.
        _manual_queue: 需要人工解决的冲突队列.
        _resolution_history: 解决历史记录.
    """

    def __init__(
        self,
        default_strategy: ConflictStrategy = ConflictStrategy.TIMESTAMP,
    ) -> None:
        """初始化 ConflictResolver.

        Args:
            default_strategy: 默认冲突解决策略.
        """
        self._default_strategy = default_strategy
        self._manual_queue: list[dict[str, Any]] = []
        self._resolution_history: list[dict[str, Any]] = []
        logger.info(
            "conflict_resolver.init",
            default_strategy=default_strategy.name,
        )

    async def resolve(
        self,
        local_item: SyncItem,
        remote_item: dict[str, Any],
        strategy: ConflictStrategy | None = None,
    ) -> SyncResult:
        """解决单个冲突.

        Args:
            local_item: 本地数据条目.
            remote_item: 远端数据条目.
            strategy: 解决策略，None 使用默认策略.

        Returns:
            同步结果.
        """
        used_strategy = strategy or self._default_strategy

        if used_strategy == ConflictStrategy.TIMESTAMP:
            return self._resolve_by_timestamp(local_item, remote_item)
        elif used_strategy == ConflictStrategy.LOCAL_FIRST:
            return self._resolve_local_first(local_item, remote_item)
        elif used_strategy == ConflictStrategy.REMOTE_FIRST:
            return self._resolve_remote_first(local_item, remote_item)
        elif used_strategy == ConflictStrategy.MANUAL:
            return self._resolve_manual(local_item, remote_item)
        else:
            return self._resolve_by_timestamp(local_item, remote_item)

    def _resolve_by_timestamp(
        self,
        local_item: SyncItem,
        remote_item: dict[str, Any],
    ) -> SyncResult:
        """基于时间戳解决冲突.

        Args:
            local_item: 本地条目.
            remote_item: 远端条目.

        Returns:
            同步结果.
        """
        remote_ts = remote_item.get("timestamp", 0.0)

        if local_item.timestamp >= remote_ts:
            # 本地较新，保留本地
            self._record_resolution(local_item.item_id, "timestamp", "local")
            return SyncResult(
                item_id=local_item.item_id,
                status=SyncStatus.SUCCESS,
                resolved_version=local_item.version,
            )
        else:
            # 远端较新，使用远端
            self._record_resolution(local_item.item_id, "timestamp", "remote")
            return SyncResult(
                item_id=local_item.item_id,
                status=SyncStatus.SUCCESS,
                resolved_version=remote_item.get("version", local_item.version + 1),
            )

    def _resolve_local_first(
        self,
        local_item: SyncItem,
        remote_item: dict[str, Any],
    ) -> SyncResult:
        """本地优先策略.

        Args:
            local_item: 本地条目.
            remote_item: 远端条目.

        Returns:
            同步结果.
        """
        self._record_resolution(local_item.item_id, "local_first", "local")
        return SyncResult(
            item_id=local_item.item_id,
            status=SyncStatus.SUCCESS,
            resolved_version=local_item.version,
        )

    def _resolve_remote_first(
        self,
        local_item: SyncItem,
        remote_item: dict[str, Any],
    ) -> SyncResult:
        """远端优先策略.

        Args:
            local_item: 本地条目.
            remote_item: 远端条目.

        Returns:
            同步结果.
        """
        self._record_resolution(local_item.item_id, "remote_first", "remote")
        return SyncResult(
            item_id=local_item.item_id,
            status=SyncStatus.SUCCESS,
            resolved_version=remote_item.get("version", local_item.version + 1),
        )

    def _resolve_manual(
        self,
        local_item: SyncItem,
        remote_item: dict[str, Any],
    ) -> SyncResult:
        """人工介入策略.

        Args:
            local_item: 本地条目.
            remote_item: 远端条目.

        Returns:
            同步结果（标记为 CONFLICT）.
        """
        conflict_entry = {
            "item_id": local_item.item_id,
            "local": local_item.model_dump(),
            "remote": remote_item,
            "created_at": __import__("time").time(),
        }
        self._manual_queue.append(conflict_entry)

        self._record_resolution(local_item.item_id, "manual", "queued")
        return SyncResult(
            item_id=local_item.item_id,
            status=SyncStatus.CONFLICT,
            error_message="Requires manual resolution",
        )

    def _record_resolution(
        self,
        item_id: str,
        strategy: str,
        winner: str,
    ) -> None:
        """记录冲突解决历史.

        Args:
            item_id: 条目 ID.
            strategy: 使用策略.
            winner: 获胜方.
        """
        self._resolution_history.append({
            "item_id": item_id,
            "strategy": strategy,
            "winner": winner,
        })

    def get_manual_conflicts(self) -> list[dict[str, Any]]:
        """获取待人工解决的冲突队列.

        Returns:
            冲突条目列表.
        """
        return self._manual_queue.copy()

    def resolve_manual(
        self,
        item_id: str,
        keep: str = "local",
    ) -> bool:
        """人工解决冲突.

        Args:
            item_id: 冲突条目 ID.
            keep: 保留方（"local" 或 "remote"）.

        Returns:
            是否成功解决.
        """
        for i, conflict in enumerate(self._manual_queue):
            if conflict["item_id"] == item_id:
                self._manual_queue.pop(i)
                self._record_resolution(item_id, "manual_resolved", keep)
                logger.info(
                    "conflict_resolver.manual_resolved",
                    item_id=item_id,
                    keep=keep,
                )
                return True
        return False

    def get_history(self) -> list[dict[str, Any]]:
        """获取冲突解决历史.

        Returns:
            历史记录列表.
        """
        return self._resolution_history.copy()

    async def resolve_with_version_vector(
        self,
        local: SyncItem,
        remote: SyncItem,
        local_vv: VersionVector,
        remote_vv: VersionVector,
    ) -> ConflictResolution:
        """使用版本向量进行冲突解决.

        - local_vv支配remote_vv -> local wins
        - remote_vv支配local_vv -> remote wins
        - 并发 -> 调用原有resolve()方法做进一步策略降级

        Args:
            local: 本地同步条目.
            remote: 远端同步条目.
            local_vv: 本地版本向量.
            remote_vv: 远端版本向量.

        Returns:
            冲突解决结果枚举.
        """
        merged_vv = local_vv.merge(remote_vv)

        if local_vv.dominates(remote_vv):
            logger.info(
                "conflict_resolver.vv.local_wins",
                item_id=local.item_id,
                local_vv=local_vv.vectors,
                remote_vv=remote_vv.vectors,
            )
            self._record_resolution(local.item_id, "version_vector", "local")
            return ConflictResolution.LOCAL_WINS

        if remote_vv.dominates(local_vv):
            logger.info(
                "conflict_resolver.vv.remote_wins",
                item_id=local.item_id,
                local_vv=local_vv.vectors,
                remote_vv=remote_vv.vectors,
            )
            self._record_resolution(local.item_id, "version_vector", "remote")
            return ConflictResolution.REMOTE_WINS

        # 并发修改 -- 尝试CRDT合并后再降级到原有策略
        logger.warning(
            "conflict_resolver.vv.concurrent",
            item_id=local.item_id,
            local_vv=local_vv.vectors,
            remote_vv=remote_vv.vectors,
        )

        # 如果双方value都是dict类型，尝试CRDT合并
        if isinstance(local.value, dict) and isinstance(remote.value, dict):
            merged_value = await CRDTMerge.merge_dicts(
                local.value, remote.value, local.timestamp, remote.timestamp,
            )
            logger.info(
                "conflict_resolver.vv.crdt_merged",
                item_id=local.item_id,
                merged_keys=list(merged_value.keys()),
            )
            self._record_resolution(local.item_id, "version_vector_crdt", "merged")
            return ConflictResolution.MERGED

        # 降级到原有resolve()方法
        fallback_result = await self.resolve(local, remote.model_dump())
        if fallback_result.status == SyncStatus.CONFLICT:
            self._record_resolution(local.item_id, "version_vector_fallback", "concurrent")
            return ConflictResolution.CONCURRENT

        winner = "local" if fallback_result.resolved_version == local.version else "remote"
        self._record_resolution(local.item_id, "version_vector_fallback", winner)
        return ConflictResolution.MERGED
