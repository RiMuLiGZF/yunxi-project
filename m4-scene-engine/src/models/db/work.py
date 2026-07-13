"""工作开发表模块.

包含项目、任务、提交记录、代码片段、开发会话、代码使用统计等 ORM 模型。
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


class WorkProjectDB(Base):
    """工作开发 - 项目表."""

    __tablename__ = "work_projects"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    project_id = Column(Integer, nullable=False, default=0, index=True, comment="项目ID（业务ID）")
    name = Column(String(200), nullable=False, default="", comment="项目名称")
    description = Column(Text, nullable=False, default="", comment="项目描述")
    status = Column(String(20), nullable=False, default="planning", index=True,
                    comment="状态：planning/active/completed/archived")
    progress = Column(Integer, nullable=False, default=0, comment="进度百分比 0-100")
    repo_url = Column(String(500), nullable=False, default="", comment="仓库地址")
    language = Column(String(50), nullable=False, default="python", comment="主要语言")
    category = Column(String(50), nullable=False, default="", index=True, comment="项目分类")
    file_count = Column(Integer, nullable=False, default=0, comment="文件数量")
    line_count = Column(Integer, nullable=False, default=0, comment="代码行数")
    commit_count = Column(Integer, nullable=False, default=0, comment="提交次数")
    user_id = Column(String(128), nullable=False, default="default", index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_work_proj_user", "user_id"),
        Index("idx_work_proj_status", "user_id", "status"),
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（兼容前端字段名）."""
        return {
            "id": self.project_id,
            "project_id": self.project_id,
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "progress": self.progress,
            "language": self.language,
            "category": self.category,
            "repo_url": self.repo_url,
            "file_count": self.file_count,
            "line_count": self.line_count,
            "commit_count": self.commit_count,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }


class WorkTaskDB(Base):
    """工作开发 - 任务表."""

    __tablename__ = "work_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    task_id = Column(Integer, nullable=False, default=0, index=True, comment="任务ID（业务ID）")
    title = Column(String(255), nullable=False, default="", comment="任务标题")
    description = Column(Text, nullable=False, default="", comment="任务描述")
    status = Column(String(20), nullable=False, default="todo", index=True,
                    comment="状态：todo/in_progress/review/done")
    priority = Column(String(20), nullable=False, default="medium", index=True,
                      comment="优先级：low/medium/high")
    project_id = Column(Integer, nullable=False, default=0, index=True, comment="所属项目ID")
    assignee = Column(String(100), nullable=False, default="", comment="负责人")
    due_date = Column(String(20), nullable=True, comment="截止日期")
    tags = Column(JSON, default=list, comment="标签列表")
    estimate_hours = Column(Integer, nullable=False, default=0, comment="预估工时（小时）")
    spent_hours = Column(Integer, nullable=False, default=0, comment="已用工时（小时）")
    user_id = Column(String(128), nullable=False, default="default", index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_work_task_user", "user_id"),
        Index("idx_work_task_status", "user_id", "status"),
        Index("idx_work_task_project", "user_id", "project_id"),
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（兼容前端字段名）."""
        return {
            "id": self.task_id,
            "task_id": self.task_id,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "priority": self.priority,
            "project_id": self.project_id,
            "assignee": self.assignee,
            "due_date": self.due_date,
            "tags": self.tags or [],
            "estimate_hours": self.estimate_hours,
            "spent_hours": self.spent_hours,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }


class WorkCommitDB(Base):
    """工作开发 - 提交记录表."""

    __tablename__ = "work_commits"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    commit_id = Column(Integer, nullable=False, default=0, index=True, comment="提交ID（业务ID）")
    hash = Column(String(64), nullable=False, default="", comment="提交哈希")
    message = Column(Text, nullable=False, default="", comment="提交信息")
    author = Column(String(100), nullable=False, default="", comment="作者")
    branch = Column(String(100), nullable=False, default="main", comment="分支")
    project_id = Column(Integer, nullable=False, default=0, index=True, comment="所属项目ID")
    additions = Column(Integer, nullable=False, default=0, comment="新增行数")
    deletions = Column(Integer, nullable=False, default=0, comment="删除行数")
    files_changed = Column(Integer, nullable=False, default=0, comment="变更文件数")
    committed_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    user_id = Column(String(128), nullable=False, default="default", index=True)

    __table_args__ = (
        Index("idx_work_commit_user", "user_id"),
        Index("idx_work_commit_project", "user_id", "project_id"),
        Index("idx_work_commit_time", "user_id", "committed_at"),
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（兼容前端字段名）."""
        return {
            "id": self.commit_id,
            "commit_id": self.commit_id,
            "hash": self.hash,
            "message": self.message,
            "author": self.author,
            "project_id": self.project_id,
            "branch": self.branch,
            "files_changed": self.files_changed,
            "insertions": self.additions,
            "deletions": self.deletions,
            "additions": self.additions,
            "created_at": self.committed_at.strftime("%Y-%m-%d %H:%M:%S") if self.committed_at else None,
            "committed_at": self.committed_at.strftime("%Y-%m-%d %H:%M:%S") if self.committed_at else None,
        }


class WorkCodeSnippetDB(Base):
    """工作开发 - 代码片段表."""

    __tablename__ = "work_code_snippets"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    snippet_id = Column(Integer, nullable=False, default=0, index=True, comment="片段ID（业务ID）")
    title = Column(String(200), nullable=False, default="", comment="片段标题")
    language = Column(String(50), nullable=False, default="python", index=True, comment="编程语言")
    code = Column(Text, nullable=False, default="", comment="代码内容")
    description = Column(Text, nullable=False, default="", comment="描述说明")
    tags = Column(JSON, default=list, comment="标签列表")
    is_favorite = Column(Boolean, nullable=False, default=False, comment="是否收藏")
    project_id = Column(Integer, nullable=False, default=0, index=True, comment="所属项目ID（0表示无）")
    user_id = Column(String(128), nullable=False, default="default", index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_work_snippet_user", "user_id"),
        Index("idx_work_snippet_lang", "user_id", "language"),
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典."""
        return {
            "id": self.snippet_id,
            "snippet_id": self.snippet_id,
            "title": self.title,
            "language": self.language,
            "code": self.code,
            "description": self.description,
            "tags": self.tags or [],
            "is_favorite": self.is_favorite,
            "project_id": self.project_id,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }


class WorkDevSessionDB(Base):
    """工作开发 - 开发会话表."""

    __tablename__ = "work_dev_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    session_id = Column(String(64), nullable=False, default="", unique=True, index=True, comment="会话ID")
    session_type = Column(String(30), nullable=False, default="code_chat", index=True,
                          comment="会话类型：code_chat/code_review/code_generate")
    title = Column(String(200), nullable=False, default="", comment="会话标题")
    language = Column(String(50), nullable=False, default="python", comment="编程语言")
    messages_json = Column(JSON, default=list, comment="消息列表（JSON）")
    project_id = Column(Integer, nullable=False, default=0, index=True, comment="关联项目ID")
    message_count = Column(Integer, nullable=False, default=0, comment="消息数量")
    user_id = Column(String(128), nullable=False, default="default", index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_work_session_user", "user_id"),
        Index("idx_work_session_type", "user_id", "session_type"),
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典."""
        return {
            "id": self.session_id,
            "session_id": self.session_id,
            "session_type": self.session_type,
            "title": self.title,
            "language": self.language,
            "project_id": self.project_id,
            "message_count": self.message_count,
            "messages": self.messages_json or [],
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }


class WorkCodeUsageDB(Base):
    """工作开发 - 代码使用统计表."""

    __tablename__ = "work_code_usage"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    usage_id = Column(Integer, nullable=False, default=0, index=True, comment="使用记录ID（业务ID）")
    action_type = Column(String(20), nullable=False, default="generate", index=True,
                         comment="操作类型：generate/chat/execute/complete")
    operation_type = Column(String(20), nullable=False, default="",
                            comment="操作子类型：generate/review/debug/optimize/refactor/explain/test")
    language = Column(String(50), nullable=False, default="python", comment="编程语言")
    tokens_used = Column(Integer, nullable=False, default=0, comment="消耗 Token 数（估算）")
    project_id = Column(Integer, nullable=False, default=0, index=True, comment="所属项目ID")
    is_fallback = Column(Boolean, nullable=False, default=False, comment="是否为 fallback 模板模式")
    user_id = Column(String(128), nullable=False, default="default", index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("idx_work_usage_user", "user_id"),
        Index("idx_work_usage_action", "user_id", "action_type"),
        Index("idx_work_usage_time", "user_id", "created_at"),
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典."""
        return {
            "id": self.usage_id,
            "usage_id": self.usage_id,
            "action_type": self.action_type,
            "operation_type": self.operation_type,
            "language": self.language,
            "tokens_used": self.tokens_used,
            "project_id": self.project_id,
            "is_fallback": self.is_fallback,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }
