"""聊天服务表模块.

包含会话、消息等 ORM 模型。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    JSON,
    String,
    Text,
)

from .base import Base


class ChatConversationDB(Base):
    """聊天服务 - 会话表."""

    __tablename__ = "chat_conversations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(String(64), nullable=False, unique=True, index=True)
    user_id = Column(String(128), nullable=False, default="default", index=True)
    title = Column(String(255), default="新对话")
    mode = Column(String(50), default="main-chat", index=True)
    message_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_chat_conv_user", "user_id"),
        Index("idx_chat_conv_updated", "user_id", "updated_at"),
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典."""
        return {
            "id": self.conversation_id,
            "conversation_id": self.conversation_id,
            "title": self.title,
            "mode": self.mode,
            "message_count": self.message_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ChatMessageDB(Base):
    """聊天服务 - 消息表."""

    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    message_id = Column(String(64), nullable=False, unique=True, index=True)
    conversation_id = Column(String(64), nullable=False, index=True)
    user_id = Column(String(128), nullable=False, default="default", index=True)
    role = Column(String(20), nullable=False, index=True)  # user/assistant/system
    content = Column(Text, nullable=False, default="")
    mode = Column(String(50), default="main-chat", index=True)
    model = Column(String(100), default="")
    tokens_used = Column(Integer, default=0)
    is_fallback = Column(Boolean, default=False)
    extra = Column(JSON, default=dict)  # 额外数据（如记忆引用、工具调用等）
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("idx_chat_msg_conv", "conversation_id", "created_at"),
        Index("idx_chat_msg_user", "user_id", "created_at"),
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典."""
        return {
            "id": self.message_id,
            "message_id": self.message_id,
            "conversation_id": self.conversation_id,
            "role": self.role,
            "content": self.content,
            "mode": self.mode,
            "model": self.model,
            "tokens_used": self.tokens_used,
            "is_fallback": self.is_fallback,
            "extra": self.extra or {},
            "timestamp": self.created_at.timestamp() if self.created_at else 0,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
