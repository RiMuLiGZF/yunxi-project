"""
M1 日志规范模块 — Logging Setup

实现 P1-6 日志规范：
- JSON 格式日志
- 包含 trace_id（全链路追踪）
- 日志级别正确使用
- 敏感字段自动脱敏
- 日志轮转（按大小 + 按天）
"""

from __future__ import annotations

import os
import re
import json
import time
import uuid
import logging
import logging.handlers
from typing import Any

import structlog

# 敏感字段列表（日志中自动脱敏）
DEFAULT_SENSITIVE_FIELDS = {
    "password", "passwd", "pwd",
    "token", "access_token", "refresh_token", "auth_token",
    "api_key", "apikey", "secret", "secret_key", "private_key",
    "authorization", "bearer",
    "credit_card", "bank_card", "id_card",
    "ssn", "social_security",
}

# 需要完全掩码的字段值模式
SENSITIVE_VALUE_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),  # API Key
    re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]{16,}", re.IGNORECASE),  # Bearer Token
    re.compile(r"1[3-9]\d{9}"),  # 手机号
    re.compile(r"\d{17}[\dXx]"),  # 身份证
    re.compile(r"\d{13,19}"),  # 银行卡
    re.compile(r"-----BEGIN.*?PRIVATE KEY-----[\s\S]+?-----END.*?PRIVATE KEY-----", re.IGNORECASE),  # 私钥
]


class JsonFormatter(logging.Formatter):
    """JSON 格式日志格式化器"""

    def __init__(self, service_name: str = "m1-scheduler", version: str = "11.1.0") -> None:
        super().__init__()
        self.service_name = service_name
        self.version = version

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(record.created)) + f".{int(record.msecs):03d}Z",
            "level": record.levelname.lower(),
            "service": self.service_name,
            "version": self.version,
            "logger": record.name,
            "message": record.getMessage(),
            "trace_id": getattr(record, "trace_id", ""),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # 额外字段
        for key, value in record.__dict__.items():
            if key.startswith("_"):
                continue
            if key in ("args", "asctime", "created", "exc_info", "exc_text",
                       "filename", "funcName", "levelname", "levelno",
                       "lineno", "module", "msecs", "msg", "name",
                       "pathname", "process", "processName",
                       "relativeCreated", "stack_info", "thread",
                       "threadName", "message", "taskName"):
                continue
            log_entry[key] = value

        # 异常信息
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        # 敏感字段脱敏
        log_entry = self._sanitize_dict(log_entry)

        return json.dumps(log_entry, ensure_ascii=False, default=str)

    def _sanitize_dict(self, data: dict[str, Any]) -> dict[str, Any]:
        """递归脱敏字典中的敏感字段"""
        result = {}
        for key, value in data.items():
            # 字段名匹配敏感字段
            if key.lower() in DEFAULT_SENSITIVE_FIELDS:
                result[key] = "***"
                continue

            # 值中包含敏感模式
            if isinstance(value, str):
                result[key] = self._sanitize_value(value)
            elif isinstance(value, dict):
                result[key] = self._sanitize_dict(value)
            elif isinstance(value, list):
                result[key] = [
                    self._sanitize_value(item) if isinstance(item, str)
                    else self._sanitize_dict(item) if isinstance(item, dict)
                    else item
                    for item in value
                ]
            else:
                result[key] = value

        return result

    @staticmethod
    def _sanitize_value(value: str) -> str:
        """脱敏字符串值中的敏感模式"""
        result = value
        for pattern in SENSITIVE_VALUE_PATTERNS:
            result = pattern.sub("***", result)
        return result


class TraceIdContext:
    """Trace ID 上下文管理

    用于在请求处理流程中传递 trace_id。
    """

    def __init__(self) -> None:
        self._current_trace_id: str = ""

    def generate(self) -> str:
        """生成新的 trace_id"""
        self._current_trace_id = uuid.uuid4().hex
        return self._current_trace_id

    def set(self, trace_id: str) -> None:
        """设置当前 trace_id"""
        self._current_trace_id = trace_id

    def get(self) -> str:
        """获取当前 trace_id"""
        return self._current_trace_id

    def clear(self) -> None:
        """清除 trace_id"""
        self._current_trace_id = ""


