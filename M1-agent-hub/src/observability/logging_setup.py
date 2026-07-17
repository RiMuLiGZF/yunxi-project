"""
M1 日志规范模块 — Logging Setup

实现 P1-6 日志规范 + 全链路追踪增强（V11.4）：
- JSON 格式日志
- 包含 trace_id / span_id（全链路追踪，基于 contextvars 异步安全）
- 日志级别正确使用
- 敏感字段自动脱敏
- 日志轮转（按大小 + 按天）
- structlog 自动注入 trace 上下文

日志级别使用规范：
- DEBUG：开发调试信息，生产环境默认关闭，记录变量值、执行路径等
- INFO：正常业务流程信息，如请求进入、任务完成、消息投递成功
- WARNING：可恢复的异常情况，如重试、降级、参数不合法但有兜底
- ERROR：业务错误或系统异常，需要人工关注，如接口调用失败、数据库异常
- CRITICAL：致命错误，系统不可用，需要立即处理，如核心依赖全部宕机

全链路追踪：
- 从 trace_context 模块的 contextvars 读取 trace_id / span_id
- 每条日志自动注入 trace_id、span_id，便于日志关联排查
- 兼容旧版 get_trace_id / set_trace_id 函数调用方式
"""

from __future__ import annotations

import os
import re
import json
import time
import logging
import logging.handlers
from typing import Any

import structlog

# 全链路追踪上下文（基于 contextvars，异步安全）
from src.observability.trace_context import (
    get_trace_id as _ctx_get_trace_id,
    get_span_id as _ctx_get_span_id,
    set_trace_id as _ctx_set_trace_id,
    generate_trace_id as _ctx_generate_trace_id,
    clear_trace_id as _ctx_clear_trace_id,
)

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
            "span_id": getattr(record, "span_id", ""),
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
        """递归脱敏字典中的敏感字段（委托给模块级函数）"""
        return sanitize_dict(data)

    @staticmethod
    def _sanitize_value(value: str) -> str:
        """脱敏字符串值中的敏感模式"""
        result = value
        for pattern in SENSITIVE_VALUE_PATTERNS:
            result = pattern.sub("***", result)
        return result


def sanitize_dict(data: dict[str, Any]) -> dict[str, Any]:
    """递归脱敏字典中的敏感字段（模块级函数，供 structlog processor 复用）。

    Args:
        data: 待脱敏的字典数据

    Returns:
        脱敏后的字典
    """
    result: dict[str, Any] = {}
    for key, value in data.items():
        # 字段名匹配敏感字段
        if key.lower() in DEFAULT_SENSITIVE_FIELDS:
            result[key] = "***"
            continue

        # 值中包含敏感模式
        if isinstance(value, str):
            result[key] = _sanitize_value(value)
        elif isinstance(value, dict):
            result[key] = sanitize_dict(value)
        elif isinstance(value, list):
            result[key] = [
                _sanitize_value(item) if isinstance(item, str)
                else sanitize_dict(item) if isinstance(item, dict)
                else item
                for item in value
            ]
        else:
            result[key] = value

    return result


def _sanitize_value(value: str) -> str:
    """脱敏字符串值中的敏感模式（模块级函数）。

    Args:
        value: 待脱敏的字符串

    Returns:
        脱敏后的字符串
    """
    result = value
    for pattern in SENSITIVE_VALUE_PATTERNS:
        result = pattern.sub("***", result)
    return result


