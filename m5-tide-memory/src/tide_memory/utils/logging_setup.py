"""
M5 潮汐记忆系统 - 结构化日志初始化模块

基于 structlog 配置统一的结构化日志系统，支持：
- 控制台彩色输出（开发环境）
- 可选 JSON 文件输出（生产环境）
- 环境变量 M5_LOG_LEVEL 控制日志级别
- 敏感字段自动脱敏
- request_id 上下文追踪
"""

from __future__ import annotations

import logging
import os
import sys
import uuid
from contextvars import ContextVar
from typing import Any, Dict, Optional

import structlog
from structlog.contextvars import merge_contextvars
from structlog.stdlib import ProcessorFormatter

# ---------------------------------------------------------------------------
# 全局上下文变量
# ---------------------------------------------------------------------------

# request_id 上下文变量，用于链路追踪
_request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)


def get_request_id() -> Optional[str]:
    """获取当前请求的 request_id"""
    return _request_id_var.get()


def set_request_id(request_id: Optional[str] = None) -> str:
    """
    设置当前请求的 request_id

    Args:
        request_id: 可选的 request_id，不传则自动生成

    Returns:
        设置后的 request_id
    """
    if request_id is None:
        request_id = str(uuid.uuid4())[:8]
    _request_id_var.set(request_id)
    return request_id


def clear_request_id() -> None:
    """清除当前请求的 request_id"""
    _request_id_var.set(None)


# ---------------------------------------------------------------------------
# 敏感字段脱敏处理器
# ---------------------------------------------------------------------------

# 默认敏感字段列表（不区分大小写）
_DEFAULT_SENSITIVE_FIELDS = {
    "password", "passwd", "pwd", "secret", "token", "api_key", "apikey",
    "private_key", "privatekey", "access_token", "refersh_token",
    "authorization", "auth", "cookie", "session", "session_id",
    "phone", "mobile", "email", "id_card", "idcard", "address",
    "content", "body", "text", "memory_content", "original_content",
}


def _mask_sensitive_values(
    _: Any,
    __: str,
    event_dict: Dict[str, Any],
) -> Dict[str, Any]:
    """
    structlog 处理器：对敏感字段的值进行脱敏

    递归遍历 event_dict，将敏感字段的值替换为 ***MASKED***
    """
    sensitive_fields = _DEFAULT_SENSITIVE_FIELDS

    def _mask_value(value: Any, depth: int = 0) -> Any:
        if depth > 5:
            return "***MASKED***"
        if isinstance(value, dict):
            return {
                k: _mask_dict_value(k, v, depth)
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [_mask_value(item, depth + 1) for item in value]
        if isinstance(value, str) and len(value) > 64:
            # 长文本截断脱敏（避免记忆内容泄露）
            return value[:32] + "...[REDACTED]"
        return value

    def _mask_dict_value(key: str, value: Any, depth: int) -> Any:
        key_lower = key.lower()
        if key_lower in sensitive_fields:
            if isinstance(value, (dict, list)):
                return "***MASKED***"
            if isinstance(value, str):
                return "***MASKED***"
            return "***MASKED***"
        return _mask_value(value, depth + 1)

    return _mask_value(event_dict)  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# request_id 注入处理器
# ---------------------------------------------------------------------------

def _inject_request_id(
    _: Any,
    __: str,
    event_dict: Dict[str, Any],
) -> Dict[str, Any]:
    """structlog 处理器：注入当前上下文中的 request_id"""
    request_id = _request_id_var.get()
    if request_id:
        event_dict["request_id"] = request_id
    return event_dict


# ---------------------------------------------------------------------------
# 日志级别映射
# ---------------------------------------------------------------------------

_LOG_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "WARN": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
    "FATAL": logging.CRITICAL,
}


def _resolve_log_level(level_str: Optional[str]) -> int:
    """从环境变量字符串解析日志级别"""
    if not level_str:
        return logging.INFO
    level_upper = level_str.strip().upper()
    return _LOG_LEVEL_MAP.get(level_upper, logging.INFO)


# ---------------------------------------------------------------------------
# 主初始化函数
# ---------------------------------------------------------------------------

_initialized = False


def setup_logging(
    log_level: Optional[str] = None,
    log_file: Optional[str] = None,
    json_format: bool = False,
    add_request_id: bool = True,
    desensitize: bool = True,
) -> None:
    """
    初始化结构化日志系统

    Args:
        log_level: 日志级别字符串（DEBUG/INFO/WARNING/ERROR/CRITICAL），
                   优先使用环境变量 M5_LOG_LEVEL
        log_file: 日志文件路径，None 表示仅输出到控制台
        json_format: 是否使用 JSON 格式输出（生产环境建议开启）
        add_request_id: 是否在日志中添加 request_id 字段
        desensitize: 是否启用敏感字段脱敏
    """
    global _initialized
    if _initialized:
        return

    # 1. 解析日志级别（环境变量优先）
    env_level = os.environ.get("M5_LOG_LEVEL")
    effective_level = _resolve_log_level(env_level or log_level)

    # 2. 配置标准库 logging 的根处理器（用于捕获第三方库日志）
    root_logger = logging.getLogger()
    root_logger.setLevel(effective_level)

    # 清除已有处理器，避免重复输出
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    # 3. 构建 structlog 处理器链
    shared_processors = [
        # 添加上下文变量（包括 request_id 等）
        merge_contextvars,
        # 注入 request_id
        _inject_request_id if add_request_id else lambda _, __, ed: ed,
        # 敏感字段脱敏
        _mask_sensitive_values if desensitize else lambda _, __, ed: ed,
        # 标准库日志级别映射
        structlog.stdlib.add_log_level,
        # 添加日志来源（模块名）
        structlog.stdlib.add_logger_name,
        # 添加时间戳
        structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S", utc=False),
        # 栈信息格式化
        structlog.processors.ExceptionPrettyPrinter(),
    ]

    # 4. 配置 structlog
    if json_format:
        # JSON 格式（生产环境）
        renderer = structlog.processors.JSONRenderer(ensure_ascii=False)
    else:
        # 控制台彩色格式（开发环境）
        renderer = structlog.dev.ConsoleRenderer(
            colors=sys.stdout.isatty(),
            exception_formatter=structlog.dev.plain_traceback,
        )

    structlog.configure(
        processors=shared_processors + [
            # 最后一步：格式化渲染
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # 5. 配置标准库处理器（使用 structlog 的格式化器）
    formatter = ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=shared_processors,
    )

    # 控制台输出
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(effective_level)
    root_logger.addHandler(console_handler)

    # 文件输出（可选）
    if log_file:
        os.makedirs(os.path.dirname(os.path.abspath(log_file)), exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(
            ProcessorFormatter(
                processor=structlog.processors.JSONRenderer(ensure_ascii=False),
                foreign_pre_chain=shared_processors,
            )
        )
        file_handler.setLevel(effective_level)
        root_logger.addHandler(file_handler)

    # 6. 设置第三方库的日志级别（避免过于嘈杂）
    for noisy_logger in [
        "uvicorn", "uvicorn.access", "fastapi",
        "httpx", "httpcore",
        "sqlalchemy", "sqlite3",
    ]:
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)

    _initialized = True

    # 输出启动日志
    log = structlog.get_logger(__name__)
    log.info(
        "结构化日志系统初始化完成",
        log_level=logging.getLevelName(effective_level),
        log_file=log_file or "stdout_only",
        json_format=json_format,
        desensitize=desensitize,
    )


def is_initialized() -> bool:
    """检查日志系统是否已初始化"""
    return _initialized


# 便捷导入：提供 get_logger 别名
get_logger = structlog.get_logger
