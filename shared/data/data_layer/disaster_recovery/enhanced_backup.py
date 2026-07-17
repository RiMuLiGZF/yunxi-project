"""
云汐增强备份管理器 (Enhanced Backup Manager)

在现有 BackupManager 基础上增强：
- 全量备份：完整数据库备份（沿用已有实现）
- 增量备份：只备份变更数据（基于 SQLite 增量）
- 定时备份：按计划自动备份
- 备份验证：自动验证备份完整性
- 异地备份：支持备份到远程存储（本地目录模拟）

使用方式：
    from data_layer.disaster_recovery.enhanced_backup import EnhancedBackupManager

    ebm = EnhancedBackupManager(backup_root="./backups", data_root="./data")
    result = ebm.full_backup("mydb.db")
    result = ebm.incremental_backup("mydb.db")
    ebm.validate_backup("backup_001")
"""

from __future__ import annotations

import os
import sys
import json
import time
import gzip
import shutil
import sqlite3
import hashlib
import logging
import threading
from pathlib import Path
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)


# ============================================================
# 枚举
# ============================================================

class BackupMode(str, Enum):
    """备份模式"""
    FULL = "full"                    # 全量备份
    INCREMENTAL = "incremental"      # 增量备份
    DIFFERENTIAL = "differential"    # 差异备份


class ValidationLevel(str, Enum):
    """验证级别"""
    QUICK = "quick"          # 快速验证（文件存在、大小）
    CHECKSUM = "checksum"    # 校验和验证
    INTEGRITY = "integrity"  # 完整性验证（PRAGMA）
    FULL = "full"            # 完全验证（完整性 + 数据抽样）


# ============================================================
# 数据类
# ============================================================

@dataclass
class BackupSchedule:
    """备份计划"""
    schedule_id: str
    name: str
    mode: BackupMode = BackupMode.FULL
    database: str = ""
    interval_hours: float = 24.0      # 间隔小时数
    max_keep: int = 7                  # 保留份数
    enabled: bool = True
    last_run: float = 0.0
    next_run: float = 0.0
    validation_level: ValidationLevel = ValidationLevel.INTEGRITY
    remote_copy: bool = False          # 是否同步到异地
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BackupValidationResult:
    """备份验证结果"""
    backup_path: str
    level: ValidationLevel
    passed: bool = False
    file_exists: bool = False
    file_size_bytes: int = 0
    checksum_valid: bool = False
    checksum_expected: str = ""
    checksum_actual: str = ""
    integrity_passed: bool = False
    integrity_message: str = ""
    table_count: int = 0
    row_count_estimate: int = 0
    duration_seconds: float = 0.0
    error: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "backup_path": self.backup_path,
            "level": self.level.value,
            "passed": self.passed,
            "file_exists": self.file_exists,
            "file_size_bytes": self.file_size_bytes,
            "checksum_valid": self.checksum_valid,
            "integrity_passed": self.integrity_passed,
            "integrity_message": self.integrity_message,
            "table_count": self.table_count,
            "row_count_estimate": self.row_count_estimate,
            "duration_seconds": round(self.duration_seconds, 3),
            "error": self.error,
            "details": self.details,
        }


@dataclass
class RemoteBackupConfig:
    """异地备份配置"""
    enabled: bool = False
    remote_path: str = ""             # 远程路径（本地目录模拟）
    copy_full: bool = True            # 是否复制全量备份
    copy_incremental: bool = True     # 是否复制增量备份
    max_remote_backups: int = 10      # 远程保留数量
    sync_on_create: bool = True       # 创建时同步
    encryption: bool = False          # 是否加密
    compression: bool = True          # 是否压缩


@dataclass
class BackupInfo:
    """备份信息"""
    backup_id: str
    backup_type: BackupMode
    database: str
    backup_path: str
    size_bytes: int = 0
    created_at: float = 0.0
    checksum: str = ""
    parent_backup: str = ""           # 父备份（增量用）
    wal_start: int = 0                # WAL起始位置（增量用）
    wal_end: int = 0                  # WAL结束位置（增量用）
    validated: bool = False
    validation_level: str = ""
    remote_synced: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "backup_id": self.backup_id,
            "backup_type": self.backup_type.value,
            "database": self.database,
            "backup_path": self.backup_path,
            "size_bytes": self.size_bytes,
            "created_at": self.created_at,
            "checksum": self.checksum,
            "parent_backup": self.parent_backup,
            "wal_start": self.wal_start,
            "wal_end": self.wal_end,
            "validated": self.validated,
            "validation_level": self.validation_level,
            "remote_synced": self.remote_synced,
            "metadata": self.metadata,
        }


