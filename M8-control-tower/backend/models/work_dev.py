"""
M8 管理工作台 - 工作开发模型

包含 WorkProject, WorkTask, WorkCommit, WorkCodeUsage。
"""

from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, JSON, Float
from datetime import datetime

from .base import Base


class WorkProject(Base):
    """工作开发 - 项目表"""
    __tablename__ = "work_projects"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, index=True, comment="项目ID（业务ID）")
    name = Column(String(200), comment="项目名称")
    description = Column(Text, default="", comment="项目描述")
    status = Column(String(20), default="planning", comment="状态：planning/active/completed")
    progress = Column(Integer, default=0, comment="进度百分比")
    repo_url = Column(String(500), default="", comment="仓库地址")
    language = Column(String(50), default="python", comment="主要语言")
    file_count = Column(Integer, default=0, comment="文件数量")
    line_count = Column(Integer, default=0, comment="代码行数")
    commit_count = Column(Integer, default=0, comment="提交次数")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")
    user_id = Column(Integer, default=1, index=True, comment="用户ID")


class WorkTask(Base):
    """工作开发 - 任务表"""
    __tablename__ = "work_tasks"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, index=True, comment="任务ID（业务ID）")
    title = Column(String(255), comment="任务标题")
    description = Column(Text, default="", comment="任务描述")
    status = Column(String(20), default="todo", comment="状态：todo/in_progress/review/done")
    priority = Column(String(20), default="medium", comment="优先级：low/medium/high")
    project_id = Column(Integer, default=0, index=True, comment="所属项目ID")
    assignee = Column(String(100), default="", comment="负责人")
    due_date = Column(String(20), nullable=True, comment="截止日期")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")
    user_id = Column(Integer, default=1, index=True, comment="用户ID")


class WorkCommit(Base):
    """工作开发 - 提交记录表"""
    __tablename__ = "work_commits"

    id = Column(Integer, primary_key=True, index=True)
    commit_id = Column(Integer, index=True, comment="提交ID（业务ID）")
    hash = Column(String(64), default="", comment="提交哈希")
    message = Column(Text, default="", comment="提交信息")
    author = Column(String(100), default="", comment="作者")
    branch = Column(String(100), default="main", comment="分支")
    project_id = Column(Integer, default=0, index=True, comment="所属项目ID")
    additions = Column(Integer, default=0, comment="新增行数")
    deletions = Column(Integer, default=0, comment="删除行数")
    files_changed = Column(Integer, default=0, comment="变更文件数")
    committed_at = Column(DateTime, default=datetime.utcnow, comment="提交时间")
    user_id = Column(Integer, default=1, index=True, comment="用户ID")


class WorkCodeUsage(Base):
    """工作开发 - 代码使用统计表（记录 generate/chat/execute 调用）"""
    __tablename__ = "work_dev_code_usage"

    id = Column(Integer, primary_key=True, index=True)
    usage_id = Column(Integer, index=True, comment="使用记录ID（业务ID）")
    action_type = Column(String(20), default="generate", comment="操作类型：generate/chat/execute/complete")
    operation_type = Column(String(20), default="", comment="操作子类型：generate/review/debug/optimize/refactor/explain/test")
    language = Column(String(50), default="python", comment="编程语言")
    tokens_used = Column(Integer, default=0, comment="消耗 Token 数（估算）")
    project_id = Column(Integer, default=0, index=True, comment="所属项目ID（可选）")
    is_fallback = Column(Boolean, default=False, comment="是否为 fallback 模板模式")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
    user_id = Column(Integer, default=1, index=True, comment="用户ID")
