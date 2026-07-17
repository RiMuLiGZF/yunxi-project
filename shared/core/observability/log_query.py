"""
云汐日志查询与归档引擎（OP-006, P1级）
======================================

提供生产级别的日志查询和归档能力：

日志查询：
- 按级别、模块、时间范围、关键字搜索
- 支持正则表达式搜索
- 日志统计分析（级别分布、模块分布、时间分布）
- 日志分类：系统日志 / 业务日志 / 安全日志
- 日志采样（高流量场景下减少查询压力）

日志归档：
- 三级存储：热数据（7天）/ 温数据（30天）/ 冷数据（30天+）
- 自动归档调度
- 归档压缩（gzip）
- 归档索引
- 冷数据恢复

核心类：
- LogCategory: 日志分类枚举
- ArchiveTier: 归档层级枚举
- LogSearchResult: 搜索结果数据类
- LogStats: 日志统计数据类
- LogQueryEngine: 日志查询引擎
- LogArchiver: 日志归档管理器

使用方式：
    from shared.core.observability import LogQueryEngine, LogArchiver, get_log_query_engine

    # 查询日志
    engine = get_log_query_engine()
    results = engine.search(level="ERROR", module="m8", keyword="timeout")

    # 日志统计
    stats = engine.get_stats(last_hours=24)

    # 日志归档
    archiver = LogArchiver(log_dir="./logs")
    result = archiver.run_archive()
"""

import os
import re
import json
import gzip
import time
import shutil
import threading
from enum import Enum
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple, Pattern
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict


# ============================================================================
# 枚举类型
# ============================================================================

class LogCategory(str, Enum):
    """日志分类

    - SYSTEM: 系统日志（框架、中间件、基础设施）
    - BUSINESS: 业务日志（用户操作、业务流程）
    - SECURITY: 安全日志（登录、权限、攻击检测）
    - AUDIT: 审计日志（关键操作记录）
    - PERFORMANCE: 性能日志（慢查询、耗时统计）
    """
    SYSTEM = "system"
    BUSINESS = "business"
    SECURITY = "security"
    AUDIT = "audit"
    PERFORMANCE = "performance"


class ArchiveTier(str, Enum):
    """归档层级

    - HOT: 热数据（最近7天，快速查询）
    - WARM: 温数据（7-30天，压缩存储）
    - COLD: 冷数据（30天以上，归档到文件）
    """
    HOT = "hot"
    WARM = "warm"
    COLD = "cold"


# ============================================================================
# 数据模型
# ============================================================================

@dataclass
class LogEntry:
    """单条日志记录"""
    timestamp: str
    level: str
    logger: str
    module: str
    message: str
    category: LogCategory = LogCategory.SYSTEM
    trace_id: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)
    raw_line: str = ""
    file_path: str = ""
    line_number: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "level": self.level,
            "logger": self.logger,
            "module": self.module,
            "message": self.message,
            "category": self.category.value,
            "trace_id": self.trace_id,
            "extra": self.extra,
            "file_path": self.file_path,
            "line_number": self.line_number,
        }


@dataclass
class LogSearchResult:
    """日志搜索结果"""
    total: int = 0
    entries: List[LogEntry] = field(default_factory=list)
    page: int = 1
    page_size: int = 100
    has_more: bool = False
    search_time_ms: float = 0.0
    files_scanned: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total": self.total,
            "page": self.page,
            "page_size": self.page_size,
            "has_more": self.has_more,
            "search_time_ms": round(self.search_time_ms, 2),
            "files_scanned": self.files_scanned,
            "entries": [e.to_dict() for e in self.entries],
        }


@dataclass
class LogStats:
    """日志统计信息"""
    total_lines: int = 0
    level_distribution: Dict[str, int] = field(default_factory=dict)
    module_distribution: Dict[str, int] = field(default_factory=dict)
    category_distribution: Dict[str, int] = field(default_factory=dict)
    hourly_distribution: Dict[str, int] = field(default_factory=dict)
    error_count: int = 0
    warning_count: int = 0
    top_error_messages: List[Tuple[str, int]] = field(default_factory=list)
    time_range_hours: int = 24

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_lines": self.total_lines,
            "time_range_hours": self.time_range_hours,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "level_distribution": self.level_distribution,
            "module_distribution": self.module_distribution,
            "category_distribution": self.category_distribution,
            "hourly_distribution": self.hourly_distribution,
            "top_error_messages": [
                {"message": msg, "count": cnt}
                for msg, cnt in self.top_error_messages[:10]
            ],
        }


