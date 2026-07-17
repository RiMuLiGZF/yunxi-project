"""
云汐统一日志系统

支持：
- 结构化日志（JSON格式 / 可读文本格式）
- 多输出目标（控制台 + 文件 + Redis 通道）
- 日志级别动态调整（环境变量配置）
- 上下文注入（trace_id、user_id、span_id 等）
- 日志轮转（按天轮转 + 大小限制 + 自动清理 + gzip 压缩）
- 敏感字段自动脱敏（password, token, secret, key 等）
- 高性能：异步批量写入、惰性初始化
- 向后兼容：兼容标准 logging 用法
- 日志清理工具：过期日志清理、目录大小统计、日志归档

轮转配置（环境变量）：
    LOG_ROTATION_ENABLED=true/false        # 是否启用轮转，默认 true
    LOG_ROTATION_WHEN=midnight/hourly/weekly/daily  # 轮转时机，默认 midnight
    LOG_ROTATION_BACKUP_COUNT=30           # 保留份数/天数，默认 30
    LOG_ROTATION_MAX_BYTES=104857600       # 单文件最大字节数，默认 100MB
    LOG_ROTATION_COMPRESS=true/false       # 是否自动 gzip 压缩，默认 true
    LOG_ROTATION_INTERVAL=1                # 轮转间隔，默认 1

使用方式：
    from shared.core.observability import get_logger

    logger = get_logger("my_module")
    logger.info("user login", user_id="123", ip="192.168.1.1")
    logger.error("request failed", error="timeout", trace_id="abc123")
"""
import os
import sys
import gzip
import shutil
import json
import re
import logging
import logging.handlers
from typing import Optional, Dict, Any, List, Set, Tuple
from pathlib import Path
from datetime import datetime, timedelta
from contextvars import ContextVar
from functools import lru_cache


# ============================================================================
# 日志轮转配置
# ============================================================================

