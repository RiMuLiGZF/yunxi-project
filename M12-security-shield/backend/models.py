"""
云汐 M12 安全盾 - 数据模型模块
使用 SQLAlchemy 定义数据库表结构，包含 5 张核心表：
1. security_events  - 安全事件表
2. api_keys         - API 密钥表
3. ip_blacklist     - IP 黑名单表
4. waf_rules        - WAF 规则表
5. audit_logs       - 审计日志表
"""

import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

# 兼容相对导入和直接运行
try:
    from .database import Base, engine, SessionLocal, init_db
except ImportError:
    from database import Base, engine, SessionLocal, init_db

from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    Boolean,
    JSON,
    Index,
)


# ===========================================================================
# 工具函数：统一响应格式
# ===========================================================================

def make_response(data: Any = None, code: int = 0, message: str = "success") -> dict:
    """
    构造统一格式的 API 响应

    Args:
        data: 响应数据
        code: 状态码，0 表示成功
        message: 状态消息

    Returns:
        统一格式的响应字典 {code, message, data}
    """
    return {
        "code": code,
        "message": message,
        "data": data,
    }


def make_error_response(message: str, code: int = -1, data: Any = None) -> dict:
    """
    构造错误响应

    Args:
        message: 错误消息
        code: 错误码
        data: 附加数据

    Returns:
        错误响应字典
    """
    return make_response(data=data, code=code, message=message)


# ===========================================================================
# 数据模型定义
# ===========================================================================

class SecurityEvent(Base):
    """
    安全事件表

    记录所有安全相关事件，包括攻击拦截、登录失败、权限异常、
    WAF 触发、IP 封禁等安全事件。
    """
    __tablename__ = "security_events"

    id = Column(Integer, primary_key=True, index=True, comment="事件ID")
    event_type = Column(String(100), index=True, default="", comment="事件类型：waf_block/auth_fail/ip_ban/...")
    severity = Column(String(20), index=True, default="info", comment="严重级别：info/low/medium/high/critical")
    source_ip = Column(String(50), index=True, default="", comment="来源 IP 地址")
    target_path = Column(String(500), default="", comment="目标路径/接口")
    method = Column(String(10), default="", comment="请求方法")
    description = Column(Text, default="", comment="事件描述")
    rule_name = Column(String(200), default="", comment="触发的规则名称")
    user_agent = Column(String(500), default="", comment="用户代理")
    status = Column(String(20), default="active", comment="事件状态：active/resolved/ignored")
    resolved_by = Column(String(100), default="", comment="处理人")
    resolved_at = Column(DateTime, nullable=True, comment="处理时间")
    resolution_note = Column(Text, default="", comment="处理说明")
    extra_data = Column(JSON, default=dict, comment="附加数据（JSON）")
    created_at = Column(DateTime, default=datetime.now, index=True, comment="创建时间")

    __table_args__ = (
        Index("idx_security_events_created_at", "created_at"),
        Index("idx_security_events_type_severity", "event_type", "severity"),
    )

    def to_dict(self) -> dict:
        """转换为字典

        Returns:
            事件详情字典
        """
        return {
            "id": self.id,
            "event_type": self.event_type,
            "severity": self.severity,
            "source_ip": self.source_ip,
            "target_path": self.target_path,
            "method": self.method,
            "description": self.description,
            "rule_name": self.rule_name,
            "user_agent": self.user_agent,
            "status": self.status,
            "resolved_by": self.resolved_by,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolution_note": self.resolution_note,
            "extra_data": self.extra_data or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ApiKey(Base):
    """
    API 密钥表

    管理 API 密钥，支持权限分配、过期时间、使用统计。
    用于服务间调用的身份认证。
    """
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True, comment="密钥ID")
    key_name = Column(String(200), default="", comment="密钥名称/标识")
    key_hash = Column(String(255), unique=True, index=True, nullable=False, comment="密钥哈希值")
    key_prefix = Column(String(50), default="", comment="密钥前缀（用于展示）")
    owner = Column(String(200), default="", comment="所有者/使用方")
    roles = Column(JSON, default=list, comment="角色权限列表")
    scopes = Column(JSON, default=list, comment="权限范围列表")
    rate_limit = Column(Integer, default=0, comment="自定义速率限制（0=使用默认）")
    call_count = Column(Integer, default=0, comment="累计调用次数")
    last_used_at = Column(DateTime, nullable=True, comment="最后使用时间")
    expires_at = Column(DateTime, nullable=True, comment="过期时间（NULL=永不过期）")
    is_active = Column(Boolean, default=True, comment="是否启用")
    created_by = Column(String(100), default="system", comment="创建人")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")
    description = Column(Text, default="", comment="描述说明")

    __table_args__ = (
        Index("idx_api_keys_active", "is_active"),
    )

    def to_dict(self, include_hash: bool = False) -> dict:
        """转换为字典

        Args:
            include_hash: 是否包含密钥哈希（默认不包含，安全考虑）

        Returns:
            密钥信息字典
        """
        result = {
            "id": self.id,
            "key_name": self.key_name,
            "key_prefix": self.key_prefix,
            "owner": self.owner,
            "roles": self.roles or [],
            "scopes": self.scopes or [],
            "rate_limit": self.rate_limit,
            "call_count": self.call_count,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "is_active": self.is_active,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "description": self.description,
        }
        if include_hash:
            result["key_hash"] = self.key_hash
        return result