# ============================================================
# 增强备份管理器
# ============================================================

class EnhancedBackupManager:
    """
    增强备份管理器

    在基础备份功能上提供：
    - 增量备份（基于 WAL 日志）
    - 备份验证
    - 异地备份（本地目录模拟）
    - 备份元数据管理
    """

    META_FILENAME = "backup_meta.json"
    MANIFEST_FILENAME = "manifest.json"

    def __init__(
        self,
        backup_root: str,
        data_root: str,
        remote_config: Optional[RemoteBackupConfig] = None,
    ):
        self.backup_root = Path(backup_root).resolve()
        self.data_root = Path(data_root).resolve()
        self.remote_config = remote_config or RemoteBackupConfig()

        self.backup_root.mkdir(parents=True, exist_ok=True)

        # 备份索引
        self._index: Dict[str, BackupInfo] = {}
        self._index_by_db: Dict[str, List[str]] = {}
        self._lock = threading.RLock()

        # 加载已有索引
        self._load_index()

    # ------------------------------------------------------------------
    #  索引管理
    # ------------------------------------------------------------------

    def _index_file(self) -> Path:
        return self.backup_root / "backup_index.json"

    def _load_index(self) -> None:
        """加载备份索引"""
        index_file = self._index_file()
        if not index_file.exists():
            return

        try:
            with open(index_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            for backup_id, info_data in data.get("backups", {}).items():
                try:
                    info = BackupInfo(
                        backup_id=backup_id,
                        backup_type=BackupMode(info_data.get("backup_type", "full")),
                        database=info_data.get("database", ""),
                        backup_path=info_data.get("backup_path", ""),
                        size_bytes=info_data.get("size_bytes", 0),
                        created_at=info_data.get("created_at", 0),
                        checksum=info_data.get("checksum", ""),
                        parent_backup=info_data.get("parent_backup", ""),
                        wal_start=info_data.get("wal_start", 0),
                        wal_end=info_data.get("wal_end", 0),
                        validated=info_data.get("validated", False),
                        validation_level=info_data.get("validation_level", ""),
                        remote_synced=info_data.get("remote_synced", False),
                        metadata=info_data.get("metadata", {}),
                    )
                    self._index[backup_id] = info
                    db = info.database
                    if db not in self._index_by_db:
                        self._index_by_db[db] = []
                    self._index_by_db[db].append(backup_id)
                except Exception:
                    continue

            # 按时间排序
            for db in self._index_by_db:
                self._index_by_db[db].sort(
                    key=lambda bid: self._index[bid].created_at
                )

        except Exception as e:
            logger.warning("Failed to load backup index: %s", e)

    def _save_index(self) -> None:
        """保存备份索引"""
        index_file = self._index_file()
        try:
            data = {
                "version": "1.0",
                "updated_at": time.time(),
                "backups": {
                    bid: info.to_dict()
                    for bid, info in self._index.items()
                },
            }
            with open(index_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("Failed to save backup index: %s", e)

    def _add_to_index(self, info: BackupInfo) -> None:
        """添加备份到索引"""
        with self._lock:
            self._index[info.backup_id] = info
            db = info.database
            if db not in self._index_by_db:
                self._index_by_db[db] = []
            if info.backup_id not in self._index_by_db[db]:
                self._index_by_db[db].append(info.backup_id)
                self._index_by_db[db].sort(key=lambda bid: self._index[bid].created_at)
            self._save_index()

    # ------------------------------------------------------------------
    #  全量备份
    # ------------------------------------------------------------------

    def full_backup(self, db_filename: str, backup_name: Optional[str] = None) -> Dict[str, Any]:
        """
        执行全量备份

        Args:
            db_filename: 数据库文件名（相对于 data_root）
            backup_name: 可选的备份名称

        Returns:
            备份结果字典
        """
        start_time = time.time()
        db_path = self.data_root / db_filename
        if not db_path.exists():
            return {
                "success": False,
                "error": f"Database not found: {db_path}",
            }

        # 生成备份ID和目录
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_id = backup_name or f"full_{Path(db_filename).stem}_{timestamp}"
        backup_dir = self.backup_root / backup_id
        backup_dir.mkdir(parents=True, exist_ok=True)

        backup_file = backup_dir / f"{Path(db_filename).stem}.db"

        try:
            # 使用 SQLite 在线备份 API
            src_conn = sqlite3.connect(str(db_path))
            dst_conn = sqlite3.connect(str(backup_file))

            try:
                src_conn.backup(dst_conn, pages=50)
            finally:
                dst_conn.close()
                src_conn.close()

            # 计算校验和
            checksum = self._compute_sha256(str(backup_file))
            file_size = backup_file.stat().st_size

            # 写入元数据
            info = BackupInfo(
                backup_id=backup_id,
                backup_type=BackupMode.FULL,
                database=db_filename,
                backup_path=str(backup_dir),
                size_bytes=file_size,
                created_at=time.time(),
                checksum=checksum,
            )

            self._write_manifest(backup_dir, info)
            self._add_to_index(info)

            # 异地同步
            if self.remote_config.enabled and self.remote_config.sync_on_create and self.remote_config.copy_full:
                self._sync_to_remote(backup_dir, backup_id)
                info.remote_synced = True
                self._save_index()

            duration = time.time() - start_time

            return {
                "success": True,
                "backup_id": backup_id,
                "backup_type": "full",
                "backup_path": str(backup_dir),
                "size_bytes": file_size,
                "size_mb": round(file_size / (1024 * 1024), 2),
                "checksum": checksum,
                "duration_seconds": round(duration, 3),
            }

        except Exception as e:
            logger.error("Full backup failed: %s", e)
            # 清理失败的备份
            if backup_dir.exists():
                shutil.rmtree(backup_dir, ignore_errors=True)
            return {
                "success": False,
                "error": str(e),
            }

    # ------------------------------------------------------------------
    #  增量备份
    # ------------------------------------------------------------------

    def incremental_backup(self, db_filename: str, backup_name: Optional[str] = None) -> Dict[str, Any]:
        """
        执行增量备份

        基于 SQLite WAL 模式实现：备份 WAL 文件作为增量数据。
        如果数据库不在 WAL 模式，自动启用 WAL。

        Args:
            db_filename: 数据库文件名
            backup_name: 可选的备份名称

        Returns:
            备份结果字典
        """
        start_time = time.time()
        db_path = self.data_root / db_filename
        if not db_path.exists():
            return {
                "success": False,
                "error": f"Database not found: {db_path}",
            }

        # 确保 WAL 模式
        self._ensure_wal_mode(str(db_path))

        # 找最近的全量备份作为基准
        full_backup = self._get_latest_full_backup(db_filename)
        if not full_backup:
            # 没有全量备份，先做一次全量
            logger.info("No full backup found, performing initial full backup")
            return self.full_backup(db_filename, backup_name)

        # 生成备份ID和目录
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_id = backup_name or f"incr_{Path(db_filename).stem}_{timestamp}"
        backup_dir = self.backup_root / backup_id
        backup_dir.mkdir(parents=True, exist_ok=True)

        try:
            wal_path = db_path.with_suffix(db_path.suffix + "-wal")
            wal_size = 0
            wal_start = 0
            wal_end = 0

            # 获取当前WAL文件大小作为结束位置
            if wal_path.exists():
                wal_size = wal_path.stat().st_size
                wal_end = wal_size

            # 获取上一次增量的WAL位置
            last_incr = self._get_latest_incremental_backup(db_filename)
            if last_incr:
                wal_start = last_incr.wal_end

            # 执行检查点，将WAL写入主数据库文件
            conn = sqlite3.connect(str(db_path))
            try:
                conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
                conn.commit()
            finally:
                conn.close()

            # 复制 WAL 文件（如果存在且有内容）
            wal_backup = backup_dir / "wal"
            wal_data_file = backup_dir / "wal_data.bin"

            if wal_path.exists() and wal_size > 0:
                # 复制 WAL 文件中增量部分
                with open(wal_path, "rb") as f:
                    f.seek(wal_start)
                    incremental_data = f.read()

                if incremental_data:
                    with open(wal_data_file, "wb") as f:
                        f.write(incremental_data)

                    # 压缩增量数据
                    compressed_file = backup_dir / "wal_data.bin.gz"
                    with open(wal_data_file, "rb") as f_in:
                        with gzip.open(compressed_file, "wb") as f_out:
                            f_out.write(f_in.read())
                    wal_data_file.unlink(missing_ok=True)
                else:
                    # 没有新数据
                    wal_end = wal_start
            else:
                wal_end = wal_start

            # 计算增量数据大小
            incr_size = 0
            compressed_file = backup_dir / "wal_data.bin.gz"
            if compressed_file.exists():
                incr_size = compressed_file.stat().st_size

            # 计算校验和
            checksum = self._compute_dir_checksum(str(backup_dir))

            # 写入元数据
            info = BackupInfo(
                backup_id=backup_id,
                backup_type=BackupMode.INCREMENTAL,
                database=db_filename,
                backup_path=str(backup_dir),
                size_bytes=incr_size,
                created_at=time.time(),
                checksum=checksum,
                parent_backup=full_backup.backup_id,
                wal_start=wal_start,
                wal_end=wal_end,
            )

            self._write_manifest(backup_dir, info)
            self._add_to_index(info)

            # 异地同步
            if self.remote_config.enabled and self.remote_config.sync_on_create and self.remote_config.copy_incremental:
                self._sync_to_remote(backup_dir, backup_id)
                info.remote_synced = True
                self._save_index()

            duration = time.time() - start_time

            return {
                "success": True,
                "backup_id": backup_id,
                "backup_type": "incremental",
                "backup_path": str(backup_dir),
                "size_bytes": incr_size,
                "size_kb": round(incr_size / 1024, 2),
                "checksum": checksum,
                "parent_backup": full_backup.backup_id,
                "wal_start": wal_start,
                "wal_end": wal_end,
                "wal_new_bytes": wal_end - wal_start,
                "duration_seconds": round(duration, 3),
            }

        except Exception as e:
            logger.error("Incremental backup failed: %s", e)
            if backup_dir.exists():
                shutil.rmtree(backup_dir, ignore_errors=True)
            return {
                "success": False,
                "error": str(e),
            }

    # ------------------------------------------------------------------
    #  备份验证
    # ------------------------------------------------------------------

    def validate_backup(
        self,
        backup_id: str,
        level: ValidationLevel = ValidationLevel.INTEGRITY,
    ) -> BackupValidationResult:
        """
        验证备份完整性

        Args:
            backup_id: 备份ID
            level: 验证级别

        Returns:
            验证结果
        """
        start_time = time.time()
        result = BackupValidationResult(
            backup_path="",
            level=level,
        )

        with self._lock:
            info = self._index.get(backup_id)

        if not info:
            result.error = f"Backup not found: {backup_id}"
            result.duration_seconds = time.time() - start_time
            return result

        result.backup_path = info.backup_path
        backup_dir = Path(info.backup_path)

        # 1. 文件存在检查
        if not backup_dir.exists():
            result.error = "Backup directory not found"
            result.duration_seconds = time.time() - start_time
            return result

        result.file_exists = True

        # 计算目录大小
        total_size = 0
        for f in backup_dir.rglob("*"):
            if f.is_file():
                total_size += f.stat().st_size
        result.file_size_bytes = total_size

        if level == ValidationLevel.QUICK:
            result.passed = True
            result.duration_seconds = time.time() - start_time
            self._update_validation_status(backup_id, level, True)
            return result

        # 2. 校验和验证
        if level in (ValidationLevel.CHECKSUM, ValidationLevel.INTEGRITY, ValidationLevel.FULL):
            if info.checksum:
                if info.backup_type == BackupMode.FULL:
                    # 全量备份：验证数据库文件本身的校验和
                    db_file = self._find_db_file(backup_dir)
                    if db_file:
                        actual_checksum = self._compute_sha256(str(db_file))
                    else:
                        actual_checksum = ""
                else:
                    # 增量备份：验证整个目录的校验和（排除manifest）
                    actual_checksum = self._compute_dir_checksum(str(backup_dir))
                result.checksum_expected = info.checksum
                result.checksum_actual = actual_checksum
                result.checksum_valid = (actual_checksum == info.checksum)
            else:
                result.checksum_valid = True  # 没有校验和则跳过

            if level == ValidationLevel.CHECKSUM:
                result.passed = result.checksum_valid
                result.duration_seconds = time.time() - start_time
                self._update_validation_status(backup_id, level, result.passed)
                return result

        # 3. 完整性验证
        if level in (ValidationLevel.INTEGRITY, ValidationLevel.FULL):
            db_file = self._find_db_file(backup_dir)
            if db_file and info.backup_type == BackupMode.FULL:
                try:
                    conn = sqlite3.connect(str(db_file))
                    cursor = conn.cursor()

                    # PRAGMA integrity_check
                    cursor.execute("PRAGMA integrity_check")
                    integrity_result = cursor.fetchone()
                    result.integrity_message = integrity_result[0] if integrity_result else "unknown"
                    result.integrity_passed = (result.integrity_message == "ok")

                    # 表数量
                    cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
                    result.table_count = cursor.fetchone()[0]

                    # 估算行数
                    if result.table_count > 0:
                        try:
                            cursor.execute(
                                "SELECT SUM(seq) FROM sqlite_sequence"
                            )
                            row = cursor.fetchone()
                            if row and row[0]:
                                result.row_count_estimate = row[0]
                        except Exception:
                            # sqlite_sequence 表可能不存在（无AUTOINCREMENT表时）
                            pass

                    conn.close()

                    # 如果是FULL级别，执行数据抽样
                    if level == ValidationLevel.FULL:
                        self._full_validation_extra(cursor, result)

                except Exception as e:
                    result.integrity_passed = False
                    result.error = f"Integrity check error: {e}"

                result.passed = result.integrity_passed and result.checksum_valid
            else:
                # 增量备份只验证校验和
                result.integrity_passed = True
                result.passed = result.checksum_valid

        result.duration_seconds = time.time() - start_time
        self._update_validation_status(backup_id, level, result.passed)
        return result

    def _full_validation_extra(self, cursor: sqlite3.Cursor, result: BackupValidationResult) -> None:
        """完全验证的额外检查"""
        extra_checks = {}
        try:
            # 检查每个表是否可以查询
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            sample_ok = 0
            for table in tables[:10]:  # 最多检查10个表
                try:
                    cursor.execute(f"SELECT * FROM '{table}' LIMIT 1")
                    cursor.fetchone()
                    sample_ok += 1
                except Exception:
                    pass
            extra_checks["tables_sampled"] = len(tables)
            extra_checks["tables_accessible"] = sample_ok
        except Exception as e:
            extra_checks["error"] = str(e)

        result.details["full_validation"] = extra_checks

    def _update_validation_status(self, backup_id: str, level: ValidationLevel, passed: bool) -> None:
        """更新验证状态"""
        with self._lock:
            info = self._index.get(backup_id)
            if info:
                info.validated = passed
                info.validation_level = level.value
                self._save_index()

    # ------------------------------------------------------------------
    #  异地备份
    # ------------------------------------------------------------------

    def sync_to_remote(self, backup_id: str) -> bool:
        """手动同步备份到异地"""
        with self._lock:
            info = self._index.get(backup_id)
            if not info:
                return False

            backup_dir = Path(info.backup_path)
            if not backup_dir.exists():
                return False

            success = self._sync_to_remote(backup_dir, backup_id)
            if success:
                info.remote_synced = True
                self._save_index()
            return success

    def _sync_to_remote(self, backup_dir: Path, backup_id: str) -> bool:
        """同步备份到异地存储（本地目录模拟）"""
        if not self.remote_config.enabled:
            return False

        remote_path = Path(self.remote_config.remote_path)
        if not remote_path:
            return False

        try:
            remote_path.mkdir(parents=True, exist_ok=True)
            remote_backup = remote_path / backup_id

            if remote_backup.exists():
                shutil.rmtree(remote_backup)

            shutil.copytree(backup_dir, remote_backup)
            logger.info("Backup synced to remote: %s", backup_id)
            return True

        except Exception as e:
            logger.error("Remote sync failed: %s", e)
            return False

    def sync_all_to_remote(self) -> Dict[str, Any]:
        """同步所有未同步的备份到异地"""
        synced = []
        failed = []

        with self._lock:
            backups = list(self._index.values())

        for info in backups:
            if not info.remote_synced:
                if self.remote_config.copy_full and info.backup_type == BackupMode.FULL:
                    if self.sync_to_remote(info.backup_id):
                        synced.append(info.backup_id)
                    else:
                        failed.append(info.backup_id)
                elif self.remote_config.copy_incremental and info.backup_type == BackupMode.INCREMENTAL:
                    if self.sync_to_remote(info.backup_id):
                        synced.append(info.backup_id)
                    else:
                        failed.append(info.backup_id)

        return {
            "synced_count": len(synced),
            "failed_count": len(failed),
            "synced": synced,
            "failed": failed,
        }

    def cleanup_remote(self) -> int:
        """清理远程备份（按保留数量）"""
        if not self.remote_config.enabled:
            return 0

        remote_path = Path(self.remote_config.remote_path)
        if not remote_path.exists():
            return 0

        # 获取所有备份目录并按时间排序
        backups = []
        for d in remote_path.iterdir():
            if d.is_dir():
                manifest = d / self.MANIFEST_FILENAME
                if manifest.exists():
                    try:
                        with open(manifest, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        backups.append((data.get("created_at", 0), d))
                    except Exception:
                        pass

        # 按时间排序（新的在前）
        backups.sort(key=lambda x: x[0], reverse=True)

        # 删除超出保留数量的
        removed = 0
        for i, (_, d) in enumerate(backups):
            if i >= self.remote_config.max_remote_backups:
                shutil.rmtree(d, ignore_errors=True)
                removed += 1

        return removed

    # ------------------------------------------------------------------
    #  查询接口
    # ------------------------------------------------------------------

    def list_backups(
        self,
        database: Optional[str] = None,
        backup_type: Optional[BackupMode] = None,
    ) -> List[BackupInfo]:
        """列出备份"""
        with self._lock:
            if database:
                backup_ids = self._index_by_db.get(database, [])
                result = [self._index[bid] for bid in backup_ids if bid in self._index]
            else:
                result = list(self._index.values())

            if backup_type:
                result = [b for b in result if b.backup_type == backup_type]

            # 按时间倒序
            result.sort(key=lambda b: b.created_at, reverse=True)
            return result

    def get_backup(self, backup_id: str) -> Optional[BackupInfo]:
        """获取指定备份信息"""
        with self._lock:
            return self._index.get(backup_id)

    def get_latest_full_backup(self, database: str) -> Optional[BackupInfo]:
        """获取最新的全量备份"""
        return self._get_latest_full_backup(database)

    def _get_latest_full_backup(self, database: str) -> Optional[BackupInfo]:
        with self._lock:
            backup_ids = self._index_by_db.get(database, [])
            for bid in reversed(backup_ids):
                info = self._index.get(bid)
                if info and info.backup_type == BackupMode.FULL:
                    return info
        return None

    def _get_latest_incremental_backup(self, database: str) -> Optional[BackupInfo]:
        with self._lock:
            backup_ids = self._index_by_db.get(database, [])
            for bid in reversed(backup_ids):
                info = self._index.get(bid)
                if info and info.backup_type == BackupMode.INCREMENTAL:
                    return info
        return None

    def delete_backup(self, backup_id: str) -> bool:
        """删除备份"""
        with self._lock:
            info = self._index.get(backup_id)
            if not info:
                return False

            backup_dir = Path(info.backup_path)
            if backup_dir.exists():
                shutil.rmtree(backup_dir, ignore_errors=True)

            del self._index[backup_id]
            db = info.database
            if db in self._index_by_db:
                self._index_by_db[db] = [bid for bid in self._index_by_db[db] if bid != backup_id]

            self._save_index()
            logger.info("Backup deleted: %s", backup_id)
            return True

    # ------------------------------------------------------------------
    #  辅助方法
    # ------------------------------------------------------------------

    def _ensure_wal_mode(self, db_path: str) -> bool:
        """确保数据库使用 WAL 模式"""
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            result = cursor.fetchone()
            conn.close()
            return result and result[0].lower() == "wal"
        except Exception as e:
            logger.warning("Failed to enable WAL mode: %s", e)
            return False

    def _compute_sha256(self, file_path: str) -> str:
        """计算文件 SHA-256 校验和"""
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(64 * 1024)
                if not chunk:
                    break
                sha256.update(chunk)
        return sha256.hexdigest()

    def _compute_dir_checksum(self, dir_path: str) -> str:
        """计算目录的整体校验和"""
        sha256 = hashlib.sha256()
        d = Path(dir_path)
        files = sorted(f for f in d.rglob("*") if f.is_file())
        for f in files:
            # 排除 manifest 文件本身
            if f.name == self.MANIFEST_FILENAME:
                continue
            sha256.update(f.name.encode())
            with open(f, "rb") as fh:
                while True:
                    chunk = fh.read(64 * 1024)
                    if not chunk:
                        break
                    sha256.update(chunk)
        return sha256.hexdigest()

    def _find_db_file(self, backup_dir: Path) -> Optional[Path]:
        """在备份目录中查找 .db 文件"""
        for f in backup_dir.glob("*.db"):
            if f.is_file():
                return f
        return None

    def _write_manifest(self, backup_dir: Path, info: BackupInfo) -> None:
        """写入备份清单文件"""
        manifest_path = backup_dir / self.MANIFEST_FILENAME
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(info.to_dict(), f, ensure_ascii=False, indent=2)
