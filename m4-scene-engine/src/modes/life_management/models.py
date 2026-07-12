"""生活管理模式 - Pydantic 数据模型.

定义生活管理模式相关的请求/响应数据模型，
用于 API 接口的数据校验和类型提示。
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 日程相关模型
# ---------------------------------------------------------------------------


class ScheduleCreateRequest(BaseModel):
    """创建日程请求体."""

    title: str = Field(..., description="日程标题", min_length=1, max_length=200)
    time: str = Field("09:00 - 10:00", description="时间范围", max_length=30)
    tag: str = Field("固定", description="分类标签", max_length=20)
    tag_color: str = Field("green", description="标签颜色", max_length=20)
    date: Optional[str] = Field(None, description="日期 YYYY-MM-DD")
    description: str = Field("", description="日程描述")
    all_day: bool = Field(False, description="是否全天")
    priority: str = Field("normal", description="优先级", max_length=20)


class ScheduleUpdateRequest(BaseModel):
    """更新日程请求体."""

    title: Optional[str] = Field(None, description="日程标题", max_length=200)
    time: Optional[str] = Field(None, description="时间范围", max_length=30)
    tag: Optional[str] = Field(None, description="分类标签", max_length=20)
    tag_color: Optional[str] = Field(None, description="标签颜色", max_length=20)
    date: Optional[str] = Field(None, description="日期")
    description: Optional[str] = Field(None, description="描述")
    all_day: Optional[bool] = Field(None, description="是否全天")
    priority: Optional[str] = Field(None, description="优先级", max_length=20)


# ---------------------------------------------------------------------------
# 待办相关模型
# ---------------------------------------------------------------------------


class TodoCreateRequest(BaseModel):
    """创建待办请求体."""

    title: str = Field(..., description="待办标题", min_length=1, max_length=200)
    status: str = Field("todo", description="状态：todo/in-progress/done", max_length=20)
    category: str = Field("今日待办", description="分类", max_length=50)
    priority: str = Field("normal", description="优先级", max_length=20)
    description: str = Field("", description="描述")
    due_date: Optional[str] = Field(None, description="截止日期")


class TodoUpdateRequest(BaseModel):
    """更新待办请求体."""

    title: Optional[str] = Field(None, description="标题", max_length=200)
    status: Optional[str] = Field(None, description="状态", max_length=20)
    progress: Optional[int] = Field(None, description="进度 0-100", ge=0, le=100)
    category: Optional[str] = Field(None, description="分类", max_length=50)
    priority: Optional[str] = Field(None, description="优先级", max_length=20)
    description: Optional[str] = Field(None, description="描述")
    due_date: Optional[str] = Field(None, description="截止日期")


# ---------------------------------------------------------------------------
# 习惯相关模型
# ---------------------------------------------------------------------------


class HabitCreateRequest(BaseModel):
    """创建习惯请求体."""

    name: str = Field(..., description="习惯名称", min_length=1, max_length=100)
    icon: str = Field("✅", description="图标 emoji", max_length=20)
    category: str = Field("", description="分类", max_length=50)
    frequency: str = Field("daily", description="频率：daily/weekly/monthly", max_length=20)
    description: str = Field("", description="描述")


class HabitCheckinRequest(BaseModel):
    """习惯打卡请求体."""

    note: str = Field("", description="打卡备注")


# ---------------------------------------------------------------------------
# 自动化规则相关模型
# ---------------------------------------------------------------------------


class RuleCreateRequest(BaseModel):
    """创建自动化规则请求体."""

    condition: str = Field(..., description="触发条件", min_length=1)
    action: str = Field(..., description="执行动作", min_length=1)
    title: str = Field("", description="规则标题", max_length=200)
    category: str = Field("", description="分类", max_length=50)


# ---------------------------------------------------------------------------
# 场景切换相关模型
# ---------------------------------------------------------------------------


class SceneSwitchRequest(BaseModel):
    """场景切换请求体."""

    scene_key: str = Field(..., description="场景 key", min_length=1)


# ---------------------------------------------------------------------------
# 财务相关模型
# ---------------------------------------------------------------------------


class FinanceRecordCreateRequest(BaseModel):
    """创建财务记录请求体."""

    type: str = Field("expense", description="类型：income/expense", max_length=20)
    amount: float = Field(..., description="金额", gt=0)
    category: str = Field(..., description="分类", min_length=1, max_length=50)
    description: str = Field("", description="描述")
    transaction_date: Optional[str] = Field(None, description="交易日期 YYYY-MM-DD")


# ---------------------------------------------------------------------------
# 通用响应模型
# ---------------------------------------------------------------------------


class LifeOverviewStats(BaseModel):
    """生活管理概览统计数据."""

    todo_total: int = Field(0, description="待办总数")
    todo_done: int = Field(0, description="已完成待办数")
    habit_total: int = Field(0, description="习惯总数")
    habit_done: int = Field(0, description="今日已完成习惯数")
    schedule_total: int = Field(0, description="今日日程数")
    finance_today_spending: float = Field(0.0, description="今日支出")
