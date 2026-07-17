"""
云汐统一审计框架 (shared.core.audit_framework)
=================================================
SC-007 P1级 - 审计日志全覆盖

提供全系统统一的审计日志能力，包括：
- 统一的审计事件数据模型（8大分类 + 3级严重级别）
- 多种存储后端（文件、内存）
- 审计装饰器和中间件
- 查询、筛选、导出、统计功能
- 防篡改设计（链式哈希 + 只追加写入）
- 异步写入，不影响业务性能
- 敏感信息自动脱敏

审计事件分类（AuditCategory）：
- authentication: 认证事件（登录、登出、Token刷新、登录失败）
- authorization: 授权事件（权限变更、角色分配、访问拒绝）
- configuration: 配置变更（系统配置、模块配置、密钥变更）
- data_management: 数据管理（数据导入导出、备份恢复、数据删除）
- user_management: 用户管理（用户创建、删除、修改）
- security: 安全事件（攻击检测、WAF拦截、安全策略变更）
- system: 系统事件（模块启停、系统升级、服务重启）
- api: API调用（敏感API调用记录）

审计严重级别（AuditLevel）：
- info: 普通信息
- warning: 警告
- critical: 严重

用法：
    from shared.core.audit_framework import (
        AuditLogger, AuditEvent, AuditCategory, AuditLevel,
        audit_log, get_audit_logger,
    )

    # 获取全局审计日志器
    audit = get_audit_logger()

    # 记录审计事件
    audit.log(AuditEvent(
        category=AuditCategory.AUTHENTICATION,
        action="login",
        actor="user123",
        result="success",
        ip_address="192.168.1.1",
    ))

    # 使用装饰器
    @audit_log(action="create_user", category=AuditCategory.USER_MANAGEMENT)
    def create_user(...):
        ...

    # 查询审计日志
    results = audit.query(category=AuditCategory.AUTHENTICATION, level=AuditLevel.CRITICAL)

    # 导出审计日志
    csv_data = audit.export("csv", filters={...})

    # 获取统计信息
    stats = audit.get_stats(time_range="24h")
"""

from __future__ import annotations

import json
import csv
import io
import os
import uuid
import hashlib
import threading
import logging
import asyncio
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from functools import wraps


logger = logging.getLogger("yunxi.audit")


# ===========================================================================
# 审计事件分类枚举
# ===========================================================================

class AuditCategory(str, Enum):
    """审计事件分类"""
    AUTHENTICATION = "authentication"    # 认证事件
    AUTHORIZATION = "authorization"      # 授权事件
    CONFIGURATION = "configuration"      # 配置变更
    DATA_MANAGEMENT = "data_management"  # 数据管理
    USER_MANAGEMENT = "user_management"  # 用户管理
    SECURITY = "security"                # 安全事件
    SYSTEM = "system"                    # 系统事件
    API = "api"                          # API调用

    @classmethod
    def all_categories(cls) -> List[str]:
        """获取所有分类名称列表"""
        return [c.value for c in cls]


class AuditLevel(str, Enum):
    """审计严重级别"""
    INFO = "info"        # 普通信息
    WARNING = "warning"  # 警告
    CRITICAL = "critical"  # 严重

    @classmethod
    def all_levels(cls) -> List[str]:
        """获取所有级别名称列表"""
        return [l.value for l in cls]


class AuditResult(str, Enum):
    """审计结果"""
    SUCCESS = "success"
    FAILURE = "failure"


# ===========================================================================
# 审计事件数据模型
# ===========================================================================

