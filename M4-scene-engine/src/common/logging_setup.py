"""结构化日志配置与链路追踪.

提供统一的 structlog 配置初始化，以及基于 contextvars 的请求链路追踪。
在应用启动时调用 ``setup_logging()`` 完成全局日志配置。

主要功能：
- 统一 structlog 处理器链配置（控制台/JSON 格式）
- 日志级别动态配置
- 敏感字段自动脱敏
- contextvars 链路追踪（trace_id / user_id / scene_id）
- 日志文件轮转（可选）
"""

from __future__ import annotations

import logging
import os
import sys
from contextvars import ContextVar
from typing import Any

import structlog

# ---------------------------------------------------------------------------
# ContextVars 链路追踪上下文
# ---------------------------------------------------------------------------

#: 请求追踪 ID，贯穿整个请求生命周期
trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")

#: 用户 ID，用于用户级日志关联
user_id_var: ContextVar[str] = ContextVar("user_id", default="")

#: 场景 ID，用于场景级日志关联
scene_id_var: ContextVar[str] = ContextVar("scene_id", default="")

#: 请求路径，用于日志过滤
request_path_var: ContextVar[str] = ContextVar("request_path", default="")


def get_trace_id() -> str:
    """获取当前上下文中的 trace_id.

    Returns:
        trace_id 字符串，未设置则返回空串.
    """
    return trace_id_var.get()


def set_trace_id(trace_id: str) -> None:
    """设置当前上下文中的 trace_id.

    Args:
        trace_id: 追踪 ID.
    """
    trace_id_var.set(trace_id)


def set_context(**kwargs: str) -> None:
    """批量设置链路追踪上下文.

    Args:
        **kwargs: 上下文键值对，支持 trace_id / user_id / scene_id / request_path.
    """
    if "trace_id" in kwargs:
        trace_id_var.set(kwargs["trace_id"])
    if "user_id" in kwargs:
        user_id_var.set(kwargs["user_id"])
    if "scene_id" in kwargs:
        scene_id_var.set(kwargs["scene_id"])
    if "request_path" in kwargs:
        request_path_var.set(kwargs["request_path"])


def clear_context() -> None:
    """清空所有链路追踪上下文."""
    trace_id_var.set("")
    user_id_var.set("")
    scene_id_var.set("")
    request_path_var.set("")


# ---------------------------------------------------------------------------
# 敏感字段脱敏处理器
# ---------------------------------------------------------------------------

_SENSITIVE_FIELD_PATTERNS: list[str] = [
    "password",
    "token",
    "secret",
    "api_key",
    "encryption_key",
    "admin_token",
    "authorization",
    "cookie",
]


def _is_sensitive_field(field_name: str) -> bool:
    """判断字段名是否为敏感字段.

    Args:
        field_name: 字段名.

    Returns:
        是否为敏感字段.
    """
    field_lower = field_name.lower()
    return any(pattern in field_lower for pattern in _SENSITIVE_FIELD_PATTERNS)


def _mask_sensitive_values(
    logger: logging.Logger,
    method_name: str,
    event_dict: structlog.types.EventDict,
) -> structlog.types.EventDict:
    """structlog 处理器：脱敏敏感字段值.

    递归遍历 event_dict 中的所有值，对敏感字段进行 *** 替换。

    Args:
        logger: 日志实例（未使用）.
        method_name: 日志方法名（未使用）.
        event_dict: 日志事件字典.

    Returns:
        脱敏后的事件字典.
    """

    def _mask_value(key: str, value: Any) -> Any:
        if isinstance(value, dict):
            return {k: _mask_value(k, v) for k, v in value.items()}
        if isinstance(value, list):
            return [_mask_value(key, item) for item in value]
        if _is_sensitive_field(key) and isinstance(value, str) and value:
            if len(value) <= 4:
                return "***"
            return value[:2] + "***" + value[-2:]
        return value

    return {k: _mask_value(k, v) for k, v in event_dict.items()}


# ---------------------------------------------------------------------------
# ContextVars 注入处理器
# ---------------------------------------------------------------------------