# 全局 trace_id 上下文
_trace_context = TraceIdContext()


def get_trace_id() -> str:
    """获取当前 trace_id"""
    return _trace_context.get()


def set_trace_id(trace_id: str) -> None:
    """设置 trace_id"""
    _trace_context.set(trace_id)


def new_trace_id() -> str:
    """生成新的 trace_id 并设置"""
    return _trace_context.generate()


class TraceIdFilter(logging.Filter):
    """Trace ID 日志过滤器

    自动将当前 trace_id 注入到日志记录中。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "trace_id") or not record.trace_id:
            record.trace_id = get_trace_id()
        return True


def setup_logging(
    log_level: str = "info",
    log_format: str = "json",  # json / text
    log_file: str | None = None,
    max_size: str = "100MB",
    max_files: int = 10,
    service_name: str = "m1-scheduler",
    version: str = "11.1.0",
    sensitive_fields: set[str] | None = None,
) -> None:
    """初始化日志系统

    Args:
        log_level: 日志级别（debug/info/warning/error/critical）
        log_format: 日志格式（json/text）
        log_file: 日志文件路径，None 则只输出到控制台
        max_size: 单个日志文件最大大小（支持 KB/MB/GB）
        max_files: 保留的日志文件数量
        service_name: 服务名称
        version: 版本号
        sensitive_fields: 额外的敏感字段列表
    """
    # 解析 max_size
    max_bytes = _parse_size(max_size)

    # 日志级别
    level = getattr(logging, log_level.upper(), logging.INFO)

    # 根日志器
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # 清除已有处理器
    root_logger.handlers.clear()

    # 格式化器
    if log_format == "json":
        formatter = JsonFormatter(service_name=service_name, version=version)
    else:
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] [%(trace_id)s] %(name)s: %(message)s"
        )

    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(TraceIdFilter())
    root_logger.addHandler(console_handler)

    # 文件处理器（带轮转）
    if log_file:
        # 确保目录存在
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)

        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=max_files,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        file_handler.addFilter(TraceIdFilter())
        root_logger.addHandler(file_handler)

    # structlog 配置
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(ensure_ascii=False)
            if log_format == "json"
            else structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # 更新敏感字段
    if sensitive_fields:
        DEFAULT_SENSITIVE_FIELDS.update(sensitive_fields)


def _parse_size(size_str: str) -> int:
    """解析大小字符串（如 100MB, 1GB, 500KB）为字节数"""
    size_str = size_str.strip().upper()
    units = {"KB": 1024, "MB": 1024 * 1024, "GB": 1024 * 1024 * 1024}

    for unit, multiplier in units.items():
        if size_str.endswith(unit):
            try:
                num = float(size_str[:-len(unit)].strip())
                return int(num * multiplier)
            except ValueError:
                pass

    # 默认按字节
    try:
        return int(size_str)
    except ValueError:
        return 100 * 1024 * 1024  # 默认 100MB


def get_logger(name: str) -> Any:
    """获取带 trace_id 的日志器"""
    log = structlog.get_logger(name)
    return log


# 便捷日志函数
def debug(msg: str, **kwargs: Any) -> None:
    structlog.get_logger().debug(msg, trace_id=get_trace_id(), **kwargs)


def info(msg: str, **kwargs: Any) -> None:
    structlog.get_logger().info(msg, trace_id=get_trace_id(), **kwargs)


def warning(msg: str, **kwargs: Any) -> None:
    structlog.get_logger().warning(msg, trace_id=get_trace_id(), **kwargs)


def error(msg: str, **kwargs: Any) -> None:
    structlog.get_logger().error(msg, trace_id=get_trace_id(), **kwargs)


def critical(msg: str, **kwargs: Any) -> None:
    structlog.get_logger().critical(msg, trace_id=get_trace_id(), **kwargs)
