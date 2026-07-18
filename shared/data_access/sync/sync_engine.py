"""
数据同步器（Sync Engine）
========================

提供增量/全量同步、冲突检测与解决、进度跟踪、断点续传等能力。
"""

from __future__ import annotations

import time
import uuid
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ============================================================
# 枚举定义
# ============================================================

class ConflictResolution(str, Enum):
    """冲突解决策略"""
    LAST_WRITE_WINS = "last_write_wins"
    FIRST_WRITE_WINS = "first_write_wins"
    MERGE = "merge"
    MANUAL = "manual"


class SyncMode(str, Enum):
    """同步模式"""
    FULL = "full"
    INCREMENTAL = "incremental"


class SyncStatus(str, Enum):
    """同步状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


class SyncDirection(str, Enum):
    """同步方向"""
    PUSH = "push"
    PULL = "pull"
    BIDIRECTIONAL = "bidirectional"


# ============================================================
# 数据类
# ============================================================

@dataclass
class SyncConflict:
    """同步冲突记录"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    model_name: str = ""
    record_id: Any = None
    source_version: int = 0
    target_version: int = 0
    source_data: Dict[str, Any] = field(default_factory=dict)
    target_data: Dict[str, Any] = field(default_factory=dict)
    resolution: ConflictResolution = ConflictResolution.LAST_WRITE_WINS
    resolved: bool = False
    resolved_at: Optional[float] = None
    resolved_by: str = ""


@dataclass
class SyncProgress:
    """同步进度"""
    total: int = 0
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    conflicts: int = 0
    current_model: str = ""
    start_time: float = 0.0
    end_time: Optional[float] = None

    @property
    def percent(self) -> float:
        if self.total == 0:
            return 0.0
        return round(self.processed / self.total * 100, 2)

    @property
    def elapsed_ms(self) -> float:
        end = self.end_time or time.time()
        return (end - self.start_time) * 1000

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total": self.total,
            "processed": self.processed,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "conflicts": self.conflicts,
            "current_model": self.current_model,
            "percent": self.percent,
            "elapsed_ms": round(self.elapsed_ms, 2),
            "start_time": self.start_time,
            "end_time": self.end_time,
        }


@dataclass
class SyncRecord:
    """同步执行记录"""
    sync_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    mode: SyncMode = SyncMode.INCREMENTAL
    direction: SyncDirection = SyncDirection.BIDIRECTIONAL
    source: str = ""
    target: str = ""
    status: SyncStatus = SyncStatus.PENDING
    progress: SyncProgress = field(default_factory=SyncProgress)
    conflicts: List[SyncConflict] = field(default_factory=list)
    error_message: str = ""
    checkpoint: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sync_id": self.sync_id,
            "mode": self.mode.value,
            "direction": self.direction.value,
            "source": self.source,
            "target": self.target,
            "status": self.status.value,
            "progress": self.progress.to_dict(),
            "conflicts_count": len(self.conflicts),
            "error_message": self.error_message,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# ============================================================
# 同步端点抽象
# ============================================================