class AuditEvent:
    """
    审计事件数据模型

    完整记录一次审计事件的所有信息，支持链式哈希防篡改。
    """

    def __init__(
        self,
        category: Union[AuditCategory, str] = AuditCategory.SYSTEM,
        level: Union[AuditLevel, str] = AuditLevel.INFO,
        actor: str = "",
        module: str = "system",
        action: str = "",
        resource_type: str = "",
        resource_id: str = "",
        description: str = "",
        result: Union[AuditResult, str] = AuditResult.SUCCESS,
        ip_address: str = "",
        user_agent: str = "",
        request_id: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        # 以下字段由框架自动填充
        event_id: Optional[str] = None,
        timestamp: Optional[datetime] = None,
        prev_hash: str = "",
    ):
        self.event_id = event_id or uuid.uuid4().hex
        self.timestamp = timestamp or datetime.now(tz=timezone.utc)
        self.category = category.value if isinstance(category, AuditCategory) else category
        self.level = level.value if isinstance(level, AuditLevel) else level
        self.actor = actor
        self.module = module
        self.action = action
        self.resource_type = resource_type
        self.resource_id = str(resource_id) if resource_id else ""
        self.description = description
        self.result = result.value if isinstance(result, AuditResult) else result
        self.ip_address = ip_address
        self.user_agent = user_agent[:500] if user_agent else ""
        self.request_id = request_id
        self.metadata = metadata or {}
        self.prev_hash = prev_hash
        self._hash = ""  # 本条记录的哈希（计算后填充）

    def to_dict(self, sanitize: bool = True) -> Dict[str, Any]:
        """
        转换为字典

        Args:
            sanitize: 是否脱敏敏感信息

        Returns:
            字典形式的审计事件
        """
        data = {
            "event_id": self.event_id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else "",
            "category": self.category,
            "level": self.level,
            "actor": self.actor,
            "module": self.module,
            "action": self.action,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "description": self.description,
            "result": self.result,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "request_id": self.request_id,
            "metadata": self.metadata,
            "prev_hash": self.prev_hash,
            "hash": self._hash,
        }

        if sanitize:
            self._sanitize_event(data)

        return data

    @staticmethod
    def _sanitize_event(data: Dict[str, Any]) -> None:
        """脱敏审计事件中的敏感信息"""
        # 脱敏 metadata 中的敏感字段
        if data.get("metadata") and isinstance(data["metadata"], dict):
            try:
                from .security import mask_dict_sensitive
                data["metadata"] = mask_dict_sensitive(data["metadata"])
            except ImportError:
                # 如果 security 模块不可用，手动脱敏常见敏感字段
                sensitive_keys = {
                    "password", "secret", "token", "api_key", "private_key",
                    "authorization", "cookie", "session",
                }
                metadata = data["metadata"]
                for key in list(metadata.keys()):
                    if key.lower() in sensitive_keys:
                        metadata[key] = "***"

        # 脱敏描述中的敏感信息
        if data.get("description"):
            try:
                from .security import mask_sensitive_data
                data["description"] = mask_sensitive_data(data["description"])
            except ImportError:
                pass

    def compute_hash(self) -> str:
        """
        计算本条记录的哈希值（用于防篡改链式校验）

        哈希内容包含：event_id + timestamp + category + level + actor +
        module + action + result + prev_hash

        Returns:
            SHA256 哈希十六进制字符串
        """
        hash_content = (
            f"{self.event_id}|"
            f"{self.timestamp.isoformat() if self.timestamp else ''}|"
            f"{self.category}|"
            f"{self.level}|"
            f"{self.actor}|"
            f"{self.module}|"
            f"{self.action}|"
            f"{self.result}|"
            f"{self.prev_hash}"
        )
        self._hash = hashlib.sha256(hash_content.encode("utf-8")).hexdigest()
        return self._hash

    @property
    def hash_value(self) -> str:
        """获取本条记录的哈希值"""
        if not self._hash:
            self.compute_hash()
        return self._hash

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AuditEvent":
        """从字典创建审计事件"""
        event = cls(
            event_id=data.get("event_id", ""),
            category=data.get("category", AuditCategory.SYSTEM),
            level=data.get("level", AuditLevel.INFO),
            actor=data.get("actor", ""),
            module=data.get("module", "system"),
            action=data.get("action", ""),
            resource_type=data.get("resource_type", ""),
            resource_id=data.get("resource_id", ""),
            description=data.get("description", ""),
            result=data.get("result", AuditResult.SUCCESS),
            ip_address=data.get("ip_address", ""),
            user_agent=data.get("user_agent", ""),
            request_id=data.get("request_id", ""),
            metadata=data.get("metadata", {}),
            prev_hash=data.get("prev_hash", ""),
        )
        ts = data.get("timestamp", "")
        if ts:
            try:
                event.timestamp = datetime.fromisoformat(ts)
            except (ValueError, TypeError):
                event.timestamp = datetime.now(tz=timezone.utc)
        event._hash = data.get("hash", "")
        return event

    def verify_hash(self) -> bool:
        """验证本条记录的哈希是否正确"""
        if not self._hash:
            return False
        # 保存原始哈希
        original_hash = self._hash
        # 临时清空，重新计算
        self._hash = ""
        computed = self.compute_hash()
        # 恢复原始哈希
        is_valid = (original_hash == computed)
        self._hash = original_hash
        return is_valid


# ===========================================================================
# 存储后端接口
# ===========================================================================

class AuditStorageBackend:
    """
    审计日志存储后端接口（抽象基类）

    各模块可实现自己的存储后端（文件、数据库、内存等）。
    """

    def append(self, event: AuditEvent) -> None:
        """追加一条审计记录"""
        raise NotImplementedError

    def query(
        self,
        category: Optional[str] = None,
        level: Optional[str] = None,
        actor: Optional[str] = None,
        module: Optional[str] = None,
        action: Optional[str] = None,
        result: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "timestamp",
        sort_order: str = "desc",
    ) -> Tuple[List[AuditEvent], int]:
        """
        查询审计日志

        Returns:
            (事件列表, 总数)
        """
        raise NotImplementedError

    def get_last_hash(self) -> str:
        """获取最后一条记录的哈希（用于链式哈希）"""
        raise NotImplementedError

    def get_all(self) -> List[AuditEvent]:
        """获取所有记录（用于校验和导出）"""
        raise NotImplementedError

    def clean_expired(self, retention_days: int) -> int:
        """清理过期的审计日志"""
        raise NotImplementedError


# ===========================================================================
# 内存存储后端（用于测试和无持久化场景）
# ===========================================================================

class MemoryAuditStorage(AuditStorageBackend):
    """
    内存版审计日志存储

    适用于测试和单进程临时场景，进程重启后数据丢失。
    """

    def __init__(self, max_records: int = 10000):
        self._events: List[AuditEvent] = []
        self._lock = threading.Lock()
        self._max_records = max_records

    def append(self, event: AuditEvent) -> None:
        with self._lock:
            # 设置前一条记录的哈希（链式哈希）
            if self._events:
                event.prev_hash = self._events[-1].hash_value
            else:
                event.prev_hash = ""
            # 计算本条记录的哈希
            event.compute_hash()
            self._events.append(event)
            # 超过最大记录数时移除最旧的
            if len(self._events) > self._max_records:
                self._events = self._events[-self._max_records:]

    def query(
        self,
        category: Optional[str] = None,
        level: Optional[str] = None,
        actor: Optional[str] = None,
        module: Optional[str] = None,
        action: Optional[str] = None,
        result: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "timestamp",
        sort_order: str = "desc",
    ) -> Tuple[List[AuditEvent], int]:
        with self._lock:
            events = list(self._events)

        # 筛选
        filtered = events
        if category:
            filtered = [e for e in filtered if e.category == category]
        if level:
            filtered = [e for e in filtered if e.level == level]
        if actor:
            filtered = [e for e in filtered if actor.lower() in e.actor.lower()]
        if module:
            filtered = [e for e in filtered if e.module == module]
        if action:
            filtered = [e for e in filtered if e.action == action]
        if result:
            filtered = [e for e in filtered if e.result == result]
        if start_time:
            filtered = [e for e in filtered if e.timestamp >= start_time]
        if end_time:
            filtered = [e for e in filtered if e.timestamp <= end_time]

        # 排序
        reverse = sort_order.lower() == "desc"
        filtered.sort(key=lambda e: getattr(e, sort_by, e.timestamp), reverse=reverse)

        total = len(filtered)

        # 分页
        start = (page - 1) * page_size
        end = start + page_size
        items = filtered[start:end]

        return items, total

    def get_last_hash(self) -> str:
        with self._lock:
            if self._events:
                return self._events[-1].hash_value
        return ""

    def get_all(self) -> List[AuditEvent]:
        with self._lock:
            return list(self._events)

    def clean_expired(self, retention_days: int) -> int:
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=retention_days)
        with self._lock:
            original_count = len(self._events)
            self._events = [e for e in self._events if e.timestamp >= cutoff]
            return original_count - len(self._events)