class LogRotationConfig:
    """日志轮转配置（支持环境变量覆盖）

    默认配置：
    - 按天轮转（midnight）
    - 保留 30 天
    - 单个日志文件最大 100MB（兜底防止单日过大）
    - 自动 gzip 压缩旧日志
    - 轮转功能默认启用

    环境变量：
        LOG_ROTATION_ENABLED=true/false    # 是否启用轮转
        LOG_ROTATION_WHEN=midnight/hourly/weekly/daily  # 轮转时机
        LOG_ROTATION_BACKUP_COUNT=30       # 保留份数/天数
        LOG_ROTATION_MAX_BYTES=104857600   # 单文件最大字节数（兜底）
        LOG_ROTATION_COMPRESS=true/false   # 是否自动压缩旧日志
        LOG_ROTATION_INTERVAL=1            # 轮转间隔
    """

    # 默认值
    DEFAULT_ENABLED = True
    DEFAULT_WHEN = "midnight"
    DEFAULT_BACKUP_COUNT = 30
    DEFAULT_MAX_BYTES = 100 * 1024 * 1024  # 100MB
    DEFAULT_COMPRESS = True
    DEFAULT_INTERVAL = 1

    # 合法的 when 值
    VALID_WHEN_VALUES = {"S", "M", "H", "D", "W0", "W1", "W2", "W3", "W4", "W5", "W6",
                         "midnight", "hourly", "daily", "weekly"}

    # when 到标准值的映射（友好名称 -> logging.handlers 标准值）
    _WHEN_MAPPING = {
        "hourly": "H",
        "daily": "midnight",
        "weekly": "W0",
    }

    def __init__(
        self,
        enabled: Optional[bool] = None,
        when: Optional[str] = None,
        backup_count: Optional[int] = None,
        max_bytes: Optional[int] = None,
        compress: Optional[bool] = None,
        interval: Optional[int] = None,
    ):
        """
        初始化轮转配置，未指定的参数从环境变量读取，环境变量未设置则使用默认值。

        Args:
            enabled: 是否启用轮转
            when: 轮转时机（midnight/hourly/weekly/daily 或标准值）
            backup_count: 保留的备份文件数
            max_bytes: 单文件最大字节数（size 模式或兜底）
            compress: 是否自动 gzip 压缩
            interval: 轮转间隔（配合 when 使用）
        """
        # 从环境变量读取
        env_enabled = os.getenv("LOG_ROTATION_ENABLED",
                                os.getenv("YUNXI_LOG_ROTATION_ENABLED", ""))
        env_when = os.getenv("LOG_ROTATION_WHEN",
                             os.getenv("YUNXI_LOG_ROTATION_WHEN", ""))
        env_backup = os.getenv("LOG_ROTATION_BACKUP_COUNT",
                               os.getenv("YUNXI_LOG_ROTATION_BACKUP_COUNT", ""))
        env_max_bytes = os.getenv("LOG_ROTATION_MAX_BYTES",
                                  os.getenv("YUNXI_LOG_ROTATION_MAX_BYTES", ""))
        env_compress = os.getenv("LOG_ROTATION_COMPRESS",
                                 os.getenv("YUNXI_LOG_ROTATION_COMPRESS", ""))
        env_interval = os.getenv("LOG_ROTATION_INTERVAL",
                                 os.getenv("YUNXI_LOG_ROTATION_INTERVAL", ""))

        # enabled
        if enabled is not None:
            self.enabled = enabled
        elif env_enabled:
            self.enabled = env_enabled.lower() in ("true", "1", "yes", "on")
        else:
            self.enabled = self.DEFAULT_ENABLED

        # when
        if when is not None:
            self.when = self._normalize_when(when)
        elif env_when:
            self.when = self._normalize_when(env_when)
        else:
            self.when = self.DEFAULT_WHEN

        # backup_count
        if backup_count is not None:
            self.backup_count = max(0, backup_count)
        elif env_backup:
            try:
                self.backup_count = max(0, int(env_backup))
            except (ValueError, TypeError):
                self.backup_count = self.DEFAULT_BACKUP_COUNT
        else:
            self.backup_count = self.DEFAULT_BACKUP_COUNT

        # max_bytes
        if max_bytes is not None:
            self.max_bytes = max(0, max_bytes)
        elif env_max_bytes:
            try:
                self.max_bytes = max(0, int(env_max_bytes))
            except (ValueError, TypeError):
                self.max_bytes = self.DEFAULT_MAX_BYTES
        else:
            self.max_bytes = self.DEFAULT_MAX_BYTES

        # compress
        if compress is not None:
            self.compress = compress
        elif env_compress:
            self.compress = env_compress.lower() in ("true", "1", "yes", "on")
        else:
            self.compress = self.DEFAULT_COMPRESS

        # interval
        if interval is not None:
            self.interval = max(1, interval)
        elif env_interval:
            try:
                self.interval = max(1, int(env_interval))
            except (ValueError, TypeError):
                self.interval = self.DEFAULT_INTERVAL
        else:
            self.interval = self.DEFAULT_INTERVAL

    @classmethod
    def _normalize_when(cls, when: str) -> str:
        """标准化 when 值，支持友好名称"""
        when_lower = when.lower().strip()
        if when_lower in cls._WHEN_MAPPING:
            return cls._WHEN_MAPPING[when_lower]
        # 检查是否为标准值（不区分大小写匹配）
        for valid in cls.VALID_WHEN_VALUES:
            if when_lower == valid.lower():
                return valid
        # 不合法时返回默认
        return cls.DEFAULT_WHEN

    @property
    def is_time_based(self) -> bool:
        """是否为基于时间的轮转"""
        return self.when != "size" and self.when in {"S", "M", "H", "D", "W0", "W1",
                                                      "W2", "W3", "W4", "W5", "W6", "midnight"}

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "enabled": self.enabled,
            "when": self.when,
            "backup_count": self.backup_count,
            "max_bytes": self.max_bytes,
            "compress": self.compress,
            "interval": self.interval,
            "is_time_based": self.is_time_based,
        }

    def __repr__(self) -> str:
        return (f"LogRotationConfig(enabled={self.enabled}, when='{self.when}', "
                f"backup_count={self.backup_count}, max_bytes={self.max_bytes}, "
                f"compress={self.compress}, interval={self.interval})")


# ============================================================================
# 带 gzip 压缩的轮转文件处理器
# ============================================================================

