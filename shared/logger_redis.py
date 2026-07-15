"""
云汐系统 - Redis 日志处理器

基于 shared/logger.py 扩展，当 Redis 可用时将结构化日志写入 Redis list。
如果 Redis 不可用，静默降级到文件日志。
"""

from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any, Optional

from .logger import get_logger

# ---------------------------------------------------------------------------
# 可选依赖：redis
# ---------------------------------------------------------------------------
try:
    import redis
    _REDIS_AVAILABLE = True
except ImportError:
    redis = None  # type: ignore
    _REDIS_AVAILABLE = False

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
REDIS_LOG_KEY = "yunxi:logs"
REDIS_LOG_MAX_LEN = 10000
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = 0

# 延迟初始化的 Redis 客户端缓存
_redis_client: Optional[Any] = None
_redis_connection_failed = False


def _get_redis_client() -> Optional[Any]:
    """获取 Redis 客户端（带连接缓存和失败标记）.

    Returns:
        Redis 客户端实例，或 None（不可用/连接失败）
    """
    global _redis_client, _redis_connection_failed

    if not _REDIS_AVAILABLE:
        return None
    if _redis_connection_failed:
        return None
    if _redis_client is not None:
        try:
            _redis_client.ping()
            return _redis_client
        except Exception:
            _redis_client = None

    try:
        client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            health_check_interval=30,
        )
        client.ping()
        _redis_client = client
        return client
    except Exception:
        _redis_connection_failed = True
        return None


def _reset_redis_client() -> None:
    """重置 Redis 客户端缓存（用于测试或重连）."""
    global _redis_client, _redis_connection_failed
    _redis_client = None
    _redis_connection_failed = False


class RedisLogHandler(logging.Handler):
    """Redis 日志处理器.

    将日志记录序列化为 JSON 后写入 Redis list，使用 LPUSH + LTRIM
    保留最近 N 条日志。
    """

    def __init__(
        self,
        redis_key: str = REDIS_LOG_KEY,
        max_len: int = REDIS_LOG_MAX_LEN,
        level: int = logging.DEBUG,
    ) -> None:
        super().__init__(level=level)
        self.redis_key = redis_key
        self.max_len = max_len

    def emit(self, record: logging.LogRecord) -> None:
        """发送日志记录到 Redis."""
        client = _get_redis_client()
        if client is None:
            # Redis 不可用，静默跳过（保留父 handler 的文件/控制台输出）
            return

        try:
            log_entry = self._format_entry(record)
            # 使用 pipeline 减少往返
            pipe = client.pipeline()
            pipe.lpush(self.redis_key, json.dumps(log_entry, ensure_ascii=False))
            pipe.ltrim(self.redis_key, 0, self.max_len - 1)
            pipe.execute()
        except Exception:
            # 写入 Redis 失败时静默降级，避免阻塞业务
            self.handleError(record)

    def _format_entry(self, record: logging.LogRecord) -> dict[str, Any]:
        """将 LogRecord 格式化为结构化字典.

        提取字段：timestamp, level, module, message, trace_id, request_id
        """
        entry: dict[str, Any] = {
            "timestamp": getattr(record, "created", time.time()),
            "level": record.levelname,
            "module": record.name,
            "message": self.format(record),
            "trace_id": getattr(record, "trace_id", ""),
            "request_id": getattr(record, "request_id", ""),
        }

        # 附加 extra 字段（如果存在）
        for key in ("trace_id", "request_id"):
            if key in record.__dict__ and not entry.get(key):
                entry[key] = record.__dict__[key]

        # 异常信息
        if record.exc_info and record.exc_info[0] is not None:
            entry["exception"] = self.formatException(record.exc_info)

        return entry


def get_logger_with_redis(name: str = "yunxi", level: str = "INFO") -> logging.Logger:
    """获取带 Redis 支持的日志记录器.

    在原有 get_logger 基础上，如果 Redis 可用则附加 RedisLogHandler。

    Args:
        name: 日志记录器名称
        level: 日志级别

    Returns:
        logging.Logger 实例
    """
    logger = get_logger(name, level)

    # 检查是否已添加 Redis handler（避免重复）
    has_redis = any(isinstance(h, RedisLogHandler) for h in logger.handlers)
    if not has_redis:
        redis_handler = RedisLogHandler()
        redis_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(redis_handler)

    return logger


def get_logs_from_redis(count: int = 100) -> list[dict[str, Any]]:
    """从 Redis 查询最近日志.

    Args:
        count: 返回条数（默认 100）

    Returns:
        日志条目列表（按时间倒序，最新的在前）
    """
    client = _get_redis_client()
    if client is None:
        return []

    try:
        raw_logs = client.lrange(REDIS_LOG_KEY, 0, count - 1)
        logs: list[dict[str, Any]] = []
        for raw in raw_logs:
            try:
                logs.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
        return logs
    except Exception:
        return []


def bind_trace_context(logger: logging.Logger, trace_id: str = "", request_id: str = "") -> logging.LoggerAdapter:
    """将 trace_id / request_id 绑定到日志适配器.

    Args:
        logger: 基础日志记录器
        trace_id: 追踪 ID
        request_id: 请求 ID

    Returns:
        带上下文绑定的 LoggerAdapter
    """
    extra = {
        "trace_id": trace_id,
        "request_id": request_id,
    }
    return logging.LoggerAdapter(logger, extra)