class TraceContextFilter(logging.Filter):
    """Trace 上下文日志过滤器

    自动从 contextvars 读取当前 trace_id / span_id 并注入到日志记录中。
    基于 contextvars 实现，协程安全，支持异步环境。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # 注入 trace_id
        if not hasattr(record, "trace_id") or not record.trace_id:
            record.trace_id = _ctx_get_trace_id()
        # 注入 span_id
        if not hasattr(record, "span_id") or not record.span_id:
            record.span_id = _ctx_get_span_id()
        return True


# ── 兼容旧版 API（委托给 trace_context 模块） ──────────────

def get_trace_id() -> str:
    """获取当前 trace_id（从 contextvars 读取，异步安全）。

    如不存在则自动生成新的 trace_id 并设置到上下文。

    Returns:
        当前 trace_id 字符串
    """
    return _ctx_get_trace_id()


def set_trace_id(trace_id: str) -> Any:
    """设置当前 trace_id（写入 contextvars，异步安全）。

    Args:
        trace_id: 要设置的 trace_id 字符串

    Returns:
        contextvars.Token 对象，可用于恢复原值
    """
    return _ctx_set_trace_id(trace_id)


def new_trace_id() -> str:
    """生成新的 trace_id 并设置到上下文。

    Returns:
        新生成的 trace_id
    """
    tid = _ctx_generate_trace_id()
    _ctx_set_trace_id(tid)
    return tid


def clear_trace_id() -> None:
    """清除当前 trace_id（置空）。"""
    _ctx_clear_trace_id()


def get_span_id() -> str:
    """获取当前 span_id（从 contextvars 读取）。

    Returns:
        当前 span_id 字符串
    """
    return _ctx_get_span_id()


def add_trace_context_processor(logger_name: str | None = None) -> None:
    """为 structlog 添加 trace 上下文注入 processor。

    自定义 processor，从 contextvars 读取 trace_id 和 span_id，
    自动注入到每条 structlog 日志条目中。

    Args:
        logger_name: 可选，指定日志器名称，暂未使用（保留扩展）
    """
    # 此函数作为对外 API 保留，实际注入在 setup_logging 的 processor 链中完成
    _ = logger_name  # 静默未使用参数


def _inject_trace_context(
    logger: Any,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """structlog processor：从 contextvars 注入 trace_id / span_id。

    自动将当前上下文中的 trace_id 和 span_id 添加到日志事件中。
    若事件字典中已存在 trace_id（如调用方手动传入），则以传入值为准。

    Args:
        logger: 日志器实例（structlog 约定参数）
        method_name: 调用的日志方法名（structlog 约定参数）
        event_dict: 日志事件字典

    Returns:
        注入了 trace_id / span_id 的事件字典
    """
    if "trace_id" not in event_dict or not event_dict["trace_id"]:
        event_dict["trace_id"] = _ctx_get_trace_id()
    if "span_id" not in event_dict or not event_dict["span_id"]:
        event_dict["span_id"] = _ctx_get_span_id()
    return event_dict


def _sanitize_event_dict(
    logger: Any,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """structlog processor：对日志事件字典进行敏感字段脱敏。

    复用 JsonFormatter 的脱敏逻辑，对 structlog 输出的日志也进行
    敏感字段检查与掩码处理。

    Args:
        logger: 日志器实例（structlog 约定参数）
        method_name: 调用的日志方法名（structlog 约定参数）
        event_dict: 日志事件字典

    Returns:
        脱敏后的事件字典
    """
    return _sanitize_dict(event_dict)


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
    console_handler.addFilter(TraceContextFilter())
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
        file_handler.addFilter(TraceContextFilter())
        root_logger.addHandler(file_handler)

    # structlog 配置
    # processor 链：合并 contextvars -> 注入 trace_id/span_id -> 添加日志级别
    #               -> 时间戳 -> JSON/Console 渲染
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _inject_trace_context,  # 自动从 contextvars 注入 trace_id / span_id
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _sanitize_event_dict,   # 敏感字段脱敏
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
# 注：trace_id / span_id 由 structlog processor 自动从 contextvars 注入，
#     无需手动传入。若需覆盖可在 kwargs 中显式指定。

def debug(msg: str, **kwargs: Any) -> None:
    """输出 DEBUG 级别日志。

    Args:
        msg: 日志消息
        **kwargs: 附加的结构化字段
    """
    structlog.get_logger().debug(msg, **kwargs)


def info(msg: str, **kwargs: Any) -> None:
    """输出 INFO 级别日志。

    Args:
        msg: 日志消息
        **kwargs: 附加的结构化字段
    """
    structlog.get_logger().info(msg, **kwargs)


def warning(msg: str, **kwargs: Any) -> None:
    """输出 WARNING 级别日志。

    Args:
        msg: 日志消息
        **kwargs: 附加的结构化字段
    """
    structlog.get_logger().warning(msg, **kwargs)


def error(msg: str, **kwargs: Any) -> None:
    """输出 ERROR 级别日志。

    Args:
        msg: 日志消息
        **kwargs: 附加的结构化字段
    """
    structlog.get_logger().error(msg, **kwargs)


def critical(msg: str, **kwargs: Any) -> None:
    """输出 CRITICAL 级别日志。

    Args:
        msg: 日志消息
        **kwargs: 附加的结构化字段
    """
    structlog.get_logger().critical(msg, **kwargs)