class GzipTimedRotatingFileHandler(logging.handlers.TimedRotatingFileHandler):
    """支持自动 gzip 压缩的时间轮转文件处理器

    轮转时自动将旧日志文件压缩为 .gz 格式，节省磁盘空间。
    线程安全（继承自父类的锁机制）。
    """

    def __init__(self, *args, compress: bool = True, **kwargs):
        super().__init__(*args, **kwargs)
        self.compress = compress

    def doRollover(self):
        """执行轮转，完成后自动压缩旧文件"""
        # 先执行父类的轮转逻辑
        super().doRollover()

        if not self.compress:
            return

        # 找到刚轮转出来的旧文件并压缩
        # TimedRotatingFileHandler 轮转后，旧文件名为 baseFilename + suffix
        # 我们需要找到所有未压缩的旧日志文件并压缩
        self._compress_rotated_files()

    def _compress_rotated_files(self):
        """压缩所有已轮转但未压缩的旧日志文件"""
        import glob

        # 获取 baseFilename 的目录和前缀
        base_dir = os.path.dirname(self.baseFilename) or "."
        base_name = os.path.basename(self.baseFilename)

        # 查找已轮转的文件（带有日期后缀，不是 .gz）
        pattern = os.path.join(base_dir, f"{base_name}.*")
        for filepath in glob.glob(pattern):
            # 跳过已经压缩的文件
            if filepath.endswith(".gz"):
                continue
            # 跳过当前正在写入的文件
            if filepath == self.baseFilename:
                continue
            # 跳过 error 日志的压缩（已由 error handler 自己处理）
            # 检查是否存在对应的 .gz 文件，如果已存在则跳过
            gz_path = filepath + ".gz"
            if os.path.exists(gz_path):
                continue

            try:
                with open(filepath, 'rb') as f_in:
                    with gzip.open(gz_path, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
                # 压缩成功后删除原文件
                os.remove(filepath)
            except Exception:
                # 压缩失败时静默，不影响日志写入
                pass


class GzipRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """支持自动 gzip 压缩的大小轮转文件处理器

    轮转时自动将旧日志文件压缩为 .gz 格式，节省磁盘空间。
    线程安全（继承自父类的锁机制）。
    """

    def __init__(self, *args, compress: bool = True, **kwargs):
        super().__init__(*args, **kwargs)
        self.compress = compress

    def doRollover(self):
        """执行轮转，完成后自动压缩旧文件"""
        super().doRollover()

        if not self.compress:
            return

        self._compress_rotated_files()

    def _compress_rotated_files(self):
        """压缩所有已轮转但未压缩的旧日志文件"""
        import glob

        base_dir = os.path.dirname(self.baseFilename) or "."
        base_name = os.path.basename(self.baseFilename)

        # 查找已轮转的文件（带有数字后缀，不是 .gz）
        pattern = os.path.join(base_dir, f"{base_name}.*")
        for filepath in glob.glob(pattern):
            if filepath.endswith(".gz"):
                continue
            if filepath == self.baseFilename:
                continue

            gz_path = filepath + ".gz"
            if os.path.exists(gz_path):
                continue

            try:
                with open(filepath, 'rb') as f_in:
                    with gzip.open(gz_path, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
                os.remove(filepath)
            except Exception:
                pass


# ============================================================================
# 日志清理工具函数
# ============================================================================

def get_log_dir_size(log_dir: str) -> Tuple[int, int]:
    """统计日志目录的总大小和文件数量

    Args:
        log_dir: 日志目录路径

    Returns:
        (总字节数, 文件数量)
    """
    total_size = 0
    file_count = 0
    log_path = Path(log_dir)

    if not log_path.exists():
        return 0, 0

    for f in log_path.rglob("*"):
        if f.is_file():
            try:
                total_size += f.stat().st_size
                file_count += 1
            except OSError:
                pass

    return total_size, file_count


def clean_expired_logs(
    log_dir: str,
    max_age_days: int = 30,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """清理过期日志文件

    Args:
        log_dir: 日志目录路径
        max_age_days: 最大保留天数
        dry_run: 试运行模式，只统计不删除

    Returns:
        清理结果字典
    """
    log_path = Path(log_dir)
    if not log_path.exists():
        return {"deleted": 0, "freed_bytes": 0, "log_dir": log_dir, "dry_run": dry_run}

    cutoff_time = datetime.now() - timedelta(days=max_age_days)
    deleted_count = 0
    freed_bytes = 0

    for f in log_path.rglob("*"):
        if not f.is_file():
            continue
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime)
            if mtime < cutoff_time:
                size = f.stat().st_size
                if not dry_run:
                    f.unlink()
                deleted_count += 1
                freed_bytes += size
        except OSError:
            pass

    return {
        "deleted": deleted_count,
        "freed_bytes": freed_bytes,
        "freed_mb": round(freed_bytes / (1024 * 1024), 2),
        "log_dir": log_dir,
        "max_age_days": max_age_days,
        "dry_run": dry_run,
    }


def archive_logs(
    log_dir: str,
    output_dir: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Dict[str, Any]:
    """归档指定时间段的日志

    Args:
        log_dir: 日志目录
        output_dir: 归档输出目录
        start_date: 开始日期（YYYY-MM-DD）
        end_date: 结束日期（YYYY-MM-DD）

    Returns:
        归档结果字典
    """
    log_path = Path(log_dir)
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    if not log_path.exists():
        return {"archived": 0, "output_dir": str(output_dir)}

    # 解析日期
    start_dt = None
    end_dt = None
    if start_date:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    if end_date:
        end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)

    archived_count = 0

    for f in log_path.rglob("*"):
        if not f.is_file():
            continue
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime)
            # 日期过滤
            if start_dt and mtime < start_dt:
                continue
            if end_dt and mtime >= end_dt:
                continue

            # 复制到归档目录，保持目录结构
            rel_path = f.relative_to(log_path)
            dest = out_path / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(f), str(dest))
            archived_count += 1
        except (OSError, ValueError):
            pass

    return {
        "archived": archived_count,
        "output_dir": str(output_dir),
        "start_date": start_date,
        "end_date": end_date,
    }


# ============================================================================
# 敏感字段脱敏配置
# ============================================================================

# 需要脱敏的字段名（不区分大小写，支持部分匹配）
SENSITIVE_FIELDS: Set[str] = {
    "password", "passwd", "pwd",
    "token", "access_token", "refresh_token", "api_token",
    "secret", "secret_key", "api_key", "app_key", "private_key",
    "authorization", "auth", "auth_token",
    "cookie", "session", "session_id",
    "credit_card", "card_number", "cvv",
    "phone", "mobile", "email",
    "id_card", "idcard", "identity",
}

# 脱敏替换值
MASK_VALUE = "***MASKED***"

# 部分匹配的字段前缀/后缀
SENSITIVE_PATTERNS: List[str] = [
    r".*password.*", r".*token.*", r".*secret.*",
    r".*key.*", r".*auth.*", r".*credential.*",
]


def mask_sensitive_data(data: Any, depth: int = 0, max_depth: int = 5) -> Any:
    """
    递归脱敏敏感数据

    Args:
        data: 需要脱敏的数据
        depth: 当前递归深度
        max_depth: 最大递归深度

    Returns:
        脱敏后的数据
    """
    if depth > max_depth:
        return data

    if data is None:
        return None

    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            key_lower = str(key).lower()
            # 检查是否为敏感字段
            if _is_sensitive_field(key_lower):
                result[key] = MASK_VALUE
            else:
                result[key] = mask_sensitive_data(value, depth + 1, max_depth)
        return result

    if isinstance(data, (list, tuple)):
        return [mask_sensitive_data(item, depth + 1, max_depth) for item in data]

    # 字符串类型：检查是否为常见敏感格式
    if isinstance(data, str):
        # 长 token/key 模式（32位以上十六进制或base64）
        if len(data) > 32 and re.match(r'^[a-zA-Z0-9+/=\-]{32,}$', data):
            # 可能是 token/key，保留前后各4位
            return data[:4] + MASK_VALUE + data[-4:]
        return data

    return data


def _is_sensitive_field(field_name: str) -> bool:
    """
    判断字段名是否为敏感字段

    Args:
        field_name: 字段名（小写）

    Returns:
        是否为敏感字段
    """
    # 精确匹配
    if field_name in SENSITIVE_FIELDS:
        return True

    # 正则匹配
    for pattern in SENSITIVE_PATTERNS:
        if re.match(pattern, field_name, re.IGNORECASE):
            return True

    return False


# ============================================================================
# 日志格式化器
# ============================================================================

class JsonFormatter(logging.Formatter):
    """JSON格式日志格式化器（生产环境）"""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "message": record.getMessage(),
        }

        # 添加异常信息
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        # 添加上下文信息（从 record 属性注入）
        for attr in ("trace_id", "span_id", "user_id", "module_key", "request_id"):
            val = getattr(record, attr, None)
            if val is not None:
                log_entry[attr] = val

        # 添加 extra 字段（从 record 中提取非标准字段）
        extra = {}
        standard_attrs = {
            'name', 'msg', 'args', 'levelname', 'levelno', 'pathname',
            'filename', 'module', 'exc_info', 'exc_text', 'stack_info',
            'lineno', 'funcName', 'created', 'msecs', 'relativeCreated',
            'thread', 'threadName', 'processName', 'process', 'message',
            'asctime', 'taskName',
            'trace_id', 'span_id', 'user_id', 'module_key', 'request_id',
        }
        for key, value in record.__dict__.items():
            if key not in standard_attrs and not key.startswith('_'):
                extra[key] = value

        if extra:
            # 对 extra 进行敏感字段脱敏
            log_entry["extra"] = mask_sensitive_data(extra)

        return json.dumps(log_entry, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    """文本格式日志格式化器（开发环境，带颜色）"""

    COLORS = {
        "DEBUG": "\033[36m",     # 青色
        "INFO": "\033[32m",      # 绿色
        "WARNING": "\033[33m",   # 黄色
        "ERROR": "\033[31m",     # 红色
        "CRITICAL": "\033[35m",  # 紫色
    }
    RESET = "\033[0m"

    def __init__(self, *args, use_color: bool = True, **kwargs):
        super().__init__(*args, **kwargs)
        self.use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        if self.use_color:
            color = self.COLORS.get(record.levelname, "")
            reset = self.RESET if color else ""
        else:
            color = ""
            reset = ""

        timestamp = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")

        # 上下文信息
        context_parts = []
        trace_id = getattr(record, "trace_id", None)
        if trace_id:
            context_parts.append(f"trace:{trace_id[:8]}")
        span_id = getattr(record, "span_id", None)
        if span_id:
            context_parts.append(f"span:{span_id[:8]}")
        user_id = getattr(record, "user_id", None)
        if user_id:
            context_parts.append(f"user:{user_id}")

        context = f" [{', '.join(context_parts)}]" if context_parts else ""

        # 额外信息（取前几个关键字段）
        extra_parts = []
        standard_attrs = {
            'name', 'msg', 'args', 'levelname', 'levelno', 'pathname',
            'filename', 'module', 'exc_info', 'exc_text', 'stack_info',
            'lineno', 'funcName', 'created', 'msecs', 'relativeCreated',
            'thread', 'threadName', 'processName', 'process', 'message',
            'asctime', 'taskName',
            'trace_id', 'span_id', 'user_id', 'module_key', 'request_id',
        }
        for key, value in record.__dict__.items():
            if key not in standard_attrs and not key.startswith('_'):
                extra_parts.append(f"{key}={value}")
        extra_str = f" ({'; '.join(extra_parts[:5])})" if extra_parts else ""

        return (
            f"{timestamp} {color}{record.levelname:<8}{reset} "
            f"{record.name}{context}: {record.getMessage()}{extra_str}"
        )


# ============================================================================
# Redis 日志处理器（带降级和批量优化）
# ============================================================================

class RedisLogHandler(logging.Handler):
    """Redis 日志处理器（高性能版）

    将结构化日志写入 Redis list 通道，支持：
    - 连接失败自动降级（静默）
    - 批量写入（减少网络往返）
    - 日志条数上限（自动截断）
    - 惰性连接（首次写入才连接）
    """

    def __init__(
        self,
        redis_key: str = "yunxi:logs",
        max_len: int = 10000,
        level: int = logging.INFO,
        redis_url: Optional[str] = None,
    ):
        super().__init__(level=level)
        self.redis_key = redis_key
        self.max_len = max_len
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self._client = None
        self._available = None  # None=未检测, True=可用, False=不可用

    def _get_client(self):
        """获取 Redis 客户端（惰性初始化，带失败缓存）"""
        if self._available is False:
            return None

        if self._client is not None:
            return self._client

        try:
            import redis
            self._client = redis.Redis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_connect_timeout=1,
                socket_timeout=1,
                health_check_interval=30,
            )
            self._client.ping()
            self._available = True
            return self._client
        except Exception:
            self._available = False
            self._client = None
            return None

    def emit(self, record: logging.LogRecord) -> None:
        """发送日志到 Redis"""
        client = self._get_client()
        if client is None:
            return

        try:
            # 使用 JSON 格式化器格式化为 JSON 字符串
            if hasattr(self, 'formatter') and self.formatter:
                log_str = self.format(record)
            else:
                log_str = json.dumps({
                    "timestamp": record.created,
                    "level": record.levelname,
                    "module": record.name,
                    "message": record.getMessage(),
                }, ensure_ascii=False)

            # LPUSH + LTRIM 保持固定长度
            pipe = client.pipeline()
            pipe.lpush(self.redis_key, log_str)
            pipe.ltrim(self.redis_key, 0, self.max_len - 1)
            pipe.execute()
        except Exception:
            # 写入失败静默降级
            self._available = False

    def reset(self):
        """重置连接状态（用于重连）"""
        self._available = None
        self._client = None


# ============================================================================
# 上下文变量（用于跨函数传递日志上下文）
# ============================================================================

_log_context_var: ContextVar[Dict[str, Any]] = ContextVar(
    "log_context",
    default={},
)


def set_log_context(**kwargs) -> None:
    """
    设置全局日志上下文（线程/协程安全）

    上下文中的字段会自动附加到每条日志中。

    Args:
        **kwargs: 上下文字段键值对

    示例:
        set_log_context(trace_id="abc123", user_id="456")
    """
    current = _log_context_var.get()
    # 创建新 dict 避免修改 default
    ctx = dict(current) if current else {}
    ctx.update(kwargs)
    _log_context_var.set(ctx)


def clear_log_context() -> None:
    """清除全局日志上下文"""
    _log_context_var.set({})


def get_log_context() -> Dict[str, Any]:
    """获取当前日志上下文（返回副本，避免外部修改）"""
    current = _log_context_var.get()
    return dict(current) if current else {}


# ============================================================================
# 上下文注入过滤器
# ============================================================================

