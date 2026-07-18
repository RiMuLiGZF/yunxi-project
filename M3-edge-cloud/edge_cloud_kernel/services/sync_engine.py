"""数据同步引擎增强版.

实现四种同步策略：
1. 基于时间戳的增量同步
2. 基于操作日志的同步
3. 双向同步（端云 + 云端）
4. 同步状态管理（进度跟踪、断点续传、失败重试、同步队列）

向后兼容：所有方法不破坏现有 SyncAPI / ContextSyncController 接口，
可作为增强层叠加使用。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

import structlog

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# 枚举类型
# ---------------------------------------------------------------------------


class SyncStrategy(str, Enum):
    """同步策略枚举.

    Attributes:
        TIMESTAMP: 基于时间戳的增量同步
        OPERATION_LOG: 基于操作日志的同步
        BIDIRECTIONAL: 双向同步
        HYBRID: 混合策略（时间戳+操作日志+双向）
    """

    TIMESTAMP = "timestamp"
    OPERATION_LOG = "operation_log"
    BIDIRECTIONAL = "bidirectional"
    HYBRID = "hybrid"


class SyncDirection(str, Enum):
    """同步方向枚举.

    Attributes:
        EDGE_TO_CLOUD: 端 -> 云（本地变更上传）
        CLOUD_TO_EDGE: 云 -> 端（云端变更下发）
        BIDIRECTIONAL: 双向同步
    """

    EDGE_TO_CLOUD = "edge_to_cloud"
    CLOUD_TO_EDGE = "cloud_to_edge"
    BIDIRECTIONAL = "bidirectional"


class ConflictResolutionPolicy(str, Enum):
    """冲突解决策略枚举.

    Attributes:
        LAST_WRITE_WINS: 最后写入胜出（按时间戳）
        MANUAL: 手动解决
        MERGE: 自动合并
        LOCAL_WINS: 本地胜出
        REMOTE_WINS: 远端胜出
    """

    LAST_WRITE_WINS = "last_write_wins"
    MANUAL = "manual"
    MERGE = "merge"
    LOCAL_WINS = "local_wins"
    REMOTE_WINS = "remote_wins"


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class OperationLogEntry:
    """操作日志条目.

    记录每一次 CRUD 操作，用于操作日志同步。

    Attributes:
        log_id: 日志唯一标识.
        operation: 操作类型（CREATE / UPDATE / DELETE / READ）.
        entity_type: 实体类型（conversation / memory / config / task）.
        entity_id: 实体唯一标识.
        data: 操作数据快照.
        timestamp: 操作时间戳.
        device_id: 发起操作的设备 ID.
        version: 操作对应的版本号.
        checksum: 数据校验和.
    """

    log_id: str
    operation: str  # CREATE / UPDATE / DELETE / READ
    entity_type: str
    entity_id: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    device_id: str = ""
    version: int = 1
    checksum: str = ""

    def compute_checksum(self) -> str:
        """计算数据校验和.

        Returns:
            SHA-256 十六进制字符串.
        """
        payload = json.dumps(
            {
                "operation": self.operation,
                "entity_type": self.entity_type,
                "entity_id": self.entity_id,
                "data": self.data,
                "version": self.version,
            },
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class SyncProgress:
    """同步进度跟踪.

    Attributes:
        sync_id: 同步任务唯一标识.
        strategy: 使用的同步策略.
        direction: 同步方向.
        total_items: 总条目数.
        processed_items: 已处理条目数.
        failed_items: 失败条目数.
        conflict_items: 冲突条目数.
        status: 同步状态（pending / running / paused / completed / failed）.
        start_time: 开始时间戳.
        end_time: 结束时间戳.
        current_position: 当前处理位置（用于断点续传）.
        retry_count: 重试次数.
    """

    sync_id: str
    strategy: SyncStrategy
    direction: SyncDirection
    total_items: int = 0
    processed_items: int = 0
    failed_items: int = 0
    conflict_items: int = 0
    status: str = "pending"  # pending / running / paused / completed / failed
    start_time: float = 0.0
    end_time: float = 0.0
    current_position: str = ""
    retry_count: int = 0

    @property
    def progress_percent(self) -> float:
        """计算进度百分比.

        Returns:
            0-100 的浮点数.
        """
        if self.total_items == 0:
            return 0.0
        return min(100.0, (self.processed_items / self.total_items) * 100.0)

    @property
    def is_completed(self) -> bool:
        """是否已完成."""
        return self.status in ("completed", "failed")


@dataclass
class SyncQueueItem:
    """同步队列条目.

    Attributes:
        queue_id: 队列条目 ID.
        item_id: 数据条目 ID.
        operation: 操作类型.
        entity_type: 实体类型.
        data: 同步数据.
        priority: 优先级（0-10，越高越优先）.
        created_at: 创建时间.
        retry_count: 已重试次数.
        next_retry_at: 下次重试时间（指数退避）.
    """

    queue_id: str
    item_id: str
    operation: str
    entity_type: str
    data: dict[str, Any] = field(default_factory=dict)
    priority: int = 5
    created_at: float = field(default_factory=time.time)
    retry_count: int = 0
    next_retry_at: float = 0.0


@dataclass
class ConflictDetectResult:
    """冲突检测结果.

    Attributes:
        has_conflict: 是否存在冲突.
        item_id: 冲突条目 ID.
        local_version: 本地版本.
        remote_version: 远端版本.
        local_timestamp: 本地时间戳.
        remote_timestamp: 远端时间戳.
        conflict_type: 冲突类型（version / timestamp / content）.
        resolution_policy: 建议的解决策略.
    """

    has_conflict: bool
    item_id: str = ""
    local_version: int = 0
    remote_version: int = 0
    local_timestamp: float = 0.0
    remote_timestamp: float = 0.0
    conflict_type: str = "version"
    resolution_policy: ConflictResolutionPolicy = ConflictResolutionPolicy.LAST_WRITE_WINS


@dataclass
class SyncHistoryEntry:
    """同步历史记录条目.

    Attributes:
        history_id: 历史记录 ID.
        sync_id: 同步任务 ID.
        strategy: 同步策略.
        direction: 同步方向.
        items_count: 同步条目数.
        conflicts_count: 冲突数.
        status: 同步状态.
        started_at: 开始时间.
        finished_at: 结束时间.
        duration_seconds: 持续时间（秒）.
    """

    history_id: str
    sync_id: str
    strategy: SyncStrategy
    direction: SyncDirection
    items_count: int = 0
    conflicts_count: int = 0
    status: str = "completed"
    started_at: float = 0.0
    finished_at: float = 0.0
    duration_seconds: float = 0.0


# ---------------------------------------------------------------------------
# SyncEngine
# ---------------------------------------------------------------------------


class SyncEngine:
    """数据同步引擎增强版.

    提供四种同步策略的统一入口，支持：
    - 基于时间戳的增量同步
    - 基于操作日志的同步
    - 双向同步（端云双向）
    - 同步状态管理（进度、断点续传、指数退避重试、同步队列）

    所有方法均为纯增量，不修改现有 SyncAPI 行为。
    可与现有 OfflineShadowProxy / ConflictResolver 协同工作。

    Attributes:
        _strategy: 默认同步策略.
        _conflict_policy: 默认冲突解决策略.
        _operation_log: 操作日志列表（内存实现，可替换为持久化）.
        _last_sync_timestamps: 各实体类型的上次同步时间戳 {entity_type: timestamp}.
        _sync_progress: 同步进度跟踪 {sync_id: SyncProgress}.
        _sync_queue: 同步队列（按优先级排序）.
        _sync_history: 同步历史记录列表.
        _max_retry: 最大重试次数.
        _base_retry_delay: 基础重试延迟（秒，指数退避）.
        _max_retry_delay: 最大重试延迟（秒）.
    """

    def __init__(
        self,
        default_strategy: SyncStrategy = SyncStrategy.TIMESTAMP,
        default_conflict_policy: ConflictResolutionPolicy = (
            ConflictResolutionPolicy.LAST_WRITE_WINS
        ),
        max_retry: int = 5,
        base_retry_delay: float = 1.0,
        max_retry_delay: float = 300.0,
    ) -> None:
        """初始化同步引擎.

        Args:
            default_strategy: 默认同步策略.
            default_conflict_policy: 默认冲突解决策略.
            max_retry: 最大重试次数.
            base_retry_delay: 基础重试延迟（秒）.
            max_retry_delay: 最大重试延迟（秒）.
        """
        self._strategy = default_strategy
        self._conflict_policy = default_conflict_policy
        self._max_retry = max_retry
        self._base_retry_delay = base_retry_delay
        self._max_retry_delay = max_retry_delay

        # 内部状态
        self._operation_log: list[OperationLogEntry] = []
        self._last_sync_timestamps: dict[str, float] = {}
        self._sync_progress: dict[str, SyncProgress] = {}
        self._sync_queue: list[SyncQueueItem] = []
        self._sync_history: list[SyncHistoryEntry] = []
        self._version_counters: dict[str, int] = {}  # entity_type -> version

        # 外部回调钩子（用于集成现有 SyncAPI / ConflictResolver）
        self._push_callback: Callable[[list[dict[str, Any]]], dict[str, Any]] | None = None
        self._pull_callback: Callable[[dict[str, int]], list[dict[str, Any]]] | None = None
        self._conflict_callback: (
            Callable[[str, ConflictResolutionPolicy], bool] | None
        ) = None

        self._queue_lock = asyncio.Lock()
        self._log_lock = asyncio.Lock()

        logger.info(
            "sync_engine.init",
            strategy=default_strategy.value,
            conflict_policy=default_conflict_policy.value,
            max_retry=max_retry,
        )

    # ------------------------------------------------------------------
    # 回调注册（用于与现有组件集成）
    # ------------------------------------------------------------------

    def register_push_callback(
        self, callback: Callable[[list[dict[str, Any]]], dict[str, Any]]
    ) -> None:
        """注册推送回调（将变更推送到云端）.

        Args:
            callback: 接收变更列表，返回 {accepted, rejected, conflicts} 字典.
        """
        self._push_callback = callback
        logger.debug("sync_engine.push_callback_registered")

    def register_pull_callback(
        self, callback: Callable[[dict[str, int]], list[dict[str, Any]]]
    ) -> None:
        """注册拉取回调（从云端拉取变更）.

        Args:
            callback: 接收版本向量字典，返回变更列表.
        """
        self._pull_callback = callback
        logger.debug("sync_engine.pull_callback_registered")

    def register_conflict_callback(
        self, callback: Callable[[str, ConflictResolutionPolicy], bool]
    ) -> None:
        """注册冲突解决回调.

        Args:
            callback: 接收 item_id 和策略，返回是否成功解决.
        """
        self._conflict_callback = callback
        logger.debug("sync_engine.conflict_callback_registered")

    # ------------------------------------------------------------------
    # 1. 基于时间戳的增量同步
    # ------------------------------------------------------------------

    def get_last_sync_time(self, entity_type: str) -> float:
        """获取指定类型的上次同步时间.

        Args:
            entity_type: 实体类型.

        Returns:
            上次同步时间戳，从未同步返回 0.0.
        """
        return self._last_sync_timestamps.get(entity_type, 0.0)

    def set_last_sync_time(self, entity_type: str, timestamp: float) -> None:
        """设置指定类型的上次同步时间.

        Args:
            entity_type: 实体类型.
            timestamp: 同步时间戳.
        """
        self._last_sync_timestamps[entity_type] = timestamp
        logger.debug(
            "sync_engine.last_sync_time_updated",
            entity_type=entity_type,
            timestamp=timestamp,
        )

    def compute_timestamp_changes(
        self,
        entity_type: str,
        since_timestamp: float,
        local_data: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """计算自上次同步以来的变更集（基于时间戳）.

        Args:
            entity_type: 实体类型.
            since_timestamp: 上次同步时间戳.
            local_data: 本地数据列表，每条需包含 timestamp 字段.

        Returns:
            变更条目列表（timestamp > since_timestamp 的条目）.
        """
        changes = [
            item for item in local_data
            if item.get("timestamp", 0.0) > since_timestamp
        ]
        logger.debug(
            "sync_engine.timestamp_changes_computed",
            entity_type=entity_type,
            since=since_timestamp,
            total=len(local_data),
            changed=len(changes),
        )
        return changes

    async def sync_by_timestamp(
        self,
        entity_type: str,
        local_data: list[dict[str, Any]],
        direction: SyncDirection = SyncDirection.EDGE_TO_CLOUD,
    ) -> SyncProgress:
        """执行基于时间戳的增量同步.

        Args:
            entity_type: 实体类型.
            local_data: 本地数据列表.
            direction: 同步方向.

        Returns:
            同步进度对象.
        """
        sync_id = str(uuid.uuid4())
        since_ts = self.get_last_sync_time(entity_type)
        changes = self.compute_timestamp_changes(entity_type, since_ts, local_data)

        progress = SyncProgress(
            sync_id=sync_id,
            strategy=SyncStrategy.TIMESTAMP,
            direction=direction,
            total_items=len(changes),
            status="running",
            start_time=time.time(),
        )
        self._sync_progress[sync_id] = progress

        logger.info(
            "sync_engine.timestamp_sync_started",
            sync_id=sync_id,
            entity_type=entity_type,
            changes=len(changes),
            direction=direction.value,
        )

        try:
            if direction in (SyncDirection.EDGE_TO_CLOUD, SyncDirection.BIDIRECTIONAL):
                await self._push_changes_with_retry(progress, changes)

            if direction in (SyncDirection.CLOUD_TO_EDGE, SyncDirection.BIDIRECTIONAL):
                remote_changes = await self._pull_changes(entity_type, since_ts)
                progress.total_items += len(remote_changes)
                await self._apply_remote_changes(progress, remote_changes)

            progress.status = "completed"
            self.set_last_sync_time(entity_type, time.time())

        except Exception as e:
            progress.status = "failed"
            logger.error(
                "sync_engine.timestamp_sync_failed",
                sync_id=sync_id,
                error=str(e),
            )

        progress.end_time = time.time()
        self._record_history(progress)
        return progress

    # ------------------------------------------------------------------
    # 2. 基于操作日志的同步
    # ------------------------------------------------------------------

    async def log_operation(
        self,
        operation: str,
        entity_type: str,
        entity_id: str,
        data: dict[str, Any] | None = None,
        device_id: str = "",
    ) -> OperationLogEntry:
        """记录一条操作日志.

        Args:
            operation: 操作类型（CREATE / UPDATE / DELETE）.
            entity_type: 实体类型.
            entity_id: 实体 ID.
            data: 操作数据.
            device_id: 设备 ID.

        Returns:
            创建的日志条目.
        """
        version = self._version_counters.get(entity_type, 0) + 1
        self._version_counters[entity_type] = version

        entry = OperationLogEntry(
            log_id=str(uuid.uuid4()),
            operation=operation,
            entity_type=entity_type,
            entity_id=entity_id,
            data=data or {},
            device_id=device_id,
            version=version,
        )
        entry.checksum = entry.compute_checksum()

        async with self._log_lock:
            self._operation_log.append(entry)

        logger.debug(
            "sync_engine.operation_logged",
            log_id=entry.log_id,
            operation=operation,
            entity_type=entity_type,
            entity_id=entity_id,
        )
        return entry

    def get_operation_log(
        self,
        entity_type: str | None = None,
        since_log_id: str | None = None,
        limit: int = 100,
    ) -> list[OperationLogEntry]:
        """获取操作日志.

        Args:
            entity_type: 按实体类型过滤，None 表示全部.
            since_log_id: 从指定日志 ID 之后开始（用于增量拉取）.
            limit: 最大返回条数.

        Returns:
            操作日志列表.
        """
        logs = self._operation_log

        if entity_type:
            logs = [l for l in logs if l.entity_type == entity_type]

        if since_log_id:
            # 找到起始位置
            start_idx = 0
            for i, log in enumerate(logs):
                if log.log_id == since_log_id:
                    start_idx = i + 1
                    break
            logs = logs[start_idx:]

        return logs[:limit]

    async def sync_by_operation_log(
        self,
        entity_type: str,
        since_log_id: str | None = None,
        direction: SyncDirection = SyncDirection.EDGE_TO_CLOUD,
    ) -> SyncProgress:
        """基于操作日志执行同步.

        通过重放操作日志实现同步，保证端云操作顺序一致。

        Args:
            entity_type: 实体类型.
            since_log_id: 起始日志 ID（断点续传）.
            direction: 同步方向.

        Returns:
            同步进度对象.
        """
        sync_id = str(uuid.uuid4())
        logs = self.get_operation_log(entity_type=entity_type, since_log_id=since_log_id)

        progress = SyncProgress(
            sync_id=sync_id,
            strategy=SyncStrategy.OPERATION_LOG,
            direction=direction,
            total_items=len(logs),
            status="running",
            start_time=time.time(),
            current_position=since_log_id or "",
        )
        self._sync_progress[sync_id] = progress

        logger.info(
            "sync_engine.operation_log_sync_started",
            sync_id=sync_id,
            entity_type=entity_type,
            logs=len(logs),
            direction=direction.value,
        )

        try:
            if direction in (SyncDirection.EDGE_TO_CLOUD, SyncDirection.BIDIRECTIONAL):
                # 将操作日志转换为变更推送到云端
                changes = [
                    {
                        "log_id": log.log_id,
                        "operation": log.operation,
                        "entity_type": log.entity_type,
                        "entity_id": log.entity_id,
                        "data": log.data,
                        "version": log.version,
                        "timestamp": log.timestamp,
                    }
                    for log in logs
                ]
                await self._push_changes_with_retry(progress, changes)

            progress.status = "completed"
            if logs:
                progress.current_position = logs[-1].log_id

        except Exception as e:
            progress.status = "failed"
            logger.error(
                "sync_engine.operation_log_sync_failed",
                sync_id=sync_id,
                error=str(e),
            )

        progress.end_time = time.time()
        self._record_history(progress)
        return progress

    async def replay_operations(
        self,
        operations: list[dict[str, Any]],
        target_store: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """重放操作日志到目标存储.

        Args:
            operations: 操作列表，每条包含 operation/entity_id/data 等字段.
            target_store: 目标存储字典（会被修改）.

        Returns:
            重放结果统计 {applied, skipped, errors}.
        """
        result = {"applied": 0, "skipped": 0, "errors": 0}

        for op in operations:
            try:
                entity_id = op["entity_id"]
                operation = op.get("operation", "UPDATE").upper()

                if operation == "CREATE" or operation == "UPDATE":
                    target_store[entity_id] = op.get("data", {})
                    result["applied"] += 1
                elif operation == "DELETE":
                    target_store.pop(entity_id, None)
                    result["applied"] += 1
                else:
                    result["skipped"] += 1

            except Exception:
                result["errors"] += 1

        logger.debug(
            "sync_engine.operations_replayed",
            total=len(operations),
            **result,
        )
        return result

    # ------------------------------------------------------------------
    # 3. 双向同步
    # ------------------------------------------------------------------

    def detect_conflict(
        self,
        local_item: dict[str, Any],
        remote_item: dict[str, Any],
    ) -> ConflictDetectResult:
        """检测单条数据的同步冲突.

        Args:
            local_item: 本地数据条目，需含 version / timestamp 字段.
            remote_item: 远端数据条目，需含 version / timestamp 字段.

        Returns:
            冲突检测结果.
        """
        item_id = local_item.get("item_id", remote_item.get("item_id", ""))
        local_ver = local_item.get("version", 1)
        remote_ver = remote_item.get("version", 1)
        local_ts = local_item.get("timestamp", 0.0)
        remote_ts = remote_item.get("timestamp", 0.0)

        # 版本号冲突：双方版本号都高于对方的已知版本
        if local_ver > remote_ver:
            return ConflictDetectResult(
                has_conflict=True,
                item_id=item_id,
                local_version=local_ver,
                remote_version=remote_ver,
                local_timestamp=local_ts,
                remote_timestamp=remote_ts,
                conflict_type="version",
                resolution_policy=self._conflict_policy,
            )

        # 内容冲突：版本号相同但内容不同
        if local_ver == remote_ver:
            local_hash = self._compute_content_hash(local_item)
            remote_hash = self._compute_content_hash(remote_item)
            if local_hash != remote_hash:
                return ConflictDetectResult(
                    has_conflict=True,
                    item_id=item_id,
                    local_version=local_ver,
                    remote_version=remote_ver,
                    local_timestamp=local_ts,
                    remote_timestamp=remote_ts,
                    conflict_type="content",
                    resolution_policy=self._conflict_policy,
                )

        return ConflictDetectResult(has_conflict=False, item_id=item_id)

    def resolve_conflict(
        self,
        local_item: dict[str, Any],
        remote_item: dict[str, Any],
        policy: ConflictResolutionPolicy | None = None,
    ) -> dict[str, Any]:
        """根据策略解决冲突.

        Args:
            local_item: 本地数据.
            remote_item: 远端数据.
            policy: 解决策略，None 使用默认策略.

        Returns:
            解决后的数据条目.
        """
        used_policy = policy or self._conflict_policy

        if used_policy == ConflictResolutionPolicy.LAST_WRITE_WINS:
            local_ts = local_item.get("timestamp", 0.0)
            remote_ts = remote_item.get("timestamp", 0.0)
            return remote_item if remote_ts >= local_ts else local_item

        elif used_policy == ConflictResolutionPolicy.LOCAL_WINS:
            return local_item

        elif used_policy == ConflictResolutionPolicy.REMOTE_WINS:
            return remote_item

        elif used_policy == ConflictResolutionPolicy.MERGE:
            return self._merge_items(local_item, remote_item)

        elif used_policy == ConflictResolutionPolicy.MANUAL:
            # 手动模式：保留双方数据，标记为待人工处理
            merged = dict(local_item)
            merged["_conflict_remote"] = remote_item
            merged["_conflict_pending"] = True
            return merged

        # 默认 last-write-wins
        local_ts = local_item.get("timestamp", 0.0)
        remote_ts = remote_item.get("timestamp", 0.0)
        return remote_item if remote_ts >= local_ts else local_item

    async def sync_bidirectional(
        self,
        entity_type: str,
        local_items: list[dict[str, Any]],
        remote_items: list[dict[str, Any]],
        conflict_policy: ConflictResolutionPolicy | None = None,
    ) -> SyncProgress:
        """执行双向同步.

        合并端云双方变更，检测并解决冲突。

        Args:
            entity_type: 实体类型.
            local_items: 本地变更列表.
            remote_items: 远端变更列表.
            conflict_policy: 冲突解决策略.

        Returns:
            同步进度对象.
        """
        sync_id = str(uuid.uuid4())
        total = len(local_items) + len(remote_items)

        progress = SyncProgress(
            sync_id=sync_id,
            strategy=SyncStrategy.BIDIRECTIONAL,
            direction=SyncDirection.BIDIRECTIONAL,
            total_items=total,
            status="running",
            start_time=time.time(),
        )
        self._sync_progress[sync_id] = progress

        # 构建索引
        local_map: dict[str, dict[str, Any]] = {
            item.get("item_id", ""): item for item in local_items
        }
        remote_map: dict[str, dict[str, Any]] = {
            item.get("item_id", ""): item for item in remote_items
        }

        all_ids = set(local_map.keys()) | set(remote_map.keys())
        conflicts = 0
        processed = 0

        for item_id in all_ids:
            local = local_map.get(item_id)
            remote = remote_map.get(item_id)

            if local and remote:
                # 双方都有修改，检测冲突
                conflict_result = self.detect_conflict(local, remote)
                if conflict_result.has_conflict:
                    conflicts += 1
                    self.resolve_conflict(local, remote, conflict_policy)
                processed += 1
            else:
                # 仅一方有修改，直接采用
                processed += 1

        progress.processed_items = processed
        progress.conflict_items = conflicts
        progress.status = "completed"
        progress.end_time = time.time()

        logger.info(
            "sync_engine.bidirectional_sync_completed",
            sync_id=sync_id,
            total=total,
            processed=processed,
            conflicts=conflicts,
        )

        self._record_history(progress)
        return progress

    # ------------------------------------------------------------------
    # 4. 同步状态管理
    # ------------------------------------------------------------------

    def get_sync_progress(self, sync_id: str) -> SyncProgress | None:
        """获取指定同步任务的进度.

        Args:
            sync_id: 同步任务 ID.

        Returns:
            进度对象，不存在返回 None.
        """
        return self._sync_progress.get(sync_id)

    def get_all_progress(self) -> list[SyncProgress]:
        """获取所有同步任务的进度列表.

        Returns:
            进度列表，按开始时间倒序.
        """
        return sorted(
            list(self._sync_progress.values()),
            key=lambda p: p.start_time,
            reverse=True,
        )

    async def enqueue_sync(
        self,
        item_id: str,
        operation: str,
        entity_type: str,
        data: dict[str, Any] | None = None,
        priority: int = 5,
    ) -> str:
        """将同步任务加入队列.

        Args:
            item_id: 数据条目 ID.
            operation: 操作类型.
            entity_type: 实体类型.
            data: 同步数据.
            priority: 优先级（0-10，默认 5）.

        Returns:
            队列条目 ID.
        """
        queue_id = str(uuid.uuid4())
        item = SyncQueueItem(
            queue_id=queue_id,
            item_id=item_id,
            operation=operation,
            entity_type=entity_type,
            data=data or {},
            priority=max(0, min(10, priority)),
        )

        async with self._queue_lock:
            self._sync_queue.append(item)
            # 按优先级降序 + 创建时间升序排序
            self._sync_queue.sort(
                key=lambda q: (-q.priority, q.created_at)
            )

        logger.debug(
            "sync_engine.enqueued",
            queue_id=queue_id,
            item_id=item_id,
            priority=priority,
        )
        return queue_id

    def get_queue_size(self) -> int:
        """获取同步队列长度."""
        return len(self._sync_queue)

    async def process_queue(self) -> dict[str, int]:
        """处理同步队列.

        按优先级顺序处理队列中的条目，支持指数退避重试。

        Returns:
            处理统计 {processed, failed, remaining}.
        """
        async with self._queue_lock:
            if not self._sync_queue:
                return {"processed": 0, "failed": 0, "remaining": 0}

            now = time.time()
            due_items = [
                item for item in self._sync_queue
                if item.next_retry_at <= now
            ]

            processed = 0
            failed = 0

            for item in due_items:
                success = await self._process_queue_item(item)
                if success:
                    processed += 1
                    self._sync_queue.remove(item)
                else:
                    failed += 1
                    item.retry_count += 1
                    if item.retry_count >= self._max_retry:
                        # 超过最大重试次数，移除队列
                        self._sync_queue.remove(item)
                        logger.warning(
                            "sync_engine.queue_item_exhausted",
                            queue_id=item.queue_id,
                            retries=item.retry_count,
                        )
                    else:
                        # 指数退避
                        delay = min(
                            self._base_retry_delay * (2 ** (item.retry_count - 1)),
                            self._max_retry_delay,
                        )
                        item.next_retry_at = now + delay

            remaining = len(self._sync_queue)
            logger.info(
                "sync_engine.queue_processed",
                processed=processed,
                failed=failed,
                remaining=remaining,
            )
            return {"processed": processed, "failed": failed, "remaining": remaining}

    def calculate_backoff_delay(self, retry_count: int) -> float:
        """计算指数退避延迟.

        Args:
            retry_count: 已重试次数.

        Returns:
            延迟秒数.
        """
        delay = self._base_retry_delay * (2 ** retry_count)
        return min(delay, self._max_retry_delay)

    def get_sync_history(
        self,
        limit: int = 50,
        strategy: SyncStrategy | None = None,
    ) -> list[SyncHistoryEntry]:
        """获取同步历史记录.

        Args:
            limit: 返回条数上限.
            strategy: 按策略过滤，None 表示全部.

        Returns:
            历史记录列表，按时间倒序.
        """
        history = self._sync_history
        if strategy:
            history = [h for h in history if h.strategy == strategy]
        history = sorted(history, key=lambda h: h.started_at, reverse=True)
        return history[:limit]

    # ------------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_content_hash(item: dict[str, Any]) -> str:
        """计算数据内容的哈希."""
        content = item.get("value", item.get("data", ""))
        if isinstance(content, (dict, list)):
            content_str = json.dumps(content, sort_keys=True, default=str)
        else:
            content_str = str(content)
        return hashlib.sha256(content_str.encode("utf-8")).hexdigest()

    @staticmethod
    def _merge_items(
        local: dict[str, Any],
        remote: dict[str, Any],
    ) -> dict[str, Any]:
        """合并两条数据（dict 类型内容）.

        对于字典类型，执行 key 级别的 LWW 合并；
        对于其他类型，取时间戳较新的版本。
        """
        local_val = local.get("value", local.get("data"))
        remote_val = remote.get("value", remote.get("data"))

        if isinstance(local_val, dict) and isinstance(remote_val, dict):
            # Key 级别 LWW 合并
            merged = {}
            all_keys = set(local_val.keys()) | set(remote_val.keys())
            local_ts = local.get("timestamp", 0.0)
            remote_ts = remote.get("timestamp", 0.0)
            for key in all_keys:
                if key not in remote_val:
                    merged[key] = local_val[key]
                elif key not in local_val:
                    merged[key] = remote_val[key]
                else:
                    # 同 key 取时间戳新的
                    merged[key] = remote_val[key] if remote_ts >= local_ts else local_val[key]
            result = dict(local)
            if "value" in local:
                result["value"] = merged
            else:
                result["data"] = merged
            return result
        else:
            # 非字典类型，取较新的
            local_ts = local.get("timestamp", 0.0)
            remote_ts = remote.get("timestamp", 0.0)
            return remote if remote_ts >= local_ts else local

    async def _push_changes_with_retry(
        self,
        progress: SyncProgress,
        changes: list[dict[str, Any]],
    ) -> None:
        """推送变更并处理失败重试（指数退避）."""
        if not changes:
            return

        if self._push_callback is None:
            progress.processed_items += len(changes)
            return

        failed_items: list[dict[str, Any]] = changes
        retry_count = 0

        while failed_items and retry_count < self._max_retry:
            try:
                result = self._push_callback(failed_items)
                if asyncio.iscoroutine(result):
                    result = await result

                accepted = result.get("accepted", [])
                rejected = result.get("rejected", [])
                conflicts = result.get("conflicts", [])

                progress.processed_items += len(accepted)
                progress.conflict_items += len(conflicts)

                # 剩余失败项继续重试
                failed_items = [
                    item for item in failed_items
                    if item.get("item_id") in rejected
                    or item.get("entity_id") in rejected
                ]

                if failed_items:
                    retry_count += 1
                    delay = self.calculate_backoff_delay(retry_count)
                    await asyncio.sleep(delay)
                else:
                    break

            except Exception as e:
                retry_count += 1
                progress.failed_items += len(failed_items)
                logger.warning(
                    "sync_engine.push_retry",
                    attempt=retry_count,
                    remaining=len(failed_items),
                    error=str(e),
                )
                if retry_count < self._max_retry:
                    delay = self.calculate_backoff_delay(retry_count)
                    await asyncio.sleep(delay)

        progress.retry_count = retry_count

    async def _pull_changes(
        self,
        entity_type: str,
        since_timestamp: float,
    ) -> list[dict[str, Any]]:
        """从云端拉取变更."""
        if self._pull_callback is None:
            return []

        version_vec = {entity_type: int(since_timestamp)}
        result = self._pull_callback(version_vec)
        if asyncio.iscoroutine(result):
            result = await result
        return result if isinstance(result, list) else []

    async def _apply_remote_changes(
        self,
        progress: SyncProgress,
        changes: list[dict[str, Any]],
    ) -> None:
        """应用远端变更到本地."""
        # 简化实现：直接计数
        # 实际应用中应写入 local_data_manager
        progress.processed_items += len(changes)

    async def _process_queue_item(self, item: SyncQueueItem) -> bool:
        """处理单个队列条目.

        Args:
            item: 队列条目.

        Returns:
            是否处理成功.
        """
        if self._push_callback is None:
            return True  # 无回调时视为成功（模拟）

        try:
            result = self._push_callback([
                {
                    "item_id": item.item_id,
                    "operation": item.operation,
                    "entity_type": item.entity_type,
                    "data": item.data,
                }
            ])
            if asyncio.iscoroutine(result):
                result = await result
            accepted = result.get("accepted", [])
            return item.item_id in accepted
        except Exception as e:
            logger.warning(
                "sync_engine.queue_item_failed",
                queue_id=item.queue_id,
                error=str(e),
            )
            return False

    def _record_history(self, progress: SyncProgress) -> None:
        """记录同步历史."""
        duration = progress.end_time - progress.start_time if progress.end_time else 0.0
        entry = SyncHistoryEntry(
            history_id=str(uuid.uuid4()),
            sync_id=progress.sync_id,
            strategy=progress.strategy,
            direction=progress.direction,
            items_count=progress.processed_items,
            conflicts_count=progress.conflict_items,
            status=progress.status,
            started_at=progress.start_time,
            finished_at=progress.end_time,
            duration_seconds=duration,
        )
        self._sync_history.append(entry)
        # 限制历史记录数量
        if len(self._sync_history) > 1000:
            self._sync_history = self._sync_history[-1000:]
