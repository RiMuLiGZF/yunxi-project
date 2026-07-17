"""
云汐 M9 开发者工坊 - 数据模型模块
使用 SQLAlchemy 定义数据库表结构
"""

import sys
import os
import time
import logging
from datetime import datetime
from typing import Optional, List
from pathlib import Path

# 确保当前目录（backend）在 sys.path 最前面，避免与 shared/config.py 等模块名冲突
_backend_dir = Path(__file__).resolve().parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))
else:
    # 如果已存在，移到最前面以确保优先级
    sys.path.remove(str(_backend_dir))
    sys.path.insert(0, str(_backend_dir))

# 兼容相对导入和直接运行
try:
    from .config import get_settings
except ImportError:
    from config import get_settings

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Text,
    DateTime,
    Boolean,
    Float,
    JSON,
    Index,
)
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool

# 慢查询告警日志
slow_query_logger = logging.getLogger("m9.slow_query")


# ===== 数据库初始化 =====
settings = get_settings()
# P2-2: SQLite 使用 StaticPool（单连接复用），避免多连接并发写入问题
engine = create_engine(
    settings.get_db_url(),
    connect_args={"check_same_thread": False},  # SQLite 多线程支持
    echo=settings.debug,
    poolclass=StaticPool,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """获取数据库会话（依赖注入用，含慢查询检测）"""
    db = SessionLocal()
    try:
        # P2-2: 记录开始时间用于慢查询检测
        start = time.time()
        yield db
        elapsed = time.time() - start
        if elapsed > 1.0:  # 超过1秒视为慢查询
            slow_query_logger.warning(f"慢查询检测: 会话存在 {elapsed:.2f}s")
    finally:
        db.close()


def init_db():
    """初始化数据库，创建所有表"""
    Base.metadata.create_all(bind=engine)


# ===== 数据模型定义 =====

class WorkspaceProject(Base):
    """工作区项目模型"""
    __tablename__ = "workspace_projects"

    id = Column(Integer, primary_key=True, index=True, comment="项目ID")
    name = Column(String(255), nullable=False, comment="项目名称")
    path = Column(String(1024), nullable=False, unique=True, comment="项目路径")
    description = Column(Text, default="", comment="项目描述")
    icon = Column(String(255), default="folder", comment="项目图标")
    last_opened = Column(DateTime, nullable=True, comment="最后打开时间")
    tags = Column(JSON, default=list, comment="标签列表")
    open_count = Column(Integer, default=0, comment="打开次数")
    total_dev_time = Column(Float, default=0.0, comment="累计开发时长（分钟）")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间")

    # P2-2: 添加查询索引
    __table_args__ = (
        Index('idx_wp_path', 'path'),
        Index('idx_wp_name', 'name'),
        Index('idx_wp_last_opened', 'last_opened'),
    )

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "name": self.name,
            "path": self.path,
            "description": self.description,
            "icon": self.icon,
            "last_opened": self.last_opened.isoformat() if self.last_opened else None,
            "tags": self.tags or [],
            "open_count": self.open_count,
            "total_dev_time": round(self.total_dev_time, 2),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class VSCodeSession(Base):
    """VS Code 会话记录模型"""
    __tablename__ = "vscode_sessions"

    id = Column(Integer, primary_key=True, index=True, comment="会话ID")
    pid = Column(Integer, nullable=False, comment="进程ID")
    project_path = Column(String(1024), nullable=True, comment="关联项目路径")
    start_time = Column(DateTime, default=datetime.now, comment="开始时间")
    end_time = Column(DateTime, nullable=True, comment="结束时间")
    status = Column(String(50), default="running", comment="状态：running/closed/crashed")
    window_title = Column(String(255), default="", comment="窗口标题")

    # P2-2: 添加查询索引
    __table_args__ = (
        Index('idx_vs_status', 'status'),
        Index('idx_vs_project_path', 'project_path'),
        Index('idx_vs_start_time', 'start_time'),
    )

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "pid": self.pid,
            "project_path": self.project_path,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "status": self.status,
            "window_title": self.window_title,
        }


