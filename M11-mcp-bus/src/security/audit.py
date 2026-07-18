"""M11 MCP Bus - 安全层 - 审计日志.

核心审计逻辑从 services/audit.py 抽离，
提供统一的审计日志接口，便于安全层统一管理。

注意：services/audit.py 保留为业务层封装，
核心逻辑下沉到 security/audit.py。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from ..db import Base, get_engine, get_session

try:
    from sqlalchemy import JSON, Column, DateTime, Index, Integer, String, Text
    _HAS_SQLALCHEMY = True
except ImportError:
    _HAS_SQLALCHEMY = False


# ============================================================
# 事件类型常量
# ============================================================

class AuditEventType:
    """审计事件类型常量."""

    # 服务器相关
    SERVER_REGISTER = "server_register"
    SERVER_REMOVE = "server_remove"
    SERVER_UPDATE = "server_update"
    SERVER_HEARTBEAT = "server_heartbeat"

    # 工具相关
    TOOL_CALL = "tool_call"
    TOOL_REFRESH = "tool_refresh"

    # API Key 相关
    API_KEY_CREATE = "api_key_create"
    API_KEY_DELETE = "api_key_delete"
    API_KEY_UPDATE = "api_key_update"
    API_KEY_USE = "api_key_use"

    # 配置相关
    CONFIG_CHANGE = "config_change"

    # 认证相关
    AUTH_SUCCESS = "auth_success"
    AUTH_FAILURE = "auth_failure"
    LOGIN = "login"
    LOGOUT = "logout"

    # 权限相关
    PERMISSION_DENIED = "permission_denied"

    # 限流相关
    RATE_LIMIT = "rate_limit"

    # 安全相关
    SECURITY_ALERT = "security_alert"


# 所有事件类型列表（用于校验）
ALL_AUDIT_EVENT_TYPES = [
    AuditEventType.SERVER_REGISTER,
    AuditEventType.SERVER_REMOVE,
    AuditEventType.SERVER_UPDATE,
    AuditEventType.SERVER_HEARTBEAT,
    AuditEventType.TOOL_CALL,
    AuditEventType.TOOL_REFRESH,
    AuditEventType.API_KEY_CREATE,
    AuditEventType.API_KEY_DELETE,
    AuditEventType.API_KEY_UPDATE,
    AuditEventType.API_KEY_USE,
    AuditEventType.CONFIG_CHANGE,
    AuditEventType.AUTH_SUCCESS,
    AuditEventType.AUTH_FAILURE,
    AuditEventType.LOGIN,
    AuditEventType.LOGOUT,
    AuditEventType.PERMISSION_DENIED,
    AuditEventType.RATE_LIMIT,
    AuditEventType.SECURITY_ALERT,
]


# ============================================================
# 审计日志表模型（可选：如果 SQLAlchemy 可用）
# ============================================================

if _HAS_SQLALCHEMY:

    class AuditLogEntry(Base):
        """审计日志表.

        记录系统中所有关键操作事件，用于安全审计和问题追溯。
        """

        __tablename__ = "audit_logs"

        id = Column(Integer, primary_key=True, autoincrement=True, index=True, comment="日志ID")
        event_type = Column(String(50), index=True, nullable=False, comment="事件类型")
        actor = Column(String(100), index=True, default="", comment="操作主体")
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
            """转换为字典."""
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

else:
    AuditLogEntry = None  # type: ignore


# ============================================================
# 审计日志服务
# ============================================================

class AuditLogger:
    """审计日志服务.

    提供审计事件记录和查询功能，所有事件持久化到数据库。
    支持按事件类型、操作主体、时间范围等多维度查询。

    设计原则:
    - 审计日志写入失败不应影响主流程
    - 所有敏感操作都应记录审计日志
    - 审计日志不可修改、不可删除
    """

    def __init__(self) -> None:
        """初始化审计日志服务."""
        self._ensure_table()

    def _ensure_table(self) -> None:
        """确保审计日志表存在."""
        if not _HAS_SQLALCHEMY or AuditLogEntry is None:
            return
        try:
            engine = get_engine()
            AuditLogEntry.__table__.create(bind=engine, checkfirst=True)
        except Exception:
            # 表可能已存在或数据库未初始化
            pass

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
            event_type: 事件类型（使用 AuditEventType 常量）
            actor: 操作主体（如用户名、API Key 名称、服务名）
            action: 具体操作动作（如 create, delete, update, call）
            resource: 操作的资源标识（如 server:123, tool:xxx）
            metadata: 附加元数据字典
            description: 人类可读的事件描述
            ip_address: 操作者 IP 地址

        Returns:
            审计日志记录 ID，失败返回 0
        """
        if not _HAS_SQLALCHEMY or AuditLogEntry is None:
            return 0

        db = get_session()
        try:
            log = AuditLogEntry(
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
            return log.id  # type: ignore
        except Exception:
            db.rollback()
            # 审计日志写入失败不应影响主流程
            return 0
        finally:
            db.close()

    # --------------------------------------------------------
    # 便捷方法：安全相关事件
    # --------------------------------------------------------

    def log_auth_success(
        self,
        actor: str = "",
        ip_address: str = "",
        **kwargs,
    ) -> int:
        """记录认证成功事件."""
        return self.log_event(
            event_type=AuditEventType.AUTH_SUCCESS,
            actor=actor,
            action="authenticate",
            resource="auth",
            metadata=kwargs,
            description=f"认证成功: {actor}",
            ip_address=ip_address,
        )

    def log_auth_failure(
        self,
        actor: str = "",
        reason: str = "",
        ip_address: str = "",
        **kwargs,
    ) -> int:
        """记录认证失败事件."""
        return self.log_event(
            event_type=AuditEventType.AUTH_FAILURE,
            actor=actor,
            action="authenticate",
            resource="auth",
            metadata={"reason": reason, **kwargs},
            description=f"认证失败: {actor} ({reason})",
            ip_address=ip_address,
        )

    def log_permission_denied(
        self,
        actor: str = "",
        permission: str = "",
        resource: str = "",
        ip_address: str = "",
        **kwargs,
    ) -> int:
        """记录权限拒绝事件."""
        return self.log_event(
            event_type=AuditEventType.PERMISSION_DENIED,
            actor=actor,
            action="denied",
            resource=resource,
            metadata={"permission": permission, **kwargs},
            description=f"权限拒绝: {actor} 需要 {permission}",
            ip_address=ip_address,
        )

    def log_rate_limit(
        self,
        actor: str = "",
        resource: str = "",
        limit: int = 0,
        ip_address: str = "",
        **kwargs,
    ) -> int:
        """记录限流触发事件."""
        return self.log_event(
            event_type=AuditEventType.RATE_LIMIT,
            actor=actor,
            action="rate_limited",
            resource=resource,
            metadata={"limit": limit, **kwargs},
            description=f"限流触发: {actor} (限制: {limit})",
            ip_address=ip_address,
        )

    def log_security_alert(
        self,
        severity: str = "warning",
        message: str = "",
        actor: str = "",
        ip_address: str = "",
        **kwargs,
    ) -> int:
        """记录安全告警事件."""
        return self.log_event(
            event_type=AuditEventType.SECURITY_ALERT,
            actor=actor,
            action="alert",
            resource="security",
            metadata={"severity": severity, "message": message, **kwargs},
            description=f"安全告警 [{severity}]: {message}",
            ip_address=ip_address,
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
    ) -> Tuple[List[Any], int]:
        """查询审计日志.

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
        if not _HAS_SQLALCHEMY or AuditLogEntry is None:
            return [], 0

        db = get_session()
        try:
            query = db.query(AuditLogEntry)

            if event_type:
                query = query.filter(AuditLogEntry.event_type == event_type)
            if actor:
                query = query.filter(AuditLogEntry.actor.like(f"%{actor}%"))
            if action:
                query = query.filter(AuditLogEntry.action == action)
            if start_time:
                query = query.filter(AuditLogEntry.created_at >= start_time)
            if end_time:
                query = query.filter(AuditLogEntry.created_at <= end_time)

            total = query.count()
            logs = (
                query.order_by(AuditLogEntry.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )

            return logs, total
        finally:
            db.close()

    def get_recent_logs(self, limit: int = 50) -> List[Any]:
        """获取最近的审计日志.

        Args:
            limit: 返回数量限制

        Returns:
            审计日志列表（按时间倒序）
        """
        if not _HAS_SQLALCHEMY or AuditLogEntry is None:
            return []

        db = get_session()
        try:
            return (
                db.query(AuditLogEntry)
                .order_by(AuditLogEntry.created_at.desc())
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
        if not _HAS_SQLALCHEMY or AuditLogEntry is None:
            return {"total_events": 0, "days": days, "event_type_counts": {}}

        db = get_session()
        try:
            from datetime import timedelta
            from sqlalchemy import func

            start_date = datetime.utcnow() - timedelta(days=days)

            # 按事件类型统计
            type_stats = (
                db.query(
                    AuditLogEntry.event_type,
                    func.count(AuditLogEntry.id).label("count"),
                )
                .filter(AuditLogEntry.created_at >= start_date)
                .group_by(AuditLogEntry.event_type)
                .all()
            )

            total = db.query(AuditLogEntry).filter(
                AuditLogEntry.created_at >= start_date
            ).count()

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
# 全局单例
# ============================================================

_audit_logger: Optional[AuditLogger] = None


def get_audit_logger() -> AuditLogger:
    """获取全局审计日志单例.

    Returns:
        AuditLogger 实例
    """
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger


__all__ = [
    # 事件类型
    "AuditEventType",
    "ALL_AUDIT_EVENT_TYPES",
    # 数据模型
    "AuditLogEntry",
    # 服务类
    "AuditLogger",
    "get_audit_logger",
]