def _inject_contextvars(
    logger: logging.Logger,
    method_name: str,
    event_dict: structlog.types.EventDict,
) -> structlog.types.EventDict:
    """structlog 处理器：注入 contextvars 中的链路追踪信息.

    将当前上下文中的 trace_id / user_id / scene_id / request_path
    自动注入到每条日志中。

    Args:
        logger: 日志实例（未使用）.
        method_name: 日志方法名（未使用）.
        event_dict: 日志事件字典.

    Returns:
        注入上下文后的事件字典.
    """
    trace_id = trace_id_var.get()
    if trace_id:
        event_dict["trace_id"] = trace_id

    user_id = user_id_var.get()
    if user_id:
        event_dict["user_id"] = user_id

    scene_id = scene_id_var.get()
    if scene_id:
        event_dict["scene_id"] = scene_id

    request_path = request_path_var.get()
    if request_path:
        event_dict["request_path"] = request_path

    return event_dict


# ---------------------------------------------------------------------------
# 日志配置初始化
# ---------------------------------------------------------------------------

# 是否已初始化标记
_initialized = False


def setup_logging(
    level: str = "info",
    format_type: str = "console",
    log_file: str | None = None,
    max_size_mb: int = 100,
    max_files: int = 10,
    sensitive_fields: list[str] | None = None,
) -> None:
    """初始化全局结构化日志配置.

    只需在应用启动时调用一次。重复调用会被忽略。

    Args:
        level: 日志级别 (debug / info / warning / error / critical).
        format_type: 输出格式 (json / console).
        log_file: 日志文件路径，为 None 则仅输出到控制台.
        max_size_mb: 单日志文件最大大小（MB）.
        max_files: 日志文件保留份数.
        sensitive_fields: 额外的敏感字段名列表，会自动脱敏.
    """
    global _initialized
    if _initialized:
        return

    # 注册额外敏感字段
    if sensitive_fields:
        _SENSITIVE_FIELD_PATTERNS.extend(
            f.lower() for f in sensitive_fields if f.lower() not in _SENSITIVE_FIELD_PATTERNS
        )

    # 日志级别
    log_level = getattr(logging, level.upper(), logging.INFO)

    # 标准库 logging 基础配置
    logging.basicConfig(
        format="%(message)s",
        level=log_level,
        stream=sys.stdout,
    )

    # 减少第三方库的日志噪音
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("starlette").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)

    # 构建处理器链
    processors: list[Any] = [
        # 注入上下文变量
        _inject_contextvars,
        # 敏感字段脱敏
        _mask_sensitive_values,
        # 添加时间戳
        structlog.processors.TimeStamper(fmt="iso", utc=False),
        # 添加日志级别
        structlog.processors.add_log_level,
        # 栈信息格式化
        structlog.processors.ExceptionPrettyPrinter(),
    ]

    # 输出格式
    if format_type == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        # 控制台友好格式
        processors.extend([
            structlog.dev.ConsoleRenderer(
                colors=sys.stdout.isatty(),
                pad_event=35,
            ),
        ])

    # 文件输出处理器
    if log_file:
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)

        from logging.handlers import RotatingFileHandler
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=max_size_mb * 1024 * 1024,
            backupCount=max_files,
            encoding="utf-8",
        )
        file_handler.setLevel(log_level)
        file_handler.setFormatter(logging.Formatter("%(message)s"))
        logging.getLogger().addHandler(file_handler)

    # 配置 structlog
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    _initialized = True

    logger = structlog.get_logger(__name__)
    logger.info(
        "logging.setup_complete",
        level=level,
        format=format_type,
        log_file=bool(log_file),
        sensitive_fields_count=len(_SENSITIVE_FIELD_PATTERNS),
    )


def set_log_level(level: str) -> None:
    """动态调整日志级别.

    Args:
        level: 新的日志级别 (debug / info / warning / error).
    """
    log_level = getattr(logging, level.upper(), None)
    if log_level is None:
        return

    logging.getLogger().setLevel(log_level)
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
    )

    logger = structlog.get_logger(__name__)
    logger.info("logging.level_changed", new_level=level)


def is_initialized() -> bool:
    """检查日志系统是否已初始化.

    Returns:
        是否已初始化.
    """
    return _initialized
