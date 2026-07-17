"""
跨模块数据迁移公共工具库
========================

将各模块 M8→目标模块 迁移脚本中重复的公共组件抽取为统一库，
供 M4/M5/M6/M7/M9 等所有迁移脚本复用。

包含组件：
- 数据类：MigrationStats / TableMigrationStats / MigrationCheckpoint
- 进度追踪：ProgressTracker / format_duration
- 重试机制：retry_with_backoff / RetryableError
- 断点续传：CheckpointManager
- 数据转换：row_to_dict / safe_str / parse_datetime / safe_json_loads
- 幂等性检查：IdempotencyChecker
- 迁移执行器基类：BaseDataMigrator

设计原则：
- 不依赖任何特定模块的业务代码
- 支持 sqlite3 原生连接与 SQLAlchemy 两种接入方式
- 线程安全（关键路径使用 threading.Lock）
- 完整的类型提示与 docstring
- 与现有代码风格保持一致
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, TypeVar

# ---------------------------------------------------------------------------
# 类型变量
# ---------------------------------------------------------------------------

T = TypeVar("T")


# ===========================================================================
# 1. 数据类
# ===========================================================================

@dataclass
class TableMigrationStats:
    """单表迁移统计信息.

    Attributes:
        table_name: 表名
        source_total: 源表总记录数
        migrated: 成功迁移数
        skipped: 跳过数（重复/幂等）
        failed: 失败数
        errors: 错误信息列表（仅保留最近的若干条，避免内存膨胀）
        start_time: 开始时间戳（秒）
        end_time: 结束时间戳（秒）
    """

    table_name: str
    source_total: int = 0
    migrated: int = 0
    skipped: int = 0
    failed: int = 0
    errors: List[str] = field(default_factory=list)
    start_time: Optional[float] = None
    end_time: Optional[float] = None

    @property
    def duration_seconds(self) -> float:
        """迁移耗时（秒）."""
        if self.start_time and self.end_time:
            return round(self.end_time - self.start_time, 3)
        return 0.0

    @property
    def success_rate(self) -> str:
        """成功率字符串."""
        total = self.migrated + self.failed
        if total == 0:
            return "N/A"
        return f"{self.migrated / total * 100:.1f}%"

    def add_error(self, error_msg: str, max_errors: int = 50) -> None:
        """记录错误，超过上限时丢弃最早的.

        Args:
            error_msg: 错误信息
            max_errors: 最大保留错误数，默认 50 条
        """
        self.errors.append(error_msg)
        if len(self.errors) > max_errors:
            self.errors = self.errors[-max_errors:]

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于序列化）."""
        return {
            "table_name": self.table_name,
            "source_total": self.source_total,
            "migrated": self.migrated,
            "skipped": self.skipped,
            "failed": self.failed,
            "success_rate": self.success_rate,
            "duration_seconds": self.duration_seconds,
            "errors": self.errors[:10],  # 序列化时只保留前10条
        }