# ===========================================================================
# JSON 文件存储后端（默认后端）
# ===========================================================================

class JsonFileAuditStorage(AuditStorageBackend):
    """
    JSON 文件版审计日志存储（只追加模式）

    特性：
    - 每行一条 JSON 记录（JSONL 格式），便于增量追加
    - 文件锁保证并发安全
    - 支持按日期自动分文件
    - 支持保留策略自动清理
    """

    def __init__(
        self,
        log_dir: Optional[Path] = None,
        max_file_size_mb: int = 100,
        retention_days: int = 180,
    ):
        if log_dir is None:
            log_dir = Path.home() / ".yunxi" / "audit"
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.max_file_size_mb = max_file_size_mb
        self.retention_days = retention_days
        self._lock = threading.Lock()
        self._last_hash = ""
        self._last_hash_file = self.log_dir / ".last_hash"

        # 加载最后一条记录的哈希
        self._load_last_hash()

    def _get_current_file(self) -> Path:
        """获取当前日志文件路径（按日期分文件）"""
        today = datetime.now(tz=timezone.utc).strftime("%Y%m%d")
        return self.log_dir / f"audit_{today}.jsonl"

    def _load_last_hash(self) -> None:
        """从文件加载最后一条记录的哈希"""
        try:
            if self._last_hash_file.exists():
                self._last_hash = self._last_hash_file.read_text(encoding="utf-8").strip()
        except Exception as e:
            logger.warning("加载审计最后哈希失败: %s", e)
            self._last_hash = ""

    def _save_last_hash(self, hash_val: str) -> None:
        """保存最后一条记录的哈希"""
        try:
            self._last_hash_file.write_text(hash_val, encoding="utf-8")
        except Exception as e:
            logger.warning("保存审计最后哈希失败: %s", e)

    def append(self, event: AuditEvent) -> None:
        with self._lock:
            # 设置前一条记录的哈希
            event.prev_hash = self._last_hash
            # 计算本条记录的哈希
            event.compute_hash()

            # 追加写入文件
            log_file = self._get_current_file()
            try:
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(event.to_dict(sanitize=False), ensure_ascii=False) + "\n")
            except Exception as e:
                logger.error("审计日志写入文件失败: %s", e)
                # 写入失败也要更新内存中的哈希吗？不，写入失败不更新
                return

            # 更新最后哈希
            self._last_hash = event.hash_value
            self._save_last_hash(self._last_hash)

    def _iter_all_events(self) -> List[AuditEvent]:
        """迭代所有日志文件中的事件"""
        events = []
        try:
            for log_file in sorted(self.log_dir.glob("audit_*.jsonl")):
                try:
                    with open(log_file, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                data = json.loads(line)
                                events.append(AuditEvent.from_dict(data))
                            except json.JSONDecodeError:
                                continue
                except Exception as e:
                    logger.warning("读取审计日志文件 %s 失败: %s", log_file, e)
        except Exception as e:
            logger.error("枚举审计日志文件失败: %s", e)
        return events

    def query(
        self,
        category: Optional[str] = None,
        level: Optional[str] = None,
        actor: Optional[str] = None,
        module: Optional[str] = None,
        action: Optional[str] = None,
        result: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "timestamp",
        sort_order: str = "desc",
    ) -> Tuple[List[AuditEvent], int]:
        events = self._iter_all_events()

        # 筛选
        filtered = events
        if category:
            filtered = [e for e in filtered if e.category == category]
        if level:
            filtered = [e for e in filtered if e.level == level]
        if actor:
            filtered = [e for e in filtered if actor.lower() in e.actor.lower()]
        if module:
            filtered = [e for e in filtered if e.module == module]
        if action:
            filtered = [e for e in filtered if e.action == action]
        if result:
            filtered = [e for e in filtered if e.result == result]
        if start_time:
            filtered = [e for e in filtered if e.timestamp >= start_time]
        if end_time:
            filtered = [e for e in filtered if e.timestamp <= end_time]

        # 排序
        reverse = sort_order.lower() == "desc"
        filtered.sort(key=lambda e: getattr(e, sort_by, e.timestamp), reverse=reverse)

        total = len(filtered)

        # 分页
        start = (page - 1) * page_size
        end = start + page_size
        items = filtered[start:end]

        return items, total

    def get_last_hash(self) -> str:
        with self._lock:
            return self._last_hash

    def get_all(self) -> List[AuditEvent]:
        return self._iter_all_events()

    def clean_expired(self, retention_days: Optional[int] = None) -> int:
        """清理过期的审计日志文件"""
        days = retention_days if retention_days is not None else self.retention_days
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)
        deleted = 0
        try:
            for log_file in self.log_dir.glob("audit_*.jsonl"):
                try:
                    # 从文件名提取日期
                    name = log_file.stem  # audit_YYYYMMDD
                    date_str = name.replace("audit_", "")
                    file_date = datetime.strptime(date_str, "%Y%m%d").replace(tzinfo=timezone.utc)
                    if file_date < cutoff:
                        log_file.unlink()
                        deleted += 1
                except (ValueError, IndexError):
                    continue
        except Exception as e:
            logger.error("清理过期审计日志失败: %s", e)
        return deleted


