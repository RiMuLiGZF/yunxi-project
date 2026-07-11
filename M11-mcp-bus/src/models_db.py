"""M11 MCP Bus - 数据库模型.

定义 MCP 服务、工具、调用记录、API Key 等核心数据结构的 SQLAlchemy 模型。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, JSON, DateTime, Index, ForeignKey
from sqlalchemy.orm import relationship

from .db import Base


class McpServer(Base):
    """MCP 服务注册表.

    存储所有已注册的 MCP 服务信息，包括传输类型、端点地址、健康状态等。
    """

    __tablename__ = "mcp_servers"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True, comment="服务ID")
    name = Column(String(100), unique=True, index=True, nullable=False, comment="服务名称")
    description = Column(Text, default="", comment="服务描述")
    transport_type = Column(String(20), default="http", comment="传输类型：http/sse/stdio")
    endpoint = Column(String(500), default="", comment="服务端点地址")
    status = Column(String(20), index=True, default="offline", comment="状态：online/offline")
    api_key = Column(String(200), default="", comment="服务鉴权密钥")
    health_check_url = Column(String(500), default="", comment="健康检查地址")
    last_heartbeat = Column(DateTime, nullable=True, index=True, comment="最后心跳时间")
    created_at = Column(DateTime, default=datetime.utcnow, index=True, comment="创建时间")

    # 关联：该服务下的工具列表
    tools = relationship("McpTool", back_populates="server", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_server_status_name", "status", "name"),
    )

    def to_dict(self) -> dict:
        """转换为字典."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "transport_type": self.transport_type,
            "endpoint": self.endpoint,
            "status": self.status,
            "health_check_url": self.health_check_url,
            "last_heartbeat": self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class McpTool(Base):
    """MCP 工具注册表.

    存储所有已注册 MCP 服务提供的工具清单，支持缓存与刷新。
    """

    __tablename__ = "mcp_tools"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True, comment="工具ID")
    server_id = Column(Integer, ForeignKey("mcp_servers.id", ondelete="CASCADE"), index=True, nullable=False, comment="所属服务ID")
    name = Column(String(200), index=True, nullable=False, comment="工具名称")
    description = Column(Text, default="", comment="工具描述")
    category = Column(String(50), index=True, default="general", comment="工具分类")
    input_schema = Column(JSON, default=dict, comment="输入参数 Schema(JSON)")
    cached_at = Column(DateTime, default=datetime.utcnow, comment="缓存时间")

    # 关联：所属服务
    server = relationship("McpServer", back_populates="tools")

    __table_args__ = (
        Index("ix_tool_server_name", "server_id", "name", unique=True),
        Index("ix_tool_category", "category"),
    )

    def to_dict(self, include_schema: bool = True) -> dict:
        """转换为字典.

        Args:
            include_schema: 是否包含完整的 input_schema
        """
        result = {
            "id": self.id,
            "server_id": self.server_id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "cached_at": self.cached_at.isoformat() if self.cached_at else None,
        }
        if include_schema:
            result["input_schema"] = self.input_schema or {}
        return result


class McpCall(Base):
    """MCP 调用记录表.

    记录每次工具调用的详细信息，用于审计和监控分析。
    """

    __tablename__ = "mcp_calls"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True, comment="调用ID")
    tool_name = Column(String(200), index=True, nullable=False, comment="被调用工具名")
    server_id = Column(Integer, index=True, nullable=True, comment="目标服务ID")
    consumer = Column(String(100), index=True, default="", comment="调用方标识")
    status = Column(String(20), index=True, default="success", comment="状态：success/failed")
    duration_ms = Column(Integer, default=0, comment="耗时（毫秒）")
    error_message = Column(Text, default="", comment="错误信息")
    request_snippet = Column(Text, default="", comment="请求摘要")
    response_snippet = Column(Text, default="", comment="响应摘要")
    created_at = Column(DateTime, default=datetime.utcnow, index=True, comment="创建时间")

    __table_args__ = (
        Index("ix_call_status_time", "status", "created_at"),
        Index("ix_call_tool_time", "tool_name", "created_at"),
    )

    def to_dict(self) -> dict:
        """转换为字典."""
        return {
            "id": self.id,
            "tool_name": self.tool_name,
            "server_id": self.server_id,
            "consumer": self.consumer,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "error_message": self.error_message,
            "request_snippet": self.request_snippet,
            "response_snippet": self.response_snippet,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ApiKey(Base):
    """API 密钥表.

    存储用于鉴权的 API Key，支持权限控制和限流。
    """

    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True, comment="密钥ID")
    key_hash = Column(String(128), unique=True, index=True, nullable=False, comment="密钥哈希")
    name = Column(String(100), default="", comment="密钥名称")
    permissions = Column(JSON, default=list, comment="权限列表(JSON)")
    rate_limit = Column(Integer, default=100, comment="限流阈值（次/分钟）")
    created_at = Column(DateTime, default=datetime.utcnow, index=True, comment="创建时间")
    expires_at = Column(DateTime, nullable=True, index=True, comment="过期时间")
    last_used_at = Column(DateTime, nullable=True, index=True, comment="最后使用时间")

    __table_args__ = (
        Index("ix_apikey_name", "name"),
    )

    def to_dict(self) -> dict:
        """转换为字典（不包含 key_hash 以保证安全）."""
        return {
            "id": self.id,
            "name": self.name,
            "permissions": self.permissions or [],
            "rate_limit": self.rate_limit,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
        }