class IpBlacklist(Base):
    """
    IP 黑名单表

    管理被封禁的 IP 地址，支持 IP 段、自动解封时间、封禁原因。
    """
    __tablename__ = "ip_blacklist"

    id = Column(Integer, primary_key=True, index=True, comment="记录ID")
    ip_address = Column(String(50), unique=True, index=True, nullable=False, comment="IP 地址或 CIDR 段")
    ip_type = Column(String(20), default="single", comment="IP 类型：single/cidr/range")
    reason = Column(Text, default="", comment="封禁原因")
    severity = Column(String(20), default="medium", comment="威胁级别：low/medium/high/critical")
    source = Column(String(100), default="manual", comment="来源：manual/auto/waf/import")
    banned_by = Column(String(100), default="system", comment="封禁操作人")
    banned_at = Column(DateTime, default=datetime.now, index=True, comment="封禁时间")
    expires_at = Column(DateTime, nullable=True, comment="过期时间（NULL=永久）")
    is_active = Column(Boolean, default=True, comment="是否生效")
    hit_count = Column(Integer, default=0, comment="命中次数")
    last_hit_at = Column(DateTime, nullable=True, comment="最后命中时间")
    extra_data = Column(JSON, default=dict, comment="附加数据")

    __table_args__ = (
        Index("idx_ip_blacklist_active", "is_active"),
        Index("idx_ip_blacklist_expires", "expires_at"),
    )

    def to_dict(self) -> dict:
        """转换为字典

        Returns:
            黑名单记录字典
        """
        return {
            "id": self.id,
            "ip_address": self.ip_address,
            "ip_type": self.ip_type,
            "reason": self.reason,
            "severity": self.severity,
            "source": self.source,
            "banned_by": self.banned_by,
            "banned_at": self.banned_at.isoformat() if self.banned_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "is_active": self.is_active,
            "hit_count": self.hit_count,
            "last_hit_at": self.last_hit_at.isoformat() if self.last_hit_at else None,
            "extra_data": self.extra_data or {},
        }


