'''
M10 系统卫士 - 审计日志模块

记录所有拦截操作的审计日志：
- 日志级别：info/warning/critical
- 日志内容：时间、类型、触发条件、动作、结果
- 双轨存储：内存缓存 + 数据库持久化
'''

from __future__ import annotations

import time
import uuid
import threading
from collections import deque
from typing import Any

from .config import get_config
from .models import AuditLog, AuditLogLevel


class AuditLogger:
    '''审计日志记录器.

    记录所有系统防护操作的审计日志，支持按级别、类型、时间筛选查询。
    采用双轨存储：内存 deque 缓存（快速查询） + 数据库持久化（重启不丢失）。
    数据库写入采用异步队列，避免阻塞主流程。
    '''

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
        '''初始化审计日志记录器.'''
        config = get_config()
        self.config = config
        self.audit_cfg = config.audit

        # 内存日志存储（缓存，最新1000条）
        self._logs: deque[AuditLog] = deque(maxlen=1000)

        # 统计计数
        self._stats = {
            'total': 0,
            'info': 0,
            'warning': 0,
            'critical': 0,
        }

        # 沙盒模式标记
        self._sandbox_mode = config.sandbox.enabled

        # 数据库持久化（延迟导入，避免循环依赖）
        self._db_enabled = False
        self._write_queue: deque[AuditLog] = deque()
        self._write_thread = None
        self._stop_event = threading.Event()

    def enable_db_persistence(self) -> None:
        '''启用数据库持久化（在数据库初始化完成后调用）.'''
        if self._db_enabled:
            return
        self._db_enabled = True

        # 启动异步写入线程
        self._write_thread = threading.Thread(
            target=self._db_write_loop,
            daemon=True,
            name='m10-audit-db-writer',
        )
        self._write_thread.start()

    def _db_write_loop(self) -> None:
        '''数据库异步写入循环.'''
        try:
            from .repositories.audit_repository import AuditRepository
        except Exception:
            return

        while not self._stop_event.is_set():
            try:
                # 批量写入（最多20条一批）
                batch = []
                for _ in range(20):
                    if self._write_queue:
                        batch.append(self._write_queue.popleft())
                    else:
                        break

                if not batch:
                    time.sleep(0.5)
                    continue

                for log_entry in batch:
                    try:
                        AuditRepository.add_log(
                            log_id=log_entry.log_id,
                            level=log_entry.level.value,
                            log_type=log_entry.log_type,
                            trigger_condition=log_entry.trigger_condition,
                            action=log_entry.action,
                            result=log_entry.result,
                            details=log_entry.details,
                        )
                    except Exception:
                        pass  # 写入失败不影响主流程

            except Exception:
                time.sleep(1)

    def stop(self) -> None:
        '''停止审计日志写入，刷新剩余数据.'''
        self._stop_event.set()
        # 尝试刷新剩余队列中的数据
        if self._write_queue:
            try:
                from .repositories.audit_repository import AuditRepository
                while self._write_queue:
                    log_entry = self._write_queue.popleft()
                    try:
                        AuditRepository.add_log(
                            log_id=log_entry.log_id,
                            level=log_entry.level.value,
                            log_type=log_entry.log_type,
                            trigger_condition=log_entry.trigger_condition,
                            action=log_entry.action,
                            result=log_entry.result,
                            details=log_entry.details,
                        )
                    except Exception:
                        pass
            except Exception:
                pass

    def log(
        self,
        log_type: str,
        trigger_condition: str,
        action: str,
        result: str,
        level: AuditLogLevel = AuditLogLevel.INFO,
        details: dict[str, Any] | None = None,
    ) -> AuditLog:
        '''记录一条审计日志.

        Args:
            log_type: 日志类型
            trigger_condition: 触发条件描述
            action: 执行的动作
            result: 执行结果
            level: 日志级别
            details: 详细信息字典

        Returns:
            创建的审计日志对象
        '''
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

        # 写入内存缓存
        self._logs.append(log_entry)

        # 更新统计
        self._stats['total'] += 1
        self._stats[level.value] += 1

        # 异步写入数据库
        if self._db_enabled:
            self._write_queue.append(log_entry)

        return log_entry

    def log_info(
        self,
        log_type: str,
        trigger_condition: str,
        action: str,
        result: str,
        details: dict[str, Any] | None = None,
    ) -> AuditLog:
        '''记录 info 级别审计日志.'''
        return self.log(log_type, trigger_condition, action, result, AuditLogLevel.INFO, details)

    def log_warning(
        self,
        log_type: str,
        trigger_condition: str,
        action: str,
        result: str,
        details: dict[str, Any] | None = None,
    ) -> AuditLog:
        '''记录 warning 级别审计日志.'''
        return self.log(log_type, trigger_condition, action, result, AuditLogLevel.WARNING, details)

    def log_critical(
        self,
        log_type: str,
        trigger_condition: str,
        action: str,
        result: str,
        details: dict[str, Any] | None = None,
    ) -> AuditLog:
        '''记录 critical 级别审计日志.'''
        return self.log(log_type, trigger_condition, action, result, AuditLogLevel.CRITICAL, details)

    def get_logs(
        self,
        limit: int = 100,
        level: str | None = None,
        log_type: str | None = None,
        start_time: float | None = None,
        end_time: float | None = None,
        use_db: bool = False,
    ) -> list[AuditLog] | list[dict]:
        '''查询审计日志.

        Args:
            limit: 返回数量限制
            level: 按级别过滤
            log_type: 按类型过滤
            start_time: 开始时间戳
            end_time: 结束时间戳
            use_db: 是否从数据库查询（查询历史数据时使用）

        Returns:
            审计日志列表（按时间倒序）
        '''
        if use_db and self._db_enabled:
            try:
                from .repositories.audit_repository import AuditRepository
                return AuditRepository.get_logs(
                    limit=limit,
                    level=level,
                    log_type=log_type,
                    start_time=start_time,
                    end_time=end_time,
                )
            except Exception:
                pass  # 数据库查询失败，回退到内存

        # 从内存缓存查询
        logs = list(reversed(self._logs))

        if level:
            logs = [l for l in logs if l.level.value == level]
        if log_type:
            logs = [l for l in logs if l.log_type == log_type]
        if start_time:
            logs = [l for l in logs if l.timestamp >= start_time]
        if end_time:
            logs = [l for l in logs if l.timestamp <= end_time]

        return logs[:limit]

    def get_stats(self) -> dict[str, Any]:
        '''获取审计日志统计信息.

        Returns:
            统计信息字典
        '''
        # 内存中的类型统计
        type_stats: dict[str, int] = {}
        for log in self._logs:
            type_stats[log.log_type] = type_stats.get(log.log_type, 0) + 1

        # 如果启用了数据库，合并数据库统计
        db_total = 0
        if self._db_enabled:
            try:
                from .repositories.audit_repository import AuditRepository
                db_stats = AuditRepository.get_stats()
                db_total = db_stats.get('total', 0)
                # 合并级别统计（数据库的更全）
                if 'by_level' in db_stats:
                    self._stats = db_stats['by_level']
                    self._stats['total'] = db_total
            except Exception:
                pass

        return {
            'total': max(self._stats['total'], db_total),
            'by_level': {
                'info': self._stats['info'],
                'warning': self._stats['warning'],
                'critical': self._stats['critical'],
            },
            'by_type': type_stats,
            'sandbox_mode': self._sandbox_mode,
            'storage': 'database' if self._db_enabled else 'memory_only',
            'memory_cache_size': len(self._logs),
        }

    def get_log_types(self) -> list[str]:
        '''获取所有日志类型.'''
        types = set()
        for log in self._logs:
            types.add(log.log_type)
        return sorted(types)

    def clear_logs(self) -> int:
        '''清空审计日志.

        Returns:
            清除的日志数量（内存中的数量）
        '''
        count = len(self._logs)
        self._logs.clear()
        self._stats = {
            'total': 0,
            'info': 0,
            'warning': 0,
            'critical': 0,
        }

        # 同时清空数据库
        if self._db_enabled:
            try:
                from .repositories.audit_repository import AuditRepository
                db_count = AuditRepository.clear_logs()
                count = max(count, db_count)
            except Exception:
                pass

        return count

    def export_logs(
        self,
        format: str = 'json',
        level: str | None = None,
        start_time: float | None = None,
        end_time: float | None = None,
    ) -> str:
        '''导出审计日志.

        Args:
            format: 导出格式 (json/csv)
            level: 级别过滤
            start_time: 开始时间
            end_time: 结束时间

        Returns:
            导出的字符串
        '''
        logs = self.get_logs(limit=10000, level=level, start_time=start_time, end_time=end_time)

        if format == 'csv':
            lines = ['log_id,timestamp,level,log_type,trigger_condition,action,result']
            for log in logs:
                if isinstance(log, dict):
                    line = ','.join([
                        str(log.get('log_id', '')),
                        str(log.get('timestamp', '')),
                        str(log.get('level', '')),
                        str(log.get('log_type', '')),
                        f'"{log.get("trigger_condition", "")}"',
                        f'"{log.get("action", "")}"',
                        f'"{log.get("result", "")}"',
                    ])
                else:
                    line = ','.join([
                        log.log_id,
                        str(log.timestamp),
                        log.level.value,
                        log.log_type,
                        f'"{log.trigger_condition}"',
                        f'"{log.action}"',
                        f'"{log.result}"',
                    ])
                lines.append(line)
            return '\n'.join(lines)
        else:
            import json
            log_dicts = []
            for log in logs:
                if isinstance(log, dict):
                    log_dicts.append(log)
                else:
                    log_dicts.append(log.to_dict())
            return json.dumps(log_dicts, ensure_ascii=False, indent=2)


# 全局单例获取函数
_audit_logger_instance = None


def get_audit_logger() -> AuditLogger:
    '''获取审计日志记录器单例.'''
    global _audit_logger_instance
    if _audit_logger_instance is None:
        _audit_logger_instance = AuditLogger()
    return _audit_logger_instance