@dataclass
class ArchiveResult:
    """归档结果"""
    success: bool = True
    files_archived: int = 0
    files_compressed: int = 0
    bytes_freed: int = 0
    cold_moved: int = 0
    warm_moved: int = 0
    error: str = ""
    archive_time_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "files_archived": self.files_archived,
            "files_compressed": self.files_compressed,
            "bytes_freed": self.bytes_freed,
            "bytes_freed_mb": round(self.bytes_freed / (1024 * 1024), 2),
            "cold_moved": self.cold_moved,
            "warm_moved": self.warm_moved,
            "error": self.error,
            "archive_time_ms": round(self.archive_time_ms, 2),
        }


# ============================================================================
# 日志查询引擎
# ============================================================================

class LogQueryEngine:
    """日志查询引擎

    支持多维度日志搜索和统计分析：
    - 按级别过滤（DEBUG/INFO/WARNING/ERROR/CRITICAL）
    - 按模块过滤
    - 按时间范围过滤
    - 按关键字搜索（支持正则）
    - 按分类过滤（系统/业务/安全/审计/性能）
    - 日志统计分析
    """

    # 日志级别映射
    LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

    # 模块到日志文件名的映射
    MODULE_LOG_MAP = {
        "m8": ["yunxi.m8.log", "m8.log"],
        "m1": ["yunxi.m1.log", "m1.log"],
        "m2": ["yunxi.m2.log", "m2.log"],
        "m3": ["yunxi.m3.log", "m3.log"],
        "m4": ["yunxi.m4.log", "m4.log"],
        "m5": ["yunxi.m5.log", "m5.log"],
        "m6": ["yunxi.m6.log", "m6.log"],
        "m7": ["yunxi.m7.log", "m7.log"],
        "m9": ["yunxi.m9.log", "m9.log"],
        "m10": ["yunxi.m10.log", "m10.log"],
        "m11": ["yunxi.m11.log", "m11.log"],
        "m12": ["yunxi.m12.log", "m12.log"],
        "gateway": ["gateway.log", "api-gateway.log"],
    }

    # 安全相关关键字（用于自动识别安全日志）
    SECURITY_KEYWORDS = [
        "login", "auth", "password", "token", "permission",
        "unauthorized", "forbidden", "attack", "injection", "xss",
        "csrf", "sql injection", "brute force", "suspicious",
        "security", "vulnerability", "exploit",
    ]

    # 业务相关关键字
    BUSINESS_KEYWORDS = [
        "user", "order", "payment", "transaction", "register",
        "profile", "settings", "preference", "workflow", "task",
        "agent", "conversation", "message", "chat",
    ]

    # 性能相关关键字
    PERFORMANCE_KEYWORDS = [
        "slow", "timeout", "latency", "performance", "throughput",
        "qps", "tps", "response_time", "duration", "耗时", "超时",
    ]

    def __init__(
        self,
        log_dir: Optional[str] = None,
        max_file_size_mb: int = 500,
    ):
        """
        Args:
            log_dir: 日志目录路径，None 则从环境变量或默认路径获取
            max_file_size_mb: 单次扫描最大文件大小（MB），防止超大文件导致内存溢出
        """
        if log_dir is None:
            log_dir = os.getenv("LOG_DIR", os.getenv("YUNXI_LOG_DIR", "./logs"))
        self._log_dir = Path(log_dir).resolve()
        self._max_file_size = max_file_size_mb * 1024 * 1024
        self._lock = threading.Lock()

    @property
    def log_dir(self) -> Path:
        """日志目录"""
        return self._log_dir

    # -----------------------------------------------------------------------
    # 日志搜索
    # -----------------------------------------------------------------------

    def search(
        self,
        level: Optional[str] = None,
        module: Optional[str] = None,
        keyword: Optional[str] = None,
        regex: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        category: Optional[LogCategory] = None,
        trace_id: Optional[str] = None,
        page: int = 1,
        page_size: int = 100,
        case_sensitive: bool = False,
        sample_rate: float = 1.0,
    ) -> LogSearchResult:
        """搜索日志

        Args:
            level: 日志级别（DEBUG/INFO/WARNING/ERROR/CRITICAL）
            module: 模块名
            keyword: 关键字搜索
            regex: 正则表达式搜索（优先级高于 keyword）
            start_time: 开始时间（ISO 格式或 YYYY-MM-DD HH:MM:SS）
            end_time: 结束时间
            category: 日志分类
            trace_id: 追踪 ID
            page: 页码（从 1 开始）
            page_size: 每页条数
            case_sensitive: 是否区分大小写
            sample_rate: 采样率（0-1，1 表示全部）

        Returns:
            LogSearchResult
        """
        start_time_search = time.time()
        result = LogSearchResult(page=page, page_size=page_size)

        # 解析时间范围
        start_dt = self._parse_time(start_time) if start_time else None
        end_dt = self._parse_time(end_time) if end_time else None

        # 编译正则
        pattern: Optional[Pattern] = None
        if regex:
            flags = 0 if case_sensitive else re.IGNORECASE
            try:
                pattern = re.compile(regex, flags)
            except re.error:
                pattern = None
        elif keyword:
            flags = 0 if case_sensitive else re.IGNORECASE
            pattern = re.compile(re.escape(keyword), flags)

        # 获取要扫描的文件列表
        log_files = self._get_log_files(module)
        result.files_scanned = len(log_files)

        # 计算跳过的条目数
        skip = (page - 1) * page_size
        collected = 0
        total_matched = 0

        for log_file in log_files:
            if not log_file.exists():
                continue

            # 检查文件大小
            try:
                if log_file.stat().st_size > self._max_file_size:
                    continue
            except OSError:
                continue

            entries = self._parse_log_file(
                log_file,
                level=level,
                pattern=pattern,
                start_dt=start_dt,
                end_dt=end_dt,
                category=category,
                trace_id=trace_id,
                module=module,
            )

            # 采样
            if sample_rate < 1.0 and sample_rate > 0:
                import random
                entries = [e for e in entries if random.random() < sample_rate]

            total_matched += len(entries)

            # 分页
            for entry in entries:
                if skip > 0:
                    skip -= 1
                    continue
                if collected < page_size:
                    result.entries.append(entry)
                    collected += 1
                else:
                    result.has_more = True
                    break

            if result.has_more:
                break

        result.total = total_matched
        result.search_time_ms = (time.time() - start_time_search) * 1000

        return result

    def _get_log_files(self, module: Optional[str] = None) -> List[Path]:
        """获取要扫描的日志文件列表"""
        if not self._log_dir.exists():
            return []

        files: List[Path] = []

        if module:
            # 按模块过滤
            candidates = self.MODULE_LOG_MAP.get(module.lower(), [f"{module}.log"])
            for candidate in candidates:
                log_file = self._log_dir / candidate
                if log_file.exists():
                    files.append(log_file)
                # 也检查压缩文件
                gz_file = log_file.with_suffix(log_file.suffix + ".gz")
                if gz_file.exists():
                    files.append(gz_file)
                # 检查带日期后缀的文件
                for f in self._log_dir.glob(f"{candidate}.*"):
                    if f.is_file() and not f.name.endswith(".gz"):
                        files.append(f)
        else:
            # 扫描所有 .log 文件
            for f in sorted(self._log_dir.glob("*.log"), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True):
                if f.is_file():
                    files.append(f)

        return files

    def _parse_log_file(
        self,
        log_file: Path,
        level: Optional[str] = None,
        pattern: Optional[Pattern] = None,
        start_dt: Optional[datetime] = None,
        end_dt: Optional[datetime] = None,
        category: Optional[LogCategory] = None,
        trace_id: Optional[str] = None,
        module: Optional[str] = None,
    ) -> List[LogEntry]:
        """解析单个日志文件

        支持 JSON 格式和文本格式的日志。
        """
        entries: List[LogEntry] = []
        level_upper = level.upper() if level else None

        # 判断是否为 gz 压缩文件
        is_gz = log_file.suffix == ".gz"

        try:
            if is_gz:
                opener = lambda: gzip.open(str(log_file), "rt", encoding="utf-8", errors="replace")
            else:
                opener = lambda: open(str(log_file), "r", encoding="utf-8", errors="replace")

            with opener() as f:
                line_num = 0
                for line in f:
                    line_num += 1
                    line = line.rstrip("\n\r")
                    if not line:
                        continue

                    # 尝试 JSON 解析
                    entry = self._parse_json_line(line, log_file, line_num)
                    if entry is None:
                        # 尝试文本格式解析
                        entry = self._parse_text_line(line, log_file, line_num)

                    if entry is None:
                        continue

                    # 模块推断
                    if not entry.module and module:
                        entry.module = module
                    elif not entry.module:
                        entry.module = self._infer_module_from_filename(log_file)

                    # 分类推断
                    if entry.category == LogCategory.SYSTEM:
                        entry.category = self._categorize_log(entry)

                    # 过滤条件
                    if level_upper and entry.level.upper() != level_upper:
                        # 也检查 ERROR 级别是否包含 CRITICAL
                        if level_upper == "ERROR" and entry.level.upper() == "CRITICAL":
                            pass
                        else:
                            continue

                    if category and entry.category != category:
                        continue

                    if trace_id and entry.trace_id != trace_id:
                        continue

                    # 时间过滤
                    entry_dt = self._parse_timestamp(entry.timestamp)
                    if entry_dt:
                        if start_dt and entry_dt < start_dt:
                            continue
                        if end_dt and entry_dt > end_dt:
                            continue

                    # 关键字/正则匹配
                    if pattern:
                        search_target = entry.message
                        if entry.extra:
                            search_target += " " + json.dumps(entry.extra, ensure_ascii=False)
                        if not pattern.search(search_target):
                            continue

                    entries.append(entry)

        except (OSError, IOError):
            pass

        return entries

    def _parse_json_line(self, line: str, log_file: Path, line_num: int) -> Optional[LogEntry]:
        """尝试解析 JSON 格式的日志行"""
        if not line.strip().startswith("{"):
            return None

        try:
            data = json.loads(line)
            return LogEntry(
                timestamp=str(data.get("timestamp", "")),
                level=str(data.get("level", "INFO")),
                logger=str(data.get("logger", "")),
                module=str(data.get("module", data.get("module_key", ""))),
                message=str(data.get("message", "")),
                trace_id=str(data.get("trace_id", "")),
                extra={k: v for k, v in data.items() if k not in {
                    "timestamp", "level", "logger", "module", "module_key",
                    "message", "trace_id", "span_id", "function", "line",
                }},
                raw_line=line,
                file_path=str(log_file),
                line_number=line_num,
            )
        except (json.JSONDecodeError, ValueError):
            return None

    def _parse_text_line(self, line: str, log_file: Path, line_num: int) -> Optional[LogEntry]:
        """尝试解析文本格式的日志行

        支持格式：
        - 2024-01-01 12:00:00 INFO module: message
        - [2024-01-01 12:00:00] [INFO] [module] message
        """
        # 尝试匹配标准格式
        patterns = [
            # 2024-01-01 12:00:00 INFO module: message
            r"^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:[.,]\d+)?)\s+(\w+)\s+([^:]+):\s+(.*)$",
            # [2024-01-01 12:00:00] [INFO] [module] message
            r"^\[(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:[.,]\d+)?)\]\s*\[(\w+)\]\s*\[([^\]]+)\]\s*(.*)$",
        ]

        for pat in patterns:
            match = re.match(pat, line)
            if match:
                timestamp, level, module, message = match.groups()
                return LogEntry(
                    timestamp=timestamp,
                    level=level.upper(),
                    logger=module.strip(),
                    module=module.strip(),
                    message=message.strip(),
                    raw_line=line,
                    file_path=str(log_file),
                    line_number=line_num,
                )

        return None

    def _categorize_log(self, entry: LogEntry) -> LogCategory:
        """根据日志内容推断分类"""
        msg_lower = entry.message.lower()
        level_upper = entry.level.upper()

        # 安全日志
        for kw in self.SECURITY_KEYWORDS:
            if kw in msg_lower:
                return LogCategory.SECURITY

        # 审计日志（通常是 INFO 级别，包含操作记录）
        if level_upper == "INFO" and any(kw in msg_lower for kw in ["create", "update", "delete", "modify", "操作"]):
            if entry.logger and "audit" in entry.logger.lower():
                return LogCategory.AUDIT

        # 性能日志
        for kw in self.PERFORMANCE_KEYWORDS:
            if kw in msg_lower:
                return LogCategory.PERFORMANCE

        # 业务日志
        for kw in self.BUSINESS_KEYWORDS:
            if kw in msg_lower:
                return LogCategory.BUSINESS

        return LogCategory.SYSTEM

    def _infer_module_from_filename(self, log_file: Path) -> str:
        """从文件名推断模块名"""
        name = log_file.stem
        # 去掉日期后缀
        for suffix in [".log", ".error", "-error"]:
            if name.endswith(suffix):
                name = name[: -len(suffix)]

        # 去掉 yunxi. 前缀
        if name.startswith("yunxi."):
            name = name[6:]

        return name

    def _parse_time(self, time_str: str) -> Optional[datetime]:
        """解析时间字符串"""
        formats = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%d",
            "%Y/%m/%d %H:%M:%S",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(time_str, fmt)
            except ValueError:
                continue
        return None

    def _parse_timestamp(self, timestamp: str) -> Optional[datetime]:
        """解析日志时间戳"""
        if not timestamp:
            return None
        return self._parse_time(timestamp)

    # -----------------------------------------------------------------------
    # 日志统计
    # -----------------------------------------------------------------------

    def get_stats(
        self,
        last_hours: int = 24,
        module: Optional[str] = None,
    ) -> LogStats:
        """获取日志统计信息

        Args:
            last_hours: 统计最近多少小时
            module: 按模块统计，None 表示全部

        Returns:
            LogStats
        """
        stats = LogStats(time_range_hours=last_hours)
        start_dt = datetime.now() - timedelta(hours=last_hours)

        log_files = self._get_log_files(module)
        error_messages: Dict[str, int] = defaultdict(int)

        for log_file in log_files:
            if not log_file.exists():
                continue

            is_gz = log_file.suffix == ".gz"
            try:
                if is_gz:
                    opener = lambda: gzip.open(str(log_file), "rt", encoding="utf-8", errors="replace")
                else:
                    opener = lambda: open(str(log_file), "r", encoding="utf-8", errors="replace")

                with opener() as f:
                    for line in f:
                        line = line.rstrip("\n\r")
                        if not line:
                            continue

                        entry = self._parse_json_line(line, log_file, 0)
                        if entry is None:
                            entry = self._parse_text_line(line, log_file, 0)
                        if entry is None:
                            continue

                        # 时间过滤
                        entry_dt = self._parse_timestamp(entry.timestamp)
                        if entry_dt and entry_dt < start_dt:
                            continue

                        stats.total_lines += 1

                        # 级别分布
                        level = entry.level.upper()
                        stats.level_distribution[level] = stats.level_distribution.get(level, 0) + 1

                        if level in ("ERROR", "CRITICAL"):
                            stats.error_count += 1
                            # 统计错误消息（取前100个字符作为key）
                            msg_key = entry.message[:100]
                            error_messages[msg_key] += 1
                        elif level == "WARNING":
                            stats.warning_count += 1

                        # 模块分布
                        if entry.module:
                            stats.module_distribution[entry.module] = (
                                stats.module_distribution.get(entry.module, 0) + 1
                            )

                        # 分类分布
                        cat = self._categorize_log(entry).value
                        stats.category_distribution[cat] = (
                            stats.category_distribution.get(cat, 0) + 1
                        )

                        # 小时分布
                        if entry_dt:
                            hour_key = entry_dt.strftime("%Y-%m-%d %H:00")
                            stats.hourly_distribution[hour_key] = (
                                stats.hourly_distribution.get(hour_key, 0) + 1
                            )

            except (OSError, IOError):
                continue

        # Top 错误消息
        stats.top_error_messages = sorted(
            error_messages.items(), key=lambda x: x[1], reverse=True
        )[:10]

        return stats

    # -----------------------------------------------------------------------
    # 日志级别和分类列表
    # -----------------------------------------------------------------------

    def get_available_levels(self) -> List[str]:
        """获取可用的日志级别"""
        return list(self.LEVELS)

    def get_available_modules(self) -> List[str]:
        """获取有日志的模块列表"""
        if not self._log_dir.exists():
            return []

        modules = set()
        for f in self._log_dir.glob("*.log"):
            module = self._infer_module_from_filename(f)
            if module:
                modules.add(module)

        return sorted(modules)

    def get_available_categories(self) -> List[str]:
        """获取可用的日志分类"""
        return [c.value for c in LogCategory]

    def get_log_file_list(self) -> List[Dict[str, Any]]:
        """获取日志文件列表"""
        if not self._log_dir.exists():
            return []

        files = []
        for f in sorted(self._log_dir.glob("*"), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True):
            if f.is_file() and (f.suffix == ".log" or f.suffix == ".gz"):
                try:
                    stat = f.stat()
                    files.append({
                        "name": f.name,
                        "size_bytes": stat.st_size,
                        "size_kb": round(stat.st_size / 1024, 2),
                        "modified_time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        "is_compressed": f.suffix == ".gz",
                    })
                except OSError:
                    pass

        return files


