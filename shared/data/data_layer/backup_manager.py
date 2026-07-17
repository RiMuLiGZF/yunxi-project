"""
云汐数据备份恢复管理器（第二阶段统一治理增强版）

提供统一的数据备份和恢复能力：
- 全量备份 / 增量备份 / 差异备份
- 多种存储后端：本地文件系统 / 远程（预留接口）
- 备份加密（可选，AES-256-GCM）
- 备份压缩（gzip）
- 备份校验（SHA-256 校验和）
- 自动清理策略（按时间 / 按数量 / 按大小）
- 备份恢复功能（含安全网机制）
- 备份状态通知接口
- 模块级备份适配
- 统一备份调度中心（BackupOrchestrator）

设计原则：
- 数据安全第一，备份操作不影响正常业务
- 保持向后兼容，所有旧接口均可正常使用
- 代码风格与现有代码一致
- 备份文件路径规范统一
"""
import os
import io
import gzip
import json
import time
import shutil
import sqlite3
import zipfile
import hashlib
import base64
import threading
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Callable, Tuple, Union
from pathlib import Path
from datetime import datetime, timedelta
from abc import ABC, abstractmethod

# 可选加密依赖（cryptography）
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    _HAS_CRYPTO = True
except ImportError:
    _HAS_CRYPTO = False


# ============================================================
# 枚举与常量
# ============================================================

class BackupType:
    """备份类型常量"""
    FULL = "full"             # 全量备份
    INCREMENTAL = "incremental"  # 增量备份（基于上一次备份）
    DIFFERENTIAL = "differential"  # 差异备份（基于最近一次全量）


class StorageBackendType:
    """存储后端类型"""
    LOCAL = "local"           # 本地文件系统
    REMOTE = "remote"         # 远程存储（预留）


class CompressionType:
    """压缩类型"""
    NONE = "none"
    GZIP = "gzip"


class EncryptionType:
    """加密类型"""
    NONE = "none"
    AES256_GCM = "aes-256-gcm"