# ===========================================================================
# 主审计日志器
# ===========================================================================

class AuditLogger:
    """
    统一审计日志器

    提供审计事件的记录、查询、导出、统计等核心功能。
    支持异步写入，不影响业务性能。
    """

    def __init__(
        self,
        storage: Optional[AuditStorageBackend] = None,
        async_mode: bool = False,
        queue_size: int = 1000,
    ):
        """
        初始化审计日志器

        Args:
            storage: 存储后端，默认使用 JSON 文件存储
            async_mode: 是否启用异步写入模式
            queue_size: 异步队列大小（async_mode=True 时有效）
        """
        if storage is None:
            storage = JsonFileAuditStorage()
        self._storage = storage
        self._async_mode = async_mode
        self._queue: Optional[asyncio.Queue] = None
        self._writer_task: Optional[asyncio.Task] = None
        self._sync_lock = threading.Lock()

        if async_mode:
            self._init_async_writer(queue_size)

    def _init_async_writer(self, queue_size: int) -> None:
        """初始化异步写入器"""
        try:
            self._queue = asyncio.Queue(maxsize=queue_size)
        except RuntimeError:
            # 如果没有事件循环，降级为同步模式
            self._async_mode = False
            logger.warning("审计日志异步模式初始化失败，降级为同步模式")

    async def _async_writer_loop(self) -> None:
        """异步写入循环"""
        if self._queue is None:
            return
        while True:
            try:
                event = await self._queue.get()
                if event is None:  # 哨兵值，用于停止
                    break
                try:
                    self._storage.append(event)
                except Exception as e:
                    logger.error("异步审计日志写入失败: %s", e)
                finally:
                    self._queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("审计日志异步写入循环异常: %s", e)

    def start_async_writer(self) -> None:
        """启动异步写入任务（需在事件循环中调用）"""
        if self._async_mode and self._writer_task is None:
            try:
                self._writer_task = asyncio.create_task(self._async_writer_loop())
            except RuntimeError:
                self._async_mode = False

    async def stop_async_writer(self) -> None:
        """停止异步写入任务"""
        if self._writer_task and not self._writer_task.done():
            if self._queue is not None:
                await self._queue.put(None)  # 发送停止信号
                await self._queue.join()
            self._writer_task.cancel()
            try:
                await self._writer_task
            except asyncio.CancelledError:
                pass
            self._writer_task = None

    def log(self, event: AuditEvent) -> AuditEvent:
        """
        记录审计事件

        Args:
            event: 审计事件对象

        Returns:
            记录后的审计事件（包含计算后的哈希等）
        """
        if self._async_mode and self._queue is not None:
            try:
                self._queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("审计日志队列已满，降级为同步写入")
                self._storage.append(event)
        else:
            with self._sync_lock:
                self._storage.append(event)

        return event

    def log_simple(
        self,
        action: str,
        category: Union[AuditCategory, str] = AuditCategory.SYSTEM,
        level: Union[AuditLevel, str] = AuditLevel.INFO,
        actor: str = "",
        module: str = "system",
        result: Union[AuditResult, str] = AuditResult.SUCCESS,
        ip_address: str = "",
        description: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        user_agent: str = "",
        request_id: str = "",
    ) -> AuditEvent:
        """
        便捷方法：简单记录一条审计事件

        Args:
            action: 操作类型
            category: 事件分类
            level: 严重级别
            actor: 操作者
            module: 模块
            result: 结果
            ip_address: IP地址
            description: 描述
            metadata: 附加元数据
            user_agent: 用户代理
            request_id: 请求ID

        Returns:
            记录后的审计事件
        """
        event = AuditEvent(
            category=category,
            level=level,
            actor=actor,
            module=module,
            action=action,
            description=description,
            result=result,
            ip_address=ip_address,
            user_agent=user_agent,
            request_id=request_id,
            metadata=metadata,
        )
        return self.log(event)

    def query(
        self,
        category: Optional[Union[AuditCategory, str]] = None,
        level: Optional[Union[AuditLevel, str]] = None,
        actor: Optional[str] = None,
        module: Optional[str] = None,
        action: Optional[str] = None,
        result: Optional[Union[AuditResult, str]] = None,
        start_time: Optional[Union[datetime, str]] = None,
        end_time: Optional[Union[datetime, str]] = None,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "timestamp",
        sort_order: str = "desc",
    ) -> Dict[str, Any]:
        """
        查询审计日志

        Args:
            category: 按分类筛选
            level: 按级别筛选
            actor: 按操作者筛选
            module: 按模块筛选
            action: 按操作筛选
            result: 按结果筛选
            start_time: 开始时间
            end_time: 结束时间
            page: 页码
            page_size: 每页数量
            sort_by: 排序字段
            sort_order: 排序方向（asc/desc）

        Returns:
            {"items": [...], "total": N, "page": page, "page_size": page_size}
        """
        # 转换枚举类型
        cat = category.value if isinstance(category, AuditCategory) else category
        lvl = level.value if isinstance(level, AuditLevel) else level
        res = result.value if isinstance(result, AuditResult) else result

        # 转换时间字符串
        st = None
        if start_time:
            if isinstance(start_time, str):
                try:
                    st = datetime.fromisoformat(start_time)
                except ValueError:
                    st = None
            else:
                st = start_time

        et = None
        if end_time:
            if isinstance(end_time, str):
                try:
                    et = datetime.fromisoformat(end_time)
                except ValueError:
                    et = None
            else:
                et = end_time

        items, total = self._storage.query(
            category=cat,
            level=lvl,
            actor=actor,
            module=module,
            action=action,
            result=res,
            start_time=st,
            end_time=et,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
        )

        return {
            "items": [e.to_dict() for e in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def get_event(self, event_id: str) -> Optional[Dict[str, Any]]:
        """
        获取单条审计事件详情

        Args:
            event_id: 事件ID

        Returns:
            事件字典，不存在返回 None
        """
        # 使用 query 精确匹配 event_id
        all_events = self._storage.get_all()
        for event in all_events:
            if event.event_id == event_id:
                return event.to_dict()
        return None

    def export(
        self,
        format: str = "json",
        category: Optional[str] = None,
        level: Optional[str] = None,
        actor: Optional[str] = None,
        module: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> str:
        """
        导出审计日志

        Args:
            format: 导出格式（json/csv）
            category: 按分类筛选
            level: 按级别筛选
            actor: 按操作者筛选
            module: 按模块筛选
            start_time: 开始时间
            end_time: 结束时间

        Returns:
            导出的字符串内容
        """
        # 查询所有符合条件的记录（不分页）
        items, _ = self._storage.query(
            category=category,
            level=level,
            actor=actor,
            module=module,
            start_time=start_time,
            end_time=end_time,
            page=1,
            page_size=100000,  # 导出上限 10万条
        )

        if format.lower() == "csv":
            return self._export_csv(items)
        else:
            return self._export_json(items)

    def _export_json(self, events: List[AuditEvent]) -> str:
        """导出为 JSON 格式"""
        data = [e.to_dict() for e in events]
        return json.dumps(data, ensure_ascii=False, indent=2)

    def _export_csv(self, events: List[AuditEvent]) -> str:
        """导出为 CSV 格式"""
        output = io.StringIO()
        writer = csv.writer(output)

        # CSV 表头
        headers = [
            "事件ID", "时间", "分类", "级别", "操作者", "模块", "操作",
            "资源类型", "资源ID", "描述", "结果", "IP地址", "User-Agent",
            "请求ID", "元数据",
        ]
        writer.writerow(headers)

        for event in events:
            metadata_str = json.dumps(event.metadata, ensure_ascii=False) if event.metadata else ""
            writer.writerow([
                event.event_id,
                event.timestamp.strftime("%Y-%m-%d %H:%M:%S") if event.timestamp else "",
                event.category,
                event.level,
                event.actor,
                event.module,
                event.action,
                event.resource_type,
                event.resource_id,
                event.description,
                event.result,
                event.ip_address,
                event.user_agent,
                event.request_id,
                metadata_str,
            ])

        return output.getvalue()

    def get_stats(self, time_range: str = "24h") -> Dict[str, Any]:
        """
        获取审计统计信息

        Args:
            time_range: 时间范围（1h/24h/7d/30d/all）

        Returns:
            统计数据字典
        """
        # 解析时间范围
        now = datetime.now(tz=timezone.utc)
        if time_range == "1h":
            start = now - timedelta(hours=1)
        elif time_range == "24h":
            start = now - timedelta(days=1)
        elif time_range == "7d":
            start = now - timedelta(days=7)
        elif time_range == "30d":
            start = now - timedelta(days=30)
        else:  # all
            start = None

        # 获取时间范围内的所有事件
        events, total = self._storage.query(
            start_time=start,
            page=1,
            page_size=100000,
        )

        # 按分类统计
        by_category: Dict[str, int] = {}
        # 按级别统计
        by_level: Dict[str, int] = {}
        # 按模块统计
        by_module: Dict[str, int] = {}
        # 按结果统计
        by_result: Dict[str, int] = {}
        # 按操作统计（Top 10）
        by_action: Dict[str, int] = {}
        # 按天统计（用于趋势图）
        by_day: Dict[str, int] = {}

        for event in events:
            # 分类统计
            cat = event.category
            by_category[cat] = by_category.get(cat, 0) + 1

            # 级别统计
            lvl = event.level
            by_level[lvl] = by_level.get(lvl, 0) + 1

            # 模块统计
            mod = event.module
            by_module[mod] = by_module.get(mod, 0) + 1

            # 结果统计
            res = event.result
            by_result[res] = by_result.get(res, 0) + 1

            # 操作统计
            act = event.action
            by_action[act] = by_action.get(act, 0) + 1

            # 按天统计
            if event.timestamp:
                day = event.timestamp.strftime("%Y-%m-%d")
                by_day[day] = by_day.get(day, 0) + 1

        # Top 10 操作
        top_actions = sorted(by_action.items(), key=lambda x: x[1], reverse=True)[:10]

        # 按天趋势排序
        sorted_days = dict(sorted(by_day.items()))

        return {
            "total": total,
            "time_range": time_range,
            "by_category": by_category,
            "by_level": by_level,
            "by_module": by_module,
            "by_result": by_result,
            "top_actions": [{"action": a, "count": c} for a, c in top_actions],
            "by_day": sorted_days,
            "critical_count": by_level.get("critical", 0),
            "warning_count": by_level.get("warning", 0),
            "failure_count": by_result.get("failure", 0),
        }

    def verify_integrity(self) -> Dict[str, Any]:
        """
        验证审计日志完整性（链式哈希校验）

        Returns:
            {"valid": bool, "total_records": int, "error_index": int, "error_detail": str}
        """
        events = self._storage.get_all()
        prev_hash = ""

        for i, event in enumerate(events):
            # 验证前一条哈希
            if event.prev_hash != prev_hash:
                return {
                    "valid": False,
                    "total_records": len(events),
                    "error_index": i,
                    "error_detail": f"第 {i} 条记录的 prev_hash 不匹配，"
                                   f"期望: {prev_hash[:16]}..., 实际: {event.prev_hash[:16]}...",
                }

            # 验证本条哈希
            if not event.verify_hash():
                return {
                    "valid": False,
                    "total_records": len(events),
                    "error_index": i,
                    "error_detail": f"第 {i} 条记录的哈希校验失败",
                }

            prev_hash = event.hash_value

        return {
            "valid": True,
            "total_records": len(events),
            "error_index": -1,
            "error_detail": "",
        }

    def clean_expired(self, retention_days: Optional[int] = None) -> int:
        """清理过期的审计日志"""
        return self._storage.clean_expired(retention_days)

    @property
    def storage(self) -> AuditStorageBackend:
        """获取存储后端"""
        return self._storage


# ===========================================================================
# 审计装饰器
# ===========================================================================

def audit_log(
    action: str,
    category: Union[AuditCategory, str] = AuditCategory.SYSTEM,
    level: Union[AuditLevel, str] = AuditLevel.INFO,
    module: str = "system",
    resource_type: str = "",
    audit_logger: Optional[AuditLogger] = None,
):
    """
    审计日志装饰器

    自动记录函数调用的审计事件，支持同步和异步函数。

    用法：
        @audit_log("create_user", AuditCategory.USER_MANAGEMENT)
        def create_user(username, ...):
            ...

        # 异步函数
        @audit_log("delete_user", AuditCategory.USER_MANAGEMENT, level=AuditLevel.WARNING)
        async def delete_user(user_id):
            ...

    被装饰函数可以通过以下方式提供审计上下文：
    - 函数参数中的 request 对象（自动提取 IP、User-Agent）
    - 函数参数中的 current_user（自动提取操作者信息）
    - 函数返回值中的 _audit_context 字典（覆盖默认行为）
    """
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            return await _audit_wrapper(
                func, True, action, category, level, module,
                resource_type, audit_logger, args, kwargs
            )

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            return _audit_wrapper_sync(
                func, action, category, level, module,
                resource_type, audit_logger, args, kwargs
            )

        import inspect
        if inspect.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator


def _extract_audit_context(
    args: tuple,
    kwargs: dict,
) -> Dict[str, Any]:
    """从函数参数中提取审计上下文"""
    ctx = {
        "actor": "",
        "ip_address": "",
        "user_agent": "",
        "request_id": "",
    }

    # 从 kwargs 中提取
    request = kwargs.get("request")
    if request:
        try:
            # 提取 IP
            if hasattr(request, "client") and request.client:
                ctx["ip_address"] = request.client.host
            # 从 header 提取 X-Forwarded-For
            forwarded = request.headers.get("X-Forwarded-For", "")
            if forwarded:
                ctx["ip_address"] = forwarded.split(",")[0].strip()
            # 提取 User-Agent
            ctx["user_agent"] = request.headers.get("User-Agent", "")
            # 提取请求 ID
            ctx["request_id"] = request.headers.get("X-Request-ID", "")
            # 从 request.state 提取 trace_id
            if hasattr(request, "state"):
                trace_id = getattr(request.state, "trace_id", "")
                if trace_id:
                    ctx["request_id"] = trace_id
        except Exception:
            pass

    # 提取 current_user
    current_user = kwargs.get("current_user")
    if current_user:
        if isinstance(current_user, dict):
            ctx["actor"] = current_user.get("username", "") or current_user.get("user_id", "")
        elif hasattr(current_user, "username"):
            ctx["actor"] = current_user.username

    return ctx


async def _audit_wrapper(
    func,
    is_async: bool,
    action: str,
    category: Union[AuditCategory, str],
    level: Union[AuditLevel, str],
    module: str,
    resource_type: str,
    audit_logger: Optional[AuditLogger],
    args: tuple,
    kwargs: dict,
):
    """异步审计包装器"""
    if audit_logger is None:
        audit_logger = get_audit_logger()

    ctx = _extract_audit_context(args, kwargs)

    result_status = AuditResult.SUCCESS
    description = ""
    metadata: Dict[str, Any] = {}

    try:
        result = await func(*args, **kwargs)

        # 检查返回值是否包含审计上下文
        if isinstance(result, dict) and "_audit_context" in result:
            audit_ctx = result["_audit_context"]
            if isinstance(audit_ctx, dict):
                if "result" in audit_ctx:
                    result_status = audit_ctx["result"]
                if "description" in audit_ctx:
                    description = audit_ctx["description"]
                if "metadata" in audit_ctx:
                    metadata.update(audit_ctx["metadata"])
                if "resource_id" in audit_ctx:
                    resource_type = resource_type or audit_ctx.get("resource_type", "")

        # 检查 ApiResponse 风格的返回
        if hasattr(result, 'code'):
            if result.code != 0:
                result_status = AuditResult.FAILURE
                metadata["error_message"] = getattr(result, 'message', '')
        elif isinstance(result, dict) and result.get("code", 0) != 0:
            result_status = AuditResult.FAILURE
            metadata["error_message"] = result.get("message", "")

        return result
    except Exception as e:
        result_status = AuditResult.FAILURE
        metadata["error"] = str(e)
        metadata["error_type"] = type(e).__name__
        raise
    finally:
        try:
            event = AuditEvent(
                category=category,
                level=level,
                actor=ctx["actor"],
                module=module,
                action=action,
                resource_type=resource_type,
                description=description,
                result=result_status,
                ip_address=ctx["ip_address"],
                user_agent=ctx["user_agent"],
                request_id=ctx["request_id"],
                metadata=metadata,
            )
            audit_logger.log(event)
        except Exception as e:
            # 审计日志写入失败不影响主流程
            logger.warning("审计日志写入失败（装饰器）: %s", e)


def _audit_wrapper_sync(
    func,
    action: str,
    category: Union[AuditCategory, str],
    level: Union[AuditLevel, str],
    module: str,
    resource_type: str,
    audit_logger: Optional[AuditLogger],
    args: tuple,
    kwargs: dict,
):
    """同步审计包装器"""
    if audit_logger is None:
        audit_logger = get_audit_logger()

    ctx = _extract_audit_context(args, kwargs)

    result_status = AuditResult.SUCCESS
    description = ""
    metadata: Dict[str, Any] = {}

    try:
        result = func(*args, **kwargs)

        # 检查返回值是否包含审计上下文
        if isinstance(result, dict) and "_audit_context" in result:
            audit_ctx = result["_audit_context"]
            if isinstance(audit_ctx, dict):
                if "result" in audit_ctx:
                    result_status = audit_ctx["result"]
                if "description" in audit_ctx:
                    description = audit_ctx["description"]
                if "metadata" in audit_ctx:
                    metadata.update(audit_ctx["metadata"])

        # 检查 ApiResponse 风格的返回
        if hasattr(result, 'code'):
            if result.code != 0:
                result_status = AuditResult.FAILURE
                metadata["error_message"] = getattr(result, 'message', '')
        elif isinstance(result, dict) and result.get("code", 0) != 0:
            result_status = AuditResult.FAILURE
            metadata["error_message"] = result.get("message", "")

        return result
    except Exception as e:
        result_status = AuditResult.FAILURE
        metadata["error"] = str(e)
        metadata["error_type"] = type(e).__name__
        raise
    finally:
        try:
            event = AuditEvent(
                category=category,
                level=level,
                actor=ctx["actor"],
                module=module,
                action=action,
                resource_type=resource_type,
                description=description,
                result=result_status,
                ip_address=ctx["ip_address"],
                user_agent=ctx["user_agent"],
                request_id=ctx["request_id"],
                metadata=metadata,
            )
            audit_logger.log(event)
        except Exception as e:
            logger.warning("审计日志写入失败（装饰器）: %s", e)


# ===========================================================================
# FastAPI 审计中间件
# ===========================================================================

class AuditMiddleware:
    """
    FastAPI 审计中间件

    自动记录敏感 API 调用的审计日志。
    可配置敏感路径列表，只记录匹配的路径。

    用法：
        from shared.core.audit_framework import AuditMiddleware

        app.add_middleware(
            AuditMiddleware,
            sensitive_paths=["/api/admin/*", "/api/users/*"],
            audit_logger=get_audit_logger(),
        )
    """

    def __init__(
        self,
        app,
        sensitive_paths: Optional[List[str]] = None,
        audit_logger: Optional[AuditLogger] = None,
        skip_paths: Optional[List[str]] = None,
        record_all: bool = False,
    ):
        self.app = app
        self.sensitive_paths = sensitive_paths or []
        self.skip_paths = skip_paths or ["/health", "/docs", "/openapi.json", "/favicon.ico"]
        self.audit_logger = audit_logger or get_audit_logger()
        self.record_all = record_all

    async def __call__(self, scope, receive, send):
        # 只处理 HTTP 请求
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        from starlette.requests import Request
        request = Request(scope, receive=receive)
        path = request.url.path

        # 跳过不需要审计的路径
        if self._should_skip(path):
            await self.app(scope, receive, send)
            return

        # 判断是否需要记录
        if not self.record_all and not self._is_sensitive(path):
            await self.app(scope, receive, send)
            return

        # 收集请求信息
        ip_address = ""
        user_agent = ""
        request_id = ""
        actor = ""

        try:
            if request.client:
                ip_address = request.client.host
            forwarded = request.headers.get("X-Forwarded-For", "")
            if forwarded:
                ip_address = forwarded.split(",")[0].strip()
            user_agent = request.headers.get("User-Agent", "")
            request_id = request.headers.get("X-Request-ID", "")
        except Exception:
            pass

        # 尝试从 request.state 获取用户信息
        result_status = AuditResult.SUCCESS
        status_code = 200

        # 包装 send 以捕获响应状态码
        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)

            # 根据状态码判断结果
            if status_code >= 400:
                result_status = AuditResult.FAILURE
        except Exception as e:
            result_status = AuditResult.FAILURE
            raise
        finally:
            try:
                # 从 scope 中获取用户信息（如果中间件已设置）
                try:
                    if hasattr(request, "state") and hasattr(request.state, "user"):
                        user = request.state.user
                        if isinstance(user, dict):
                            actor = user.get("username", "") or user.get("user_id", "")
                except Exception:
                    pass

                level = AuditLevel.INFO
                if status_code >= 500:
                    level = AuditLevel.CRITICAL
                elif status_code >= 400:
                    level = AuditLevel.WARNING

                event = AuditEvent(
                    category=AuditCategory.API,
                    level=level,
                    actor=actor,
                    module="api",
                    action=f"{request.method} {path}",
                    resource_type="api_endpoint",
                    result=result_status,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    request_id=request_id,
                    metadata={
                        "method": request.method,
                        "path": path,
                        "status_code": status_code,
                    },
                )
                self.audit_logger.log(event)
            except Exception as e:
                logger.warning("审计中间件写入失败: %s", e)

    def _is_sensitive(self, path: str) -> bool:
        """判断路径是否为敏感路径"""
        from fnmatch import fnmatch
        for pattern in self.sensitive_paths:
            if fnmatch(path, pattern):
                return True
        return False

    def _should_skip(self, path: str) -> bool:
        """判断是否跳过审计"""
        from fnmatch import fnmatch
        for pattern in self.skip_paths:
            if fnmatch(path, pattern):
                return True
        return False


# ===========================================================================
# 认证审计钩子
# ===========================================================================

class AuthAuditHook:
    """
    认证审计钩子

    集成到认证中间件中，自动记录认证相关的审计事件。
    实现了 shared.core.auth.middleware.AuditLogger 接口。
    """

    def __init__(self, audit_logger: Optional[AuditLogger] = None):
        self.audit_logger = audit_logger or get_audit_logger()

    def log_auth(
        self,
        request=None,
        auth_result: str = "success",
        auth_type: Optional[str] = None,
        user_info: Optional[Dict[str, Any]] = None,
        error_detail: Optional[str] = None,
    ) -> None:
        """
        记录认证审计日志（实现统一认证中间件的 AuditLogger 接口）

        Args:
            request: 请求对象
            auth_result: 认证结果（success/failed/denied）
            auth_type: 认证方式（jwt/api_key/none）
            user_info: 用户信息
            error_detail: 错误详情
        """
        # 提取请求信息
        ip_address = ""
        user_agent = ""
        request_id = ""

        if request is not None:
            try:
                if hasattr(request, "client") and request.client:
                    ip_address = request.client.host
                if hasattr(request, "headers"):
                    forwarded = request.headers.get("X-Forwarded-For", "")
                    if forwarded:
                        ip_address = forwarded.split(",")[0].strip()
                    user_agent = request.headers.get("User-Agent", "")
                    request_id = request.headers.get("X-Request-ID", "")
            except Exception:
                pass

        actor = ""
        if user_info:
            if isinstance(user_info, dict):
                actor = user_info.get("username", "") or user_info.get("user_id", "")

        # 确定级别
        if auth_result == "failed":
            level = AuditLevel.WARNING
        elif auth_result == "denied":
            level = AuditLevel.WARNING
        else:
            level = AuditLevel.INFO

        # 确定结果
        result = AuditResult.SUCCESS if auth_result == "success" else AuditResult.FAILURE

        # 描述
        description = ""
        if auth_result == "success":
            description = f"{auth_type or 'unknown'} 认证成功"
        elif auth_result == "failed":
            description = f"认证失败: {error_detail or '未知原因'}"
        elif auth_result == "denied":
            description = f"访问被拒绝: {error_detail or '权限不足'}"

        metadata = {}
        if auth_type:
            metadata["auth_type"] = auth_type
        if error_detail:
            metadata["error_detail"] = error_detail

        event = AuditEvent(
            category=AuditCategory.AUTHENTICATION,
            level=level,
            actor=actor,
            module="auth",
            action="authenticate",
            result=result,
            description=description,
            ip_address=ip_address,
            user_agent=user_agent,
            request_id=request_id,
            metadata=metadata,
        )

        try:
            self.audit_logger.log(event)
        except Exception as e:
            logger.warning("认证审计日志写入失败: %s", e)


# ===========================================================================
# 全局单例
# ===========================================================================

_global_audit_logger: Optional[AuditLogger] = None
_init_lock = threading.Lock()


def get_audit_logger() -> AuditLogger:
    """
    获取全局审计日志器（单例模式）

    Returns:
        全局 AuditLogger 实例
    """
    global _global_audit_logger
    if _global_audit_logger is None:
        with _init_lock:
            if _global_audit_logger is None:
                _global_audit_logger = AuditLogger()
    return _global_audit_logger


def set_audit_logger(logger: AuditLogger) -> None:
    """
    设置全局审计日志器（用于自定义配置）

    Args:
        logger: 自定义的 AuditLogger 实例
    """
    global _global_audit_logger
    with _init_lock:
        _global_audit_logger = logger


# ===========================================================================
# 快捷函数
# ===========================================================================

def audit_event(
    action: str,
    category: Union[AuditCategory, str] = AuditCategory.SYSTEM,
    level: Union[AuditLevel, str] = AuditLevel.INFO,
    actor: str = "",
    module: str = "system",
    result: Union[AuditResult, str] = AuditResult.SUCCESS,
    ip_address: str = "",
    description: str = "",
    **kwargs,
) -> AuditEvent:
    """
    便捷函数：快速记录一条审计事件

    Args:
        action: 操作类型
        category: 事件分类
        level: 严重级别
        actor: 操作者
        module: 模块
        result: 结果
        ip_address: IP地址
        description: 描述
        **kwargs: 其他字段（resource_type, resource_id, user_agent, request_id, metadata）

    Returns:
        记录后的审计事件
    """
    logger = get_audit_logger()
    event = AuditEvent(
        category=category,
        level=level,
        actor=actor,
        module=module,
        action=action,
        resource_type=kwargs.get("resource_type", ""),
        resource_id=kwargs.get("resource_id", ""),
        description=description,
        result=result,
        ip_address=ip_address,
        user_agent=kwargs.get("user_agent", ""),
        request_id=kwargs.get("request_id", ""),
        metadata=kwargs.get("metadata"),
    )
    return logger.log(event)


# ===========================================================================
# 模块导出
# ===========================================================================

__all__ = [
    # 枚举
    "AuditCategory",
    "AuditLevel",
    "AuditResult",
    # 数据模型
    "AuditEvent",
    # 存储后端
    "AuditStorageBackend",
    "MemoryAuditStorage",
    "JsonFileAuditStorage",
    # 主日志器
    "AuditLogger",
    # 装饰器
    "audit_log",
    # 中间件
    "AuditMiddleware",
    # 认证钩子
    "AuthAuditHook",
    # 全局单例
    "get_audit_logger",
    "set_audit_logger",
    # 快捷函数
    "audit_event",
]