# ============================================================================
# 日志归档管理器
# ============================================================================

class LogArchiver:
    """日志归档管理器

    三级归档策略：
    - HOT: 热数据（最近7天），保留原始格式，快速查询
    - WARM: 温数据（7-30天），gzip 压缩存储
    - COLD: 冷数据（30天以上），归档到独立目录

    支持：
    - 自动归档调度
    - 归档索引管理
    - 冷数据恢复
    - 归档空间统计
    """

    def __init__(
        self,
        log_dir: Optional[str] = None,
        archive_dir: Optional[str] = None,
        hot_days: int = 7,
        warm_days: int = 23,  # 7 + 23 = 30 天
        cold_dir: Optional[str] = None,
    ):
        """
        Args:
            log_dir: 日志目录
            archive_dir: 归档目录（温数据存储位置）
            hot_days: 热数据保留天数
            warm_days: 温数据保留天数（在热数据之后）
            cold_dir: 冷数据归档目录
        """
        if log_dir is None:
            log_dir = os.getenv("LOG_DIR", os.getenv("YUNXI_LOG_DIR", "./logs"))
        self._log_dir = Path(log_dir).resolve()

        if archive_dir is None:
            archive_dir = self._log_dir / "archive"
        self._archive_dir = Path(archive_dir).resolve()

        if cold_dir is None:
            cold_dir = self._archive_dir / "cold"
        self._cold_dir = Path(cold_dir).resolve()

        self._hot_days = hot_days
        self._warm_days = warm_days
        self._cold_threshold_days = hot_days + warm_days

        self._lock = threading.Lock()
        self._index_file = self._archive_dir / "archive_index.json"

    # -----------------------------------------------------------------------
    # 执行归档
    # -----------------------------------------------------------------------

    def run_archive(self, dry_run: bool = False) -> ArchiveResult:
        """执行归档操作

        Args:
            dry_run: 试运行模式，只统计不实际操作

        Returns:
            ArchiveResult
        """
        start_time = time.time()
        result = ArchiveResult()

        try:
            # 确保目录存在
            if not dry_run:
                self._archive_dir.mkdir(parents=True, exist_ok=True)
                self._cold_dir.mkdir(parents=True, exist_ok=True)

            now = datetime.now()
            hot_cutoff = now - timedelta(days=self._hot_days)
            cold_cutoff = now - timedelta(days=self._cold_threshold_days)

            if not self._log_dir.exists():
                result.success = True
                result.archive_time_ms = (time.time() - start_time) * 1000
                return result

            # 扫描日志目录
            for log_file in self._log_dir.glob("*.log*"):
                if not log_file.is_file():
                    continue

                try:
                    mtime = datetime.fromtimestamp(log_file.stat().st_mtime)
                    file_size = log_file.stat().st_size

                    # 冷数据：超过 cold_threshold_days 天
                    if mtime < cold_cutoff:
                        if not dry_run:
                            self._move_to_cold(log_file)
                        result.cold_moved += 1
                        result.bytes_freed += file_size
                        result.files_archived += 1
                    # 温数据：超过 hot_days 但未到 cold
                    elif mtime < hot_cutoff:
                        if log_file.suffix != ".gz":
                            if not dry_run:
                                self._compress_to_warm(log_file)
                            result.warm_moved += 1
                            result.files_compressed += 1
                            result.files_archived += 1
                            # 压缩后大约节省 70% 空间
                            result.bytes_freed += int(file_size * 0.7)

                except OSError:
                    continue

            # 扫描归档目录中的温数据，移到冷数据
            if self._archive_dir.exists():
                for arch_file in self._archive_dir.glob("*.gz"):
                    if not arch_file.is_file():
                        continue
                    try:
                        mtime = datetime.fromtimestamp(arch_file.stat().st_mtime)
                        if mtime < cold_cutoff:
                            if not dry_run:
                                self._move_archive_to_cold(arch_file)
                            result.cold_moved += 1
                            result.files_archived += 1
                    except OSError:
                        continue

            # 更新索引
            if not dry_run:
                self._update_index()

            result.success = True
            result.archive_time_ms = (time.time() - start_time) * 1000

        except Exception as e:
            result.success = False
            result.error = str(e)
            result.archive_time_ms = (time.time() - start_time) * 1000

        return result

    def _compress_to_warm(self, log_file: Path) -> bool:
        """压缩日志文件到温存储"""
        try:
            gz_path = self._archive_dir / (log_file.name + ".gz")

            # 如果已存在则跳过
            if gz_path.exists():
                # 删除原始文件
                log_file.unlink()
                return True

            # 压缩
            with open(log_file, "rb") as f_in:
                with gzip.open(str(gz_path), "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)

            # 删除原始文件
            log_file.unlink()
            return True
        except Exception:
            return False

    def _move_to_cold(self, log_file: Path) -> bool:
        """移动日志文件到冷存储"""
        try:
            # 先压缩（如果未压缩）
            if log_file.suffix != ".gz":
                gz_name = log_file.name + ".gz"
                gz_path = self._cold_dir / gz_name

                if not gz_path.exists():
                    with open(log_file, "rb") as f_in:
                        with gzip.open(str(gz_path), "wb") as f_out:
                            shutil.copyfileobj(f_in, f_out)

                log_file.unlink()
            else:
                dest = self._cold_dir / log_file.name
                if not dest.exists():
                    shutil.move(str(log_file), str(dest))
                else:
                    log_file.unlink()

            return True
        except Exception:
            return False

    def _move_archive_to_cold(self, arch_file: Path) -> bool:
        """将归档目录中的文件移到冷存储"""
        try:
            dest = self._cold_dir / arch_file.name
            if not dest.exists():
                shutil.move(str(arch_file), str(dest))
            else:
                arch_file.unlink()
            return True
        except Exception:
            return False

    # -----------------------------------------------------------------------
    # 归档索引
    # -----------------------------------------------------------------------

    def _update_index(self) -> None:
        """更新归档索引"""
        try:
            index = {
                "updated_at": datetime.now().isoformat(),
                "hot_days": self._hot_days,
                "warm_days": self._warm_days,
                "cold_threshold_days": self._cold_threshold_days,
                "warm_files": [],
                "cold_files": [],
                "warm_size_bytes": 0,
                "cold_size_bytes": 0,
            }

            # 温数据索引
            if self._archive_dir.exists():
                for f in self._archive_dir.glob("*.gz"):
                    if f.is_file():
                        try:
                            stat = f.stat()
                            index["warm_files"].append({
                                "name": f.name,
                                "size_bytes": stat.st_size,
                                "modified_time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                            })
                            index["warm_size_bytes"] += stat.st_size
                        except OSError:
                            pass

            # 冷数据索引
            if self._cold_dir.exists():
                for f in self._cold_dir.glob("*.gz"):
                    if f.is_file():
                        try:
                            stat = f.stat()
                            index["cold_files"].append({
                                "name": f.name,
                                "size_bytes": stat.st_size,
                                "modified_time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                            })
                            index["cold_size_bytes"] += stat.st_size
                        except OSError:
                            pass

            self._index_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._index_file, "w", encoding="utf-8") as f:
                json.dump(index, f, indent=2, ensure_ascii=False)

        except Exception:
            pass

    def get_archive_index(self) -> Dict[str, Any]:
        """获取归档索引"""
        try:
            if self._index_file.exists():
                with open(self._index_file, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass

        return {
            "updated_at": None,
            "hot_days": self._hot_days,
            "warm_days": self._warm_days,
            "cold_threshold_days": self._cold_threshold_days,
            "warm_files": [],
            "cold_files": [],
            "warm_size_bytes": 0,
            "cold_size_bytes": 0,
        }

    # -----------------------------------------------------------------------
    # 冷数据恢复
    # -----------------------------------------------------------------------

    def restore_from_cold(
        self,
        file_name: str,
        output_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        """从冷存储恢复日志文件

        Args:
            file_name: 要恢复的文件名
            output_dir: 输出目录，None 则恢复到日志目录

        Returns:
            恢复结果字典
        """
        try:
            cold_file = self._cold_dir / file_name
            if not cold_file.exists():
                return {"success": False, "error": f"File not found in cold storage: {file_name}"}

            if output_dir is None:
                output_dir = str(self._log_dir)

            out_path = Path(output_dir)
            out_path.mkdir(parents=True, exist_ok=True)

            dest = out_path / file_name

            # 复制文件
            shutil.copy2(str(cold_file), str(dest))

            return {
                "success": True,
                "restored_file": str(dest),
                "size_bytes": cold_file.stat().st_size,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # -----------------------------------------------------------------------
    # 空间统计
    # -----------------------------------------------------------------------

    def get_storage_stats(self) -> Dict[str, Any]:
        """获取存储统计信息"""
        stats = {
            "hot": {"size_bytes": 0, "file_count": 0},
            "warm": {"size_bytes": 0, "file_count": 0},
            "cold": {"size_bytes": 0, "file_count": 0},
            "total_size_bytes": 0,
            "total_files": 0,
        }

        # 热数据
        if self._log_dir.exists():
            for f in self._log_dir.glob("*.log*"):
                if f.is_file():
                    try:
                        stats["hot"]["size_bytes"] += f.stat().st_size
                        stats["hot"]["file_count"] += 1
                    except OSError:
                        pass

        # 温数据
        if self._archive_dir.exists():
            for f in self._archive_dir.glob("*.gz"):
                if f.is_file():
                    try:
                        stats["warm"]["size_bytes"] += f.stat().st_size
                        stats["warm"]["file_count"] += 1
                    except OSError:
                        pass

        # 冷数据
        if self._cold_dir.exists():
            for f in self._cold_dir.glob("*.gz"):
                if f.is_file():
                    try:
                        stats["cold"]["size_bytes"] += f.stat().st_size
                        stats["cold"]["file_count"] += 1
                    except OSError:
                        pass

        stats["total_size_bytes"] = (
            stats["hot"]["size_bytes"]
            + stats["warm"]["size_bytes"]
            + stats["cold"]["size_bytes"]
        )
        stats["total_files"] = (
            stats["hot"]["file_count"]
            + stats["warm"]["file_count"]
            + stats["cold"]["file_count"]
        )

        # 添加人类可读的大小
        for tier in ["hot", "warm", "cold"]:
            stats[tier]["size_mb"] = round(stats[tier]["size_bytes"] / (1024 * 1024), 2)

        stats["total_size_mb"] = round(stats["total_size_bytes"] / (1024 * 1024), 2)

        return stats

    def get_archive_config(self) -> Dict[str, Any]:
        """获取归档配置"""
        return {
            "log_dir": str(self._log_dir),
            "archive_dir": str(self._archive_dir),
            "cold_dir": str(self._cold_dir),
            "hot_days": self._hot_days,
            "warm_days": self._warm_days,
            "cold_threshold_days": self._cold_threshold_days,
        }


# ============================================================================
# 全局单例
# ============================================================================

_query_engine: Optional[LogQueryEngine] = None
_query_engine_lock = threading.Lock()


def get_log_query_engine(log_dir: Optional[str] = None) -> LogQueryEngine:
    """获取全局日志查询引擎（单例）

    Args:
        log_dir: 日志目录

    Returns:
        LogQueryEngine 实例
    """
    global _query_engine
    if _query_engine is None:
        with _query_engine_lock:
            if _query_engine is None:
                _query_engine = LogQueryEngine(log_dir=log_dir)
    return _query_engine


def reset_log_query_engine() -> None:
    """重置全局日志查询引擎（主要用于测试）"""
    global _query_engine
    with _query_engine_lock:
        _query_engine = None


# ============================================================================
# 模块导出
# ============================================================================

__all__ = [
    # 枚举
    "LogCategory",
    "ArchiveTier",
    # 数据模型
    "LogEntry",
    "LogSearchResult",
    "LogStats",
    "ArchiveResult",
    # 主类
    "LogQueryEngine",
    "LogArchiver",
    # 全局函数
    "get_log_query_engine",
    "reset_log_query_engine",
]
