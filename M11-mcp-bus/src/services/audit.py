"""M11 MCP Bus - 审计日志服务.

记录所有关键操作的审计事件，包括服务器注册/删除、工具调用、
API Key 管理、配置变更等，支持按条件查询。
审计日志持久化存储到数据库的审计表中。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import JSON, Column, DateTime, Index, Integer, String, Text

from ..db import Base, get_engine, get_session


# ============================================================
# 审计日志表模型
# ============================================================

class AuditLog(Base):
    """审计日志表.

    记录系统中所有关键操作事件，用于安全审计和问题追溯。
    """

    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True, comment="日志ID")
    event_type = Column(String(50), index=True, nullable=False, comment="事件类型")
    actor = Column(String(100), index=True, default="", comment="操作主体（用户/服务/API Key）")
    action = Column(String(50), index=True, default="", comment="操作动作")
    resource = Column(String(200), index=True, default="", comment="操作对象资源")
    extra_data = Column("metadata", JSON, default=dict, comment="附加元数据(JSON)")
    description = Column(Text, default="", comment="事件描述")
    ip_address = Column(String(50), default="", comment="IP 地址")
    created_at = Column(DateTime, default=datetime.utcnow, index=True, comment="创建时间")

    __table_args__ = (
        Index("ix_audit_event_time", "event_type", "created_at"),
        Index("ix_audit_actor_time", "actor", "created_at"),
    )

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典.

        Returns:
            字典形式的日志记录
        """
        return {
            "id": self.id,
            "event_type": self.event_type,
            "actor": self.actor or "",
            "action": self.action or "",
            "resource": self.resource or "",
            "metadata": self.extra_data or {},
            "description": self.description or "",
            "ip_address": self.ip_address or "",
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ============================================================
# 事件类型常量
# ============================================================

class EventType:
    """审计事件类型常量."""

    SERVER_REGISTER = "server_register"      # 服务器注册
    SERVER_REMOVE = "server_remove"          # 服务器删除
    TOOL_CALL = "tool_call"                  # 工具调用
    API_KEY_CREATE = "api_key_create"        # API Key 创建
    API_KEY_DELETE = "api_key_delete"        # API Key 删除
    CONFIG_CHANGE = "config_change"          # 配置变更
    LOGIN = "login"                          # 登录
    LOGOUT = "logout"                        # 登出
    PERMISSION_DENIED = "permission_denied"  # 权限拒绝
    RATE_LIMIT = "rate_limit"                # 限流触发


# 所有事件类型列表（用于校验）
ALL_EVENT_TYPES = [
    EventType.SERVER_REGISTER,
    EventType.SERVER_REMOVE,
    EventType.TOOL_CALL,
    EventType.API_KEY_CREATE,
    EventType.API_KEY_DELETE,
    EventType.CONFIG_CHANGE,
    EventType.LOGIN,
    EventType.LOGOUT,
    EventType.PERMISSION_DENIED,
    EventType.RATE_LIMIT,
]


# ============================================================
# 审计日志服务
# ============================================================

class AuditLogger:
    """审计日志服务.

    提供审计事件记录和查询功能，所有事件持久化到数据库。
    支持按事件类型、操作主体、时间范围等多维度查询。
    """

    def __init__(self) -> None:
        """初始化审计日志服务.

        确保审计表存在。
        """
        self._ensure_table()

    def _ensure_table(self) -> None:
        """确保审计日志表存在."""
        import logging
        logger = logging.getLogger(__name__)
        try:
            engine = get_engine()
            AuditLog.__table__.create(bind=engine, checkfirst=True)
        except Exception as e:
            # 表可能已存在或数据库未初始化，记录警告
            # 首次写入时会再次尝试建表
            logger.warning("审计日志表初始化检查失败: %s", e)

    # --------------------------------------------------------
    # 记录事件
    # --------------------------------------------------------

    def log_event(
        self,
        event_type: str,
        actor: str = "",
        action: str = "",
        resource: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        description: str = "",
        ip_address: str = "",
    ) -> int:
        """记录审计事件.

        Args:
            event_type: 事件类型（使用 EventType 常量）
            actor: 操作主体（如用户名、API Key 名称、服务名）
            action: 具体操作动作（如 create, delete, update, call）
            resource: 操作的资源标识（如 server:123, tool:xxx）
            metadata: 附加元数据字典
            description: 人类可读的事件描述
            ip_address: 操作者 IP 地址

        Returns:
            审计日志记录 ID
        """
        db = get_session()
        try:
            log = AuditLog(
                event_type=event_type,
                actor=actor or "",
                action=action or "",
                resource=resource or "",
                extra_data=metadata or {},
                description=description or "",
                ip_address=ip_address or "",
                created_at=datetime.utcnow(),
            )
            db.add(log)
            db.commit()
            db.refresh(log)
            return log.id
        except Exception:
            db.rollback()
            # 审计日志写入失败不应影响主流程
            return 0
        finally:
            db.close()

    # --------------------------------------------------------
    # 便捷方法
    # --------------------------------------------------------

    def log_server_register(
        self,
        server_name: str,
        actor: str = "system",
        server_id: Optional[int] = None,
        **kwargs,
    ) -> int:
        """记录服务器注册事件.

        Args:
            server_name: 服务器名称
            actor: 操作主体
            server_id: 服务器 ID
            **kwargs: 其他元数据

        Returns:
            日志记录 ID
        """
        metadata = {"server_name": server_name, **kwargs}
        if server_id is not None:
            metadata["server_id"] = server_id

        return self.log_event(
            event_type=EventType.SERVER_REGISTER,
            actor=actor,
            action="register",
            resource=f"server:{server_id}" if server_id else f"server:{server_name}",
            metadata=metadata,
            description=f"服务器注册: {server_name}",
        )

    def log_server_remove(
        self,
        server_name: str,
        actor: str = "system",
        server_id: Optional[int] = None,
        **kwargs,
    ) -> int:
        """记录服务器删除事件.

        Args:
            server_name: 服务器名称
            actor: 操作主体
            server_id: 服务器 ID
            **kwargs: 其他元数据

        Returns:
            日志记录 ID
        """
        metadata = {"server_name": server_name, **kwargs}
        if server_id is not None:
            metadata["server_id"] = server_id

        return self.log_event(
            event_type=EventType.SERVER_REMOVE,
            actor=actor,
            action="remove",
            resource=f"server:{server_id}" if server_id else f"server:{server_name}",
            metadata=metadata,
            description=f"服务器删除: {server_name}",
        )

    def log_tool_call(
        self,
        tool_name: str,
        actor: str = "api",
        status: str = "success",
        duration_ms: int = 0,
        **kwargs,
    ) -> int:
        """记录工具调用事件.

        Args:
            tool_name: 工具名称
            actor: 调用方
            status: 调用状态（success/failed）
            duration_ms: 耗时（毫秒）
            **kwargs: 其他元数据

        Returns:
            日志记录 ID
        """
        return self.log_event(
            event_type=EventType.TOOL_CALL,
            actor=actor,
            action="call",
            resource=f"tool:{tool_name}",
            metadata={
                "tool_name": tool_name,
                "status": status,
                "duration_ms": duration_ms,
                **kwargs,
            },
            description=f"工具调用: {tool_name} ({status})",
        )

    def log_api_key_create(
        self,
        key_name: str,
        actor: str = "system",
        key_id: Optional[int] = None,
        **kwargs,
    ) -> int:
        """记录 API Key 创建事件.

        Args:
            key_name: Key 名称
            actor: 操作主体
            key_id: Key ID
            **kwargs: 其他元数据

        Returns:
            日志记录 ID
        """
        metadata = {"key_name": key_name, **kwargs}
        if key_id is not None:
            metadata["key_id"] = key_id

        return self.log_event(
            event_type=EventType.API_KEY_CREATE,
            actor=actor,
            action="create",
            resource=f"api_key:{key_id}" if key_id else f"api_key:{key_name}",
            metadata=metadata,
            description=f"API Key 创建: {key_name}",
        )

    def log_api_key_delete(
        self,
        key_name: str,
        actor: str = "system",
        key_id: Optional[int] = None,
        **kwargs,
    ) -> int:
        """记录 API Key 删除事件.

        Args:
            key_name: Key 名称
            actor: 操作主体
            key_id: Key ID
            **kwargs: 其他元数据

        Returns:
            日志记录 ID
        """
        metadata = {"key_name": key_name, **kwargs}
        if key_id is not None:
            metadata["key_id"] = key_id

        return self.log_event(
            event_type=EventType.API_KEY_DELETE,
            actor=actor,
            action="delete",
            resource=f"api_key:{key_id}" if key_id else f"api_key:{key_name}",
            metadata=metadata,
            description=f"API Key 删除: {key_name}",
        )

    def log_config_change(
        self,
        config_key: str,
        old_value: Any = None,
        new_value: Any = None,
        actor: str = "system",
        **kwargs,
    ) -> int:
        """记录配置变更事件.

        Args:
            config_key: 配置项键名
            old_value: 旧值
            new_value: 新值
            actor: 操作主体
            **kwargs: 其他元数据

        Returns:
            日志记录 ID
        """
        return self.log_event(
            event_type=EventType.CONFIG_CHANGE,
            actor=actor,
            action="update",
            resource=f"config:{config_key}",
            metadata={
                "config_key": config_key,
                "old_value": str(old_value) if old_value is not None else "",
                "new_value": str(new_value) if new_value is not None else "",
                **kwargs,
            },
            description=f"配置变更: {config_key}",
        )

    # --------------------------------------------------------
    # 查询日志
    # --------------------------------------------------------

    def query_logs(
        self,
        event_type: Optional[str] = None,
        actor: Optional[str] = None,
        action: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[AuditLog], int]:
        """查询审计日志.

        支持按事件类型、操作主体、动作、时间范围过滤，分页返回。

        Args:
            event_type: 按事件类型过滤
            actor: 按操作主体过滤（模糊匹配）
            action: 按操作动作过滤
            start_time: 开始时间（包含）
            end_time: 结束时间（包含）
            page: 页码，从 1 开始
            page_size: 每页数量

        Returns:
            (日志列表, 总数) 元组
        """
        db = get_session()
        try:
            query = db.query(AuditLog)

            if event_type:
                query = query.filter(AuditLog.event_type == event_type)
            if actor:
                query = query.filter(AuditLog.actor.like(f"%{actor}%"))
            if action:
                query = query.filter(AuditLog.action == action)
            if start_time:
                query = query.filter(AuditLog.created_at >= start_time)
            if end_time:
                query = query.filter(AuditLog.created_at <= end_time)

            total = query.count()
            logs = (
                query.order_by(AuditLog.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )

            return logs, total
        finally:
            db.close()

    def get_recent_logs(self, limit: int = 50) -> List[AuditLog]:
        """获取最近的审计日志.

        Args:
            limit: 返回数量限制

        Returns:
            审计日志列表（按时间倒序）
        """
        db = get_session()
        try:
            return (
                db.query(AuditLog)
                .order_by(AuditLog.created_at.desc())
                .limit(limit)
                .all()
            )
        finally:
            db.close()

    def get_stats(self, days: int = 7) -> Dict[str, Any]:
        """获取审计日志统计数据.

        Args:
            days: 统计天数

        Returns:
            统计信息字典
        """
        db = get_session()
        try:
            from datetime import timedelta
            from sqlalchemy import func

            start_date = datetime.utcnow() - timedelta(days=days)

            # 按事件类型统计
            type_stats = (
                db.query(
                    AuditLog.event_type,
                    func.count(AuditLog.id).label("count"),
                )
                .filter(AuditLog.created_at >= start_date)
                .group_by(AuditLog.event_type)
                .all()
            )

            # 总数
            total = db.query(AuditLog).filter(AuditLog.created_at >= start_date).count()

            event_counts = {row.event_type: row.count for row in type_stats}

            return {
                "total_events": total,
                "days": days,
                "event_type_counts": event_counts,
            }
        except Exception:
            return {
                "total_events": 0,
                "days": days,
                "event_type_counts": {},
            }
        finally:
            db.close()


# ============================================================
# 单例实例
# ============================================================

audit_logger = AuditLogger()