class SyncEndpoint(ABC):
    """
    同步端点抽象。

    源和目标都实现此接口，提供统一的数据读写能力。
    """

    @abstractmethod
    def get_name(self) -> str:
        ...

    @abstractmethod
    def list_models(self) -> List[str]:
        ...

    @abstractmethod
    def get_records(
        self,
        model_name: str,
        since_version: Optional[int] = None,
        since_timestamp: Optional[float] = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> Tuple[List[Dict[str, Any]], int]:
        ...

    @abstractmethod
    def get_record(self, model_name: str, record_id: Any) -> Optional[Dict[str, Any]]:
        ...

    @abstractmethod
    def upsert_record(self, model_name: str, data: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        ...

    @abstractmethod
    def delete_record(self, model_name: str, record_id: Any) -> bool:
        ...

    @abstractmethod
    def get_version(self, model_name: str) -> int:
        ...

    @abstractmethod
    def get_record_version(self, model_name: str, record_id: Any) -> int:
        ...


# ============================================================
# 基于 Repository 的同步端点
# ============================================================

class RepositorySyncEndpoint(SyncEndpoint):
    """
    基于 Repository 的同步端点实现。

    包装一组 Repository，提供 SyncEndpoint 接口。
    """

    def __init__(self, name: str, repositories: Dict[str, Any]):
        """
        Args:
            name: 端点名称
            repositories: {model_name: repository_instance} 字典
        """
        self._name = name
        self._repositories = repositories
        self._model_versions: Dict[str, int] = {}

    def get_name(self) -> str:
        return self._name

    def list_models(self) -> List[str]:
        return sorted(self._repositories.keys())

    def get_records(
        self,
        model_name: str,
        since_version: Optional[int] = None,
        since_timestamp: Optional[float] = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> Tuple[List[Dict[str, Any]], int]:
        repo = self._repositories.get(model_name)
        if not repo:
            return [], 0

        query = repo.query()

        if since_version is not None:
            query.add_filter("version", "gt", since_version)
        if since_timestamp is not None:
            query.add_filter("updated_at", "gt", since_timestamp)

        total = query.count()

        items = query.limit(limit).offset(offset).all()
        data_list = [item.to_dict() if hasattr(item, "to_dict") else item for item in items]

        return data_list, total

    def get_record(self, model_name: str, record_id: Any) -> Optional[Dict[str, Any]]:
        repo = self._repositories.get(model_name)
        if not repo:
            return None
        item = repo.get_by_id(record_id)
        if item is None:
            return None
        return item.to_dict() if hasattr(item, "to_dict") else item

    def upsert_record(self, model_name: str, data: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        repo = self._repositories.get(model_name)
        if not repo:
            return False, {}

        pk_field = "id"
        if hasattr(repo, "model_class") and repo.model_class:
            pk = repo.model_class.get_primary_key_field()
            if pk:
                pk_field = pk

        record_id = data.get(pk_field)

        if record_id is not None:
            existing = repo.get_by_id(record_id)
            if existing:
                # 更新
                updated = repo.update(record_id, data)
                if updated:
                    result = updated.to_dict() if hasattr(updated, "to_dict") else updated
                    return True, result
                return False, {}

        # 创建
        created = repo.create(data)
        result = created.to_dict() if hasattr(created, "to_dict") else created
        return True, result

    def delete_record(self, model_name: str, record_id: Any) -> bool:
        repo = self._repositories.get(model_name)
        if not repo:
            return False
        return repo.delete(record_id)

    def get_version(self, model_name: str) -> int:
        return self._model_versions.get(model_name, 0)

    def get_record_version(self, model_name: str, record_id: Any) -> int:
        data = self.get_record(model_name, record_id)
        if data and "version" in data:
            return int(data["version"] or 0)
        return 0

    def set_model_version(self, model_name: str, version: int) -> None:
        """设置模型版本号"""
        self._model_versions[model_name] = version


# ============================================================
# 同步引擎
# ============================================================

class SyncEngine:
    """
    数据同步引擎。

    支持增量/全量同步、冲突检测与解决、进度跟踪、断点续传。
    """

    def __init__(
        self,
        source: SyncEndpoint,
        target: SyncEndpoint,
        conflict_resolution: ConflictResolution = ConflictResolution.LAST_WRITE_WINS,
        batch_size: int = 100,
    ):
        self._source = source
        self._target = target
        self._conflict_resolution = conflict_resolution
        self._batch_size = batch_size
        self._sync_history: List[SyncRecord] = []
        self._active_sync: Optional[SyncRecord] = None
        self._callbacks: Dict[str, List[Callable]] = {
            "on_progress": [],
            "on_conflict": [],
            "on_complete": [],
            "on_error": [],
        }
        self._paused = False

    # ---- 回调 ----

    def on(self, event: str, callback: Callable) -> None:
        """注册事件回调"""
        if event not in self._callbacks:
            self._callbacks[event] = []
        self._callbacks[event].append(callback)

    def _fire(self, event: str, *args: Any, **kwargs: Any) -> None:
        for cb in self._callbacks.get(event, []):
            try:
                cb(*args, **kwargs)
            except Exception as e:
                logger.error(f"Sync callback error ({event}): {e}")

    # ---- 同步控制 ----

    def pause(self) -> None:
        """暂停同步"""
        self._paused = True
        if self._active_sync:
            self._active_sync.status = SyncStatus.PAUSED

    def resume(self) -> None:
        """恢复同步"""
        self._paused = False

    # ---- 同步执行 ----

    def sync(
        self,
        mode: SyncMode = SyncMode.INCREMENTAL,
        direction: SyncDirection = SyncDirection.BIDIRECTIONAL,
        models: Optional[List[str]] = None,
        checkpoint: Optional[Dict[str, Any]] = None,
    ) -> SyncRecord:
        """执行同步"""
        record = SyncRecord(
            mode=mode,
            direction=direction,
            source=self._source.get_name(),
            target=self._target.get_name(),
            status=SyncStatus.RUNNING,
            progress=SyncProgress(start_time=time.time()),
            checkpoint=checkpoint or {},
        )
        self._active_sync = record
        self._sync_history.append(record)
        self._paused = False

        try:
            if models is None:
                models = self._get_common_models()

            self._estimate_total(record, models, mode)

            if direction in (SyncDirection.PUSH, SyncDirection.BIDIRECTIONAL):
                self._sync_direction(record, self._source, self._target, models, mode)

            if direction in (SyncDirection.PULL, SyncDirection.BIDIRECTIONAL):
                self._sync_direction(record, self._target, self._source, models, mode)

            record.status = SyncStatus.COMPLETED
            record.progress.end_time = time.time()
            record.updated_at = time.time()
            self._fire("on_complete", record)

        except Exception as e:
            record.status = SyncStatus.FAILED
            record.error_message = str(e)
            record.progress.end_time = time.time()
            record.updated_at = time.time()
            logger.exception(f"Sync failed: {e}")
            self._fire("on_error", e)

        self._active_sync = None
        return record

    def _get_common_models(self) -> List[str]:
        source_models = set(self._source.list_models())
        target_models = set(self._target.list_models())
        return sorted(source_models & target_models)

    def _estimate_total(self, record: SyncRecord, models: List[str], mode: SyncMode) -> None:
        total = 0
        for model in models:
            try:
                _, count = self._source.get_records(model, limit=1, offset=0)
                total += count
            except Exception:
                pass
        if record.direction == SyncDirection.BIDIRECTIONAL:
            total *= 2
        record.progress.total = max(total, 1)

    def _sync_direction(
        self,
        record: SyncRecord,
        source: SyncEndpoint,
        target: SyncEndpoint,
        models: List[str],
        mode: SyncMode,
    ) -> None:
        for model in models:
            if self._paused:
                break
            record.progress.current_model = model
            self._sync_model(record, source, target, model, mode)

    def _sync_model(
        self,
        record: SyncRecord,
        source: SyncEndpoint,
        target: SyncEndpoint,
        model_name: str,
        mode: SyncMode,
    ) -> None:
        offset = 0
        since_version = None

        if mode == SyncMode.INCREMENTAL:
            try:
                since_version = target.get_version(model_name)
            except Exception:
                since_version = None

        while True:
            if self._paused:
                # 保存检查点
                record.checkpoint[f"{model_name}_offset"] = offset
                break

            try:
                records, _ = source.get_records(
                    model_name,
                    since_version=since_version,
                    limit=self._batch_size,
                    offset=offset,
                )
            except Exception as e:
                logger.error(f"Failed to fetch from {source.get_name()}/{model_name}: {e}")
                break

            if not records:
                break

            for data in records:
                self._sync_record(record, target, model_name, data)
                record.progress.processed += 1
                record.updated_at = time.time()
                self._fire("on_progress", record.progress)

            offset += len(records)
            if len(records) < self._batch_size:
                break

        # 更新目标端版本
        try:
            source_version = source.get_version(model_name)
            # 简化：同步完成后设置版本
            if hasattr(target, "set_model_version"):
                target.set_model_version(model_name, max(source_version, target.get_version(model_name)))  # type: ignore
        except Exception:
            pass

    def _sync_record(
        self,
        record: SyncRecord,
        target: SyncEndpoint,
        model_name: str,
        source_data: Dict[str, Any],
    ) -> None:
        record_id = source_data.get("id")
        if record_id is None:
            record.progress.failed += 1
            return

        try:
            target_record = target.get_record(model_name, record_id)

            if target_record is None:
                success, _ = target.upsert_record(model_name, source_data)
                if success:
                    record.progress.succeeded += 1
                else:
                    record.progress.failed += 1
                return

            source_version = int(source_data.get("version", 0) or 0)
            target_version = int(target_record.get("version", 0) or 0)

            if source_version == target_version:
                record.progress.succeeded += 1
                return

            if source_version > target_version:
                success, _ = target.upsert_record(model_name, source_data)
                if success:
                    record.progress.succeeded += 1
                else:
                    record.progress.failed += 1
                return

            # 目标版本更高，产生冲突
            conflict = SyncConflict(
                model_name=model_name,
                record_id=record_id,
                source_version=source_version,
                target_version=target_version,
                source_data=source_data,
                target_data=target_record,
                resolution=self._conflict_resolution,
            )
            self._resolve_conflict(conflict, target, model_name)
            record.conflicts.append(conflict)
            record.progress.conflicts += 1

            if conflict.resolved:
                record.progress.succeeded += 1
            else:
                record.progress.failed += 1

        except Exception as e:
            logger.error(f"Sync record {record_id} failed: {e}")
            record.progress.failed += 1

    def _resolve_conflict(
        self,
        conflict: SyncConflict,
        target: SyncEndpoint,
        model_name: str,
    ) -> None:
        if conflict.resolution == ConflictResolution.LAST_WRITE_WINS:
            # 目标版本更高，保留目标
            conflict.resolved = True
            conflict.resolved_at = time.time()
            conflict.resolved_by = "last_write_wins"

        elif conflict.resolution == ConflictResolution.FIRST_WRITE_WINS:
            success, _ = target.upsert_record(model_name, conflict.source_data)
            conflict.resolved = success
            conflict.resolved_at = time.time() if success else None
            conflict.resolved_by = "first_write_wins"

        elif conflict.resolution == ConflictResolution.MERGE:
            merged = dict(conflict.target_data)
            for key, value in conflict.source_data.items():
                if key not in merged or merged[key] is None:
                    merged[key] = value
            merged["version"] = max(conflict.source_version, conflict.target_version)
            success, _ = target.upsert_record(model_name, merged)
            conflict.resolved = success
            conflict.resolved_at = time.time() if success else None
            conflict.resolved_by = "merge"

        elif conflict.resolution == ConflictResolution.MANUAL:
            conflict.resolved = False
            conflict.resolved_by = "manual"

        self._fire("on_conflict", conflict)

    # ---- 查询 ----

    def get_active_sync(self) -> Optional[SyncRecord]:
        return self._active_sync

    def get_progress(self) -> Optional[SyncProgress]:
        if self._active_sync:
            return self._active_sync.progress
        return None

    def get_history(self, limit: int = 20) -> List[SyncRecord]:
        return sorted(
            self._sync_history,
            key=lambda r: r.created_at,
            reverse=True,
        )[:limit]

    def get_status(self) -> Dict[str, Any]:
        """获取同步引擎状态"""
        active = self._active_sync
        return {
            "is_syncing": active is not None,
            "active_sync": active.to_dict() if active else None,
            "history_count": len(self._sync_history),
            "source": self._source.get_name(),
            "target": self._target.get_name(),
            "conflict_resolution": self._conflict_resolution.value,
        }
