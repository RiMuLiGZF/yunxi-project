"""上下文增量同步控制器.

管理端云之间的上下文数据增量同步。
基于 checksum 比较实现差异检测，仅同步变更数据。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from enum import Enum
from typing import Any

import structlog

from edge_cloud_kernel.models.sync_models import (
    SessionState,
    SyncItem,
    SyncResult,
    SyncStatus,
)
from edge_cloud_kernel.local_data.sync_client import SyncClient

logger = structlog.get_logger(__name__)


class ConflictResolutionStrategy(str, Enum):
    """冲突解决策略枚举.

    Attributes:
        LOCAL_WINS: 本地版本优先.
        REMOTE_WINS: 远端版本优先.
        MANUAL: 记录冲突等待人工解决.
        HIGHEST_VERSION: 版本号高的优先.
    """

    LOCAL_WINS = "local_wins"
    REMOTE_WINS = "remote_wins"
    MANUAL = "manual"
    HIGHEST_VERSION = "highest_version"


class ConflictRecord:
    """同步冲突记录.

    Attributes:
        item_id: 冲突条目ID.
        key: 冲突数据键.
        local_version: 本地版本号.
        remote_version: 远端版本号.
        detected_at: 冲突检测时间戳.
        resolution: 解决策略.
    """

    def __init__(
        self,
        item_id: str,
        key: str,
        local_version: int,
        remote_version: int,
        resolution: ConflictResolutionStrategy = ConflictResolutionStrategy.MANUAL,
    ) -> None:
        self.item_id = item_id
        self.key = key
        self.local_version = local_version
        self.remote_version = remote_version
        self.detected_at = time.time()
        self.resolution = resolution

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "key": self.key,
            "local_version": self.local_version,
            "remote_version": self.remote_version,
            "detected_at": self.detected_at,
            "resolution": self.resolution.value,
        }


class ConflictRegistry:
    """冲突注册表.

    记录所有同步冲突，支持查询和批量清理。
    """

    def __init__(self, max_size: int = 1000) -> None:
        self._conflicts: dict[str, ConflictRecord] = {}
        self._max_size = max_size

    def register(self, record: ConflictRecord) -> None:
        """注册冲突记录."""
        if len(self._conflicts) >= self._max_size:
            # 淘汰最旧的记录
            oldest_key = min(
                self._conflicts,
                key=lambda k: self._conflicts[k].detected_at,
            )
            del self._conflicts[oldest_key]
        self._conflicts[record.item_id] = record
        logger.warning(
            "conflict_registry.registered",
            item_id=record.item_id,
            key=record.key,
            local_v=record.local_version,
            remote_v=record.remote_version,
        )

    def get(self, item_id: str) -> ConflictRecord | None:
        return self._conflicts.get(item_id)

    def list_all(self) -> list[ConflictRecord]:
        return list(self._conflicts.values())

    def clear_resolved(self) -> int:
        """清除所有非MANUAL状态的已解决冲突，返回清除数量."""
        to_remove = [
            k for k, v in self._conflicts.items()
            if v.resolution != ConflictResolutionStrategy.MANUAL
        ]
        for k in to_remove:
            del self._conflicts[k]
        return len(to_remove)

    @property
    def count(self) -> int:
        return len(self._conflicts)


class ContextSyncController:
    """上下文增量同步控制器.

    负责管理端云之间会话上下文、记忆和配置的增量同步，
    基于版本号和校验和检测变更，仅同步差异数据。

    Attributes:
        _sync_client: 云端同步客户端.
        _local_state: 本地状态追踪（key -> version/checksum）.
        _sync_interval_s: 同步间隔（秒）.
        _running: 是否正在运行.
    """

    def __init__(
        self,
        sync_client: SyncClient | None = None,
        sync_interval_s: float = 30.0,
        conflict_resolution_strategy: ConflictResolutionStrategy = ConflictResolutionStrategy.HIGHEST_VERSION,
    ) -> None:
        """初始化 ContextSyncController.

        Args:
            sync_client: 云端同步客户端.
            sync_interval_s: 自动同步间隔（秒）.
            conflict_resolution_strategy: 双向同步冲突解决策略.
        """
        self._sync_client = sync_client
        self._local_state: dict[str, dict[str, Any]] = {}
        self._sync_interval_s = sync_interval_s
        self._running = False
        self._sync_task: asyncio.Task[None] | None = None
        self._pending_items: list[SyncItem] = []
        self._conflict_resolution_strategy = conflict_resolution_strategy
        self._conflict_registry = ConflictRegistry()
        logger.info(
            "context_sync_controller.init",
            interval_s=sync_interval_s,
            conflict_strategy=conflict_resolution_strategy.value,
        )

    async def start(self) -> None:
        """启动定时同步任务."""
        if self._running:
            return
        self._running = True
        self._sync_task = asyncio.create_task(self._sync_loop())
        logger.info("context_sync_controller.started")

    async def stop(self) -> None:
        """停止定时同步任务."""
        self._running = False
        if self._sync_task:
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass
        logger.info("context_sync_controller.stopped")

    async def _sync_loop(self) -> None:
        """定时同步主循环."""
        while self._running:
            try:
                await self.sync_pending()
            except Exception:
                logger.exception("context_sync_controller.sync_error")
            await asyncio.sleep(self._sync_interval_s)

    async def add_sync_item(self, item: SyncItem) -> None:
        """添加待同步条目.

        Args:
            item: 同步条目.
        """
        self._pending_items.append(item)
        self._local_state[item.key] = {
            "version": item.version,
            "checksum": item.checksum,
            "timestamp": item.timestamp,
        }
        logger.debug(
            "context_sync_controller.item_added",
            item_id=item.item_id,
            key=item.key,
        )

    async def sync_pending(self) -> list[SyncResult]:
        """同步所有待处理条目.

        Returns:
            同步结果列表.
        """
        if not self._pending_items:
            return []

        items = self._pending_items.copy()
        self._pending_items.clear()

        results: list[SyncResult] = []
        for item in items:
            try:
                result = await self._sync_single(item)
                results.append(result)
            except Exception as e:
                results.append(SyncResult(
                    item_id=item.item_id,
                    status=SyncStatus.FAILED,
                    error_message=str(e),
                ))

        logger.info(
            "context_sync_controller.sync_completed",
            total=len(items),
            success=sum(1 for r in results if r.status == SyncStatus.SUCCESS),
        )
        return results

    @staticmethod
    def _compute_checksum(data: Any) -> str:
        """计算数据的 SHA-256 校验和.

        将数据序列化为 JSON 字符串后计算哈希值，用于增量差异检测。

        Args:
            data: 待计算校验和的数据（需可 JSON 序列化）.

        Returns:
            十六进制格式的 SHA-256 校验和字符串.
        """
        serialized = json.dumps(data, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    async def _fetch_remote_checksum(self, key: str) -> str | None:
        """从远端获取指定 key 的 checksum.

        Args:
            key: 数据键.

        Returns:
            远端 checksum 字符串，获取失败返回 None.
        """
        if self._sync_client is None:
            return None
        try:
            results = await self._sync_client.download([key])
            if results and results[0].status == SyncStatus.SUCCESS:
                return results[0].remote_checksum
        except Exception as e:
            logger.warning(
                "context_sync_controller.fetch_remote_checksum_error",
                key=key,
                error=str(e),
            )
        return None

    async def _sync_single(self, item: SyncItem) -> SyncResult:
        """基于 checksum 的增量同步单个条目.

        同步流程：
        1. 计算本地数据 checksum
        2. 获取远端 checksum
        3. 比较两者：相同则跳过，不同则上传/下载

        对于双向同步（BIDIRECTIONAL），额外进行版本冲突检测。

        Args:
            item: 同步条目.

        Returns:
            同步结果.
        """
        if self._sync_client is None:
            return SyncResult(
                item_id=item.item_id,
                status=SyncStatus.SKIPPED,
                error_message="SyncClient not configured",
            )

        # 双向同步冲突检测
        if item.sync_type.value == "bidirectional":
            conflict_result = await self._detect_conflict(item)
            if conflict_result is not None:
                return conflict_result

        # Step 1: 计算本地数据 checksum（如果未提供）
        local_checksum = item.checksum
        if not local_checksum:
            local_checksum = self._compute_checksum(item.value)
            item.checksum = local_checksum

        # Step 2: 获取远端 checksum
        remote_checksum = await self._fetch_remote_checksum(item.key)

        # Step 3: 比较 checksum，相同则跳过（增量同步核心逻辑）
        if remote_checksum is not None and remote_checksum == local_checksum:
            logger.debug(
                "context_sync_controller.skip_identical",
                item_id=item.item_id,
                key=item.key,
            )
            return SyncResult(
                item_id=item.item_id,
                status=SyncStatus.SKIPPED,
                remote_checksum=remote_checksum,
            )

        # Step 4: 存在差异，执行上传
        try:
            results = await self._sync_client.upload([item])
            if results and results[0].status == SyncStatus.SUCCESS:
                logger.info(
                    "context_sync_controller.synced_diff",
                    item_id=item.item_id,
                    key=item.key,
                    local_checksum=local_checksum[:8],
                    remote_checksum=(remote_checksum or "none")[:8],
                )
                return SyncResult(
                    item_id=item.item_id,
                    status=SyncStatus.SUCCESS,
                    remote_checksum=local_checksum,
                )
            else:
                error_msg = results[0].error_message if results else "Unknown error"
                return SyncResult(
                    item_id=item.item_id,
                    status=SyncStatus.FAILED,
                    error_message=error_msg,
                )
        except Exception as e:
            logger.error(
                "context_sync_controller.sync_upload_error",
                item_id=item.item_id,
                error=str(e),
            )
            return SyncResult(
                item_id=item.item_id,
                status=SyncStatus.FAILED,
                error_message=str(e),
            )

    async def _detect_conflict(self, item: SyncItem) -> SyncResult | None:
        """检测双向同步冲突.

        通过比较本地 version 与远端 version 判断是否存在冲突。
        如果存在冲突，根据 conflict_resolution_strategy 决定处理方式，
        并记录到 ConflictRegistry。

        Args:
            item: 同步条目.

        Returns:
            SyncResult 如果检测到冲突，否则 None.
        """
        try:
            remote_state = await self._fetch_remote_state(item.key)
        except Exception as e:
            logger.warning(
                "context_sync_controller.remote_fetch_failed",
                key=item.key,
                error=str(e),
            )
            return None

        if remote_state is None:
            return None  # 远端无数据，无冲突

        remote_version = remote_state.get("version", 0)
        local_version = item.version

        if remote_version == local_version:
            return None  # 版本一致，无冲突

        if remote_version > local_version:
            # 远端更新，不冲突，但需要通知调用方下载
            logger.info(
                "context_sync_controller.remote_newer",
                key=item.key,
                local_v=local_version,
                remote_v=remote_version,
            )
            return None

        # 本地版本更新但远端也有修改 -> 冲突
        conflict = ConflictRecord(
            item_id=item.item_id,
            key=item.key,
            local_version=local_version,
            remote_version=remote_version,
            resolution=self._conflict_resolution_strategy,
        )
        self._conflict_registry.register(conflict)

        resolved_version = self._resolve_conflict_version(
            local_version, remote_version, self._conflict_resolution_strategy
        )

        return SyncResult(
            item_id=item.item_id,
            status=SyncStatus.CONFLICT,
            resolved_version=resolved_version,
            error_message=(
                f"Sync conflict on '{item.key}': "
                f"local_v={local_version}, remote_v={remote_version}, "
                f"strategy={self._conflict_resolution_strategy.value}"
            ),
        )

    async def _fetch_remote_state(self, key: str) -> dict[str, Any] | None:
        """获取远端同步状态.

        通过 sync_client 获取远端指定 key 的状态快照，
        返回包含 version、checksum、timestamp 等字段的字典。

        Args:
            key: 数据键.

        Returns:
            远端状态字典，或 None（远端无数据或获取失败）.
        """
        if self._sync_client is None:
            return None
        try:
            results = await self._sync_client.download([key])
            if results and results[0].status == SyncStatus.SUCCESS:
                # 从远端同步结果中构建状态字典
                remote_item = results[0]
                state = {
                    "version": getattr(remote_item, "remote_version", 0),
                    "checksum": remote_item.remote_checksum,
                    "timestamp": time.time(),
                    "data": remote_item.value if hasattr(remote_item, "value") else None,
                }
                logger.debug(
                    "context_sync_controller.remote_state_fetched",
                    key=key,
                    version=state["version"],
                    checksum=(state["checksum"] or "none")[:8],
                )
                return state
            # 远端不存在该 key
            return None
        except Exception as e:
            logger.warning(
                "context_sync_controller.fetch_remote_state_error",
                key=key,
                error=str(e),
            )
            return None

    @staticmethod
    def _resolve_conflict_version(
        local_version: int,
        remote_version: int,
        strategy: ConflictResolutionStrategy,
    ) -> int:
        """根据策略计算冲突解决后的版本号.

        Args:
            local_version: 本地版本号.
            remote_version: 远端版本号.
            strategy: 冲突解决策略.

        Returns:
            解决后的版本号.
        """
        if strategy == ConflictResolutionStrategy.LOCAL_WINS:
            return local_version
        elif strategy == ConflictResolutionStrategy.REMOTE_WINS:
            return remote_version
        elif strategy == ConflictResolutionStrategy.HIGHEST_VERSION:
            return max(local_version, remote_version)
        else:  # MANUAL
            return local_version  # 默认保留本地

    async def sync_session(self, session: SessionState) -> SyncResult:
        """同步会话状态.

        Args:
            session: 会话状态快照.

        Returns:
            同步结果.
        """
        item = SyncItem(
            item_id=f"session_{session.session_id}",
            key=f"session:{session.session_id}",
            value=session.model_dump(),
            version=session.sync_version,
        )
        result = await self._sync_single(item)
        return result

    @property
    def pending_count(self) -> int:
        """获取待同步条目数.

        Returns:
            待同步条目数量.
        """
        return len(self._pending_items)

    @property
    def conflict_registry(self) -> ConflictRegistry:
        """获取冲突注册表.

        Returns:
            ConflictRegistry 实例.
        """
        return self._conflict_registry