@dataclass
class MigrationStats:
    """整体迁移统计信息.

    Attributes:
        migration_id: 迁移任务唯一标识
        dry_run: 是否为试运行模式
        start_time: 开始时间戳（秒）
        end_time: 结束时间戳（秒）
        tables: 各表的迁移统计（表名 -> TableMigrationStats）
    """

    migration_id: str = ""
    dry_run: bool = False
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    tables: Dict[str, TableMigrationStats] = field(default_factory=dict)

    # ---- 聚合属性 ----

    @property
    def total_source(self) -> int:
        """所有表的源数据总数."""
        return sum(t.source_total for t in self.tables.values())

    @property
    def total_migrated(self) -> int:
        """所有表的成功迁移总数."""
        return sum(t.migrated for t in self.tables.values())

    @property
    def total_skipped(self) -> int:
        """所有表的跳过总数."""
        return sum(t.skipped for t in self.tables.values())

    @property
    def total_failed(self) -> int:
        """所有表的失败总数."""
        return sum(t.failed for t in self.tables.values())

    @property
    def duration_seconds(self) -> float:
        """总耗时（秒）."""
        if self.start_time and self.end_time:
            return round(self.end_time - self.start_time, 3)
        return 0.0

    @property
    def has_errors(self) -> bool:
        """是否存在失败记录."""
        return self.total_failed > 0 or any(t.errors for t in self.tables.values())

    # ---- 方法 ----

    def get_table(self, table_name: str) -> TableMigrationStats:
        """获取或创建单表统计对象.

        Args:
            table_name: 表名

        Returns:
            TableMigrationStats 实例
        """
        if table_name not in self.tables:
            self.tables[table_name] = TableMigrationStats(table_name=table_name)
        return self.tables[table_name]

    def mark_start(self) -> None:
        """标记迁移开始."""
        self.start_time = time.time()

    def mark_end(self) -> None:
        """标记迁移结束."""
        self.end_time = time.time()

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于序列化输出）."""
        return {
            "migration_id": self.migration_id,
            "dry_run": self.dry_run,
            "duration_seconds": self.duration_seconds,
            "total_source": self.total_source,
            "total_migrated": self.total_migrated,
            "total_skipped": self.total_skipped,
            "total_failed": self.total_failed,
            "tables": {name: t.to_dict() for name, t in self.tables.items()},
        }

    def summary_text(self) -> str:
        """生成可读的汇总文本."""
        lines = [
            "",
            "=" * 60,
            "  迁移统计汇总",
            "=" * 60,
            f"  迁移ID: {self.migration_id}",
            f"  模式: {'DRY-RUN' if self.dry_run else 'FULL MIGRATION'}",
            f"  总耗时: {format_duration(self.duration_seconds)}",
            f"  迁移表数: {len(self.tables)}",
            f"  源数据总数: {self.total_source:,}",
            f"  成功迁移: {self.total_migrated:,}",
            f"  跳过(重复): {self.total_skipped:,}",
            f"  失败: {self.total_failed:,}",
            "-" * 60,
            f"  {'表名':<30} {'源数':>8} {'迁移':>8} {'跳过':>8} {'失败':>8} {'耗时':>8}",
            "  " + "-" * 68,
        ]
        for name, t in self.tables.items():
            lines.append(
                f"  {name:<30} {t.source_total:>8,} {t.migrated:>8,} "
                f"{t.skipped:>8,} {t.failed:>8,} {format_duration(t.duration_seconds):>8}"
            )
        lines.append("=" * 60)
        return "\n".join(lines)


@dataclass
class MigrationCheckpoint:
    """迁移断点数据结构.

    Attributes:
        migration_id: 迁移任务ID
        created_at: 创建时间
        updated_at: 最后更新时间
        completed_tables: 已完成的表名列表
        table_offsets: 各表的处理偏移量 {表名: offset/last_id}
        table_stats: 各表当前统计快照（可选）
        error: 中断时的错误信息（可选）
        extra: 扩展字段，各迁移脚本可自定义存储
    """

    migration_id: str = ""
    created_at: str = ""
    updated_at: str = ""
    completed_tables: List[str] = field(default_factory=list)
    table_offsets: Dict[str, Any] = field(default_factory=dict)
    table_stats: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    error: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MigrationCheckpoint":
        """从字典反序列化."""
        cp = cls()
        for key, value in data.items():
            if hasattr(cp, key):
                setattr(cp, key, value)
        return cp

    def is_table_complete(self, table_name: str) -> bool:
        """检查表是否已完成."""
        return table_name in self.completed_tables

    def mark_table_complete(self, table_name: str) -> None:
        """标记表已完成."""
        if table_name not in self.completed_tables:
            self.completed_tables.append(table_name)
        self.table_offsets.pop(table_name, None)
        self.updated_at = datetime.now().isoformat()


# ===========================================================================
# 2. 进度追踪
# ===========================================================================

class ProgressTracker:
    """迁移进度追踪器，支持百分比、速率、ETA 估算.

    支持三种报告方式：
    - print：直接打印到控制台（带进度条）
    - logger：通过 logging.Logger 输出
    - callback：自定义回调函数

    线程安全：内部使用锁保护计数器。

    Attributes:
        total: 总任务数
        label: 标签文本
        current: 已完成数
    """

    def __init__(
        self,
        total: int,
        label: str = "进度",
        report_interval: float = 5.0,
        logger: Optional[logging.Logger] = None,
        callback: Optional[Callable[["ProgressTracker"], None]] = None,
        show_bar: bool = True,
    ):
        """
        Args:
            total: 总任务数
            label: 进度标签
            report_interval: 报告间隔（秒）
            logger: 日志器，为 None 则使用 print
            callback: 自定义报告回调，参数为 ProgressTracker 实例
            show_bar: 是否显示进度条（仅 print 模式有效）
        """
        self.total = max(total, 0)
        self.label = label
        self.report_interval = report_interval
        self.logger = logger
        self.callback = callback
        self.show_bar = show_bar

        self._current: int = 0
        self._start_time: float = time.time()
        self._last_report: float = 0.0
        self._lock = threading.Lock()

    # ---- 公共属性 ----

    @property
    def current(self) -> int:
        """已完成数."""
        with self._lock:
            return self._current

    @property
    def percent(self) -> float:
        """完成百分比 (0-100)."""
        if self.total == 0:
            return 100.0
        with self._lock:
            return min(self._current / self.total * 100, 100.0)

    @property
    def rate(self) -> float:
        """处理速率（条/秒）."""
        elapsed = time.time() - self._start_time
        if elapsed < 0.001:
            return 0.0
        with self._lock:
            return self._current / elapsed

    @property
    def eta_seconds(self) -> float:
        """预计剩余时间（秒）."""
        rate = self.rate
        if rate <= 0:
            return 0.0
        with self._lock:
            remaining = max(self.total - self._current, 0)
        return remaining / rate

    @property
    def elapsed_seconds(self) -> float:
        """已用时间（秒）."""
        return time.time() - self._start_time

    # ---- 公共方法 ----

    def update(self, n: int = 1) -> None:
        """更新已完成数量.

        Args:
            n: 新增完成数
        """
        with self._lock:
            self._current += n

        if self.should_report():
            self.report()

    def set_total(self, total: int) -> None:
        """重新设置总数（用于总数动态变化的场景）."""
        self.total = max(total, 0)
        if self.should_report():
            self.report()

    def should_report(self) -> bool:
        """判断是否应该触发报告.

        Returns:
            True 表示应该报告
        """
        now = time.time()
        if now - self._last_report >= self.report_interval:
            return True
        # 完成时也报告一次
        with self._lock:
            if self._current >= self.total > 0:
                return True
        return False

    def report(self) -> None:
        """输出进度报告."""
        self._last_report = time.time()

        # 自定义回调优先
        if self.callback:
            self.callback(self)
            return

        msg = self.get_report()

        if self.logger:
            self.logger.info(msg)
        else:
            # print 模式，使用 \r 实现单行刷新
            end_char = "\n" if self.percent >= 100 else "\r"
            print(msg, end=end_char, flush=True)

    def get_report(self) -> str:
        """获取进度报告字符串.

        Returns:
            格式化的进度文本
        """
        if self.total == 0:
            return f"[{self.label}] 0/0 (无数据)"

        pct = self.percent
        rate = self.rate
        eta_str = format_duration(self.eta_seconds) if rate > 0 else "计算中..."

        if self.show_bar and not self.logger:
            # 带进度条的简洁格式（print 模式）
            bar_len = 30
            filled = int(bar_len * pct / 100)
            bar = "█" * filled + "░" * (bar_len - filled)
            return (
                f"  {self.label}: [{bar}] {pct:5.1f}% "
                f"({self.current:,}/{self.total:,}) "
                f"速率: {rate:,.0f}/s ETA: {eta_str}"
            )
        else:
            # 日志模式：纯文本
            return (
                f"[{self.label}] {self.current:,}/{self.total:,} ({pct:.1f}%) "
                f"速率: {rate:,.1f} 条/秒, ETA: {eta_str}"
            )

    def finish(self) -> None:
        """标记完成并输出最终报告."""
        with self._lock:
            self._current = self.total
        self.report()


def format_duration(seconds: float) -> str:
    """将秒数格式化为人类可读的时长.

    Args:
        seconds: 秒数

    Returns:
        格式化字符串，如 "30s", "2m 30s", "1h 15m", "2天 3h"
    """
    seconds = int(max(seconds, 0))

    if seconds < 60:
        return f"{seconds}s"

    if seconds < 3600:
        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes}m {secs}s" if secs > 0 else f"{minutes}m"

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60

    if hours < 24:
        return f"{hours}h {minutes}m" if minutes > 0 else f"{hours}h"

    days = hours // 24
    hours_remain = hours % 24
    return f"{days}天 {hours_remain}h" if hours_remain > 0 else f"{days}天"


# ===========================================================================
# 3. 重试机制
# ===========================================================================

class RetryableError(Exception):
    """可重试异常标记类.

    当业务逻辑中抛出此异常（或其子类）时，retry_with_backoff 会进行重试。
    若抛出其他异常，则根据 retry_exceptions 参数决定是否重试。
    """


def retry_with_backoff(
    func: Optional[Callable[..., T]] = None,
    *,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    backoff_factor: float = 2.0,
    retry_exceptions: Optional[Tuple[type, ...]] = None,
    logger: Optional[logging.Logger] = None,
) -> Any:
    """带指数退避的重试工具.

    支持两种使用方式：

    1. 函数式调用::

        result = retry_with_backoff(lambda: do_work(), max_retries=3)

    2. 装饰器模式::

        @retry_with_backoff(max_retries=3, base_delay=1.0)
        def do_work():
            ...

    Args:
        func: 要执行的函数（函数式调用时传入）
        max_retries: 最大重试次数（不含首次执行），默认 3
        base_delay: 初始延迟秒数，默认 1.0
        max_delay: 最大延迟秒数，默认 30.0
        backoff_factor: 退避因子，默认 2.0
        retry_exceptions: 需要重试的异常类型元组，默认 RetryableError + 所有 Exception
            （当为 None 时，仅重试 RetryableError 及其子类）
        logger: 日志器，为 None 时使用 print

    Returns:
        函数执行结果

    Raises:
        最后一次失败时抛出的异常
    """
    # 确定重试的异常类型
    if retry_exceptions is None:
        retry_exceptions = (RetryableError,)

    def _log(msg: str, level: str = "info") -> None:
        if logger:
            getattr(logger, level)(msg)
        else:
            print(msg)

    def _execute(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        last_exception: Optional[Exception] = None

        for attempt in range(max_retries + 1):
            try:
                return fn(*args, **kwargs)
            except retry_exceptions as e:
                last_exception = e
                if attempt < max_retries:
                    delay = min(base_delay * (backoff_factor ** attempt), max_delay)
                    _log(
                        f"  [RETRY] 第 {attempt + 1} 次失败: {e}，"
                        f"{delay:.1f}s 后重试 (剩余 {max_retries - attempt} 次)",
                        level="warning",
                    )
                    time.sleep(delay)
                else:
                    _log(
                        f"  [ERROR] 重试 {max_retries} 次后仍失败: {e}",
                        level="error",
                    )
            except Exception as e:
                # 不在重试列表中的异常，直接抛出
                raise

        raise last_exception  # type: ignore

    # 装饰器模式：func 为 None 时返回装饰器
    if func is None:
        def decorator(fn: Callable[..., T]) -> Callable[..., T]:
            def wrapper(*args: Any, **kwargs: Any) -> T:
                return _execute(fn, *args, **kwargs)
            return wrapper
        return decorator

    # 函数式调用：直接执行
    return _execute(func)


# ===========================================================================
# 4. 断点续传
# ===========================================================================

class CheckpointManager:
    """迁移断点续传管理器.

    以 JSON 文件形式持久化断点信息，支持：
    - 保存/加载/清除断点
    - 表级别的完成标记与偏移量记录
    - 线程安全（文件写入加锁）
    - 原子写入（先写临时文件再替换，避免写坏）

    Attributes:
        checkpoint_dir: 断点文件所在目录
        checkpoint_name: 断点文件名（不含扩展名）
        checkpoint_path: 完整的断点文件路径
    """

    def __init__(
        self,
        checkpoint_dir: str | os.PathLike,
        checkpoint_name: str = "migration_checkpoint",
    ):
        """
        Args:
            checkpoint_dir: 断点文件存放目录
            checkpoint_name: 断点文件名（不含 .json 后缀）
        """
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_name = checkpoint_name
        self.checkpoint_path = self.checkpoint_dir / f"{checkpoint_name}.json"
        self._data: MigrationCheckpoint = MigrationCheckpoint(
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
        )
        self._lock = threading.Lock()
        self._loaded = False

    # ---- 核心方法 ----

    def exists(self) -> bool:
        """检查断点文件是否存在.

        Returns:
            True 表示存在
        """
        return self.checkpoint_path.exists()

    def save(self, data: Optional[dict] = None) -> None:
        """保存断点.

        Args:
            data: 要保存的数据字典，为 None 则保存内部 _data
        """
        with self._lock:
            if data is not None:
                # 更新内部数据
                self._data = MigrationCheckpoint.from_dict(data)
            self._data.updated_at = datetime.now().isoformat()

            # 确保目录存在
            self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

            # 原子写入：先写临时文件，再替换
            temp_path = self.checkpoint_path.with_suffix(".tmp")
            try:
                with open(temp_path, "w", encoding="utf-8") as f:
                    json.dump(self._data.to_dict(), f, ensure_ascii=False, indent=2)
                # 替换原文件
                temp_path.replace(self.checkpoint_path)
            except IOError as e:
                # 失败时清理临时文件
                if temp_path.exists():
                    try:
                        temp_path.unlink()
                    except IOError:
                        pass
                raise IOError(f"保存 checkpoint 失败: {e}") from e

    def load(self) -> Optional[dict]:
        """加载断点.

        Returns:
            断点数据字典，不存在或读取失败返回 None
        """
        if not self.exists():
            return None

        try:
            with open(self.checkpoint_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._data = MigrationCheckpoint.from_dict(data)
            self._loaded = True
            return self._data.to_dict()
        except (json.JSONDecodeError, IOError) as e:
            self._log_warning(f"读取 checkpoint 失败: {e}，将从头开始")
            return None

    def clear(self) -> None:
        """清除断点文件（迁移成功完成后调用）."""
        with self._lock:
            if self.checkpoint_path.exists():
                try:
                    self.checkpoint_path.unlink()
                except IOError as e:
                    self._log_warning(f"清除 checkpoint 失败: {e}")
            self._data = MigrationCheckpoint(
                created_at=datetime.now().isoformat(),
                updated_at=datetime.now().isoformat(),
            )
            self._loaded = False

    # ---- 便捷方法：表级操作 ----

    def is_table_complete(self, table_name: str) -> bool:
        """检查表是否已标记为完成.

        Args:
            table_name: 表名

        Returns:
            True 表示已完成
        """
        return self._data.is_table_complete(table_name)

    def mark_table_complete(self, table_name: str) -> None:
        """标记单表完成并保存断点.

        Args:
            table_name: 表名
        """
        with self._lock:
            self._data.mark_table_complete(table_name)
        self.save()

    def get_table_offset(self, table_name: str) -> Any:
        """获取表的当前偏移量.

        Args:
            table_name: 表名

        Returns:
            偏移量值，不存在返回 None 或 0（根据存储类型）
        """
        return self._data.table_offsets.get(table_name)

    def set_table_offset(self, table_name: str, offset: Any) -> None:
        """设置表的偏移量（不保存，需手动调用 save）.

        Args:
            table_name: 表名
            offset: 偏移量值
        """
        with self._lock:
            self._data.table_offsets[table_name] = offset
            self._data.updated_at = datetime.now().isoformat()

    def get_extra(self, key: str, default: Any = None) -> Any:
        """获取扩展字段值.

        Args:
            key: 字段名
            default: 默认值

        Returns:
            字段值
        """
        return self._data.extra.get(key, default)

    def set_extra(self, key: str, value: Any) -> None:
        """设置扩展字段值（不保存）.

        Args:
            key: 字段名
            value: 字段值
        """
        with self._lock:
            self._data.extra[key] = value
            self._data.updated_at = datetime.now().isoformat()

    @property
    def data(self) -> MigrationCheckpoint:
        """内部数据对象（只读访问）."""
        return self._data

    # ---- 内部方法 ----

    def _log_warning(self, msg: str) -> None:
        """输出警告（避免依赖 logger 导致循环引用）."""
        print(f"  [WARN] {msg}")


# ===========================================================================
# 5. 数据转换工具
# ===========================================================================

def row_to_dict(row: Any) -> Dict[str, Any]:
    """将数据库行对象转换为字典.

    支持以下行类型：
    - sqlite3.Row
    - SQLAlchemy Row / RowMapping
    - 普通 dict（直接返回）
    - 任意具有 keys() 方法并支持下标访问的对象

    Args:
        row: 数据库行对象

    Returns:
        字段名 -> 值 的字典

    Raises:
        TypeError: 不支持的行类型
    """
    if row is None:
        return {}

    # 已经是字典
    if isinstance(row, dict):
        return row

    # SQLAlchemy RowMapping / 有 _mapping 属性
    if hasattr(row, "_mapping"):
        try:
            return dict(row._mapping)
        except Exception:
            pass

    # SQLAlchemy Row / 有 _asdict 方法（namedtuple 风格）
    if hasattr(row, "_asdict"):
        try:
            return row._asdict()
        except Exception:
            pass

    # sqlite3.Row / 有 keys() 方法 + 可迭代
    if hasattr(row, "keys"):
        try:
            return {key: row[key] for key in row.keys()}
        except Exception:
            pass

    # 最后尝试：转为 dict
    try:
        return dict(row)
    except (TypeError, ValueError) as e:
        raise TypeError(f"无法将 {type(row).__name__} 转换为字典: {e}") from e


def safe_str(value: Any, default: str = "", max_length: Optional[int] = None) -> str:
    """安全地将值转换为字符串.

    Args:
        value: 待转换的值
        default: 值为 None 时的默认返回值
        max_length: 最大长度限制，超出则截断

    Returns:
        转换后的字符串
    """
    if value is None:
        return default

    try:
        result = str(value)
    except Exception:
        return default

    if max_length is not None and len(result) > max_length:
        result = result[:max_length]

    return result


# 常见的日期时间格式列表
_DATETIME_FORMATS: List[str] = [
    # ISO 8601 系列
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
    # 空格分隔系列
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    # 仅日期
    "%Y-%m-%d",
    "%Y/%m/%d",
    # 中文格式
    "%Y年%m月%d日 %H:%M:%S",
    "%Y年%m月%d日",
]


def parse_datetime(value: Any) -> Optional[datetime]:
    """多格式解析日期时间字符串.

    支持常见的日期时间格式，包括 ISO 8601、空格分隔、仅日期等。
    若值已经是 datetime 对象则直接返回。

    Args:
        value: 待解析的值（字符串 / datetime / None）

    Returns:
        datetime 对象，解析失败返回 None
    """
    if value is None or value == "":
        return None

    if isinstance(value, datetime):
        return value

    if not isinstance(value, str):
        try:
            value = str(value)
        except Exception:
            return None

    value = value.strip()
    if not value:
        return None

    for fmt in _DATETIME_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue

    return None


def safe_json_loads(value: Any, default: Any = None) -> Any:
    """安全地解析 JSON 字符串.

    Args:
        value: 待解析的值
        default: 解析失败时的默认返回值

    Returns:
        解析后的 Python 对象，失败返回 default
    """
    if value is None:
        return default

    # 已经是 dict/list，直接返回
    if isinstance(value, (dict, list)):
        return value

    if not isinstance(value, str):
        try:
            value = str(value)
        except Exception:
            return default

    value = value.strip()
    if not value:
        return default

    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError, ValueError):
        return default


# ===========================================================================
# 6. 幂等性检查
# ===========================================================================

class IdempotencyChecker:
    """幂等性检查器：检查记录是否已存在于目标表.

    支持：
    - 单键检查（单个唯一字段）
    - 复合键检查（多个字段组合唯一）
    - 批量检查（减少数据库往返）
    - 内存缓存（可选，适合小表高频检查场景）

    兼容 sqlite3 原生连接和 SQLAlchemy session。
    """

    def __init__(
        self,
        conn: Any,
        table_name: str,
        unique_keys: List[str],
        use_cache: bool = False,
        cache_max_size: int = 10000,
    ):
        """
        Args:
            conn: 数据库连接（sqlite3.Connection 或 SQLAlchemy Session）
            table_name: 目标表名
            unique_keys: 唯一键字段列表（单键传 [\"id\"]，复合键传 [\"user_id\", \"item_id\"]）
            use_cache: 是否启用内存缓存
            cache_max_size: 缓存最大条数
        """
        self.conn = conn
        self.table_name = table_name
        self.unique_keys = list(unique_keys)
        self.use_cache = use_cache
        self.cache_max_size = cache_max_size

        # 缓存：用 frozenset of (key, value) 对 作为 key
        self._cache: Set[frozenset] = set()
        self._lock = threading.Lock()

        # 检测连接类型
        self._is_sqlalchemy = self._detect_sqlalchemy()

    def _detect_sqlalchemy(self) -> bool:
        """检测是否为 SQLAlchemy session."""
        try:
            from sqlalchemy.orm import Session
            return isinstance(self.conn, Session)
        except ImportError:
            return False

    def _make_cache_key(self, **kwargs: Any) -> frozenset:
        """生成缓存键."""
        items = [(k, str(kwargs.get(k, ""))) for k in self.unique_keys]
        return frozenset(items)

    def exists(self, **kwargs: Any) -> bool:
        """检查单条记录是否已存在.

        Args:
            **kwargs: 唯一键字段的值

        Returns:
            True 表示已存在
        """
        # 检查缓存
        if self.use_cache:
            cache_key = self._make_cache_key(**kwargs)
            with self._lock:
                if cache_key in self._cache:
                    return True

        # 构建查询
        conditions = " AND ".join(f"{k} = ?" for k in self.unique_keys)
        values = tuple(kwargs.get(k) for k in self.unique_keys)
        query = f"SELECT 1 FROM {self.table_name} WHERE {conditions} LIMIT 1"

        result = False

        if self._is_sqlalchemy:
            # SQLAlchemy 方式
            row = self.conn.execute(query, values).fetchone()
            result = row is not None
        else:
            # sqlite3 方式
            cursor = self.conn.execute(query, values)
            result = cursor.fetchone() is not None

        # 更新缓存
        if result and self.use_cache:
            cache_key = self._make_cache_key(**kwargs)
            with self._lock:
                if len(self._cache) < self.cache_max_size:
                    self._cache.add(cache_key)

        return result

    def batch_check(self, keys_list: List[Dict[str, Any]]) -> Set[str]:
        """批量检查记录是否已存在.

        Args:
            keys_list: 唯一键字典列表，每个 dict 包含所有 unique_keys 的值

        Returns:
            已存在记录的标识集合，每个标识是 "key1=val1|key2=val2" 格式的字符串
        """
        if not keys_list:
            return set()

        existing: Set[str] = set()

        if self._is_sqlalchemy:
            # SQLAlchemy：逐条检查（通用方式）
            # 批量查询需要动态构建 SQL，用 OR 连接
            if len(self.unique_keys) == 1:
                # 单键批量：用 IN 查询
                key = self.unique_keys[0]
                values = [item.get(key) for item in keys_list]
                placeholders = ", ".join("?" for _ in values)
                query = (
                    f"SELECT {key} FROM {self.table_name} "
                    f"WHERE {key} IN ({placeholders})"
                )
                rows = self.conn.execute(query, tuple(values)).fetchall()
                for row in rows:
                    # 兼容 Row 和 tuple
                    if isinstance(row, tuple):
                        val = row[0]
                    else:
                        row_dict = row_to_dict(row)
                        val = row_dict[key]
                    existing.add(f"{key}={val}")
            else:
                # 复合键：逐条检查（简单可靠）
                for item in keys_list:
                    if self.exists(**item):
                        key_str = "|".join(
                            f"{k}={item.get(k)}" for k in self.unique_keys
                        )
                        existing.add(key_str)
        else:
            # sqlite3 方式
            if len(self.unique_keys) == 1:
                key = self.unique_keys[0]
                values = [item.get(key) for item in keys_list]
                placeholders = ", ".join("?" for _ in values)
                query = (
                    f"SELECT {key} FROM {self.table_name} "
                    f"WHERE {key} IN ({placeholders})"
                )
                cursor = self.conn.execute(query, tuple(values))
                for row in cursor.fetchall():
                    # 兼容 sqlite3.Row 和普通 tuple
                    if isinstance(row, tuple):
                        val = row[0]
                    else:
                        row_dict = row_to_dict(row)
                        val = row_dict[key]
                    existing.add(f"{key}={val}")
            else:
                # 复合键：逐条检查
                for item in keys_list:
                    if self.exists(**item):
                        key_str = "|".join(
                            f"{k}={item.get(k)}" for k in self.unique_keys
                        )
                        existing.add(key_str)

        # 更新缓存
        if self.use_cache:
            with self._lock:
                for item in keys_list:
                    key_str = "|".join(f"{k}={item.get(k)}" for k in self.unique_keys)
                    if key_str in existing and len(self._cache) < self.cache_max_size:
                        self._cache.add(self._make_cache_key(**item))

        return existing

    def mark_exists(self, **kwargs: Any) -> None:
        """手动标记某条记录为已存在（用于缓存预热）.

        Args:
            **kwargs: 唯一键字段的值
        """
        if not self.use_cache:
            return
        cache_key = self._make_cache_key(**kwargs)
        with self._lock:
            if len(self._cache) < self.cache_max_size:
                self._cache.add(cache_key)

    def clear_cache(self) -> None:
        """清空缓存."""
        with self._lock:
            self._cache.clear()


# ===========================================================================
# 7. 迁移执行器基类
# ===========================================================================

class BaseDataMigrator(ABC):
    """数据迁移执行器抽象基类.

    提供通用的迁移框架，子类只需实现表级的具体逻辑。

    核心能力：
    - 分批迁移 + 进度追踪
    - 幂等性检查（可配置）
    - 指数退避重试
    - 断点续传（checkpoint）
    - 统计汇总
    - 钩子方法（on_table_start / on_table_complete / on_error）

    子类需要实现的方法：
    - get_tables(): 返回待迁移表的配置列表
    - convert_row(table_name, row): 行数据转换
    - insert_batch(table_name, records): 批量插入目标库

    使用示例::

        class MyMigrator(BaseDataMigrator):
            def get_tables(self):
                return [
                    {"name": "users", "idempotent_key": "user_id"},
                    {"name": "orders", "idempotent_composite": ["user_id", "order_id"]},
                ]

            def convert_row(self, table_name, row):
                return {"field": row["field"]}

            def insert_batch(self, table_name, records):
                # 批量写入目标库
                ...
    """

    def __init__(
        self,
        source_conn: Any,
        target_conn: Any,
        *,
        batch_size: int = 1000,
        max_retries: int = 3,
        base_delay: float = 1.0,
        dry_run: bool = False,
        checkpoint_manager: Optional[CheckpointManager] = None,
        logger: Optional[logging.Logger] = None,
    ):
        """
        Args:
            source_conn: 源数据库连接
            target_conn: 目标数据库连接
            batch_size: 每批处理记录数，默认 1000
            max_retries: 失败最大重试次数，默认 3
            base_delay: 重试初始延迟秒数，默认 1.0
            dry_run: 试运行模式（不写入目标库）
            checkpoint_manager: 断点管理器，为 None 则不启用断点续传
            logger: 日志器，为 None 则使用 print
        """
        self.source_conn = source_conn
        self.target_conn = target_conn
        self.batch_size = batch_size
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.dry_run = dry_run
        self.checkpoint = checkpoint_manager
        self.logger = logger

        self.stats = MigrationStats(
            migration_id=f"migration_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            dry_run=dry_run,
        )

        self._idempotency_checkers: Dict[str, IdempotencyChecker] = {}

    # ---- 抽象方法 ----

    @abstractmethod
    def get_tables(self) -> List[Dict[str, Any]]:
        """获取待迁移表的配置列表.

        每个配置项包含：
        - name: 源表名（必填）
        - target_table: 目标表名（可选，默认与源表同名）
        - idempotent_key: 单个唯一键字段名（可选）
        - idempotent_composite: 复合唯一键字段列表（可选）
        - query: 自定义源查询 SQL（可选，默认 SELECT * FROM {name}）
        - order_by: 排序字段（可选，默认 id）
        - enabled: 是否启用（可选，默认 True）

        Returns:
            表配置字典列表
        """

    @abstractmethod
    def convert_row(self, table_name: str, row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """将源行数据转换为目标表格式.

        Args:
            table_name: 表名
            row: 源数据字典

        Returns:
            转换后的数据字典，返回 None 表示跳过该行
        """

    @abstractmethod
    def insert_batch(self, table_name: str, records: List[Dict[str, Any]]) -> Tuple[int, int]:
        """批量插入目标库.

        Args:
            table_name: 目标表名
            records: 待插入记录列表

        Returns:
            (成功插入数, 跳过数) 元组
        """

    # ---- 钩子方法（可选覆写） ----

    def on_table_start(self, table_name: str, stats: TableMigrationStats) -> None:
        """单表迁移开始钩子.

        Args:
            table_name: 表名
            stats: 该表的统计对象
        """
        msg = f"\n{'─' * 50}\n迁移表: {table_name}\n{'─' * 50}"
        self._log(msg)

    def on_table_complete(self, table_name: str, stats: TableMigrationStats) -> None:
        """单表迁移完成钩子.

        Args:
            table_name: 表名
            stats: 该表的统计对象
        """
        msg = (
            f"  完成: 迁移 {stats.migrated:,} 条, "
            f"跳过 {stats.skipped:,} 条, "
            f"失败 {stats.failed:,} 条, "
            f"耗时 {format_duration(stats.duration_seconds)}"
        )
        self._log(msg)

    def on_error(self, table_name: str, error: Exception, context: Optional[dict] = None) -> None:
        """错误钩子.

        Args:
            table_name: 表名
            error: 异常对象
            context: 上下文信息
        """
        ctx_str = f" ({context})" if context else ""
        self._log(f"  [ERROR] {table_name}: {error}{ctx_str}", level="error")

    # ---- 核心方法 ----

    def run(self) -> MigrationStats:
        """执行完整迁移流程.

        Returns:
            MigrationStats 统计信息
        """
        self.stats.mark_start()

        self._log("=" * 60)
        self._log(f"  数据迁移开始")
        self._log(f"  模式: {'DRY-RUN' if self.dry_run else 'FULL MIGRATION'}")
        self._log(f"  批次大小: {self.batch_size}")
        self._log(f"  最大重试: {self.max_retries}")
        self._log("=" * 60)

        # 加载断点
        if self.checkpoint:
            self.checkpoint.load()

        try:
            tables = self.get_tables()

            for table_config in tables:
                if not table_config.get("enabled", True):
                    continue

                table_name = table_config["name"]
                self._migrate_table(table_config)

        except Exception as e:
            self._log(f"\n[FATAL] 迁移异常: {e}", level="error")
            # 保存断点
            if self.checkpoint and not self.dry_run:
                try:
                    self.checkpoint.set_extra("fatal_error", str(e))
                    self.checkpoint.save()
                except Exception:
                    pass
        finally:
            self.stats.mark_end()

        # 输出汇总
        self._log(self.stats.summary_text())

        # 迁移成功则清除断点
        if self.checkpoint and not self.dry_run and not self.stats.has_errors:
            self.checkpoint.clear()
            self._log("  断点已清除")

        return self.stats

    # ---- 内部方法 ----

    def _migrate_table(self, table_config: Dict[str, Any]) -> None:
        """迁移单张表."""
        table_name = table_config["name"]
        target_table = table_config.get("target_table", table_name)

        table_stats = self.stats.get_table(table_name)
        table_stats.start_time = time.time()

        # 钩子：开始
        self.on_table_start(table_name, table_stats)

        # 检查断点：表已完成则跳过
        if self.checkpoint and self.checkpoint.is_table_complete(table_name):
            source_total = self._count_source(table_config)
            table_stats.source_total = source_total
            table_stats.migrated = source_total  # 假设全部已迁移
            table_stats.end_time = time.time()
            self._log(f"  [跳过] checkpoint 标记已完成，跳过该表")
            return

        # 获取源数据总数
        source_total = self._count_source(table_config)
        table_stats.source_total = source_total
        self._log(f"  源数据总数: {source_total:,}")

        if source_total == 0:
            table_stats.end_time = time.time()
            self._log(f"  [跳过] 源表无数据")
            if self.checkpoint:
                self.checkpoint.mark_table_complete(table_name)
            return

        # 初始化幂等性检查器
        idem_checker = self._get_idempotency_checker(table_config, target_table)

        # 进度追踪
        progress = ProgressTracker(
            source_total,
            label=table_name,
            logger=self.logger,
            report_interval=5.0,
        )

        # 断点续传：起始偏移
        offset = 0
        if self.checkpoint:
            saved_offset = self.checkpoint.get_table_offset(table_name)
            if saved_offset is not None:
                offset = int(saved_offset) if isinstance(saved_offset, (int, str)) else 0
                if offset > 0:
                    self._log(f"  断点续传: 从 offset={offset:,} 继续")
                    progress.update(offset)

        # 分批迁移
        batch_count = 0
        while offset < source_total:
            try:
                batch_migrated, batch_skipped, batch_failed = self._process_batch(
                    table_config,
                    target_table,
                    offset,
                    idem_checker,
                )
                table_stats.migrated += batch_migrated
                table_stats.skipped += batch_skipped
                table_stats.failed += batch_failed

                actual_processed = batch_migrated + batch_skipped + batch_failed
                progress.update(actual_processed)
                offset += actual_processed
                batch_count += 1

                # 定期保存断点
                if self.checkpoint and batch_count % 10 == 0 and not self.dry_run:
                    self.checkpoint.set_table_offset(table_name, offset)
                    self.checkpoint.save()

            except Exception as e:
                table_stats.failed += 1
                table_stats.add_error(f"batch offset={offset}: {e}")
                self.on_error(table_name, e, {"offset": offset})
                # 保存断点后抛出
                if self.checkpoint and not self.dry_run:
                    self.checkpoint.set_table_offset(table_name, offset)
                    self.checkpoint.save()
                raise

        # 标记表完成
        table_stats.end_time = time.time()

        if self.checkpoint and not self.dry_run:
            self.checkpoint.mark_table_complete(table_name)

        # 钩子：完成
        self.on_table_complete(table_name, table_stats)

    def _process_batch(
        self,
        table_config: Dict[str, Any],
        target_table: str,
        offset: int,
        idem_checker: Optional[IdempotencyChecker],
    ) -> Tuple[int, int, int]:
        """处理一批数据，返回 (迁移数, 跳过数, 失败数)."""
        table_name = table_config["name"]

        # 读取一批源数据
        batch = self._fetch_batch(table_config, offset)
        if not batch:
            return (0, 0, 0)

        # 数据转换
        converted: List[Dict[str, Any]] = []
        convert_failed = 0

        for row in batch:
            try:
                row_dict = row_to_dict(row)
                result = self.convert_row(table_name, row_dict)
                if result is not None:
                    converted.append(result)
                else:
                    # convert_row 返回 None 表示跳过
                    pass
            except Exception as e:
                convert_failed += 1
                row_id = "?"
                try:
                    rd = row_to_dict(row)
                    row_id = str(rd.get("id", "?"))
                except Exception:
                    pass
                self._log(f"  [WARN] 转换失败 id={row_id}: {e}", level="warning")

        if not converted:
            return (0, 0, convert_failed)

        # 幂等性检查（批量）
        if idem_checker and not self.dry_run:
            # 提取唯一键
            unique_keys = idem_checker.unique_keys
            keys_for_check = [
                {k: rec.get(k) for k in unique_keys}
                for rec in converted
            ]
            existing_set = idem_checker.batch_check(keys_for_check)

            # 过滤已存在的记录
            new_records = []
            skipped = 0
            for rec, keys in zip(converted, keys_for_check):
                key_str = "|".join(f"{k}={keys.get(k)}" for k in unique_keys)
                if key_str in existing_set:
                    skipped += 1
                else:
                    new_records.append(rec)
        else:
            new_records = converted
            skipped = 0

        # 插入目标库
        if self.dry_run:
            # dry-run: 不实际插入
            return (len(new_records), skipped, convert_failed)

        try:
            inserted, insert_skipped = self._retry_insert(
                target_table, new_records
            )
            return (inserted, skipped + insert_skipped, convert_failed)
        except Exception as e:
            raise e

    def _retry_insert(
        self,
        table_name: str,
        records: List[Dict[str, Any]],
    ) -> Tuple[int, int]:
        """带重试的批量插入."""
        def _do_insert():
            return self.insert_batch(table_name, records)

        return retry_with_backoff(
            _do_insert,
            max_retries=self.max_retries,
            base_delay=self.base_delay,
            logger=self.logger,
        )

    def _count_source(self, table_config: Dict[str, Any]) -> int:
        """统计源表记录数."""
        table_name = table_config["name"]
        custom_query = table_config.get("query")

        if custom_query:
            count_query = f"SELECT COUNT(*) FROM ({custom_query})"
        else:
            count_query = f"SELECT COUNT(*) FROM {table_name}"

        # 检测连接类型
        if self._is_sqlalchemy(self.source_conn):
            row = self.source_conn.execute(count_query).fetchone()
            return int(row[0]) if row else 0
        else:
            cursor = self.source_conn.execute(count_query)
            row = cursor.fetchone()
            return int(row[0]) if row else 0

    def _fetch_batch(self, table_config: Dict[str, Any], offset: int) -> List[Any]:
        """分批读取源数据."""
        table_name = table_config["name"]
        order_by = table_config.get("order_by", "id")
        custom_query = table_config.get("query")

        if custom_query:
            query = (
                f"SELECT * FROM ({custom_query}) "
                f"ORDER BY {order_by} LIMIT ? OFFSET ?"
            )
        else:
            query = (
                f"SELECT * FROM {table_name} "
                f"ORDER BY {order_by} LIMIT ? OFFSET ?"
            )

        if self._is_sqlalchemy(self.source_conn):
            result = self.source_conn.execute(query, (self.batch_size, offset))
            return list(result.fetchall())
        else:
            cursor = self.source_conn.execute(query, (self.batch_size, offset))
            return cursor.fetchall()

    def _get_idempotency_checker(
        self,
        table_config: Dict[str, Any],
        target_table: str,
    ) -> Optional[IdempotencyChecker]:
        """获取幂等性检查器（懒加载 + 缓存）."""
        table_name = table_config["name"]

        if table_name in self._idempotency_checkers:
            return self._idempotency_checkers[table_name]

        # 确定唯一键
        unique_keys: Optional[List[str]] = None
        if "idempotent_key" in table_config:
            unique_keys = [table_config["idempotent_key"]]
        elif "idempotent_composite" in table_config:
            unique_keys = list(table_config["idempotent_composite"])

        if not unique_keys:
            self._idempotency_checkers[table_name] = None  # type: ignore
            return None

        checker = IdempotencyChecker(
            self.target_conn,
            target_table,
            unique_keys,
            use_cache=False,  # 默认不启用缓存，子类可覆写
        )
        self._idempotency_checkers[table_name] = checker
        return checker

    @staticmethod
    def _is_sqlalchemy(conn: Any) -> bool:
        """检测连接是否为 SQLAlchemy session."""
        try:
            from sqlalchemy.orm import Session
            return isinstance(conn, Session)
        except ImportError:
            return False

    def _log(self, msg: str, level: str = "info") -> None:
        """日志输出."""
        if self.logger:
            getattr(self.logger, level)(msg)
        else:
            print(msg)