class MCPTool(Base):
    """MCP 工具注册模型"""
    __tablename__ = "mcp_tools"

    id = Column(Integer, primary_key=True, index=True, comment="工具ID")
    name = Column(String(255), nullable=False, unique=True, comment="工具名称")
    description = Column(Text, default="", comment="工具描述")
    endpoint = Column(String(1024), default="", comment="调用端点")
    category = Column(String(100), default="general", comment="工具分类")
    enabled = Column(Boolean, default=True, comment="是否启用")
    input_schema = Column(JSON, default=dict, comment="输入参数 Schema")
    registered_at = Column(DateTime, default=datetime.now, comment="注册时间")

    # P2-2: 添加查询索引
    __table_args__ = (
        Index('idx_mt_category', 'category'),
        Index('idx_mt_enabled', 'enabled'),
    )

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "endpoint": self.endpoint,
            "category": self.category,
            "enabled": self.enabled,
            "input_schema": self.input_schema or {},
            "registered_at": self.registered_at.isoformat() if self.registered_at else None,
        }


class DevActivity(Base):
    """开发活动日志模型"""
    __tablename__ = "dev_activities"

    id = Column(Integer, primary_key=True, index=True, comment="活动ID")
    project = Column(String(255), default="", comment="关联项目")
    activity_type = Column(String(100), nullable=False, comment="活动类型：coding/building/debugging/meeting")
    duration = Column(Float, default=0.0, comment="持续时长（分钟）")
    description = Column(Text, default="", comment="活动描述")
    timestamp = Column(DateTime, default=datetime.now, comment="活动时间")
    meta_data = Column(JSON, default=dict, comment="附加数据")

    # P2-2: 添加查询索引
    __table_args__ = (
        Index('idx_da_project', 'project'),
        Index('idx_da_timestamp', 'timestamp'),
        Index('idx_da_activity_type', 'activity_type'),
    )

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "project": self.project,
            "activity_type": self.activity_type,
            "duration": round(self.duration, 2),
            "description": self.description,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "meta_data": self.meta_data or {},
        }


# ===== P1b: 工作开发相关表（M8 迁移） =====