class ContextFilter(logging.Filter):
    """
    日志上下文注入过滤器

    将 ContextVar 中的上下文自动注入到每条 LogRecord 中，
    使得所有日志自动携带 trace_id、user_id 等上下文信息。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        ctx = _log_context_var.get()
        if ctx:
            for key, value in ctx.items():
                setattr(record, key, value)
        return True


# ============================================================================
# 统一日志管理器
# ============================================================================

class UnifiedLogger:
    """统一日志管理器

    提供结构化日志输出，支持多目标、多格式、上下文注入、敏感字段脱敏。

    使用方式:
        logger = UnifiedLogger("my_module")
        logger.info("hello", user_id="123")
        logger.error("error occurred", exc_info=True)
    """

    def __init__(
        self,
        name: str = "yunxi",
        level: str = "INFO",
        log_dir: Optional[str] = None,
        json_format: Optional[bool] = None,
        max_bytes: int = 50 * 1024 * 1024,  # 50MB（兼容旧参数）
        backup_count: int = 30,  # 保留30天/30份（兼容旧参数）
        console_output: bool = True,
        file_output: bool = True,
        redis_output: bool = False,
        redis_key: str = "yunxi:logs",
        rotation: str = "daily",  # daily / size（兼容旧参数）
        rotation_config: Optional[LogRotationConfig] = None,
        env: Optional[str] = None,
    ):
        """
        初始化统一日志器

        Args:
            name: 日志器名称
            level: 日志级别 (DEBUG/INFO/WARNING/ERROR/CRITICAL)
            log_dir: 日志目录，None则使用默认路径
            json_format: 是否使用JSON格式，None则根据环境自动判断
            max_bytes: 单个日志文件最大大小（size模式下，兼容旧参数）
            backup_count: 保留的日志文件数/天数（兼容旧参数）
            console_output: 是否输出到控制台
            file_output: 是否输出到文件
            redis_output: 是否输出到 Redis 通道
            redis_key: Redis 日志通道 key
            rotation: 轮转方式 daily/size（兼容旧参数）
            rotation_config: 轮转配置对象（优先使用，覆盖旧参数）
            env: 运行环境 development/production，None则从环境变量读取
        """
        self.name = name
        self.level = getattr(logging, level.upper(), logging.INFO)
        self.console_output = console_output
        self.file_output = file_output
        self.redis_output = redis_output
        self.redis_key = redis_key

        # 环境判断
        if env is None:
            env = os.getenv("YUNXI_ENV", os.getenv("ENV", "development"))
        self.env = env.lower()

        # 格式判断：生产环境默认 JSON，开发环境默认文本
        if json_format is None:
            json_format = self.env in ("production", "prod", "release")
        self.json_format = json_format

        # 日志目录
        if log_dir is None and file_output:
            log_dir = os.getenv("LOG_DIR", "./logs")
        self.log_dir = Path(log_dir) if log_dir else None

        # 轮转配置：优先使用 rotation_config，否则从旧参数+环境变量构建
        if rotation_config is not None:
            self.rotation_config = rotation_config
        else:
            # 根据旧参数构建配置（保持向后兼容）
            config_kwargs = {}
            if rotation == "size":
                # size 模式下使用 max_bytes
                config_kwargs["max_bytes"] = max_bytes
                config_kwargs["when"] = "size"
            else:
                # daily 模式
                config_kwargs["when"] = "midnight"
            config_kwargs["backup_count"] = backup_count
            # 其他参数从环境变量读取
            self.rotation_config = LogRotationConfig(**config_kwargs)

        # 兼容旧属性访问
        self.rotation = rotation
        self.max_bytes = self.rotation_config.max_bytes
        self.backup_count = self.rotation_config.backup_count

        # 构建日志器
        self._logger = self._build_logger()

    def _build_logger(self) -> logging.Logger:
        """构建日志器"""
        logger = logging.getLogger(self.name)
        logger.setLevel(self.level)
        logger.propagate = False

        # 清除已有 handler
        logger.handlers.clear()

        # 添加上下文过滤器
        logger.addFilter(ContextFilter())

        # 控制台输出
        if self.console_output:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(self.level)
            if self.json_format:
                console_handler.setFormatter(JsonFormatter())
            else:
                # 控制台默认带颜色（Windows 下也兼容）
                use_color = sys.stdout.isatty() and os.name != "nt" or True
                console_handler.setFormatter(TextFormatter(use_color=use_color))
            logger.addHandler(console_handler)

        # 文件输出
        if self.file_output and self.log_dir:
            self.log_dir.mkdir(parents=True, exist_ok=True)

            # 主日志文件
            main_log = self.log_dir / f"{self.name}.log"
            file_handler = self._create_file_handler(str(main_log), self.level)
            file_handler.setFormatter(JsonFormatter())
            logger.addHandler(file_handler)

            # 错误日志文件（单独文件，只记录 ERROR 及以上）
            error_log = self.log_dir / f"{self.name}-error.log"
            error_handler = self._create_file_handler(str(error_log), logging.ERROR)
            error_handler.setFormatter(JsonFormatter())
            logger.addHandler(error_handler)

        # Redis 输出
        if self.redis_output:
            redis_handler = RedisLogHandler(
                redis_key=self.redis_key,
                level=logging.WARNING,  # Redis 只记录 WARNING 及以上，减少流量
            )
            redis_handler.setFormatter(JsonFormatter())
            logger.addHandler(redis_handler)

        return logger

    def _create_file_handler(self, filename: str, level: int) -> logging.Handler:
        """创建文件 handler（根据轮转配置）

        如果轮转被禁用，则使用普通的 FileHandler。
        否则根据配置选择时间轮转或大小轮转，并支持 gzip 压缩。
        """
        config = self.rotation_config

        # 轮转被禁用时使用普通 FileHandler
        if not config.enabled:
            handler = logging.FileHandler(filename, encoding="utf-8")
            handler.setLevel(level)
            return handler

        # 根据轮转类型选择 handler
        if config.is_time_based:
            # 时间轮转（支持 gzip 压缩）
            handler = GzipTimedRotatingFileHandler(
                filename,
                when=config.when,
                interval=config.interval,
                backupCount=config.backup_count,
                encoding="utf-8",
                utc=False,
                compress=config.compress,
            )
            handler.suffix = "%Y-%m-%d"
        else:
            # 大小轮转（支持 gzip 压缩）
            handler = GzipRotatingFileHandler(
                filename,
                maxBytes=config.max_bytes,
                backupCount=config.backup_count,
                encoding="utf-8",
                compress=config.compress,
            )

        handler.setLevel(level)
        return handler

    def set_context(self, **kwargs):
        """
        设置日志上下文（附加到每条日志）

        注意：这会影响当前线程/协程中所有使用同一上下文的日志器。
        推荐使用 set_log_context() 全局函数。
        """
        set_log_context(**kwargs)

    def clear_context(self):
        """清除上下文"""
        clear_log_context()

    # ---- 日志方法 ----

    def debug(self, msg: str, *args, **kwargs):
        if args:
            msg = msg % args
        self._log(logging.DEBUG, msg, kwargs)

    def info(self, msg: str, *args, **kwargs):
        if args:
            msg = msg % args
        self._log(logging.INFO, msg, kwargs)

    def warning(self, msg: str, *args, **kwargs):
        if args:
            msg = msg % args
        self._log(logging.WARNING, msg, kwargs)

    def warn(self, msg: str, *args, **kwargs):
        self.warning(msg, *args, **kwargs)

    def error(self, msg: str, *args, exc_info=False, **kwargs):
        if args:
            msg = msg % args
        self._log(logging.ERROR, msg, kwargs, exc_info=exc_info)

    def critical(self, msg: str, *args, exc_info=False, **kwargs):
        if args:
            msg = msg % args
        self._log(logging.CRITICAL, msg, kwargs, exc_info=exc_info)

    def exception(self, msg: str, *args, **kwargs):
        if args:
            msg = msg % args
        self._log(logging.ERROR, msg, kwargs, exc_info=True)

    # LogRecord 保留属性名，不能出现在 extra 中
    _RESERVED_LOGRECORD_ATTRS = {
        "name", "msg", "args", "levelname", "levelno", "pathname",
        "filename", "module", "exc_info", "exc_text", "stack_info",
        "lineno", "funcName", "created", "msecs", "relativeCreated",
        "thread", "threadName", "process", "processName",
        "message", "asctime", "taskName",
    }

    def _log(self, level: int, msg: str, extra: Dict[str, Any], exc_info: bool = False):
        """统一日志记录方法"""
        # 对 extra 进行敏感字段脱敏
        if extra:
            extra = mask_sensitive_data(extra)
            # 过滤/重命名与 LogRecord 保留属性冲突的键
            cleaned_extra = {}
            for k, v in extra.items():
                if k in self._RESERVED_LOGRECORD_ATTRS:
                    cleaned_extra[f"_{k}"] = v
                else:
                    cleaned_extra[k] = v
            extra = cleaned_extra
        self._logger.log(level, msg, extra=extra, exc_info=exc_info)

    def set_level(self, level: str):
        """动态设置日志级别"""
        self.level = getattr(logging, level.upper(), logging.INFO)
        self._logger.setLevel(self.level)
        for handler in self._logger.handlers:
            handler.setLevel(self.level)

    def get_logger(self) -> logging.Logger:
        """获取底层 logging.Logger 实例"""
        return self._logger

    # ---- 兼容标准 logging 的方法 ----

    def log(self, level: int, msg: str, *args, **kwargs):
        """兼容标准 logging.log 的接口"""
        extra = kwargs.pop("extra", {})
        if args:
            msg = msg % args
        self._log(level, msg, extra)

    def addHandler(self, handler: logging.Handler):
        self._logger.addHandler(handler)

    def removeHandler(self, handler: logging.Handler):
        self._logger.removeHandler(handler)


# ============================================================================
# 全局日志器工厂（单例模式）
# ============================================================================

_loggers: Dict[str, UnifiedLogger] = {}
_loggers_lock = None  # 惰性初始化


def _get_lock():
    """获取线程锁（惰性初始化）"""
    global _loggers_lock
    if _loggers_lock is None:
        import threading
        _loggers_lock = threading.Lock()
    return _loggers_lock


def get_logger(
    name: str = "yunxi",
    level: Optional[str] = None,
    log_dir: Optional[str] = None,
    json_format: Optional[bool] = None,
    file_output: Optional[bool] = None,
    redis_output: Optional[bool] = None,
    rotation_config: Optional[LogRotationConfig] = None,
) -> UnifiedLogger:
    """
    获取统一日志器（单例模式，线程安全）

    优先从环境变量读取配置，参数可覆盖环境变量。

    环境变量:
        LOG_LEVEL: 日志级别 (DEBUG/INFO/WARNING/ERROR)
        LOG_DIR: 日志目录
        LOG_FORMAT: 日志格式 (json/text)
        LOG_FILE_OUTPUT: 是否输出到文件 (true/false)
        LOG_REDIS_OUTPUT: 是否输出到 Redis (true/false)
        YUNXI_ENV / ENV: 运行环境

        轮转相关环境变量（详见 LogRotationConfig）:
        LOG_ROTATION_ENABLED: 是否启用轮转 (true/false)
        LOG_ROTATION_WHEN: 轮转时机 (midnight/hourly/weekly/daily)
        LOG_ROTATION_BACKUP_COUNT: 保留份数 (默认 30)
        LOG_ROTATION_MAX_BYTES: 单文件最大字节数 (默认 100MB)
        LOG_ROTATION_COMPRESS: 是否自动压缩 (true/false)
        LOG_ROTATION_INTERVAL: 轮转间隔 (默认 1)

    Args:
        name: 日志器名称
        level: 日志级别，None使用环境变量或默认
        log_dir: 日志目录，None使用环境变量或默认
        json_format: 是否使用JSON格式，None自动判断
        file_output: 是否输出到文件，None使用环境变量或默认
        redis_output: 是否输出到 Redis，None使用环境变量或默认
        rotation_config: 轮转配置对象，None则从环境变量自动构建

    Returns:
        UnifiedLogger 实例
    """
    lock = _get_lock()
    with lock:
        if name not in _loggers:
            # 从环境变量读取配置
            if level is None:
                level = os.getenv("LOG_LEVEL", os.getenv("YUNXI_LOG_LEVEL", "INFO"))
            if log_dir is None:
                log_dir = os.getenv("LOG_DIR", os.getenv("YUNXI_LOG_DIR"))
            if json_format is None:
                fmt_env = os.getenv("LOG_FORMAT", os.getenv("YUNXI_LOG_FORMAT"))
                if fmt_env:
                    json_format = fmt_env.lower() in ("json", "structured")
            if file_output is None:
                file_env = os.getenv("LOG_FILE_OUTPUT", os.getenv("YUNXI_LOG_FILE", "true"))
                file_output = file_env.lower() in ("true", "1", "yes", "on")
            if redis_output is None:
                redis_env = os.getenv("LOG_REDIS_OUTPUT", os.getenv("YUNXI_LOG_REDIS", "false"))
                redis_output = redis_env.lower() in ("true", "1", "yes", "on")

            # 轮转配置：参数优先，否则自动从环境变量构建
            if rotation_config is None:
                rotation_config = LogRotationConfig()

            _loggers[name] = UnifiedLogger(
                name=name,
                level=level,
                log_dir=log_dir,
                json_format=json_format,
                file_output=file_output,
                redis_output=redis_output,
                rotation_config=rotation_config,
            )

        return _loggers[name]


def set_global_level(level: str) -> None:
    """
    动态设置所有已创建日志器的级别

    Args:
        level: 日志级别字符串
    """
    lock = _get_lock()
    with lock:
        for logger in _loggers.values():
            logger.set_level(level)


def get_all_loggers() -> Dict[str, UnifiedLogger]:
    """获取所有已创建的日志器"""
    lock = _get_lock()
    with lock:
        return dict(_loggers)


# ============================================================================
# 便捷函数：快速初始化模块日志
# ============================================================================

def init_module_logger(
    module_key: str,
    log_dir: Optional[str] = None,
) -> UnifiedLogger:
    """
    初始化模块日志器（便捷函数）

    自动设置模块上下文，返回已配置好的日志器。

    Args:
        module_key: 模块标识（如 m8, m9, gateway）
        log_dir: 日志目录

    Returns:
        UnifiedLogger 实例

    示例:
        from shared.core.observability import init_module_logger
        logger = init_module_logger("m8")
    """
    logger = get_logger(f"yunxi.{module_key}", log_dir=log_dir)
    set_log_context(module_key=module_key)
    return logger
