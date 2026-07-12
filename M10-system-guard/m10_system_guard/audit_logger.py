"""
M10 系统卫士 - 审计日志模块 (A5-1)

记录所有拦截操作的审计日志：
- 日志级别：info/warning/critical
- 日志内容：时间、类型、触发条件、动作、结果
- 支持内存存储和文件持久化（沙盒模式下仅内存存储）
"""

from __future__ import annotations

import time
import uuid
from collections import deque
from typing import Any

from .config import get_config
from .models import AuditLog, AuditLogLevel


class AuditLogger:
    """审计日志记录器.

    记录所有系统防护操作的审计日志，支持按级别、类型、时间筛选查询。
    沙盒模式下仅存储在内存中，不写入文件。
    """

    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._init_logger()

    def _init_logger(self):
        """初始化审计日志记录器."""
        config = get_config()
        self.config = config
        self.audit_cfg = config.audit

        # 内存日志存储
        self._logs: deque[AuditLog] = deque(maxlen=1000)

        # 统计计数
        self._stats = {
            "total": 0,
            "info": 0,
            "warning": 0,
            "critical": 0,
        }

        # 沙盒模式标记
        self._sandbox_mode = config.sandbox.enabled

    def log(
        self,
        log_type: str,
        trigger_condition: str,
        action: str,
        result: str,
        level: AuditLogLevel = AuditLogLevel.INFO,
        details: dict[str, Any] | None = None,
    ) -> AuditLog:
        """记录一条审计日志.

        Args:
            log_type: 日志类型（如 cpu_guard, memory_guard, process_limit 等）
            trigger_condition: 触发条件描述
            action: 执行的动作
            result: 执行结果
            level: 日志级别
            details: 详细信息字典

        Returns:
            创建的审计日志对象
        """
        log_entry = AuditLog(
            log_id=uuid.uuid4().hex[:16],
            timestamp=time.time(),
            level=level,
            log_type=log_type,
            trigger_condition=trigger_condition,
            action=action,
            result=result,
            details=details or {},
        )

        self._logs.append(log_entry)

        # 更新统计
        self._stats["total"] += 1
        self._stats[level.value] += 1

        return log_entry

    def log_info(
        self,
        log_type: str,
        trigger_condition: str,
        action: str,
        result: str,
        details: dict[str, Any] | None = None,
    ) -> AuditLog:
        """记录 info 级别审计日志."""
        return self.log(log_type, trigger_condition, action, result, AuditLogLevel.INFO, details)

    def log_warning(
        self,
        log_type: str,
        trigger_condition: str,
        action: str,
        result: str,
        details: dict[str, Any] | None = None,
    ) -> AuditLog:
        """记录 warning 级别审计日志."""
        return self.log(log_type, trigger_condition, action, result, AuditLogLevel.WARNING, details)

    def log_critical(
        self,
        log_type: str,
        trigger_condition: str,
        action: str,
        result: str,
        details: dict[str, Any] | None = None,
    ) -> AuditLog:
        """记录 critical 级别审计日志."""
        return self.log(log_type, trigger_condition, action, result, AuditLogLevel.CRITICAL, details)

    def get_logs(
        self,
        limit: int = 100,
        level: str | None = None,
        log_type: str | None = None,
        start_time: float | None = None,
        end_time: float | None = None,
    ) -> list[AuditLog]:
        """查询审计日志.

        Args:
            limit: 返回数量限制
            level: 按级别过滤 (info/warning/critical)
            log_type: 按类型过滤
            start_time: 开始时间戳
            end_time: 结束时间戳

        Returns:
            审计日志列表（按时间倒序）
        """
        logs = list(reversed(self._logs))

        # 级别过滤
        if level:
            logs = [l for l in logs if l.level.value == level]

        # 类型过滤
        if log_type:
            logs = [l for l in logs if l.log_type == log_type]

        # 时间过滤
        if start_time:
            logs = [l for l in logs if l.timestamp >= start_time]
        if end_time:
            logs = [l for l in logs if l.timestamp <= end_time]

        return logs[:limit]

    def get_stats(self) -> dict[str, Any]:
        """获取审计日志统计信息.

        Returns:
            统计信息字典
        """
        # 按类型统计
        type_stats: dict[str, int] = {}
        for log in self._logs:
            type_stats[log.log_type] = type_stats.get(log.log_type, 0) + 1

        return {
            "total": self._stats["total"],
            "by_level": {
                "info": self._stats["info"],
                "warning": self._stats["warning"],
                "critical": self._stats["critical"],
            },
            "by_type": type_stats,
            "sandbox_mode": self._sandbox_mode,
            "storage": "memory_only" if self._sandbox_mode else "memory_and_file",
            "max_capacity": self._logs.maxlen,
            "current_count": len(self._logs),
        }

    def get_log_types(self) -> list[str]:
        """获取所有日志类型.

        Returns:
            日志类型列表
        """
        types = set()
        for log in self._logs:
            types.add(log.log_type)
        return sorted(types)

    def clear_logs(self) -> int:
        """清空审计日志.

        Returns:
            清除的日志数量
        """
        count = len(self._logs)
        self._logs.clear()
        self._stats = {
            "total": 0,
            "info": 0,
            "warning": 0,
            "critical": 0,
        }
        return count

    def export_logs(
        self,
        format: str = "json",
        level: str | None = None,
        start_time: float | None = None,
        end_time: float | None = None,
    ) -> str:
        """导出审计日志.

        Args:
            format: 导出格式 (json/csv)
            level: 级别过滤
            start_time: 开始时间
            end_time: 结束时间

        Returns:
            导出的字符串
        """
        logs = self.get_logs(limit=10000, level=level, start_time=start_time, end_time=end_time)

        if format == "csv":
            lines = ["log_id,timestamp,level,log_type,trigger_condition,action,result"]
            for log in logs:
                line = ",".join([
                    log.log_id,
                    str(log.timestamp),
                    log.level.value,
                    log.log_type,
                    f'"{log.trigger_condition}"',
                    f'"{log.action}"',
                    f'"{log.result}"',
                ])
                lines.append(line)
            return "\n".join(lines)
        else:
            # JSON 格式
            import json
            return json.dumps([l.to_dict() for l in logs], ensure_ascii=False, indent=2)


# 全局单例获取函数
_audit_logger_instance = None


def get_audit_logger() -> AuditLogger:
    """获取审计日志记录器单例."""
    global _audit_logger_instance
    if _audit_logger_instance is None:
        _audit_logger_instance = AuditLogger()
    return _audit_logger_instance
