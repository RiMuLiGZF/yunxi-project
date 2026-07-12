"""工作开发模式 - Pydantic 数据模型.

定义工作开发模式相关的请求/响应数据模型，
用于 API 接口的数据校验和类型提示。
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 项目相关模型
# ---------------------------------------------------------------------------


class ProjectCreateRequest(BaseModel):
    """创建项目请求体."""

    name: str = Field(..., description="项目名称", min_length=1, max_length=200)
    description: str = Field("", description="项目描述")
    language: str = Field("python", description="主要语言", max_length=50)
    category: str = Field("", description="项目分类", max_length=50)
    status: str = Field("planning", description="状态", max_length=20)


class ProjectUpdateRequest(BaseModel):
    """更新项目请求体."""

    name: Optional[str] = Field(None, description="项目名称", max_length=200)
    description: Optional[str] = Field(None, description="项目描述")
    status: Optional[str] = Field(None, description="状态", max_length=20)
    language: Optional[str] = Field(None, description="主要语言", max_length=50)
    progress: Optional[int] = Field(None, description="进度百分比 0-100", ge=0, le=100)
    category: Optional[str] = Field(None, description="项目分类", max_length=50)
    repo_url: Optional[str] = Field(None, description="仓库地址", max_length=500)


# ---------------------------------------------------------------------------
# 任务相关模型
# ---------------------------------------------------------------------------


class TaskCreateRequest(BaseModel):
    """创建任务请求体."""

    title: str = Field(..., description="任务标题", min_length=1, max_length=255)
    description: str = Field("", description="任务描述")
    status: str = Field("todo", description="状态：todo/in_progress/review/done", max_length=20)
    priority: str = Field("medium", description="优先级：low/medium/high", max_length=20)
    project_id: int = Field(0, description="所属项目ID", ge=0)
    assignee: str = Field("云汐", description="负责人", max_length=100)
    due_date: Optional[str] = Field(None, description="截止日期", max_length=20)
    tags: list[str] = Field(default_factory=list, description="标签列表")
    estimate_hours: int = Field(0, description="预估工时（小时）", ge=0)


class TaskUpdateRequest(BaseModel):
    """更新任务请求体."""

    title: Optional[str] = Field(None, description="任务标题", max_length=255)
    description: Optional[str] = Field(None, description="任务描述")
    status: Optional[str] = Field(None, description="状态", max_length=20)
    priority: Optional[str] = Field(None, description="优先级", max_length=20)
    project_id: Optional[int] = Field(None, description="所属项目ID", ge=0)
    assignee: Optional[str] = Field(None, description="负责人", max_length=100)
    due_date: Optional[str] = Field(None, description="截止日期", max_length=20)
    tags: Optional[list[str]] = Field(None, description="标签列表")
    estimate_hours: Optional[int] = Field(None, description="预估工时", ge=0)
    spent_hours: Optional[int] = Field(None, description="已用工时", ge=0)


class TaskStatusUpdateRequest(BaseModel):
    """任务状态更新请求体."""

    status: str = Field(..., description="新状态：todo/in_progress/review/done", max_length=20)


# ---------------------------------------------------------------------------
# 代码相关模型
# ---------------------------------------------------------------------------


class CodeExecuteRequest(BaseModel):
    """代码执行请求体."""

    language: str = Field("python", description="编程语言", max_length=50)
    code: str = Field(..., description="代码内容")
    stdin: str = Field("", description="标准输入")


class CodeGenerateRequest(BaseModel):
    """AI 代码操作请求体."""

    prompt: str = Field(..., description="需求描述")
    language: str = Field("python", description="编程语言", max_length=50)
    operation_type: str = Field(
        "generate",
        description="操作类型：generate/review/debug/optimize/refactor/explain/test",
        max_length=20,
    )


class CodeChatRequest(BaseModel):
    """代码对话请求体."""

    message: str = Field(..., description="用户消息")
    language: str = Field("python", description="编程语言", max_length=50)
    conversation_id: str = Field("default", description="会话ID")
    context_code: str = Field("", description="上下文代码")


# ---------------------------------------------------------------------------
# Git 相关模型
# ---------------------------------------------------------------------------


class GitCommitRequest(BaseModel):
    """Git 提交请求体."""

    message: str = Field(..., description="提交信息")
    project_id: int = Field(1, description="项目ID", ge=1)


# ---------------------------------------------------------------------------
# 代码片段相关模型
# ---------------------------------------------------------------------------


class SnippetCreateRequest(BaseModel):
    """创建代码片段请求体."""

    title: str = Field(..., description="片段标题", min_length=1, max_length=200)
    language: str = Field("python", description="编程语言", max_length=50)
    code: str = Field("", description="代码内容")
    description: str = Field("", description="描述说明")
    tags: list[str] = Field(default_factory=list, description="标签列表")
    project_id: int = Field(0, description="所属项目ID", ge=0)


class SnippetUpdateRequest(BaseModel):
    """更新代码片段请求体."""

    title: Optional[str] = Field(None, description="片段标题", max_length=200)
    language: Optional[str] = Field(None, description="编程语言", max_length=50)
    code: Optional[str] = Field(None, description="代码内容")
    description: Optional[str] = Field(None, description="描述说明")
    tags: Optional[list[str]] = Field(None, description="标签列表")
    is_favorite: Optional[bool] = Field(None, description="是否收藏")


# ---------------------------------------------------------------------------
# 统计相关响应模型
# ---------------------------------------------------------------------------


class WorkDevStatsData(BaseModel):
    """工作开发概览统计数据."""

    total_projects: int = Field(0, description="项目总数")
    active_projects: int = Field(0, description="活跃项目数")
    total_tasks: int = Field(0, description="任务总数")
    done_tasks: int = Field(0, description="已完成任务数")
    in_progress_tasks: int = Field(0, description="进行中任务数")
    todo_tasks: int = Field(0, description="待办任务数")
    total_commits: int = Field(0, description="提交总数")
    week_commits: int = Field(0, description="本周提交数")
    total_lines: int = Field(0, description="代码总行数")
    task_completion_rate: float = Field(0.0, description="任务完成率")


class CommitStatsData(BaseModel):
    """提交统计数据."""

    total_commits: int = Field(0, description="提交总数")
    total_insertions: int = Field(0, description="新增行数")
    total_deletions: int = Field(0, description="删除行数")
    daily_commits: list[dict[str, Any]] = Field(default_factory=list, description="每日提交统计")
