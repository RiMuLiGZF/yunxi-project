"""
M12 安全盾 - 标准 Repository 实现（基于 shared.data_access）
============================================================

使用 shared.data_access.SQLAlchemyRepository 重构的标准 Repository 层。
M12 原有模型直接使用 SQLAlchemy，没有 Repository 层，这里作为接入示范。

接入内容：
- 为 3 个核心模型（SecurityEvent/ApiKey/IpBlacklist）建立标准 Repository
- 继承 SQLAlchemyRepository 获得标准 CRUD + 分页 + 批量操作
- 演示 UnitOfWork 事务管理
- 演示软删除 Mixin 使用
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from shared.data_access import SQLAlchemyRepository, PaginationResult, SoftDeleteMixin

# 导入 M12 模型
try:
    from ..models import (
        SecurityEvent,
        ApiKey,
        IpBlacklist,
        WafRule,
        AuditLog,
    )
except ImportError:
    from models import (  # type: ignore
        SecurityEvent,
        ApiKey,
        IpBlacklist,
        WafRule,
        AuditLog,
    )


def _utc_now() -> datetime:
    """返回 UTC 当前时间"""
    return datetime.now(timezone.utc)


# ============================================================
# 安全事件 Repository
# ============================================================

class SecurityEventRepository(SQLAlchemyRepository[SecurityEvent]):
    """
    安全事件 Repository（标准实现）。

    封装安全事件的数据访问，提供标准 CRUD + 业务特定查询。
    """

    model_class = SecurityEvent

    def list_events(
        self,
        page: int = 1,
        page_size: int = 20,
        event_type: Optional[str] = None,
        severity: Optional[str] = None,
        source_ip: Optional[str] = None,
        status: Optional[str] = None,
    ) -> PaginationResult:
        """
        分页查询安全事件。

        Args:
            page: 页码
            page_size: 每页大小
            event_type: 按事件类型过滤
            severity: 按严重级别过滤
            source_ip: 按来源 IP 过滤
            status: 按状态过滤

        Returns:
            分页结果
        """
        query = self.query()

        if event_type:
            query = query.filter(event_type=event_type)
        if severity:
            query = query.filter(severity=severity)
        if source_ip:
            query = query.filter(source_ip=source_ip)
        if status:
            query = query.filter(status=status)

        query = query.order_by("created_at", ascending=False)
        return query.paginate(page=page, page_size=page_size)

    def resolve_event(
        self,
        event_id: int,
        resolved_by: str = "system",
        resolution_note: str = "",
    ) -> bool:
        """
        处理/解决安全事件。

        Args:
            event_id: 事件 ID
            resolved_by: 处理人
            resolution_note: 处理说明

        Returns:
            是否成功
        """
        event = self.get_by_id(event_id)
        if not event:
            return False
        event.status = "resolved"
        event.resolved_by = resolved_by
        event.resolved_at = _utc_now()
        event.resolution_note = resolution_note
        self._session.flush()
        return True

    def get_stats(self) -> Dict[str, Any]:
        """
        获取安全事件统计。

        Returns:
            统计字典
        """
        total = self.count()
        active = self.count(status="active")
        resolved = self.count(status="resolved")

        # 按严重级别统计
        by_severity = {
            "critical": self.count(severity="critical"),
            "high": self.count(severity="high"),
            "medium": self.count(severity="medium"),
            "low": self.count(severity="low"),
            "info": self.count(severity="info"),
        }

        return {
            "total": total,
            "active": active,
            "resolved": resolved,
            "by_severity": by_severity,
        }


# ============================================================
# API 密钥 Repository
# ============================================================

class ApiKeyRepository(SQLAlchemyRepository[ApiKey]):
    """
    API 密钥 Repository（标准实现）。
    """

    model_class = ApiKey

    def get_by_key_hash(self, key_hash: str) -> Optional[ApiKey]:
        """
        按密钥哈希查找。

        Args:
            key_hash: 密钥哈希值

        Returns:
            密钥实例或 None
        """
        return self.get_by_field("key_hash", key_hash)

    def get_active_keys(self) -> List[ApiKey]:
        """获取所有启用的密钥"""
        return self.filter_by(is_active=True)

    def deactivate_key(self, key_id: int) -> bool:
        """
        停用密钥。

        Args:
            key_id: 密钥 ID

        Returns:
            是否成功
        """
        result = self.update(key_id, {"is_active": False})
        return result is not None

    def activate_key(self, key_id: int) -> bool:
        """
        启用密钥。

        Args:
            key_id: 密钥 ID

        Returns:
            是否成功
        """
        result = self.update(key_id, {"is_active": True})
        return result is not None

    def increment_usage(self, key_id: int) -> None:
        """
        增加使用计数。

        Args:
            key_id: 密钥 ID
        """
        key = self.get_by_id(key_id)
        if key:
            key.call_count += 1
            key.last_used_at = _utc_now()
            self._session.flush()

    def list_api_keys(
        self,
        page: int = 1,
        page_size: int = 20,
        is_active: Optional[bool] = None,
        owner: Optional[str] = None,
    ) -> PaginationResult:
        """分页查询 API 密钥"""
        query = self.query()

        if is_active is not None:
            query = query.filter(is_active=is_active)
        if owner:
            query = query.filter(owner=owner)

        query = query.order_by("created_at", ascending=False)
        return query.paginate(page=page, page_size=page_size)


# ============================================================
# IP 黑名单 Repository
# ============================================================

class IpBlacklistRepository(SQLAlchemyRepository[IpBlacklist]):
    """
    IP 黑名单 Repository（标准实现）。
    """

    model_class = IpBlacklist

    def is_ip_banned(self, ip_address: str) -> bool:
        """
        检查 IP 是否被封禁。

        Args:
            ip_address: IP 地址

        Returns:
            是否被封禁
        """
        record = self._session.query(IpBlacklist).filter(
            IpBlacklist.ip_address == ip_address,
            IpBlacklist.is_active == True,  # noqa: E712
        ).first()
        if not record:
            return False
        # 检查是否过期
        if record.expires_at and record.expires_at < _utc_now():
            return False
        return True

    def ban_ip(
        self,
        ip_address: str,
        reason: str = "",
        severity: str = "medium",
        source: str = "auto",
        banned_by: str = "system",
        expires_at: Optional[datetime] = None,
    ) -> IpBlacklist:
        """
        封禁 IP。

        Args:
            ip_address: IP 地址
            reason: 封禁原因
            severity: 威胁级别
            source: 来源
            banned_by: 操作人
            expires_at: 过期时间

        Returns:
            创建的封禁记录
        """
        # 检查是否已存在
        existing = self._session.query(IpBlacklist).filter(
            IpBlacklist.ip_address == ip_address
        ).first()

        if existing:
            existing.is_active = True
            existing.reason = reason
            existing.severity = severity
            existing.source = source
            existing.banned_by = banned_by
            existing.expires_at = expires_at
            existing.banned_at = _utc_now()
            self._session.flush()
            return existing

        return self.create({
            "ip_address": ip_address,
            "reason": reason,
            "severity": severity,
            "source": source,
            "banned_by": banned_by,
            "expires_at": expires_at,
            "is_active": True,
        })

    def unban_ip(self, ip_address: str) -> bool:
        """
        解封 IP。

        Args:
            ip_address: IP 地址

        Returns:
            是否成功
        """
        record = self._session.query(IpBlacklist).filter(
            IpBlacklist.ip_address == ip_address
        ).first()
        if not record:
            return False
        record.is_active = False
        self._session.flush()
        return True

    def list_active_bans(
        self,
        page: int = 1,
        page_size: int = 20,
        severity: Optional[str] = None,
    ) -> PaginationResult:
        """列出活跃的封禁记录"""
        query = self.query().filter(is_active=True)
        if severity:
            query = query.filter(severity=severity)
        query = query.order_by("banned_at", ascending=False)
        return query.paginate(page=page, page_size=page_size)

    def increment_hit(self, ip_address: str) -> None:
        """
        增加命中计数。

        Args:
            ip_address: IP 地址
        """
        record = self._session.query(IpBlacklist).filter(
            IpBlacklist.ip_address == ip_address
        ).first()
        if record:
            record.hit_count += 1
            record.last_hit_at = _utc_now()
            self._session.flush()


# ============================================================
# WAF 规则 Repository
# ============================================================

class WafRuleRepository(SQLAlchemyRepository[WafRule]):
    """
    WAF 规则 Repository（标准实现）。
    """

    model_class = WafRule

    def get_active_rules(self) -> List[WafRule]:
        """获取所有启用的规则"""
        return self.filter_by(is_active=True)

    def get_rules_by_type(self, rule_type: str) -> List[WafRule]:
        """按类型获取规则"""
        return self.filter_by(rule_type=rule_type, is_active=True)

    def toggle_rule(self, rule_id: int, is_active: bool) -> bool:
        """切换规则启用状态"""
        result = self.update(rule_id, {"is_active": is_active})
        return result is not None

    def increment_hit(self, rule_id: int) -> None:
        """增加规则命中次数"""
        rule = self.get_by_id(rule_id)
        if rule:
            rule.hit_count += 1
            rule.last_hit_at = _utc_now()
            self._session.flush()


# ============================================================
# 审计日志 Repository
# ============================================================

class AuditLogRepository(SQLAlchemyRepository[AuditLog]):
    """
    审计日志 Repository（标准实现）。
    """

    model_class = AuditLog

    def list_logs(
        self,
        page: int = 1,
        page_size: int = 20,
        module: Optional[str] = None,
        action: Optional[str] = None,
        user_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> PaginationResult:
        """分页查询审计日志"""
        query = self.query()

        if module:
            query = query.filter(module=module)
        if action:
            query = query.filter(action=action)
        if user_id:
            query = query.filter(user_id=user_id)
        if status:
            query = query.filter(status=status)

        query = query.order_by("created_at", ascending=False)
        return query.paginate(page=page, page_size=page_size)


# ============================================================
# M12 工作单元（Unit of Work）
# ============================================================

class M12UnitOfWork:
    """
    M12 工作单元。

    管理 M12 模块内多个 Repository 的事务协调。

    使用方式::

        from backend.repositories_v2 import M12UnitOfWork
        from backend.database import SessionLocal

        uow = M12UnitOfWork(SessionLocal)
        with uow as session:
            event_repo = uow.security_events
            key_repo = uow.api_keys
            # 多个操作在同一事务中
            event_repo.create({...})
            key_repo.create({...})
        # 自动提交或回滚
    """

    def __init__(self, session_factory: Any):
        """
        初始化工作单元。

        Args:
            session_factory: SQLAlchemy sessionmaker
        """
        self._session_factory = session_factory
        self._session: Optional[Session] = None

        # Repository 实例缓存
        self._security_events: Optional[SecurityEventRepository] = None
        self._api_keys: Optional[ApiKeyRepository] = None
        self._ip_blacklist: Optional[IpBlacklistRepository] = None
        self._waf_rules: Optional[WafRuleRepository] = None
        self._audit_logs: Optional[AuditLogRepository] = None

    def __enter__(self) -> "M12UnitOfWork":
        self._session = self._session_factory()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if self._session is None:
            return False
        if exc_type is not None:
            self._session.rollback()
        else:
            self._session.commit()
        self._session.close()
        self._session = None
        self._clear_repositories()
        return exc_type is None

    def _clear_repositories(self) -> None:
        self._security_events = None
        self._api_keys = None
        self._ip_blacklist = None
        self._waf_rules = None
        self._audit_logs = None

    @property
    def session(self) -> Session:
        """获取当前 session"""
        if self._session is None:
            raise RuntimeError("UnitOfWork is not active")
        return self._session

    # ---- Repository 访问属性 ----

    @property
    def security_events(self) -> SecurityEventRepository:
        if self._security_events is None:
            self._security_events = SecurityEventRepository(self.session)
        return self._security_events

    @property
    def api_keys(self) -> ApiKeyRepository:
        if self._api_keys is None:
            self._api_keys = ApiKeyRepository(self.session)
        return self._api_keys

    @property
    def ip_blacklist(self) -> IpBlacklistRepository:
        if self._ip_blacklist is None:
            self._ip_blacklist = IpBlacklistRepository(self.session)
        return self._ip_blacklist

    @property
    def waf_rules(self) -> WafRuleRepository:
        if self._waf_rules is None:
            self._waf_rules = WafRuleRepository(self.session)
        return self._waf_rules

    @property
    def audit_logs(self) -> AuditLogRepository:
        if self._audit_logs is None:
            self._audit_logs = AuditLogRepository(self.session)
        return self._audit_logs

    # ---- 便捷方法 ----

    def commit(self) -> None:
        """手动提交"""
        if self._session:
            self._session.commit()

    def rollback(self) -> None:
        """手动回滚"""
        if self._session:
            self._session.rollback()


# ============================================================
# 导出
# ============================================================

__all__ = [
    "SecurityEventRepository",
    "ApiKeyRepository",
    "IpBlacklistRepository",
    "WafRuleRepository",
    "AuditLogRepository",
    "M12UnitOfWork",
]