class WorkProject(Base):
    """工作项目模型（M8 work_projects 迁移）"""
    __tablename__ = "work_projects"

    id = Column(Integer, primary_key=True, index=True, comment="主键ID")
    project_id = Column(Integer, index=True, comment="项目业务ID（M8原始ID）")
    name = Column(String(200), default="", comment="项目名称")
    description = Column(Text, default="", comment="项目描述")
    status = Column(String(20), default="active", comment="状态：active/planning/completed/archived")
    progress = Column(Integer, default=0, comment="进度百分比")
    repo_url = Column(String(500), default="", comment="代码仓库地址")
    language = Column(String(50), default="", comment="主要编程语言")
    file_count = Column(Integer, default=0, comment="文件数量")
    line_count = Column(Integer, default=0, comment="代码行数")
    commit_count = Column(Integer, default=0, comment="提交次数")
    user_id = Column(String(128), index=True, comment="所属用户ID")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间")

    __table_args__ = (
        Index('idx_wp_user_id', 'user_id'),
        Index('idx_wp_status', 'status'),
        Index('idx_wp_project_id', 'project_id', unique=True),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "progress": self.progress,
            "repo_url": self.repo_url,
            "language": self.language,
            "file_count": self.file_count,
            "line_count": self.line_count,
            "commit_count": self.commit_count,
            "user_id": self.user_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class WorkTask(Base):
    """工作任务模型（M8 work_tasks 迁移）"""
    __tablename__ = "work_tasks"

    id = Column(Integer, primary_key=True, index=True, comment="主键ID")
    task_id = Column(Integer, index=True, comment="任务业务ID（M8原始ID）")
    title = Column(String(255), default="", comment="任务标题")
    description = Column(Text, default="", comment="任务描述")
    status = Column(String(20), default="todo", comment="状态：todo/in_progress/done/cancelled")
    priority = Column(String(20), default="medium", comment="优先级：low/medium/high/urgent")
    project_id = Column(Integer, index=True, comment="关联项目ID")
    assignee = Column(String(100), default="", comment="负责人")
    due_date = Column(String(20), nullable=True, comment="截止日期")
    user_id = Column(String(128), index=True, comment="所属用户ID")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间")

    __table_args__ = (
        Index('idx_wt_user_id', 'user_id'),
        Index('idx_wt_status', 'status'),
        Index('idx_wt_project_id', 'project_id'),
        Index('idx_wt_task_id', 'task_id', unique=True),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "priority": self.priority,
            "project_id": self.project_id,
            "assignee": self.assignee,
            "due_date": self.due_date,
            "user_id": self.user_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class WorkCommit(Base):
    """代码提交记录模型（M8 work_commits 迁移）"""
    __tablename__ = "work_commits"

    id = Column(Integer, primary_key=True, index=True, comment="主键ID")
    commit_id = Column(Integer, index=True, comment="提交业务ID（M8原始ID）")
    hash = Column(String(64), default="", comment="提交哈希")
    message = Column(Text, default="", comment="提交信息")
    author = Column(String(100), default="", comment="作者")
    branch = Column(String(100), default="", comment="分支")
    project_id = Column(Integer, index=True, comment="关联项目ID")
    additions = Column(Integer, default=0, comment="新增行数")
    deletions = Column(Integer, default=0, comment="删除行数")
    files_changed = Column(Integer, default=0, comment="变更文件数")
    committed_at = Column(DateTime, comment="提交时间")
    user_id = Column(String(128), index=True, comment="所属用户ID")

    __table_args__ = (
        Index('idx_wc_user_id', 'user_id'),
        Index('idx_wc_project_id', 'project_id'),
        Index('idx_wc_committed_at', 'committed_at'),
        Index('idx_wc_commit_id', 'commit_id', unique=True),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "commit_id": self.commit_id,
            "hash": self.hash,
            "message": self.message,
            "author": self.author,
            "branch": self.branch,
            "project_id": self.project_id,
            "additions": self.additions,
            "deletions": self.deletions,
            "files_changed": self.files_changed,
            "committed_at": self.committed_at.isoformat() if self.committed_at else None,
            "user_id": self.user_id,
        }


class WorkDevCodeUsage(Base):
    """代码开发用量模型（M8 work_dev_code_usage 迁移）"""
    __tablename__ = "work_dev_code_usage"

    id = Column(Integer, primary_key=True, index=True, comment="主键ID")
    usage_id = Column(Integer, index=True, comment="用量业务ID（M8原始ID）")
    action_type = Column(String(20), default="", comment="动作类型")
    operation_type = Column(String(20), default="", comment="操作类型")
    language = Column(String(50), default="", comment="编程语言")
    tokens_used = Column(Integer, default=0, comment="消耗Token数")
    project_id = Column(Integer, index=True, comment="关联项目ID")
    is_fallback = Column(Boolean, default=False, comment="是否为降级模式")
    user_id = Column(String(128), index=True, comment="所属用户ID")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")

    __table_args__ = (
        Index('idx_wdcu_user_id', 'user_id'),
        Index('idx_wdcu_project_id', 'project_id'),
        Index('idx_wdcu_created_at', 'created_at'),
        Index('idx_wdcu_usage_id', 'usage_id', unique=True),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "usage_id": self.usage_id,
            "action_type": self.action_type,
            "operation_type": self.operation_type,
            "language": self.language,
            "tokens_used": self.tokens_used,
            "project_id": self.project_id,
            "is_fallback": self.is_fallback,
            "user_id": self.user_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ===== Pydantic 响应模型（如果可用） =====
try:
    from pydantic import BaseModel, Field
    from typing import List as PydanticList

    class ProjectCreate(BaseModel):
        """项目创建请求"""
        name: str
        path: str
        description: str = ""
        icon: str = "folder"
        tags: PydanticList[str] = Field(default_factory=list)

    class ProjectUpdate(BaseModel):
        """项目更新请求"""
        name: Optional[str] = None
        description: Optional[str] = None
        icon: Optional[str] = None
        tags: Optional[PydanticList[str]] = None

    class MCPToolCall(BaseModel):
        """MCP 工具调用请求"""
        tool_name: str
        arguments: dict = Field(default_factory=dict)

    class VSCodeOpenRequest(BaseModel):
        """VS Code 打开请求"""
        path: Optional[str] = None
        file: Optional[str] = None
        new_window: bool = False

except ImportError:
    # 如果没有 pydantic，跳过响应模型定义
    pass


# 兼容直接运行：初始化数据库
if __name__ == "__main__":
    init_db()
    print(f"数据库已初始化: {settings.db_path}")
    print("已创建表:")
    for table in Base.metadata.tables:
        print(f"  - {table}")