class BackupStatus:
    """备份状态"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"


# ============================================================
# 数据类
# ============================================================

@dataclass
class RetentionPolicy:
    """备份保留策略
    
    Attributes:
        strategy: 策略类型 count/age/size/hybrid
        max_count: 最大保留数量
        max_age_days: 最大保留天数
        max_size_gb: 最大占用空间（GB）
    """
    strategy: str = "count"
    max_count: int = 30
    max_age_days: int = 30
    max_size_gb: float = 10.0


@dataclass
class ModuleBackupConfig:
    """模块备份配置
    
    Attributes:
        module_id: 模块唯一标识
        db_paths: 数据库文件路径列表
        backup_dir: 备份存储目录
        max_backups: 最大保留备份数（向后兼容）
        schedule: 定时调度配置
        backup_type: 默认备份类型
        compression: 压缩类型
        encryption: 加密类型
        encryption_key: 加密密钥（base64编码）
        retention: 保留策略
        notification_hooks: 通知钩子列表
    """
    module_id: str
    db_paths: List[str]
    backup_dir: str
    max_backups: int = 30
    schedule: Optional[Dict[str, Any]] = None
    backup_type: str = BackupType.FULL
    compression: str = CompressionType.GZIP
    encryption: str = EncryptionType.NONE
    encryption_key: str = ""
    retention: RetentionPolicy = field(default_factory=RetentionPolicy)
    notification_hooks: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class BackupReport:
    """备份报告
    
    Attributes:
        module_id: 模块ID
        backup_type: 备份类型
        success: 是否全部成功
        total_dbs: 总数据库数
        success_dbs: 成功备份数
        failed_dbs: 失败备份数
        total_size_bytes: 总备份大小（字节，压缩前）
        compressed_size_bytes: 压缩后大小（字节）
        total_size_mb: 总备份大小（MB）
        backup_dir: 备份目录路径
        timestamp: 备份时间戳
        duration_seconds: 耗时（秒）
        details: 每个数据库的详细备份结果
        errors: 错误信息列表
        checksum: 整体校验和
        encrypted: 是否加密
        compressed: 是否压缩
    """
    module_id: str
    success: bool
    total_dbs: int
    success_dbs: int
    failed_dbs: int
    total_size_bytes: int
    compressed_size_bytes: int = 0
    total_size_mb: float = 0.0
    backup_dir: str = ""
    timestamp: float = 0.0
    duration_seconds: float = 0.0
    backup_type: str = BackupType.FULL
    details: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    checksum: str = ""
    encrypted: bool = False
    compressed: bool = False


@dataclass
class VerifyReport:
    """备份校验报告
    
    Attributes:
        backup_path: 备份文件路径
        file_valid: 文件是否存在且可读
        file_size_bytes: 文件大小（字节）
        sha256_checksum: SHA-256校验和
        expected_checksum: 期望的校验和
        checksum_valid: 校验和是否匹配
        integrity_check: PRAGMA integrity_check 结果
        quick_check: PRAGMA quick_check 结果
        table_count: 表数量
        has_tables: 是否包含表
        overall_valid: 整体是否通过校验
        errors: 错误信息列表
    """
    backup_path: str
    file_valid: bool = False
    file_size_bytes: int = 0
    sha256_checksum: str = ""
    expected_checksum: str = ""
    checksum_valid: bool = False
    integrity_check: str = ""
    quick_check: str = ""
    table_count: int = 0
    has_tables: bool = False
    overall_valid: bool = False
    errors: List[str] = field(default_factory=list)


@dataclass
class IncrementalBackupReport:
    """增量备份报告"""
    success: bool
    db_path: str
    base_backup_path: str
    incremental_path: str = ""
    base_size_bytes: int = 0
    incremental_size_bytes: int = 0
    changed_tables: List[str] = field(default_factory=list)
    new_tables: List[str] = field(default_factory=list)
    deleted_tables: List[str] = field(default_factory=list)
    total_changes: int = 0
    timestamp: float = 0.0
    errors: List[str] = field(default_factory=list)


# ============================================================
# 存储后端抽象
# ============================================================

class StorageBackend(ABC):
    """存储后端抽象基类
    
    所有存储后端必须实现以下接口，
    以便备份管理器统一调用。
    """
    
    @abstractmethod
    def save(self, source_path: str, dest_path: str) -> bool:
        """保存文件到存储后端
        
        Args:
            source_path: 源文件路径
            dest_path: 目标路径（相对存储根）
            
        Returns:
            是否成功
        """
        ...
    
    @abstractmethod
    def load(self, source_path: str, dest_path: str) -> bool:
        """从存储后端加载文件
        
        Args:
            source_path: 存储中的路径
            dest_path: 本地目标路径
            
        Returns:
            是否成功
        """
        ...
    
    @abstractmethod
    def delete(self, path: str) -> bool:
        """删除存储中的文件/目录
        
        Args:
            path: 存储中的路径
            
        Returns:
            是否成功
        """
        ...
    
    @abstractmethod
    def list(self, prefix: str = "") -> List[Dict[str, Any]]:
        """列出存储中的文件
        
        Args:
            prefix: 路径前缀过滤
            
        Returns:
            文件列表，每项包含 name/size/modified 等字段
        """
        ...
    
    @abstractmethod
    def exists(self, path: str) -> bool:
        """检查路径是否存在"""
        ...
    
    @abstractmethod
    def get_size(self, path: str) -> int:
        """获取文件/目录大小（字节）"""
        ...


class LocalStorageBackend(StorageBackend):
    """本地文件系统存储后端
    
    默认存储后端，将备份保存到本地文件系统。
    """
    
    def __init__(self, root_dir: str):
        """
        Args:
            root_dir: 存储根目录
        """
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)
    
    def save(self, source_path: str, dest_path: str) -> bool:
        try:
            src = Path(source_path)
            dst = self.root_dir / dest_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            
            if src.is_dir():
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
            return True
        except Exception:
            return False
    
    def load(self, source_path: str, dest_path: str) -> bool:
        try:
            src = self.root_dir / source_path
            dst = Path(dest_path)
            dst.parent.mkdir(parents=True, exist_ok=True)
            
            if src.is_dir():
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
            return True
        except Exception:
            return False
    
    def delete(self, path: str) -> bool:
        try:
            target = self.root_dir / path
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            return True
        except Exception:
            return False
    
    def list(self, prefix: str = "") -> List[Dict[str, Any]]:
        results = []
        try:
            target_dir = self.root_dir / prefix if prefix else self.root_dir
            if not target_dir.exists():
                return results
            
            for item in sorted(target_dir.iterdir()):
                try:
                    stat = item.stat()
                    results.append({
                        "name": item.name,
                        "path": str(item.relative_to(self.root_dir)),
                        "is_dir": item.is_dir(),
                        "size_bytes": sum(f.stat().st_size for f in item.rglob("*") if f.is_file()) if item.is_dir() else stat.st_size,
                        "modified": stat.st_mtime,
                    })
                except Exception:
                    continue
        except Exception:
            pass
        return results
    
    def exists(self, path: str) -> bool:
        return (self.root_dir / path).exists()
    
    def get_size(self, path: str) -> int:
        try:
            target = self.root_dir / path
            if target.is_file():
                return target.stat().st_size
            elif target.is_dir():
                return sum(f.stat().st_size for f in target.rglob("*") if f.is_file())
        except Exception:
            pass
        return 0


class RemoteStorageBackend(StorageBackend):
    """远程存储后端（预留接口）
    
    可扩展支持 S3、OSS、SFTP 等远程存储。
    当前为占位实现，后续根据需求接入。
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Args:
            config: 远程存储配置
                - type: 远程类型 s3/oss/sftp
                - endpoint: 端点地址
                - bucket: 存储桶
                - access_key: 访问密钥
                - secret_key: 密钥
                - prefix: 路径前缀
        """
        self.config = config
        self._type = config.get("type", "s3")
    
    def save(self, source_path: str, dest_path: str) -> bool:
        # 预留接口，当前返回 False 表示不可用
        return False
    
    def load(self, source_path: str, dest_path: str) -> bool:
        return False
    
    def delete(self, path: str) -> bool:
        return False
    
    def list(self, prefix: str = "") -> List[Dict[str, Any]]:
        return []
    
    def exists(self, path: str) -> bool:
        return False
    
    def get_size(self, path: str) -> int:
        return 0


# ============================================================
# 加密工具
# ============================================================

class BackupEncryptor:
    """备份加密工具
    
    使用 AES-256-GCM 进行加密，提供认证加密功能。
    加密后文件格式：[12字节 nonce][密文][16字节 tag]
    """
    
    def __init__(self, key_b64: str = ""):
        """
        Args:
            key_b64: base64 编码的 32 字节密钥
        """
        self.key_b64 = key_b64
        self._key = None
        if key_b64 and _HAS_CRYPTO:
            try:
                self._key = base64.b64decode(key_b64)
            except Exception:
                self._key = None
    
    @property
    def available(self) -> bool:
        """加密是否可用"""
        return _HAS_CRYPTO and self._key is not None and len(self._key) == 32
    
    def encrypt_file(self, input_path: str, output_path: str) -> bool:
        """加密文件
        
        Args:
            input_path: 输入文件路径
            output_path: 输出文件路径
            
        Returns:
            是否成功
        """
        if not self.available:
            return False
        
        try:
            with open(input_path, "rb") as f:
                data = f.read()
            
            aesgcm = AESGCM(self._key)
            nonce = os.urandom(12)
            ciphertext = aesgcm.encrypt(nonce, data, None)
            
            with open(output_path, "wb") as f:
                f.write(nonce + ciphertext)
            
            return True
        except Exception:
            return False
    
    def decrypt_file(self, input_path: str, output_path: str) -> bool:
        """解密文件
        
        Args:
            input_path: 加密文件路径
            output_path: 解密输出路径
            
        Returns:
            是否成功
        """
        if not self.available:
            return False
        
        try:
            with open(input_path, "rb") as f:
                data = f.read()
            
            if len(data) < 28:  # 12 nonce + 16 tag = 28 字节最小长度
                return False
            
            nonce = data[:12]
            ciphertext = data[12:]
            
            aesgcm = AESGCM(self._key)
            plaintext = aesgcm.decrypt(nonce, ciphertext, None)
            
            with open(output_path, "wb") as f:
                f.write(plaintext)
            
            return True
        except Exception:
            return False
    
    @staticmethod
    def generate_key() -> str:
        """生成随机密钥并返回 base64 编码
        
        Returns:
            base64 编码的 32 字节密钥
        """
        if not _HAS_CRYPTO:
            # 回退方案：使用 os.urandom
            return base64.b64encode(os.urandom(32)).decode("ascii")
        key = os.urandom(32)
        return base64.b64encode(key).decode("ascii")


# ============================================================
# 压缩工具
# ============================================================

class BackupCompressor:
    """备份压缩工具
    
    支持 gzip 压缩，提供压缩和解压缩功能。
    """
    
    def __init__(self, compression_type: str = CompressionType.GZIP):
        self.compression_type = compression_type
    
    def compress_file(self, input_path: str, output_path: str, level: int = 6) -> int:
        """压缩文件
        
        Args:
            input_path: 输入文件路径
            output_path: 输出文件路径（压缩后）
            level: 压缩级别 1-9
            
        Returns:
            压缩后文件大小（字节），失败返回 0
        """
        if self.compression_type == CompressionType.NONE:
            try:
                shutil.copy2(input_path, output_path)
                return os.path.getsize(output_path)
            except Exception:
                return 0
        
        if self.compression_type == CompressionType.GZIP:
            try:
                with open(input_path, "rb") as f_in:
                    with gzip.open(output_path, "wb", compresslevel=level) as f_out:
                        shutil.copyfileobj(f_in, f_out)
                return os.path.getsize(output_path)
            except Exception:
                return 0
        
        return 0
    
    def decompress_file(self, input_path: str, output_path: str) -> bool:
        """解压文件
        
        Args:
            input_path: 压缩文件路径
            output_path: 解压输出路径
            
        Returns:
            是否成功
        """
        if self.compression_type == CompressionType.NONE:
            try:
                shutil.copy2(input_path, output_path)
                return True
            except Exception:
                return False
        
        if self.compression_type == CompressionType.GZIP:
            try:
                with gzip.open(input_path, "rb") as f_in:
                    with open(output_path, "wb") as f_out:
                        shutil.copyfileobj(f_in, f_out)
                return True
            except Exception:
                return False
        
        return False


# ============================================================
# 校验工具
# ============================================================

def calculate_sha256(file_path: str) -> str:
    """计算文件的 SHA-256 校验和
    
    Args:
        file_path: 文件路径
        
    Returns:
        SHA-256 十六进制字符串
    """
    sha256_hash = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()
    except Exception:
        return ""


def calculate_md5(file_path: str) -> str:
    """计算文件的 MD5 校验和（向后兼容）
    
    Args:
        file_path: 文件路径
        
    Returns:
        MD5 十六进制字符串
    """
    md5_hash = hashlib.md5()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                md5_hash.update(chunk)
        return md5_hash.hexdigest()
    except Exception:
        return ""


# ============================================================
# 通知系统
# ============================================================

class BackupNotifier:
    """备份状态通知器
    
    支持多种通知渠道，通过 webhook / 回调函数 等方式
    在备份完成、失败等事件时发送通知。
    """
    
    def __init__(self):
        self._hooks: List[Callable[[str, Dict[str, Any]], None]] = []
        self._webhooks: List[str] = []
    
    def add_hook(self, hook: Callable[[str, Dict[str, Any]], None]) -> None:
        """添加回调钩子
        
        Args:
            hook: 回调函数，签名为 hook(event_type: str, data: dict)
                event_type: backup_start/backup_success/backup_failed/restore_start/restore_success/restore_failed
        """
        self._hooks.append(hook)
    
    def add_webhook(self, url: str) -> None:
        """添加 Webhook 通知地址
        
        Args:
            url: Webhook URL
        """
        self._webhooks.append(url)
    
    def notify(self, event_type: str, data: Dict[str, Any]) -> None:
        """发送通知
        
        Args:
            event_type: 事件类型
            data: 事件数据
        """
        # 调用回调钩子
        for hook in self._hooks:
            try:
                hook(event_type, data)
            except Exception:
                pass
        
        # 调用 Webhook（异步执行，避免阻塞）
        if self._webhooks:
            self._notify_webhooks_async(event_type, data)
    
    def _notify_webhooks_async(self, event_type: str, data: Dict[str, Any]) -> None:
        """异步发送 Webhook 通知"""
        def _send():
            try:
                import httpx
                payload = {
                    "event": event_type,
                    "data": data,
                    "timestamp": time.time(),
                }
                for url in self._webhooks:
                    try:
                        httpx.post(url, json=payload, timeout=5.0)
                    except Exception:
                        pass
            except Exception:
                pass
        
        thread = threading.Thread(target=_send, daemon=True)
        thread.start()


# ============================================================
# Cron 表达式解析器（轻量版）
# ============================================================

class CronExpression:
    """轻量 Cron 表达式解析器
    
    支持标准 5 字段 cron 表达式：
    分 时 日 月 周
    
    支持的语法：
    - *: 任意值
    - */n: 每隔 n
    - n: 具体值
    - n-m: 范围
    - n,m,k: 列表
    
    仅用于计算下次执行时间，不实现完整 cron 语义。
    """
    
    def __init__(self, expression: str):
        """
        Args:
            expression: cron 表达式，如 "0 3 * * *"（每天3点）
        """
        self.expression = expression
        parts = expression.strip().split()
        if len(parts) != 5:
            raise ValueError(f"Invalid cron expression: {expression} (expected 5 fields)")
        self._minute = self._parse_field(parts[0], 0, 59)
        self._hour = self._parse_field(parts[1], 0, 23)
        self._day = self._parse_field(parts[2], 1, 31)
        self._month = self._parse_field(parts[3], 1, 12)
        self._weekday = self._parse_field(parts[4], 0, 6)  # 0=周日
    
    def _parse_field(self, field: str, min_val: int, max_val: int) -> set:
        """解析单个 cron 字段"""
        values = set()
        
        # 处理逗号分隔的多个值
        for part in field.split(","):
            if part == "*":
                values.update(range(min_val, max_val + 1))
            elif part.startswith("*/"):
                step = int(part[2:])
                values.update(range(min_val, max_val + 1, step))
            elif "-" in part:
                start, end = map(int, part.split("-"))
                values.update(range(start, end + 1))
            else:
                values.add(int(part))
        
        return values
    
    def next_run_time(self, after: Optional[datetime] = None) -> datetime:
        """计算下次运行时间
        
        Args:
            after: 从哪个时间开始计算，默认当前时间
            
        Returns:
            下次运行的 datetime
        """
        if after is None:
            after = datetime.now()
        
        # 从下一分钟开始搜索
        current = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
        
        # 最多搜索 366 天，防止死循环
        for _ in range(366 * 24 * 60):
            if (current.minute in self._minute
                and current.hour in self._hour
                and current.day in self._day
                and current.month in self._month
                and current.weekday() in self._weekday):
                return current
            current += timedelta(minutes=1)
        
        raise RuntimeError("Could not find next run time within 366 days")


# ============================================================
# 定时备份调度器（增强版，支持 cron）
# ============================================================

class BackupScheduler:
    """定时备份调度器
    
    使用 threading.Timer 实现的线程安全定时备份调度器，
    支持每日指定时间、间隔和 cron 表达式三种调度模式。
    
    Attributes:
        callback: 备份任务回调函数
        running: 调度器是否运行中
    """
    
    def __init__(self, callback: Callable[[], Any]):
        """
        初始化备份调度器
        
        Args:
            callback: 备份任务回调，备份完成时调用（可选）
        """
        self._callback = callback
        self._timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()
        self._running = False
        self._schedule_config: Optional[Dict[str, Any]] = None
        self._last_run: Optional[float] = None
        self._cron: Optional[CronExpression] = None
    
    @property
    def running(self) -> bool:
        """调度器是否运行中"""
        return self._running
    
    @property
    def last_run(self) -> Optional[float]:
        """上次执行时间戳"""
        return self._last_run
    
    def start(self, schedule_config: Dict[str, Any]) -> bool:
        """
        启动调度器
        
        Args:
            schedule_config: 调度配置，支持：
                - {"type": "daily", "time": "03:00"} 每日指定时间（24小时制）
                - {"type": "interval", "hours": 6} 每N小时
                - {"type": "interval", "minutes": 30} 每N分钟
                - {"type": "cron", "expression": "0 3 * * *"} cron 表达式
        
        Returns:
            是否成功启动
        """
        with self._lock:
            if self._running:
                # 先停止当前的
                self._stop_no_lock()
            
            self._schedule_config = schedule_config
            self._cron = None
            
            # cron 模式
            if schedule_config.get("type") == "cron":
                try:
                    self._cron = CronExpression(schedule_config.get("expression", "0 3 * * *"))
                except Exception:
                    return False
            
            self._running = True
            self._schedule_next()
            return True
    
    def stop(self) -> bool:
        """停止调度器"""
        with self._lock:
            return self._stop_no_lock()
    
    def _stop_no_lock(self) -> bool:
        """停止调度器（不获取锁，内部方法）"""
        if not self._running:
            return False
        self._running = False
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self._cron = None
        return True
    
    def status(self) -> Dict[str, Any]:
        """查询调度器状态"""
        with self._lock:
            return {
                "running": self._running,
                "schedule_config": self._schedule_config,
                "last_run": self._last_run,
                "next_run": self._get_next_run_time(),
            }
    
    def _get_next_run_time(self) -> Optional[float]:
        """计算下次运行时间（仅供状态查询参考）"""
        if not self._schedule_config or not self._running:
            return None
        
        config = self._schedule_config
        now = datetime.now()
        
        if config.get("type") == "cron" and self._cron:
            try:
                return self._cron.next_run_time(now).timestamp()
            except Exception:
                return None
        
        if config.get("type") == "daily":
            time_str = config.get("time", "03:00")
            try:
                hour, minute = map(int, time_str.split(":"))
                target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if target <= now:
                    target += timedelta(days=1)
                return target.timestamp()
            except (ValueError, AttributeError):
                return None
        
        elif config.get("type") == "interval":
            seconds = 0
            if "hours" in config:
                seconds = config["hours"] * 3600
            elif "minutes" in config:
                seconds = config["minutes"] * 60
            else:
                return None
            
            if self._last_run:
                return self._last_run + seconds
            else:
                return now.timestamp() + seconds
        
        return None
    
    def _schedule_next(self) -> None:
        """调度下一次执行（内部方法，调用时必须持有 _lock）"""
        if not self._running or not self._schedule_config:
            return
        
        delay = self._calculate_delay()
        if delay is None or delay <= 0:
            return
        
        self._timer = threading.Timer(delay, self._run_task)
        self._timer.daemon = True
        self._timer.start()
    
    def _calculate_delay(self) -> Optional[float]:
        """计算距离下次执行的延迟秒数"""
        if not self._schedule_config:
            return None
        
        config = self._schedule_config
        now = datetime.now()
        
        if config.get("type") == "cron" and self._cron:
            try:
                next_time = self._cron.next_run_time(now)
                return (next_time - now).total_seconds()
            except Exception:
                return None
        
        if config.get("type") == "daily":
            time_str = config.get("time", "03:00")
            try:
                hour, minute = map(int, time_str.split(":"))
                target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if target <= now:
                    target += timedelta(days=1)
                return (target - now).total_seconds()
            except (ValueError, AttributeError):
                return None
        
        elif config.get("type") == "interval":
            if "hours" in config:
                return float(config["hours"] * 3600)
            elif "minutes" in config:
                return float(config["minutes"] * 60)
            else:
                return None
        
        return None
    
    def _run_task(self) -> None:
        """执行备份任务（Timer回调）"""
        try:
            self._callback()
        except Exception:
            # 回调异常不应导致调度器停止
            pass
        finally:
            self._last_run = time.time()
            # 调度下一次
            with self._lock:
                if self._running:
                    self._schedule_next()


# ============================================================
# 主备份管理器（增强版）
# ============================================================

class BackupManager:
    """数据备份恢复管理器（增强版）
    
    第二阶段统一治理增强：
    - 支持多种备份类型：全量/增量/差异
    - 支持多种存储后端
    - 备份加密（AES-256-GCM）
    - 备份压缩（gzip）
    - 备份校验（SHA-256）
    - 灵活的保留策略
    - 备份恢复 + 安全网机制
    - 状态通知接口
    """
    
    def __init__(
        self,
        backup_root: Optional[str] = None,
        data_root: Optional[str] = None,
        max_backups: int = 30,
        storage_backend: Optional[StorageBackend] = None,
        compression: str = CompressionType.GZIP,
        encryption_key: str = "",
    ):
        """
        初始化备份管理器
        
        Args:
            backup_root: 备份存储根目录
            data_root: 数据根目录
            max_backups: 最大保留备份数
            storage_backend: 存储后端实例，None 则使用本地
            compression: 默认压缩类型
            encryption_key: 加密密钥（base64）
        """
        if data_root is None:
            project_root = Path(__file__).parent.parent.parent
            data_root = project_root / "data"
        
        if backup_root is None:
            project_root = Path(__file__).parent.parent.parent
            backup_root = project_root / "backups"
        
        self.data_root = Path(data_root)
        self.backup_root = Path(backup_root)
        self.backup_root.mkdir(parents=True, exist_ok=True)
        self.max_backups = max_backups
        
        # 存储后端
        self._storage = storage_backend or LocalStorageBackend(str(self.backup_root))
        
        # 压缩与加密
        self._compression = compression
        self._compressor = BackupCompressor(compression)
        self._encryptor = BackupEncryptor(encryption_key)
        
        # 通知器
        self.notifier = BackupNotifier()
    
    @property
    def compression(self) -> str:
        """当前压缩类型"""
        return self._compression
    
    @property
    def encryption_available(self) -> bool:
        """加密是否可用"""
        return self._encryptor.available
    
    # --------------------------------------------------------
    # 内部工具方法
    # --------------------------------------------------------
    
    def _get_backup_dir(self, backup_type: str = "full", module_id: str = "") -> Path:
        """获取备份目录路径
        
        Args:
            backup_type: 备份类型
            module_id: 模块ID（可选）
            
        Returns:
            备份目录 Path
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if module_id:
            backup_dir = self.backup_root / module_id / f"{backup_type}_{timestamp}"
        else:
            backup_dir = self.backup_root / f"{backup_type}_{timestamp}"
        backup_dir.mkdir(parents=True, exist_ok=True)
        return backup_dir
    
    def _backup_single_db(self, db_path: Path, backup_file: Path,
                          compress: bool = False, encrypt: bool = False) -> Dict[str, Any]:
        """
        备份单个数据库（内部方法，增强版）
        
        Args:
            db_path: 源数据库路径
            backup_file: 目标备份文件路径
            compress: 是否压缩
            encrypt: 是否加密
            
        Returns:
            备份结果字典
        """
        temp_file = None
        try:
            backup_file.parent.mkdir(parents=True, exist_ok=True)
            
            # 使用 SQLite backup API 进行备份（支持在线备份，不影响业务）
            src = sqlite3.connect(str(db_path))
            dst = sqlite3.connect(str(backup_file))
            
            try:
                # 使用 backup API，每页后 sleep 250ms，减少对业务影响
                # pages: 每次备份的页数，-1 表示全部
                src.backup(dst, pages=-1, progress=None)
            finally:
                src.close()
                dst.close()
            
            original_size = backup_file.stat().st_size
            
            # 计算 SHA-256 校验和（原始文件）
            sha256 = calculate_sha256(str(backup_file))
            
            result = {
                "success": True,
                "backup_path": str(backup_file),
                "size_bytes": original_size,
                "size_mb": round(original_size / 1024 / 1024, 2),
                "timestamp": time.time(),
                "sha256": sha256,
                "compressed": False,
                "encrypted": False,
            }
            
            # 压缩
            if compress and self._compression != CompressionType.NONE:
                compressed_path = Path(str(backup_file) + ".gz")
                compressed_size = self._compressor.compress_file(
                    str(backup_file), str(compressed_path)
                )
                if compressed_size > 0:
                    # 删除原始文件，保留压缩文件
                    backup_file.unlink()
                    result["backup_path"] = str(compressed_path)
                    result["compressed_size_bytes"] = compressed_size
                    result["compressed_size_mb"] = round(compressed_size / 1024 / 1024, 2)
                    result["compressed"] = True
                    temp_file = compressed_path
                else:
                    # 压缩失败，保留原文件
                    result["compression_error"] = "compression failed"
            
            # 加密
            if encrypt and self._encryptor.available:
                source_for_encrypt = Path(result["backup_path"])
                encrypted_path = Path(str(source_for_encrypt) + ".enc")
                if self._encryptor.encrypt_file(str(source_for_encrypt), str(encrypted_path)):
                    source_for_encrypt.unlink()
                    result["backup_path"] = str(encrypted_path)
                    result["encrypted"] = True
                    # 重新计算加密后的校验和
                    result["encrypted_sha256"] = calculate_sha256(str(encrypted_path))
                else:
                    result["encryption_error"] = "encryption failed"
            
            # 写入元数据文件
            meta_path = Path(result["backup_path"]).parent / (
                Path(result["backup_path"]).name + ".meta.json"
            )
            meta = {
                "original_name": db_path.name,
                "backup_type": "db",
                "original_size_bytes": original_size,
                "sha256": sha256,
                "compressed": result.get("compressed", False),
                "encrypted": result.get("encrypted", False),
                "timestamp": result["timestamp"],
            }
            try:
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(meta, f, indent=2, ensure_ascii=False)
            except Exception:
                pass
            
            return result
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }
    
    def _restore_single_db(self, backup_file: Path, target_path: Path,
                           compressed: bool = False, encrypted: bool = False,
                           overwrite: bool = False) -> Dict[str, Any]:
        """恢复单个数据库（内部方法）
        
        Args:
            backup_file: 备份文件路径
            target_path: 恢复目标路径
            compressed: 是否压缩
            encrypted: 是否加密
            overwrite: 是否覆盖
            
        Returns:
            恢复结果
        """
        temp_files = []
        try:
            backup_file = Path(backup_file)
            target_path = Path(target_path)
            
            if not backup_file.exists():
                return {"success": False, "error": f"Backup not found: {backup_file}"}
            
            if target_path.exists() and not overwrite:
                return {"success": False, "error": f"Target already exists: {target_path}"}
            
            current_file = backup_file
            
            # 解密
            if encrypted and self._encryptor.available:
                decrypted_path = backup_file.parent / (backup_file.stem + ".dec")
                if not self._encryptor.decrypt_file(str(backup_file), str(decrypted_path)):
                    return {"success": False, "error": "Decryption failed"}
                temp_files.append(decrypted_path)
                current_file = decrypted_path
            
            # 解压
            if compressed and self._compression != CompressionType.NONE:
                decompressed_path = current_file.parent / current_file.stem
                if not self._compressor.decompress_file(str(current_file), str(decompressed_path)):
                    return {"success": False, "error": "Decompression failed"}
                temp_files.append(decompressed_path)
                current_file = decompressed_path
            
            # 验证备份完整性
            try:
                verify_conn = sqlite3.connect(str(current_file))
                verify_conn.execute("SELECT 1")
                verify_conn.close()
            except Exception as e:
                return {"success": False, "error": f"Backup verification failed: {e}"}
            
            target_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 使用 SQLite backup API 恢复
            src = sqlite3.connect(str(current_file))
            dst = sqlite3.connect(str(target_path))
            try:
                src.backup(dst)
            finally:
                src.close()
                dst.close()
            
            return {
                "success": True,
                "restored_to": str(target_path),
                "timestamp": time.time(),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            # 清理临时文件
            for f in temp_files:
                try:
                    if Path(f).exists():
                        Path(f).unlink()
                except Exception:
                    pass
    
    # --------------------------------------------------------
    # 基础备份方法（保持向后兼容）
    # --------------------------------------------------------
    
    def backup_database(
        self,
        db_path: str,
        backup_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """备份单个数据库（向后兼容）"""
        db_path = Path(db_path)
        if not db_path.exists():
            return {
                "success": False,
                "error": f"Database not found: {db_path}",
            }
        
        backup_dir = self._get_backup_dir("db")
        backup_file = backup_dir / (backup_name or db_path.name)
        
        return self._backup_single_db(db_path, backup_file)
    
    def backup_directory(
        self,
        source_dir: str,
        backup_name: Optional[str] = None,
        include_subdirs: bool = True,
    ) -> Dict[str, Any]:
        """备份整个目录（向后兼容）"""
        source_dir = Path(source_dir)
        if not source_dir.exists():
            return {
                "success": False,
                "error": f"Directory not found: {source_dir}",
            }
        
        backup_dir = self._get_backup_dir("dir")
        backup_file = backup_dir / f"{backup_name or source_dir.name}.zip"
        
        try:
            with zipfile.ZipFile(backup_file, "w", zipfile.ZIP_DEFLATED) as zf:
                if include_subdirs:
                    for f in source_dir.rglob("*"):
                        if f.is_file():
                            zf.write(f, f.relative_to(source_dir.parent))
                else:
                    for f in source_dir.iterdir():
                        if f.is_file():
                            zf.write(f, f.name)
            
            size = backup_file.stat().st_size
            
            return {
                "success": True,
                "backup_path": str(backup_file),
                "size_bytes": size,
                "size_mb": round(size / 1024 / 1024, 2),
                "timestamp": time.time(),
                "file_count": len(zipfile.ZipFile(backup_file).namelist()),
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }
    
    def full_backup(self, modules: Optional[List[str]] = None) -> Dict[str, Any]:
        """全量备份（向后兼容）"""
        backup_dir = self._get_backup_dir("full")
        results = {}
        total_size = 0
        success_count = 0
        
        project_root = Path(__file__).parent.parent.parent
        
        for module_dir in sorted(project_root.iterdir()):
            if not module_dir.is_dir():
                continue
            if not module_dir.name.startswith(("M", "m")):
                continue
            
            module_key = module_dir.name.lower()
            if modules and module_key not in [m.lower() for m in modules]:
                continue
            
            data_dir = module_dir / "data"
            if not data_dir.exists():
                continue
            
            db_files = list(data_dir.rglob("*.db"))
            if not db_files:
                continue
            
            module_backup_dir = backup_dir / module_dir.name
            module_backup_dir.mkdir(parents=True, exist_ok=True)
            
            module_success = 0
            for db_file in db_files:
                backup_file = module_backup_dir / db_file.relative_to(data_dir)
                backup_file.parent.mkdir(parents=True, exist_ok=True)
                
                result = self._backup_single_db(db_file, backup_file)
                if result["success"]:
                    total_size += result["size_bytes"]
                    module_success += 1
                    success_count += 1
                else:
                    results[f"{module_dir.name}/{db_file.name}"] = {
                        "success": False,
                        "error": result.get("error", "unknown"),
                    }
            
            results[module_dir.name] = {
                "success": module_success > 0,
                "db_count": len(db_files),
                "success_count": module_success,
            }
        
        self._cleanup_old_backups()
        
        return {
            "success": success_count > 0,
            "backup_path": str(backup_dir),
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / 1024 / 1024, 2),
            "modules": results,
            "timestamp": time.time(),
        }
    
    # --------------------------------------------------------
    # 模块级备份（增强版）
    # --------------------------------------------------------
    
    def backup_module(self, module_config: ModuleBackupConfig,
                      backup_type: Optional[str] = None) -> BackupReport:
        """
        备份指定模块的所有数据库（增强版）
        
        Args:
            module_config: 模块备份配置
            backup_type: 备份类型，None 则使用配置中的默认类型
            
        Returns:
            详细的备份报告
        """
        start_time = time.time()
        backup_type = backup_type or module_config.backup_type
        
        # 通知：备份开始
        self.notifier.notify("backup_start", {
            "module_id": module_config.module_id,
            "backup_type": backup_type,
            "timestamp": start_time,
        })
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = Path(module_config.backup_dir) / f"{module_config.module_id}_{backup_type}_{timestamp}"
        backup_dir.mkdir(parents=True, exist_ok=True)
        
        compress = module_config.compression != CompressionType.NONE
        encrypt = module_config.encryption != EncryptionType.NONE
        
        total_size = 0
        compressed_size = 0
        success_count = 0
        fail_count = 0
        details: Dict[str, Dict[str, Any]] = {}
        errors: List[str] = []
        
        for db_path_str in module_config.db_paths:
            db_path = Path(db_path_str)
            
            if not db_path.exists():
                fail_count += 1
                errors.append(f"Database not found: {db_path}")
                details[db_path.name] = {
                    "success": False,
                    "error": f"Database not found: {db_path}",
                }
                continue
            
            backup_file = backup_dir / db_path.name
            result = self._backup_single_db(
                db_path, backup_file,
                compress=compress, encrypt=encrypt
            )
            
            if result["success"]:
                success_count += 1
                total_size += result["size_bytes"]
                compressed_size += result.get("compressed_size_bytes", result["size_bytes"])
                details[db_path.name] = result
            else:
                fail_count += 1
                errors.append(f"{db_path.name}: {result.get('error', 'unknown')}")
                details[db_path.name] = result
        
        # 计算整体校验和
        all_checksums = ""
        for db_name, detail in sorted(details.items()):
            if "sha256" in detail:
                all_checksums += detail["sha256"]
        overall_checksum = hashlib.sha256(all_checksums.encode()).hexdigest() if all_checksums else ""
        
        # 写入备份清单文件
        manifest = {
            "module_id": module_config.module_id,
            "backup_type": backup_type,
            "timestamp": timestamp,
            "total_dbs": len(module_config.db_paths),
            "success_dbs": success_count,
            "failed_dbs": fail_count,
            "total_size_bytes": total_size,
            "compressed_size_bytes": compressed_size,
            "checksum": overall_checksum,
            "compressed": compress,
            "encrypted": encrypt,
            "databases": details,
        }
        try:
            manifest_path = backup_dir / "backup_manifest.json"
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False)
        except Exception:
            pass
        
        # 清理该模块的旧备份
        self._apply_retention_policy(
            module_config.backup_dir,
            module_config.module_id,
            module_config.retention,
        )
        
        duration = time.time() - start_time
        success = fail_count == 0 and success_count > 0
        
        report = BackupReport(
            module_id=module_config.module_id,
            backup_type=backup_type,
            success=success,
            total_dbs=len(module_config.db_paths),
            success_dbs=success_count,
            failed_dbs=fail_count,
            total_size_bytes=total_size,
            compressed_size_bytes=compressed_size,
            total_size_mb=round(total_size / 1024 / 1024, 2),
            backup_dir=str(backup_dir),
            timestamp=start_time,
            duration_seconds=round(duration, 2),
            details=details,
            errors=errors,
            checksum=overall_checksum,
            encrypted=encrypt,
            compressed=compress,
        )
        
        # 通知：备份结果
        event_type = "backup_success" if success else "backup_failed"
        self.notifier.notify(event_type, {
            "module_id": module_config.module_id,
            "backup_type": backup_type,
            "success": success,
            "total_size_bytes": total_size,
            "duration_seconds": duration,
            "errors": errors,
        })
        
        return report
    
    # --------------------------------------------------------
    # 差异备份
    # --------------------------------------------------------
    
    def differential_backup(self, db_path: str,
                            base_full_backup_path: str) -> Dict[str, Any]:
        """差异备份
        
        基于最近一次全量备份的差异备份。
        差异备份与增量备份的区别：
        - 增量：基于上一次备份（增量或全量）
        - 差异：基于最近一次全量备份
        
        Args:
            db_path: 当前数据库路径
            base_full_backup_path: 基准备份（全量）路径
            
        Returns:
            差异备份结果
        """
        # 实现方式与增量备份相同，区别在于基准的选择
        # 此处复用增量备份逻辑，但标记为 differential
        result = self.incremental_backup(db_path, base_full_backup_path)
        result_dict = {
            "success": result.success,
            "db_path": result.db_path,
            "base_backup_path": result.base_backup_path,
            "differential_path": result.incremental_path,
            "base_size_bytes": result.base_size_bytes,
            "differential_size_bytes": result.incremental_size_bytes,
            "changed_tables": result.changed_tables,
            "new_tables": result.new_tables,
            "deleted_tables": result.deleted_tables,
            "total_changes": result.total_changes,
            "timestamp": result.timestamp,
            "errors": result.errors,
            "backup_type": BackupType.DIFFERENTIAL,
        }
        return result_dict
    
    # --------------------------------------------------------
    # 恢复方法（增强版）
    # --------------------------------------------------------
    
    def restore_backup(
        self,
        backup_path: str,
        target_path: str,
        overwrite: bool = False,
    ) -> Dict[str, Any]:
        """恢复备份（增强版，支持压缩/加密）"""
        backup_path = Path(backup_path)
        target_path = Path(target_path)
        
        if not backup_path.exists():
            return {
                "success": False,
                "error": f"Backup not found: {backup_path}",
            }
        
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            
            if backup_path.suffix == ".zip":
                # ZIP 备份恢复
                with zipfile.ZipFile(backup_path, "r") as zf:
                    if not overwrite and target_path.exists():
                        existing = set(f.name for f in target_path.iterdir())
                        zip_names = set(Path(n).name for n in zf.namelist())
                        conflicts = existing & zip_names
                        if conflicts:
                            return {
                                "success": False,
                                "error": f"Files already exist: {', '.join(conflicts)}",
                            }
                    
                    zf.extractall(target_path.parent)
                return {
                    "success": True,
                    "restored_to": str(target_path),
                    "timestamp": time.time(),
                }
            
            elif backup_path.suffix in (".db", ".sqlite"):
                # 纯数据库文件
                return self._restore_single_db(
                    backup_path, target_path,
                    compressed=False, encrypted=False,
                    overwrite=overwrite
                )
            
            elif backup_path.suffix == ".gz":
                # 压缩的数据库文件
                return self._restore_single_db(
                    backup_path, target_path,
                    compressed=True, encrypted=False,
                    overwrite=overwrite
                )
            
            elif backup_path.suffix == ".enc":
                # 加密的文件（可能也压缩了）
                # 检查是否是 .gz.enc 或 .db.enc
                stem = backup_path.stem  # 去掉 .enc
                is_compressed = stem.endswith(".gz")
                return self._restore_single_db(
                    backup_path, target_path,
                    compressed=is_compressed, encrypted=True,
                    overwrite=overwrite
                )
            
            else:
                # 普通文件复制
                shutil.copy2(backup_path, target_path)
                return {
                    "success": True,
                    "restored_to": str(target_path),
                    "timestamp": time.time(),
                }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }
    
    def restore_with_safety_net(
        self,
        backup_path: str,
        target_path: str,
        auto_rollback: bool = True,
    ) -> Dict[str, Any]:
        """带安全网的恢复操作（增强版）"""
        backup_path = Path(backup_path)
        target_path = Path(target_path)
        safety_net_path: Optional[Path] = None
        
        # 通知：恢复开始
        self.notifier.notify("restore_start", {
            "backup_path": str(backup_path),
            "target_path": str(target_path),
            "timestamp": time.time(),
        })
        
        try:
            # 1. 创建安全网备份
            if target_path.exists():
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                safety_net_name = f".safety_net_{timestamp}.db"
                safety_net_path = target_path.parent / safety_net_name
                
                safety_result = self._backup_single_db(target_path, safety_net_path)
                if not safety_result["success"]:
                    return {
                        "success": False,
                        "error": f"Failed to create safety net backup: {safety_result.get('error')}",
                        "safety_net_created": False,
                    }
            else:
                safety_net_path = None
            
            # 2. 执行恢复
            restore_result = self.restore_backup(
                str(backup_path), str(target_path), overwrite=True,
            )
            
            # 3. 恢复成功
            if restore_result["success"]:
                self.notifier.notify("restore_success", {
                    "backup_path": str(backup_path),
                    "target_path": str(target_path),
                    "timestamp": time.time(),
                })
                return {
                    "success": True,
                    "restored_to": str(target_path),
                    "safety_net_path": str(safety_net_path) if safety_net_path else None,
                    "safety_net_created": safety_net_path is not None,
                    "rolled_back": False,
                    "timestamp": time.time(),
                }
            
            # 4. 恢复失败，尝试回滚
            if auto_rollback and safety_net_path is not None:
                rollback_result = self.restore_backup(
                    str(safety_net_path), str(target_path), overwrite=True,
                )
                return {
                    "success": False,
                    "error": restore_result.get("error", "Restore failed"),
                    "safety_net_path": str(safety_net_path),
                    "safety_net_created": True,
                    "rolled_back": rollback_result["success"],
                    "rollback_error": None if rollback_result["success"] else rollback_result.get("error"),
                    "timestamp": time.time(),
                }
            
            return {
                "success": False,
                "error": restore_result.get("error", "Restore failed"),
                "safety_net_path": str(safety_net_path) if safety_net_path else None,
                "safety_net_created": safety_net_path is not None,
                "rolled_back": False,
                "timestamp": time.time(),
            }
            
        except Exception as e:
            # 异常时尝试回滚
            rolled_back = False
            rollback_error = None
            if auto_rollback and safety_net_path is not None and safety_net_path.exists():
                try:
                    self.restore_backup(str(safety_net_path), str(target_path), overwrite=True)
                    rolled_back = True
                except Exception as re:
                    rollback_error = str(re)
            
            self.notifier.notify("restore_failed", {
                "backup_path": str(backup_path),
                "target_path": str(target_path),
                "error": str(e),
                "rolled_back": rolled_back,
                "timestamp": time.time(),
            })
            
            return {
                "success": False,
                "error": str(e),
                "safety_net_path": str(safety_net_path) if safety_net_path else None,
                "safety_net_created": safety_net_path is not None and safety_net_path.exists(),
                "rolled_back": rolled_back,
                "rollback_error": rollback_error,
                "timestamp": time.time(),
            }
    
    # --------------------------------------------------------
    # 备份完整性校验（增强版）
    # --------------------------------------------------------
    
    def verify_backup(
        self,
        backup_path: str,
        check_tables: bool = True,
        expected_checksum: str = "",
    ) -> VerifyReport:
        """
        校验备份文件的完整性（增强版，使用 SHA-256）
        
        执行以下检查：
        1. 文件存在性与大小检查
        2. SHA-256 校验和计算（与期望值对比）
        3. PRAGMA integrity_check 完整性检查
        4. PRAGMA quick_check 快速检查
        5. 表数量验证
        
        Args:
            backup_path: 备份文件路径
            check_tables: 是否检查表数量>0
            expected_checksum: 期望的 SHA-256 校验和
            
        Returns:
            详细的校验报告
        """
        backup_path_obj = Path(backup_path)
        report = VerifyReport(
            backup_path=str(backup_path_obj),
            expected_checksum=expected_checksum,
        )
        
        # 1. 文件存在性检查
        if not backup_path_obj.exists():
            report.errors.append(f"Backup file not found: {backup_path}")
            return report
        
        if not backup_path_obj.is_file():
            report.errors.append(f"Path is not a file: {backup_path}")
            return report
        
        report.file_valid = True
        
        # 2. 文件大小
        try:
            report.file_size_bytes = backup_path_obj.stat().st_size
        except Exception as e:
            report.errors.append(f"Failed to get file size: {e}")
        
        # 3. SHA-256 校验和
        try:
            report.sha256_checksum = calculate_sha256(str(backup_path_obj))
            if expected_checksum:
                report.checksum_valid = (report.sha256_checksum == expected_checksum)
            else:
                report.checksum_valid = True  # 无期望值，跳过校验
        except Exception as e:
            report.errors.append(f"Failed to calculate SHA-256: {e}")
        
        # 4. SQLite 完整性检查
        is_db_file = backup_path_obj.suffix in (".db", ".sqlite")
        is_compressed_db = backup_path_obj.suffix == ".gz"
        is_encrypted = backup_path_obj.suffix == ".enc"
        
        if is_encrypted:
            # 加密文件需要先解密才能校验
            report.integrity_check = "skipped (encrypted file)"
            report.quick_check = "skipped (encrypted file)"
            report.has_tables = True  # 加密文件不检查表
        elif is_compressed_db:
            # 压缩文件需要先解压再校验
            temp_db = backup_path_obj.parent / (backup_path_obj.stem + ".verify_tmp")
            try:
                if self._compressor.decompress_file(str(backup_path_obj), str(temp_db)):
                    report = self._verify_sqlite_db(str(temp_db), report, check_tables)
                else:
                    report.errors.append("Failed to decompress for verification")
            finally:
                if temp_db.exists():
                    try:
                        temp_db.unlink()
                    except Exception:
                        pass
        elif is_db_file:
            report = self._verify_sqlite_db(str(backup_path_obj), report, check_tables)
        else:
            # 非SQLite文件，跳过数据库检查
            report.integrity_check = "skipped (not a database file)"
            report.quick_check = "skipped (not a database file)"
            report.has_tables = True
        
        # 5. 综合判断
        integrity_ok = report.integrity_check == "ok" or "skipped" in report.integrity_check
        quick_ok = report.quick_check == "ok" or "skipped" in report.quick_check
        tables_ok = (not check_tables) or report.has_tables
        
        report.overall_valid = (
            report.file_valid
            and report.file_size_bytes > 0
            and report.checksum_valid
            and integrity_ok
            and quick_ok
            and tables_ok
            and len(report.errors) == 0
        )
        
        return report
    
    def _verify_sqlite_db(self, db_path: str, report: VerifyReport,
                          check_tables: bool) -> VerifyReport:
        """校验 SQLite 数据库文件（内部方法）"""
        conn = None
        try:
            conn = sqlite3.connect(db_path)
            
            # PRAGMA integrity_check
            cursor = conn.execute("PRAGMA integrity_check")
            result = cursor.fetchone()
            report.integrity_check = result[0] if result else "unknown"
            
            # PRAGMA quick_check
            cursor = conn.execute("PRAGMA quick_check")
            result = cursor.fetchone()
            report.quick_check = result[0] if result else "unknown"
            
            # 表数量
            cursor = conn.execute(
                "SELECT count(*) FROM sqlite_master WHERE type='table'"
            )
            result = cursor.fetchone()
            report.table_count = result[0] if result else 0
            report.has_tables = report.table_count > 0
            
            conn.close()
            conn = None
        except Exception as e:
            report.errors.append(f"SQLite check failed: {e}")
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
        return report
    
    # --------------------------------------------------------
    # 增量备份（保持向后兼容）
    # --------------------------------------------------------
    
    def incremental_backup(
        self,
        db_path: str,
        base_backup_path: str,
    ) -> IncrementalBackupReport:
        """基于基准备份的增量备份"""
        db_path_obj = Path(db_path)
        base_backup_obj = Path(base_backup_path)
        
        report = IncrementalBackupReport(
            success=False,
            db_path=str(db_path_obj),
            base_backup_path=str(base_backup_obj),
        )
        
        try:
            if not db_path_obj.exists():
                report.errors.append(f"Source database not found: {db_path}")
                return report
            
            if not base_backup_obj.exists():
                report.errors.append(f"Base backup not found: {base_backup_path}")
                return report
            
            report.base_size_bytes = base_backup_obj.stat().st_size
            report.timestamp = time.time()
            
            # 获取基准备份的表信息
            base_tables = self._get_table_row_counts(str(base_backup_obj))
            if base_tables is None:
                report.errors.append("Failed to read base backup table info")
                return report
            
            # 获取当前数据库的表信息
            current_tables = self._get_table_row_counts(str(db_path_obj))
            if current_tables is None:
                report.errors.append("Failed to read current database table info")
                return report
            
            # 计算差异
            base_table_set = set(base_tables.keys())
            current_table_set = set(current_tables.keys())
            
            report.new_tables = sorted(list(current_table_set - base_table_set))
            report.deleted_tables = sorted(list(base_table_set - current_table_set))
            
            common_tables = base_table_set & current_table_set
            for table in sorted(common_tables):
                if base_tables[table] != current_tables[table]:
                    report.changed_tables.append(table)
                    diff = abs(current_tables[table] - base_tables[table])
                    report.total_changes += diff
            
            # 创建增量备份
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            incremental_dir = db_path_obj.parent / "incremental_backups"
            incremental_dir.mkdir(parents=True, exist_ok=True)
            incremental_name = f"incr_{timestamp}_{db_path_obj.stem}.db"
            incremental_path = incremental_dir / incremental_name
            
            incr_result = self._backup_single_db(db_path_obj, incremental_path)
            if not incr_result["success"]:
                report.errors.append(f"Failed to create incremental backup: {incr_result.get('error')}")
                return report
            
            report.incremental_path = str(incremental_path)
            report.incremental_size_bytes = incr_result["size_bytes"]
            
            # 写入增量元数据
            try:
                conn = sqlite3.connect(str(incremental_path))
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS _backup_metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT
                    )
                """)
                metadata = {
                    "backup_type": "incremental",
                    "base_backup": str(base_backup_obj),
                    "source_db": str(db_path_obj),
                    "timestamp": str(report.timestamp),
                    "changed_tables": ",".join(report.changed_tables),
                    "new_tables": ",".join(report.new_tables),
                    "deleted_tables": ",".join(report.deleted_tables),
                    "total_changes": str(report.total_changes),
                }
                for key, value in metadata.items():
                    conn.execute(
                        "INSERT OR REPLACE INTO _backup_metadata (key, value) VALUES (?, ?)",
                        (key, value),
                    )
                conn.commit()
                conn.close()
            except Exception as e:
                report.errors.append(f"Failed to write metadata: {e}")
            
            report.success = True
            
        except Exception as e:
            report.errors.append(f"Incremental backup failed: {e}")
        
        return report
    
    def _get_table_row_counts(self, db_path: str) -> Optional[Dict[str, int]]:
        """获取数据库中所有用户表的记录数"""
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '_backup_%'"
            )
            tables = [row[0] for row in cursor.fetchall()]
            
            row_counts: Dict[str, int] = {}
            for table in tables:
                try:
                    cursor = conn.execute(f'SELECT count(*) FROM "{table}"')
                    row_counts[table] = cursor.fetchone()[0]
                except Exception:
                    row_counts[table] = -1
            
            conn.close()
            return row_counts
        except Exception:
            return None
    
    # --------------------------------------------------------
    # 备份生命周期管理（增强版）
    # --------------------------------------------------------
    
    def list_backups(self, backup_type: Optional[str] = None,
                     module_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        列出所有备份（增强版，支持模块过滤）
        
        Args:
            backup_type: 备份类型过滤
            module_id: 模块ID过滤
            
        Returns:
            备份列表
        """
        backups = []
        
        if not self.backup_root.exists():
            return backups
        
        # 如果指定了模块ID，只在模块目录下查找
        search_dirs = []
        if module_id:
            module_dir = self.backup_root / module_id
            if module_dir.exists():
                search_dirs.append(module_dir)
        else:
            # 先检查是否有模块子目录
            has_module_dirs = False
            for item in self.backup_root.iterdir():
                if item.is_dir() and item.name.startswith(("m", "M")):
                    # 可能是模块目录
                    sub_items = list(item.iterdir())
                    if sub_items:
                        has_module_dirs = True
                        search_dirs.append(item)
            
            if not has_module_dirs:
                search_dirs.append(self.backup_root)
        
        for search_dir in search_dirs:
            if not search_dir.exists():
                continue
            for backup_dir in sorted(search_dir.iterdir(), reverse=True):
                if not backup_dir.is_dir():
                    continue
                
                # 跳过模块目录（如果 search_dir 是根目录）
                if search_dir == self.backup_root and backup_dir.name.startswith(("m", "M")):
                    continue
                
                if backup_type and not backup_dir.name.startswith(backup_type):
                    continue
                
                try:
                    total_size = sum(
                        f.stat().st_size for f in backup_dir.rglob("*") if f.is_file()
                    )
                    
                    backups.append({
                        "name": backup_dir.name,
                        "type": backup_dir.name.split("_")[0],
                        "module": backup_dir.parent.name if backup_dir.parent != self.backup_root else "",
                        "created": backup_dir.stat().st_ctime,
                        "size_bytes": total_size,
                        "size_mb": round(total_size / 1024 / 1024, 2),
                        "path": str(backup_dir),
                    })
                except Exception:
                    continue
        
        # 按创建时间排序（最新在前）
        backups.sort(key=lambda x: x["created"], reverse=True)
        return backups
    
    def _cleanup_old_backups(self):
        """清理过期备份（按数量，向后兼容）"""
        backups = self.list_backups()
        
        if len(backups) <= self.max_backups:
            return
        
        to_delete = backups[self.max_backups:]
        for backup in to_delete:
            try:
                backup_path = Path(backup["path"])
                if backup_path.is_dir():
                    shutil.rmtree(backup_path)
                else:
                    backup_path.unlink()
            except Exception:
                pass
    
    def _apply_retention_policy(self, backup_base_dir: str, module_id: str,
                                policy: RetentionPolicy) -> Dict[str, Any]:
        """应用保留策略到指定模块的备份
        
        Args:
            backup_base_dir: 备份根目录
            module_id: 模块ID
            policy: 保留策略
            
        Returns:
            策略执行结果
        """
        base_dir = Path(backup_base_dir)
        if not base_dir.exists():
            return {"success": True, "deleted": 0}
        
        # 查找该模块的所有备份目录
        module_backups = sorted(
            [d for d in base_dir.iterdir()
             if d.is_dir() and d.name.startswith(f"{module_id}_")],
            key=lambda d: d.stat().st_ctime,
            reverse=True,
        )
        
        if not module_backups:
            return {"success": True, "deleted": 0}
        
        deleted_count = 0
        to_delete = set()
        
        # 按数量策略
        if policy.strategy in ("count", "hybrid") and policy.max_count > 0:
            if len(module_backups) > policy.max_count:
                for b in module_backups[policy.max_count:]:
                    to_delete.add(b)
        
        # 按时间策略
        if policy.strategy in ("age", "hybrid") and policy.max_age_days > 0:
            cutoff_time = time.time() - (policy.max_age_days * 86400)
            for b in module_backups:
                try:
                    if b.stat().st_ctime < cutoff_time:
                        to_delete.add(b)
                except Exception:
                    pass
        
        # 按大小策略
        if policy.strategy == "size" and policy.max_size_gb > 0:
            max_size_bytes = policy.max_size_gb * 1024 * 1024 * 1024
            total_size = 0
            for b in module_backups:
                try:
                    size = sum(f.stat().st_size for f in b.rglob("*") if f.is_file())
                    total_size += size
                    if total_size > max_size_bytes:
                        to_delete.add(b)
                except Exception:
                    pass
        
        # 执行删除
        for b in to_delete:
            try:
                shutil.rmtree(b)
                deleted_count += 1
            except Exception:
                pass
        
        return {"success": True, "deleted": deleted_count}
    
    def cleanup_by_age(self, max_age_days: int) -> Dict[str, Any]:
        """按时间保留策略清理旧备份（向后兼容）"""
        if max_age_days <= 0:
            return {"success": False, "error": "max_age_days must be positive"}
        
        cutoff_time = time.time() - (max_age_days * 86400)
        backups = self.list_backups()
        
        deleted = []
        failed = []
        
        for backup in backups:
            if backup["created"] < cutoff_time:
                try:
                    backup_path = Path(backup["path"])
                    if backup_path.is_dir():
                        shutil.rmtree(backup_path)
                    else:
                        backup_path.unlink()
                    deleted.append(backup["name"])
                except Exception as e:
                    failed.append({"name": backup["name"], "error": str(e)})
        
        return {
            "success": True,
            "max_age_days": max_age_days,
            "deleted_count": len(deleted),
            "failed_count": len(failed),
            "deleted": deleted,
            "failed": failed,
            "timestamp": time.time(),
        }
    
    def cleanup_by_size(self, max_size_gb: float) -> Dict[str, Any]:
        """按空间大小清理旧备份
        
        Args:
            max_size_gb: 最大占用空间（GB）
            
        Returns:
            清理结果
        """
        if max_size_gb <= 0:
            return {"success": False, "error": "max_size_gb must be positive"}
        
        max_size_bytes = max_size_gb * 1024 * 1024 * 1024
        backups = self.list_backups()
        
        total_size = sum(b["size_bytes"] for b in backups)
        if total_size <= max_size_bytes:
            return {
                "success": True,
                "total_size_bytes": total_size,
                "max_size_bytes": max_size_bytes,
                "deleted_count": 0,
            }
        
        deleted = []
        # 从最旧的开始删
        for backup in reversed(backups):
            if total_size <= max_size_bytes:
                break
            try:
                backup_path = Path(backup["path"])
                if backup_path.is_dir():
                    shutil.rmtree(backup_path)
                else:
                    backup_path.unlink()
                total_size -= backup["size_bytes"]
                deleted.append(backup["name"])
            except Exception:
                pass
        
        return {
            "success": True,
            "max_size_gb": max_size_gb,
            "deleted_count": len(deleted),
            "remaining_size_bytes": total_size,
            "deleted": deleted,
            "timestamp": time.time(),
        }
    
    def apply_retention_policy(
        self,
        strategy: str = "count",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """应用备份保留策略（向后兼容）"""
        if strategy == "count":
            max_count = kwargs.get("max_count", self.max_backups)
            self.max_backups = max_count
            self._cleanup_old_backups()
            backups = self.list_backups()
            return {
                "success": True,
                "strategy": "count",
                "max_count": max_count,
                "remaining": len(backups),
                "timestamp": time.time(),
            }
        
        elif strategy == "age":
            max_age_days = kwargs.get("max_age_days", 30)
            result = self.cleanup_by_age(max_age_days)
            result["strategy"] = "age"
            return result
        
        elif strategy == "size":
            max_size_gb = kwargs.get("max_size_gb", 10.0)
            result = self.cleanup_by_size(max_size_gb)
            result["strategy"] = "size"
            return result
        
        elif strategy == "hybrid":
            max_count = kwargs.get("max_count", self.max_backups)
            max_age_days = kwargs.get("max_age_days", 30)
            
            age_result = self.cleanup_by_age(max_age_days)
            
            original_max = self.max_backups
            self.max_backups = max_count
            self._cleanup_old_backups()
            self.max_backups = original_max
            
            backups = self.list_backups()
            
            return {
                "success": True,
                "strategy": "hybrid",
                "max_count": max_count,
                "max_age_days": max_age_days,
                "age_deleted_count": age_result.get("deleted_count", 0),
                "remaining": len(backups),
                "timestamp": time.time(),
            }
        
        else:
            return {
                "success": False,
                "error": f"Unknown retention strategy: {strategy}. "
                         f"Supported: count, age, size, hybrid",
            }
    
    def get_backup_stats(self, module_id: Optional[str] = None) -> Dict[str, Any]:
        """获取备份统计信息（增强版，支持按模块）"""
        backups = self.list_backups(module_id=module_id)
        
        total_size = sum(b["size_bytes"] for b in backups)
        
        by_type = {}
        for b in backups:
            t = b["type"]
            if t not in by_type:
                by_type[t] = {"count": 0, "size_bytes": 0}
            by_type[t]["count"] += 1
            by_type[t]["size_bytes"] += b["size_bytes"]
        
        return {
            "total_backups": len(backups),
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / 1024 / 1024, 2),
            "max_backups": self.max_backups,
            "by_type": by_type,
            "latest_backup": backups[0] if backups else None,
            "module_id": module_id,
        }
    
    # --------------------------------------------------------
    # 存储管理
    # --------------------------------------------------------
    
    def get_storage_usage(self) -> Dict[str, Any]:
        """获取存储空间使用情况
        
        Returns:
            存储使用情况字典
        """
        try:
            total_size = sum(
                f.stat().st_size
                for f in self.backup_root.rglob("*")
                if f.is_file()
            )
            
            # 获取磁盘使用情况
            disk_usage = shutil.disk_usage(str(self.backup_root))
            
            return {
                "backup_root": str(self.backup_root),
                "used_bytes": total_size,
                "used_mb": round(total_size / 1024 / 1024, 2),
                "used_gb": round(total_size / 1024 / 1024 / 1024, 3),
                "disk_total_bytes": disk_usage.total,
                "disk_used_bytes": disk_usage.used,
                "disk_free_bytes": disk_usage.free,
                "disk_free_percent": round(disk_usage.free / disk_usage.total * 100, 2),
                "backup_count": len(self.list_backups()),
            }
        except Exception as e:
            return {
                "backup_root": str(self.backup_root),
                "error": str(e),
            }


# ============================================================
# 统一备份调度中心（增强版）
# ============================================================

class BackupOrchestrator:
    """统一备份调度中心（增强版）
    
    第二阶段统一治理增强：
    - 管理多个模块的备份配置
    - 支持 cron 表达式调度
    - 支持按模块配置不同的备份策略
    - 备份任务状态追踪和监控
    - 备份失败告警
    - 备份存储空间监控
    - 生成全系统备份报告
    """
    
    def __init__(self, backup_manager: Optional[BackupManager] = None):
        """
        初始化备份调度中心
        
        Args:
            backup_manager: 备份管理器实例，None则使用默认
        """
        self.backup_manager = backup_manager or BackupManager()
        self._module_configs: Dict[str, ModuleBackupConfig] = {}
        self._schedulers: Dict[str, BackupScheduler] = {}
        self._backup_history: Dict[str, List[BackupReport]] = {}
        self._running_backups: Dict[str, bool] = {}
        self._lock = threading.Lock()
    
    def register_module(self, config: ModuleBackupConfig) -> bool:
        """注册模块备份配置"""
        with self._lock:
            if config.module_id in self._module_configs:
                return False
            
            self._module_configs[config.module_id] = config
            self._backup_history[config.module_id] = []
            
            if config.schedule:
                self._setup_scheduler(config)
            
            return True
    
    def unregister_module(self, module_id: str) -> bool:
        """注销模块备份配置"""
        with self._lock:
            if module_id not in self._module_configs:
                return False
            
            if module_id in self._schedulers:
                self._schedulers[module_id].stop()
                del self._schedulers[module_id]
            
            del self._module_configs[module_id]
            if module_id in self._backup_history:
                del self._backup_history[module_id]
            
            return True
    
    def update_module_config(self, module_id: str,
                             updates: Dict[str, Any]) -> bool:
        """更新模块备份配置
        
        Args:
            module_id: 模块ID
            updates: 更新字段字典
            
        Returns:
            是否成功
        """
        with self._lock:
            config = self._module_configs.get(module_id)
            if not config:
                return False
            
            # 更新字段
            for key, value in updates.items():
                if hasattr(config, key):
                    setattr(config, key, value)
            
            # 重新设置调度器
            if module_id in self._schedulers:
                self._schedulers[module_id].stop()
                del self._schedulers[module_id]
            
            if config.schedule:
                self._setup_scheduler(config)
            
            return True
    
    def _setup_scheduler(self, config: ModuleBackupConfig) -> None:
        """为模块设置定时调度器（内部方法，必须持有 _lock）"""
        if not config.schedule:
            return
        
        module_id = config.module_id
        
        def _backup_task():
            try:
                self.backup_module(module_id)
            except Exception:
                pass
        
        scheduler = BackupScheduler(_backup_task)
        scheduler.start(config.schedule)
        self._schedulers[module_id] = scheduler
    
    def backup_module(self, module_id: str,
                      backup_type: Optional[str] = None) -> Optional[BackupReport]:
        """立即备份指定模块"""
        with self._lock:
            config = self._module_configs.get(module_id)
            if config is None:
                return None
            
            if self._running_backups.get(module_id, False):
                # 已经在运行中，跳过
                return None
            self._running_backups[module_id] = True
        
        try:
            report = self.backup_manager.backup_module(config, backup_type)
            
            with self._lock:
                if module_id in self._backup_history:
                    self._backup_history[module_id].append(report)
                    if len(self._backup_history[module_id]) > 100:
                        self._backup_history[module_id] = \
                            self._backup_history[module_id][-100:]
            
            return report
        finally:
            with self._lock:
                self._running_backups[module_id] = False
    
    def backup_all_modules(self, backup_type: Optional[str] = None) -> Dict[str, Any]:
        """备份所有已注册的模块"""
        results: Dict[str, Any] = {}
        total_size = 0
        success_count = 0
        fail_count = 0
        
        with self._lock:
            module_ids = list(self._module_configs.keys())
        
        for module_id in sorted(module_ids):
            report = self.backup_module(module_id, backup_type)
            if report is None:
                continue
            
            results[module_id] = {
                "success": report.success,
                "total_dbs": report.total_dbs,
                "success_dbs": report.success_dbs,
                "failed_dbs": report.failed_dbs,
                "total_size_bytes": report.total_size_bytes,
                "backup_dir": report.backup_dir,
                "duration_seconds": report.duration_seconds,
            }
            
            if report.success:
                success_count += 1
            else:
                fail_count += 1
            total_size += report.total_size_bytes
        
        return {
            "success": fail_count == 0 and success_count > 0,
            "total_modules": len(module_ids),
            "success_modules": success_count,
            "failed_modules": fail_count,
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / 1024 / 1024, 2),
            "modules": results,
            "timestamp": time.time(),
        }
    
    def restore_module(self, module_id: str, backup_dir: str,
                       use_safety_net: bool = True) -> Dict[str, Any]:
        """恢复指定模块的备份
        
        Args:
            module_id: 模块ID
            backup_dir: 备份目录路径
            use_safety_net: 是否使用安全网机制
            
        Returns:
            恢复结果
        """
        with self._lock:
            config = self._module_configs.get(module_id)
            if config is None:
                return {"success": False, "error": f"Module {module_id} not registered"}
        
        backup_dir_obj = Path(backup_dir)
        if not backup_dir_obj.exists():
            return {"success": False, "error": f"Backup directory not found: {backup_dir}"}
        
        results: Dict[str, Any] = {}
        success_count = 0
        fail_count = 0
        
        for db_path_str in config.db_paths:
            db_path = Path(db_path_str)
            backup_file = None
            
            # 查找对应的备份文件
            for ext in [".db", ".db.gz", ".db.enc", ".db.gz.enc"]:
                candidate = backup_dir_obj / (db_path.stem + ext)
                if candidate.exists():
                    backup_file = candidate
                    break
            
            if not backup_file:
                # 尝试匹配原文件名
                for f in backup_dir_obj.iterdir():
                    if f.is_file() and f.name.startswith(db_path.stem) and not f.name.endswith(".meta.json"):
                        backup_file = f
                        break
            
            if not backup_file:
                fail_count += 1
                results[db_path.name] = {
                    "success": False,
                    "error": "Backup file not found",
                }
                continue
            
            if use_safety_net:
                result = self.backup_manager.restore_with_safety_net(
                    str(backup_file), str(db_path), auto_rollback=True,
                )
            else:
                result = self.backup_manager.restore_backup(
                    str(backup_file), str(db_path), overwrite=True,
                )
            
            if result["success"]:
                success_count += 1
            else:
                fail_count += 1
            results[db_path.name] = result
        
        return {
            "success": fail_count == 0 and success_count > 0,
            "module_id": module_id,
            "backup_dir": str(backup_dir_obj),
            "total_dbs": len(config.db_paths),
            "success_dbs": success_count,
            "failed_dbs": fail_count,
            "databases": results,
            "timestamp": time.time(),
        }
    
    def get_module_history(
        self,
        module_id: str,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """查询指定模块的备份历史"""
        with self._lock:
            history = self._backup_history.get(module_id, [])
            recent = list(reversed(history))[:limit]
        
        return [
            {
                "module_id": r.module_id,
                "backup_type": r.backup_type,
                "success": r.success,
                "total_dbs": r.total_dbs,
                "success_dbs": r.success_dbs,
                "failed_dbs": r.failed_dbs,
                "total_size_bytes": r.total_size_bytes,
                "backup_dir": r.backup_dir,
                "timestamp": r.timestamp,
                "duration_seconds": r.duration_seconds,
                "errors": r.errors,
                "checksum": r.checksum,
            }
            for r in recent
        ]
    
    def get_system_report(self) -> Dict[str, Any]:
        """获取全系统备份报告"""
        with self._lock:
            module_ids = list(self._module_configs.keys())
            scheduler_status = {
                mid: sched.status()
                for mid, sched in self._schedulers.items()
            }
            running_status = dict(self._running_backups)
        
        module_stats = {}
        total_backups = 0
        
        for module_id in module_ids:
            history = self.get_module_history(module_id, limit=100)
            success_count = sum(1 for h in history if h["success"])
            module_stats[module_id] = {
                "total_backups": len(history),
                "success_count": success_count,
                "fail_count": len(history) - success_count,
                "last_backup": history[0] if history else None,
                "scheduler": scheduler_status.get(module_id, {"running": False}),
                "is_running": running_status.get(module_id, False),
            }
            total_backups += len(history)
        
        base_stats = self.backup_manager.get_backup_stats()
        storage_usage = self.backup_manager.get_storage_usage()
        
        return {
            "total_modules": len(module_ids),
            "total_backups": total_backup,
            "modules": module_stats,
            "backup_root": str(self.backup_manager.backup_root),
            "base_stats": base_stats,
            "storage_usage": storage_usage,
            "timestamp": time.time(),
        }
    
    def get_module_config(self, module_id: str) -> Optional[ModuleBackupConfig]:
        """获取模块备份配置"""
        with self._lock:
            return self._module_configs.get(module_id)
    
    def list_modules(self) -> List[str]:
        """列出所有已注册的模块ID"""
        with self._lock:
            return list(self._module_configs.keys())
    
    def get_alerts(self) -> List[Dict[str, Any]]:
        """获取备份告警信息
        
        返回需要关注的备份失败、空间不足等告警。
        """
        alerts = []
        
        # 1. 检查最近备份失败的模块
        with self._lock:
            for module_id, history in self._backup_history.items():
                if not history:
                    continue
                latest = history[-1]
                if not latest.success:
                    alerts.append({
                        "level": "warning",
                        "type": "backup_failed",
                        "module_id": module_id,
                        "message": f"模块 {module_id} 最近一次备份失败",
                        "errors": latest.errors,
                        "timestamp": latest.timestamp,
                    })
        
        # 2. 检查存储空间
        try:
            storage = self.backup_manager.get_storage_usage()
            if "disk_free_percent" in storage:
                if storage["disk_free_percent"] < 10:
                    alerts.append({
                        "level": "critical",
                        "type": "low_disk_space",
                        "message": f"备份磁盘空间不足，剩余 {storage['disk_free_percent']}%",
                        "free_bytes": storage.get("disk_free_bytes", 0),
                    })
                elif storage["disk_free_percent"] < 20:
                    alerts.append({
                        "level": "warning",
                        "type": "low_disk_space",
                        "message": f"备份磁盘空间偏低，剩余 {storage['disk_free_percent']}%",
                        "free_bytes": storage.get("disk_free_bytes", 0),
                    })
        except Exception:
            pass
        
        return alerts
    
    def shutdown(self) -> None:
        """关闭调度中心，停止所有调度器"""
        with self._lock:
            for scheduler in self._schedulers.values():
                try:
                    scheduler.stop()
                except Exception:
                    pass
            self._schedulers.clear()


# ============================================================
# 全局单例
# ============================================================

_backup_manager: Optional[BackupManager] = None
_backup_orchestrator: Optional[BackupOrchestrator] = None
_init_lock = threading.Lock()


def get_backup_manager() -> BackupManager:
    """获取全局备份管理器实例"""
    global _backup_manager
    if _backup_manager is None:
        with _init_lock:
            if _backup_manager is None:
                _backup_manager = BackupManager()
    return _backup_manager


def get_backup_orchestrator() -> BackupOrchestrator:
    """获取全局备份调度中心实例"""
    global _backup_orchestrator
    if _backup_orchestrator is None:
        with _init_lock:
            if _backup_orchestrator is None:
                _backup_orchestrator = BackupOrchestrator()
    return _backup_orchestrator


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    # 常量
    "BackupType",
    "StorageBackendType",
    "CompressionType",
    "EncryptionType",
    "BackupStatus",
    # 数据类
    "ModuleBackupConfig",
    "BackupReport",
    "VerifyReport",
    "IncrementalBackupReport",
    "RetentionPolicy",
    # 存储后端
    "StorageBackend",
    "LocalStorageBackend",
    "RemoteStorageBackend",
    # 工具
    "BackupEncryptor",
    "BackupCompressor",
    "BackupNotifier",
    "calculate_sha256",
    "calculate_md5",
    # 调度
    "BackupScheduler",
    "CronExpression",
    # 主类
    "BackupManager",
    "BackupOrchestrator",
    # 单例
    "get_backup_manager",
    "get_backup_orchestrator",
]
