"""学业规划模式 - Pydantic 数据模型.

定义学业规划模式相关的请求/响应数据模型，
用于 API 接口的数据校验和类型提示。
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 目标相关模型
# ---------------------------------------------------------------------------


class GoalCreateRequest(BaseModel):
    """创建目标请求体."""

    label: str = Field(..., description="目标名称", min_length=1, max_length=200)
    icon: str = Field("📚", description="图标 emoji", max_length=20)
    parent_id: Optional[int] = Field(None, description="父目标 ID")


class GoalUpdateRequest(BaseModel):
    """更新目标请求体."""

    label: Optional[str] = Field(None, description="目标名称", max_length=200)
    progress: Optional[int] = Field(None, description="进度 0-100", ge=0, le=100)
    status: Optional[str] = Field(None, description="状态", max_length=20)
    expanded: Optional[bool] = Field(None, description="是否展开")


# ---------------------------------------------------------------------------
# 学习计划相关模型
# ---------------------------------------------------------------------------


class PlanCreateRequest(BaseModel):
    """创建学习计划请求体."""

    title: str = Field(..., description="计划标题", min_length=1, max_length=200)
    start_time: str = Field("09:00", description="开始时间 HH:MM", max_length=10)
    end_time: str = Field("10:00", description="结束时间 HH:MM", max_length=10)
    priority: str = Field("常规", description="优先级", max_length=20)
    subject: str = Field("", description="科目", max_length=50)
    date: Optional[str] = Field(None, description="日期 YYYY-MM-DD")


# ---------------------------------------------------------------------------
# 学习笔记相关模型
# ---------------------------------------------------------------------------


class NoteCreateRequest(BaseModel):
    """创建学习笔记请求体."""

    title: str = Field(..., description="笔记标题", min_length=1, max_length=200)
    subject: str = Field(..., description="科目/分类", min_length=1, max_length=50)
    content: str = Field("", description="笔记内容")


class NoteUpdateRequest(BaseModel):
    """更新学习笔记请求体."""

    title: Optional[str] = Field(None, description="标题", max_length=200)
    subject: Optional[str] = Field(None, description="科目", max_length=50)
    content: Optional[str] = Field(None, description="内容")


# ---------------------------------------------------------------------------
# 考试相关模型
# ---------------------------------------------------------------------------


class ExamCreateRequest(BaseModel):
    """创建考试提醒请求体."""

    name: str = Field(..., description="考试名称", min_length=1, max_length=200)
    exam_date: str = Field(..., description="考试日期时间 YYYY-MM-DD HH:MM", min_length=1)
    location: str = Field("", description="考试地点", max_length=200)
    urgency: str = Field("备考中", description="紧急程度", max_length=20)


# ---------------------------------------------------------------------------
# 周目标相关模型
# ---------------------------------------------------------------------------


class WeeklyGoalItem(BaseModel):
    """周目标项."""

    id: Optional[int] = Field(None, description="目标 ID")
    category: str = Field("", description="分类", max_length=50)
    current: int = Field(0, description="当前进度", ge=0)
    total: int = Field(0, description="目标总数", ge=0)
    unit: str = Field("个", description="单位", max_length=20)
    progress: int = Field(0, description="进度百分比", ge=0, le=100)
    completed: bool = Field(False, description="是否完成")


class WeeklyGoalsUpdateRequest(BaseModel):
    """更新周目标请求体."""

    goals: list[WeeklyGoalItem] = Field(..., description="周目标列表")


# ---------------------------------------------------------------------------
# 通用响应模型
# ---------------------------------------------------------------------------


class StudyOverviewStats(BaseModel):
    """学业规划概览统计数据."""

    total_goals: int = Field(0, description="目标总数")
    total_plans: int = Field(0, description="计划总数")
    total_notes: int = Field(0, description="笔记总数")
    total_exams: int = Field(0, description="考试总数")
    today_tasks: int = Field(0, description="今日任务数")
    today_done: int = Field(0, description="今日已完成数")
    streak_days: int = Field(0, description="连续学习天数")
