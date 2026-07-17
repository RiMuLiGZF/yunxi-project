"""
云汐数据恢复管理器 (Recovery Manager)

提供多种数据恢复能力：
- 全量恢复：从全量备份恢复
- 时间点恢复（PITR）：基于 WAL 日志的时间点恢复
- 恢复前自动备份当前数据（安全网）
- 恢复验证
- 恢复进度跟踪

使用方式：
    from data_layer.disaster_recovery.recovery_manager import RecoveryManager, RecoveryMode

    rm = RecoveryManager(backup_root="./backups", data_root="./data")
    result = rm.full_recovery("backup_001", "mydb.db")
    result = rm.pitr_recovery("backup_001", target_time=..., db_name="mydb.db")
"""

from __future__ import annotations

import os
import gzip
import time
import shutil
import sqlite3
import logging
import threading
from pathlib import Path
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Callable
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# ============================================================
# 枚举
# ============================================================

class RecoveryMode(str, Enum):
    """恢复模式"""
    FULL = "full"                    # 全量恢复
    POINT_IN_TIME = "point_in_time"  # 时间点恢复
    INCREMENTAL = "incremental"      # 增量恢复


class RecoveryPhase(str, Enum):
    """恢复阶段"""
    PENDING = "pending"
    PRE_BACKUP = "pre_backup"        # 恢复前备份
    RESTORING = "restoring"          # 恢复中
    VALIDATING = "validating"        # 验证中
    COMPLETED = "completed"          # 完成
    FAILED = "failed"                # 失败
    ROLLBACK = "rollback"            # 回滚中


# ============================================================
# 数据类
# ============================================================

@dataclass
class RecoveryProgress:
    """恢复进度"""
    recovery_id: str
    mode: RecoveryMode
    phase: RecoveryPhase = RecoveryPhase.PENDING
    progress_percent: float = 0.0
    current_step: str = ""
    total_steps: int = 0
    completed_steps: int = 0
    start_time: float = 0.0
    end_time: float = 0.0
    error: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "recovery_id": self.recovery_id,
            "mode": self.mode.value,
            "phase": self.phase.value,
            "progress_percent": round(self.progress_percent, 2),
            "current_step": self.current_step,
            "total_steps": self.total_steps,
            "completed_steps": self.completed_steps,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "elapsed_seconds": round(time.time() - self.start_time, 2) if self.start_time > 0 else 0,
            "error": self.error,
            "details": self.details,
        }


@dataclass
class RecoveryResult:
    """恢复结果"""
    success: bool = False
    recovery_id: str = ""
    mode: RecoveryMode = RecoveryMode.FULL
    backup_id: str = ""
    target_db: str = ""
    duration_seconds: float = 0.0
    safety_backup_id: str = ""
    table_count: int = 0
    row_count_estimate: int = 0
    validation_passed: bool = False
    error: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "recovery_id": self.recovery_id,
            "mode": self.mode.value,
            "backup_id": self.backup_id,
            "target_db": self.target_db,
            "duration_seconds": round(self.duration_seconds, 3),
            "safety_backup_id": self.safety_backup_id,
            "table_count": self.table_count,
            "row_count_estimate": self.row_count_estimate,
            "validation_passed": self.validation_passed,
            "error": self.error,
            "details": self.details,
        }


@dataclass
class PointInTimeRecovery:
    """时间点恢复配置"""
    target_time: float = 0.0              # 目标时间戳
    base_backup_id: str = ""              # 基准全量备份ID
    wal_files: List[str] = field(default_factory=list)  # 需要重放的WAL文件
    stop_before_table: str = ""           # 可选：在某表操作前停止
    stop_after_tx: str = ""               # 可选：在某事务后停止


# ============================================================
# 恢复管理器
# ============================================================

class RecoveryManager:
    """
    数据恢复管理器

    提供安全的数据恢复能力，包括：
    - 恢复前自动备份（安全网）
    - 恢复进度跟踪
    - 恢复验证
    - 失败回滚
    """

    def __init__(self, backup_root: str, data_root: str):
        self.backup_root = Path(backup_root).resolve()
        self.data_root = Path(data_root).resolve()

        self._progress: Dict[str, RecoveryProgress] = {}
        self._lock = threading.RLock()

        # 进度回调
        self._on_progress_callbacks: List[Callable[[RecoveryProgress], None]] = []

    # ------------------------------------------------------------------
    #  进度回调
    # ------------------------------------------------------------------

    def on_progress(self, callback: Callable[[RecoveryProgress], None]) -> None:
        """注册进度回调"""
        self._on_progress_callbacks.append(callback)

    def _fire_progress(self, progress: RecoveryProgress) -> None:
        for cb in self._on_progress_callbacks:
            try:
                cb(progress)
            except Exception as e:
                logger.error("Progress callback error: %s", e)

    def _update_progress(
        self,
        recovery_id: str,
        phase: Optional[RecoveryPhase] = None,
        step: Optional[str] = None,
        percent: Optional[float] = None,
        error: Optional[str] = None,
    ) -> None:
        """更新进度"""
        with self._lock:
            progress = self._progress.get(recovery_id)
            if not progress:
                return

            if phase:
                progress.phase = phase
            if step:
                progress.current_step = step
                progress.completed_steps += 1
            if percent is not None:
                progress.progress_percent = percent
            if error:
                progress.error = error

            if phase == RecoveryPhase.COMPLETED or phase == RecoveryPhase.FAILED:
                progress.end_time = time.time()

        self._fire_progress(progress)

    # ------------------------------------------------------------------
    #  全量恢复
    # ------------------------------------------------------------------

    def full_recovery(
        self,
        backup_id: str,
        target_db: str,
        create_safety_backup: bool = True,
        validate_after: bool = True,
    ) -> RecoveryResult:
        """
        执行全量恢复

        Args:
            backup_id: 备份ID
            target_db: 目标数据库文件名（相对于 data_root）
            create_safety_backup: 是否先创建当前数据的安全备份
            validate_after: 恢复后是否验证

        Returns:
            恢复结果
        """
        recovery_id = f"rec_{int(time.time() * 1000)}"
        result = RecoveryResult(
            recovery_id=recovery_id,
            mode=RecoveryMode.FULL,
            backup_id=backup_id,
            target_db=target_db,
        )

        # 初始化进度
        progress = RecoveryProgress(
            recovery_id=recovery_id,
            mode=RecoveryMode.FULL,
            total_steps=4,  # 安全备份 + 恢复 + 验证 + 完成
            start_time=time.time(),
        )
        with self._lock:
            self._progress[recovery_id] = progress

        start_time = time.time()

        try:
            # 步骤1：找到备份
            self._update_progress(recovery_id, step="locating_backup", percent=5)

            backup_dir = self.backup_root / backup_id
            if not backup_dir.exists():
                raise ValueError(f"Backup not found: {backup_id}")

            # 找到备份中的数据库文件
            db_file = self._find_db_in_backup(backup_dir)
            if not db_file:
                raise ValueError(f"No database file found in backup: {backup_id}")

            # 步骤2：创建安全备份
            if create_safety_backup:
                self._update_progress(
                    recovery_id,
                    phase=RecoveryPhase.PRE_BACKUP,
                    step="creating_safety_backup",
                    percent=15,
                )

                safety_backup_id = self._create_safety_backup(target_db)
                result.safety_backup_id = safety_backup_id

            # 步骤3：执行恢复
            self._update_progress(
                recovery_id,
                phase=RecoveryPhase.RESTORING,
                step="restoring_database",
                percent=40,
            )

            target_path = self.data_root / target_db
            target_path.parent.mkdir(parents=True, exist_ok=True)

            # 使用 SQLite backup API 恢复
            src_conn = sqlite3.connect(str(db_file))
            dst_conn = sqlite3.connect(str(target_path))

            try:
                src_conn.backup(dst_conn, pages=50)
            finally:
                dst_conn.close()
                src_conn.close()

            # 清理 WAL 相关文件
            wal_file = target_path.with_suffix(target_path.suffix + "-wal")
            shm_file = target_path.with_suffix(target_path.suffix + "-shm")
            for f in [wal_file, shm_file]:
                if f.exists():
                    f.unlink()

            self._update_progress(recovery_id, step="restore_complete", percent=70)

            # 步骤4：验证
            if validate_after:
                self._update_progress(
                    recovery_id,
                    phase=RecoveryPhase.VALIDATING,
                    step="validating_restored_db",
                    percent=80,
                )

                validation = self._validate_restored_db(str(target_path))
                result.validation_passed = validation["passed"]
                result.table_count = validation.get("table_count", 0)
                result.row_count_estimate = validation.get("row_count_estimate", 0)

                if not validation["passed"]:
                    # 验证失败，尝试回滚
                    logger.warning("Recovery validation failed, attempting rollback")
                    self._update_progress(
                        recovery_id,
                        phase=RecoveryPhase.ROLLBACK,
                        step="rolling_back",
                        percent=90,
                    )
                    raise ValueError(f"Validation failed: {validation.get('error', 'unknown')}")

            # 完成
            result.success = True
            self._update_progress(
                recovery_id,
                phase=RecoveryPhase.COMPLETED,
                step="recovery_completed",
                percent=100,
            )

        except Exception as e:
            result.success = False
            result.error = str(e)
            self._update_progress(
                recovery_id,
                phase=RecoveryPhase.FAILED,
                step="recovery_failed",
                error=str(e),
            )
            logger.error("Full recovery failed: %s", e)

        result.duration_seconds = time.time() - start_time
        return result

    # ------------------------------------------------------------------
    #  时间点恢复 (PITR)
    # ------------------------------------------------------------------

    def pitr_recovery(
        self,
        base_backup_id: str,
        target_db: str,
        target_time: Optional[float] = None,
        target_timestamp: Optional[str] = None,
        create_safety_backup: bool = True,
        validate_after: bool = True,
    ) -> RecoveryResult:
        """
        时间点恢复（Point-In-Time Recovery）

        基于全量备份 + WAL 日志重放，恢复到指定时间点。

        Args:
            base_backup_id: 基准全量备份ID
            target_db: 目标数据库文件名
            target_time: 目标时间戳（Unix时间）
            target_timestamp: 目标时间字符串（ISO格式）
            create_safety_backup: 是否创建安全备份
            validate_after: 恢复后是否验证

        Returns:
            恢复结果
        """
        # 解析目标时间
        if target_time is None and target_timestamp:
            try:
                target_time = datetime.fromisoformat(target_timestamp.replace("Z", "+00:00")).timestamp()
            except Exception:
                target_time = datetime.now().timestamp()

        if target_time is None:
            target_time = time.time()

        recovery_id = f"pitr_{int(time.time() * 1000)}"
        result = RecoveryResult(
            recovery_id=recovery_id,
            mode=RecoveryMode.POINT_IN_TIME,
            backup_id=base_backup_id,
            target_db=target_db,
        )

        # 初始化进度
        progress = RecoveryProgress(
            recovery_id=recovery_id,
            mode=RecoveryMode.POINT_IN_TIME,
            total_steps=5,
            start_time=time.time(),
            details={"target_time": target_time},
        )
        with self._lock:
            self._progress[recovery_id] = progress

        start_time = time.time()

        try:
            # 步骤1：定位基准备份
            self._update_progress(recovery_id, step="locating_base_backup", percent=5)

            backup_dir = self.backup_root / base_backup_id
            if not backup_dir.exists():
                raise ValueError(f"Base backup not found: {base_backup_id}")

            db_file = self._find_db_in_backup(backup_dir)
            if not db_file:
                raise ValueError(f"No database file in base backup: {base_backup_id}")

            # 步骤2：安全备份
            if create_safety_backup:
                self._update_progress(
                    recovery_id,
                    phase=RecoveryPhase.PRE_BACKUP,
                    step="creating_safety_backup",
                    percent=15,
                )
                result.safety_backup_id = self._create_safety_backup(target_db)

            # 步骤3：恢复基准备份
            self._update_progress(
                recovery_id,
                phase=RecoveryPhase.RESTORING,
                step="restoring_base_backup",
                percent=35,
            )

            target_path = self.data_root / target_db
            target_path.parent.mkdir(parents=True, exist_ok=True)

            src_conn = sqlite3.connect(str(db_file))
            dst_conn = sqlite3.connect(str(target_path))
            try:
                src_conn.backup(dst_conn, pages=50)
            finally:
                dst_conn.close()
                src_conn.close()

            # 步骤4：重放 WAL（模拟 PITR）
            # 注意：SQLite 的 PITR 比较复杂，这里提供简化的基于增量备份的实现
            self._update_progress(recovery_id, step="applying_wal", percent=60)

            wal_applied = self._apply_incremental_backups(
                base_backup_id, target_path, target_time
            )
            result.details["wal_applied"] = wal_applied

            # 步骤5：验证
            if validate_after:
                self._update_progress(
                    recovery_id,
                    phase=RecoveryPhase.VALIDATING,
                    step="validating",
                    percent=85,
                )
                validation = self._validate_restored_db(str(target_path))
                result.validation_passed = validation["passed"]
                result.table_count = validation.get("table_count", 0)
                result.row_count_estimate = validation.get("row_count_estimate", 0)

            result.success = True
            self._update_progress(
                recovery_id,
                phase=RecoveryPhase.COMPLETED,
                step="pitr_completed",
                percent=100,
            )

        except Exception as e:
            result.success = False
            result.error = str(e)
            self._update_progress(
                recovery_id,
                phase=RecoveryPhase.FAILED,
                step="pitr_failed",
                error=str(e),
            )
            logger.error("PITR recovery failed: %s", e)

        result.duration_seconds = time.time() - start_time
        return result

    # ------------------------------------------------------------------
    #  增量恢复
    # ------------------------------------------------------------------

    def incremental_recovery(
        self,
        base_backup_id: str,
        incremental_backup_ids: List[str],
        target_db: str,
        create_safety_backup: bool = True,
    ) -> RecoveryResult:
        """
        基于全量 + 增量备份链恢复

        Args:
            base_backup_id: 基准全量备份ID
            incremental_backup_ids: 增量备份ID列表（按顺序）
            target_db: 目标数据库

        Returns:
            恢复结果
        """
        recovery_id = f"incr_rec_{int(time.time() * 1000)}"
        result = RecoveryResult(
            recovery_id=recovery_id,
            mode=RecoveryMode.INCREMENTAL,
            backup_id=base_backup_id,
            target_db=target_db,
        )

        progress = RecoveryProgress(
            recovery_id=recovery_id,
            mode=RecoveryMode.INCREMENTAL,
            total_steps=4 + len(incremental_backup_ids),
            start_time=time.time(),
        )
        with self._lock:
            self._progress[recovery_id] = progress

        start_time = time.time()

        try:
            # 先恢复全量基准
            self._update_progress(recovery_id, phase=RecoveryPhase.RESTORING,
                                  step="restoring_base", percent=20)

            base_dir = self.backup_root / base_backup_id
            db_file = self._find_db_in_backup(base_dir)
            if not db_file:
                raise ValueError(f"Base backup database not found: {base_backup_id}")

            target_path = self.data_root / target_db
            target_path.parent.mkdir(parents=True, exist_ok=True)

            if create_safety_backup:
                self._update_progress(recovery_id, phase=RecoveryPhase.PRE_BACKUP,
                                      step="safety_backup", percent=10)
                result.safety_backup_id = self._create_safety_backup(target_db)

            src_conn = sqlite3.connect(str(db_file))
            dst_conn = sqlite3.connect(str(target_path))
            try:
                src_conn.backup(dst_conn, pages=50)
            finally:
                dst_conn.close()
                src_conn.close()

            # 依次应用增量备份
            for i, incr_id in enumerate(incremental_backup_ids):
                percent = 20 + (i + 1) / max(len(incremental_backup_ids), 1) * 60
                self._update_progress(
                    recovery_id,
                    step=f"applying_incremental_{i+1}/{len(incremental_backup_ids)}",
                    percent=percent,
                )

                applied = self._apply_single_incremental(incr_id, target_path)
                result.details[f"applied_{incr_id}"] = applied

            # 验证
            self._update_progress(recovery_id, phase=RecoveryPhase.VALIDATING,
                                  step="validating", percent=90)
            validation = self._validate_restored_db(str(target_path))
            result.validation_passed = validation["passed"]
            result.table_count = validation.get("table_count", 0)

            result.success = True
            self._update_progress(recovery_id, phase=RecoveryPhase.COMPLETED,
                                  step="done", percent=100)

        except Exception as e:
            result.success = False
            result.error = str(e)
            self._update_progress(recovery_id, phase=RecoveryPhase.FAILED,
                                  step="failed", error=str(e))

        result.duration_seconds = time.time() - start_time
        return result

    # ------------------------------------------------------------------
    #  回滚（恢复到安全备份）
    # ------------------------------------------------------------------

    def rollback(self, recovery_id: str) -> RecoveryResult:
        """
        回滚到恢复前的安全备份

        Args:
            recovery_id: 恢复操作ID

        Returns:
            回滚结果
        """
        with self._lock:
            progress = self._progress.get(recovery_id)

        if not progress or not progress.details.get("safety_backup_id"):
            return RecoveryResult(
                success=False,
                recovery_id=recovery_id,
                error="No safety backup available for rollback",
            )

        safety_id = progress.details["safety_backup_id"]
        target_db = progress.details.get("target_db", "")

        return self.full_recovery(
            backup_id=safety_id,
            target_db=target_db,
            create_safety_backup=False,
            validate_after=True,
        )

    # ------------------------------------------------------------------
    #  进度查询
    # ------------------------------------------------------------------

    def get_progress(self, recovery_id: str) -> Optional[RecoveryProgress]:
        """获取恢复进度"""
        with self._lock:
            return self._progress.get(recovery_id)

    def list_recoveries(self, limit: int = 20) -> List[RecoveryProgress]:
        """列出最近的恢复操作"""
        with self._lock:
            items = list(self._progress.values())
            items.sort(key=lambda p: p.start_time, reverse=True)
            return items[:limit]

    # ------------------------------------------------------------------
    #  内部辅助方法
    # ------------------------------------------------------------------

    def _find_db_in_backup(self, backup_dir: Path) -> Optional[Path]:
        """在备份目录中查找数据库文件"""
        for f in backup_dir.glob("*.db"):
            if f.is_file():
                return f
        return None

    def _create_safety_backup(self, target_db: str) -> str:
        """创建安全备份（恢复前备份当前数据）"""
        target_path = self.data_root / target_db
        if not target_path.exists():
            return ""

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safety_id = f"safety_{Path(target_db).stem}_{timestamp}"
        safety_dir = self.backup_root / safety_id
        safety_dir.mkdir(parents=True, exist_ok=True)

        safety_file = safety_dir / f"{Path(target_db).stem}.db"

        try:
            src_conn = sqlite3.connect(str(target_path))
            dst_conn = sqlite3.connect(str(safety_file))
            try:
                src_conn.backup(dst_conn, pages=50)
            finally:
                dst_conn.close()
                src_conn.close()

            # 写入清单
            manifest = {
                "backup_id": safety_id,
                "backup_type": "safety",
                "database": target_db,
                "created_at": time.time(),
                "purpose": "pre-recovery safety backup",
            }
            with open(safety_dir / "manifest.json", "w", encoding="utf-8") as f:
                import json
                json.dump(manifest, f, ensure_ascii=False, indent=2)

            return safety_id
        except Exception as e:
            logger.warning("Safety backup creation failed: %s", e)
            return ""

    def _validate_restored_db(self, db_path: str) -> Dict[str, Any]:
        """验证恢复后的数据库"""
        result = {
            "passed": False,
            "table_count": 0,
            "row_count_estimate": 0,
            "error": "",
        }

        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            # 完整性检查
            cursor.execute("PRAGMA integrity_check")
            integrity = cursor.fetchone()
            if integrity and integrity[0] != "ok":
                result["error"] = f"Integrity check failed: {integrity[0]}"
                conn.close()
                return result

            # 表数量
            cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
            result["table_count"] = cursor.fetchone()[0]

            # 估算行数
            try:
                cursor.execute("SELECT SUM(seq) FROM sqlite_sequence")
                row = cursor.fetchone()
                if row and row[0]:
                    result["row_count_estimate"] = row[0]
            except Exception:
                pass

            result["passed"] = True
            conn.close()

        except Exception as e:
            result["error"] = str(e)

        return result

    def _apply_incremental_backups(
        self,
        base_backup_id: str,
        target_path: Path,
        target_time: float,
    ) -> int:
        """应用增量备份到目标数据库（PITR 简化实现）"""
        # 读取备份索引
        index_file = self.backup_root / "backup_index.json"
        if not index_file.exists():
            return 0

        import json
        with open(index_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 找到基准备份之后的所有增量备份
        base_info = data.get("backups", {}).get(base_backup_id, {})
        base_time = base_info.get("created_at", 0)

        applied = 0
        # 收集增量备份并按时间排序
        incr_backups = []
        for bid, info in data.get("backups", {}).items():
            if info.get("backup_type") == "incremental":
                if info.get("created_at", 0) >= base_time and info.get("created_at", 0) <= target_time:
                    incr_backups.append((info.get("created_at", 0), bid, info))

        incr_backups.sort(key=lambda x: x[0])

        for _, bid, info in incr_backups:
            if self._apply_single_incremental(bid, target_path):
                applied += 1

        return applied

    def _apply_single_incremental(self, incr_id: str, target_path: Path) -> bool:
        """应用单个增量备份"""
        incr_dir = self.backup_root / incr_id
        if not incr_dir.exists():
            return False

        # 查找增量数据文件（压缩或未压缩）
        wal_file = incr_dir / "wal_data.bin.gz"
        if not wal_file.exists():
            wal_file = incr_dir / "wal_data.bin"

        if not wal_file.exists():
            return False

        try:
            # 读取增量数据
            if wal_file.suffix == ".gz":
                with gzip.open(wal_file, "rb") as f:
                    wal_data = f.read()
            else:
                with open(wal_file, "rb") as f:
                    wal_data = f.read()

            if not wal_data:
                return False

            # 将 WAL 数据写入目标数据库的 WAL 文件
            target_wal = target_path.with_suffix(target_path.suffix + "-wal")

            # 追加到现有 WAL（如果有）
            existing_wal = b""
            if target_wal.exists():
                with open(target_wal, "rb") as f:
                    existing_wal = f.read()

            with open(target_wal, "wb") as f:
                f.write(existing_wal + wal_data)

            # 执行检查点，将 WAL 合并到主数据库
            conn = sqlite3.connect(str(target_path))
            try:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                conn.commit()
            finally:
                conn.close()

            return True

        except Exception as e:
            logger.warning("Failed to apply incremental backup %s: %s", incr_id, e)
            return False