class WafRule(Base):
    """
    WAF 规则表

    WAF 防护规则管理，支持规则类型、匹配模式、严重级别。
    """
    __tablename__ = "waf_rules"

    id = Column(Integer, primary_key=True, index=True, comment="规则ID")
    rule_name = Column(String(200), unique=True, nullable=False, comment="规则名称")
    rule_type = Column(String(50), index=True, default="custom", comment="规则类型：sql_injection/xss/csrf/command_injection/path_traversal/custom")
    category = Column(String(50), default="", comment="规则分类")
    pattern = Column(Text, nullable=False, comment="匹配规则（正则表达式或模式字符串）")
    match_target = Column(String(50), default="query", comment="匹配目标：query/body/path/header/all")
    severity = Column(String(20), default="medium", comment="严重级别：low/medium/high/critical")
    action = Column(String(20), default="block", comment="触发动作：block/log/challenge")
    description = Column(Text, default="", comment="规则描述")
    is_builtin = Column(Boolean, default=False, comment="是否内置规则")
    is_active = Column(Boolean, default=True, comment="是否启用")
    hit_count = Column(Integer, default=0, comment="命中次数")
    last_hit_at = Column(DateTime, nullable=True, comment="最后命中时间")
    created_by = Column(String(100), default="system", comment="创建人")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间")

    __table_args__ = (
        Index("idx_waf_rules_type_active", "rule_type", "is_active"),
    )

    def to_dict(self) -> dict:
        """转换为字典

        Returns:
            规则详情字典
        """
        return {
            "id": self.id,
            "rule_name": self.rule_name,
            "rule_type": self.rule_type,
            "category": self.category,
            "pattern": self.pattern,
            "match_target": self.match_target,
            "severity": self.severity,
            "action": self.action,
            "description": self.description,
            "is_builtin": self.is_builtin,
            "is_active": self.is_active,
            "hit_count": self.hit_count,
            "last_hit_at": self.last_hit_at.isoformat() if self.last_hit_at else None,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class TokenBlacklist(Base):
    """
    Token 黑名单表

    管理已登出或失效的 JWT Token，防止被重复使用。
    支持按过期时间自动清理。
    """
    __tablename__ = "token_blacklist"

    token_jti = Column(String(255), primary_key=True, index=True, comment="Token JTI")
    token_hash = Column(String(255), nullable=False, comment="Token 哈希")
    expired_at = Column(DateTime, nullable=False, comment="过期时间")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")

    __table_args__ = (
        Index("idx_token_blacklist_expired_at", "expired_at"),
    )

    def to_dict(self) -> dict:
        """转换为字典

        Returns:
            黑名单记录字典
        """
        return {
            "token_jti": self.token_jti,
            "token_hash": self.token_hash,
            "expired_at": self.expired_at.isoformat() if self.expired_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AuditLog(Base):
    """
    审计日志表

    全量操作审计日志，支持按用户、模块、操作类型查询。
    记录所有重要操作的完整审计轨迹。
    """
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True, comment="日志ID")
    user_id = Column(String(100), index=True, default="", comment="用户ID")
    username = Column(String(200), default="", comment="用户名")
    role = Column(String(50), default="", comment="用户角色")
    module = Column(String(100), index=True, default="", comment="操作模块")
    action = Column(String(100), index=True, default="", comment="操作类型")
    resource_type = Column(String(100), default="", comment="资源类型")
    resource_id = Column(String(100), default="", comment="资源ID")
    description = Column(Text, default="", comment="操作描述")
    source_ip = Column(String(50), index=True, default="", comment="来源 IP")
    user_agent = Column(String(500), default="", comment="用户代理")
    request_method = Column(String(10), default="", comment="请求方法")
    request_path = Column(String(500), default="", comment="请求路径")
    request_params = Column(JSON, default=dict, comment="请求参数")
    response_status = Column(Integer, default=0, comment="响应状态码")
    response_data = Column(JSON, default=dict, comment="响应数据摘要")
    status = Column(String(20), default="success", comment="操作状态：success/failed/denied")
    error_message = Column(Text, default="", comment="错误信息")
    duration_ms = Column(Integer, default=0, comment="耗时（毫秒）")
    extra_data = Column(JSON, default=dict, comment="附加数据")
    created_at = Column(DateTime, default=datetime.now, index=True, comment="创建时间")

    __table_args__ = (
        Index("idx_audit_logs_created_at", "created_at"),
        Index("idx_audit_logs_user_module", "user_id", "module"),
    )

    def to_dict(self) -> dict:
        """转换为字典

        Returns:
            审计日志字典
        """
        return {
            "id": self.id,
            "user_id": self.user_id,
            "username": self.username,
            "role": self.role,
            "module": self.module,
            "action": self.action,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "description": self.description,
            "source_ip": self.source_ip,
            "user_agent": self.user_agent,
            "request_method": self.request_method,
            "request_path": self.request_path,
            "request_params": self.request_params or {},
            "response_status": self.response_status,
            "response_data": self.response_data or {},
            "status": self.status,
            "error_message": self.error_message,
            "duration_ms": self.duration_ms,
            "extra_data": self.extra_data or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ===========================================================================
# 兼容直接运行：初始化数据库
# ===========================================================================

if __name__ == "__main__":
    init_db()
    print("数据库已初始化")
    print("已创建表:")
    for table in Base.metadata.tables:
        print(f"  - {table}")
