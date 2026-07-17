"""
云汐统一日志系统

支持：
- 结构化日志（JSON格式 / 可读文本格式）
- 多输出目标（控制台 + 文件 + Redis 通道）
- 日志级别动态调整（环境变量配置）
- 上下文注入（trace_id、user_id、span_id 等）
- 日志轮转（按天轮转 + 大小限制 + 自动清理）
- 敏感字段自动脱敏（password, token, secret, key 等）
- 高性能：异步批量写入、惰性初始化
- 向后兼容：兼容标准 logging 用法

使用方式：
    from shared.core.observability import get_logger

    logger = get_logger("my_module")
    logger.info("user login", user_id="123", ip="192.168.1.1")
    logger.error("request failed", error="timeout", trace_id="abc123")
"""
import os
import sys
import json
import re
import logging
import logging.handlers
from typing import Optional, Dict, Any, List, Set
from pathlib import Path
from datetime import datetime
from contextvars import ContextVar
from functools import lru_cache


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
        max_bytes: int = 50 * 1024 * 1024,  # 50MB
        backup_count: int = 30,  # 保留30天/30份
        console_output: bool = True,
        file_output: bool = True,
        redis_output: bool = False,
        redis_key: str = "yunxi:logs",
        rotation: str = "daily",  # daily / size
        env: Optional[str] = None,
    ):
        """
        初始化统一日志器

        Args:
            name: 日志器名称
            level: 日志级别 (DEBUG/INFO/WARNING/ERROR/CRITICAL)
            log_dir: 日志目录，None则使用默认路径
            json_format: 是否使用JSON格式，None则根据环境自动判断
            max_bytes: 单个日志文件最大大小（size模式下）
            backup_count: 保留的日志文件数/天数
            console_output: 是否输出到控制台
            file_output: 是否输出到文件
            redis_output: 是否输出到 Redis 通道
            redis_key: Redis 日志通道 key
            rotation: 轮转方式 daily/size
            env: 运行环境 development/production，None则从环境变量读取
        """
        self.name = name
        self.level = getattr(logging, level.upper(), logging.INFO)
        self.rotation = rotation
        self.max_bytes = max_bytes
        self.backup_count = backup_count
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
        """创建文件 handler（根据轮转方式）"""
        if self.rotation == "daily":
            handler = logging.handlers.TimedRotatingFileHandler(
                filename,
                when="midnight",
                interval=1,
                backupCount=self.backup_count,
                encoding="utf-8",
                utc=False,
            )
            handler.suffix = "%Y-%m-%d"
        else:  # size
            handler = logging.handlers.RotatingFileHandler(
                filename,
                maxBytes=self.max_bytes,
                backupCount=self.backup_count,
                encoding="utf-8",
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

    Args:
        name: 日志器名称
        level: 日志级别，None使用环境变量或默认
        log_dir: 日志目录，None使用环境变量或默认
        json_format: 是否使用JSON格式，None自动判断
        file_output: 是否输出到文件，None使用环境变量或默认
        redis_output: 是否输出到 Redis，None使用环境变量或默认

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

            _loggers[name] = UnifiedLogger(
                name=name,
                level=level,
                log_dir=log_dir,
                json_format=json_format,
                file_output=file_output,
                redis_output=redis_output,
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
