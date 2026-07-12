"""人际关系模式 - Pydantic 数据模型.

定义人际关系模式相关的请求/响应数据模型，
用于 API 接口的数据校验和类型提示。
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 联系人相关模型
# ---------------------------------------------------------------------------


class ContactCreateRequest(BaseModel):
    """创建联系人请求体."""

    name: str = Field(..., description="联系人姓名", min_length=1, max_length=100)
    avatar: str = Field("👤", description="头像 emoji", max_length=20)
    relation: str = Field("朋友", description="关系类型", max_length=50)
    tags: list[str] = Field(default_factory=list, description="标签列表")


class ContactUpdateRequest(BaseModel):
    """更新联系人请求体."""

    name: Optional[str] = Field(None, description="姓名", max_length=100)
    avatar: Optional[str] = Field(None, description="头像", max_length=20)
    relation: Optional[str] = Field(None, description="关系类型", max_length=50)
    relationship_type: Optional[str] = Field(None, description="关系类型（别名）", max_length=50)
    closeness: Optional[int] = Field(None, description="亲密度 0-100", ge=0, le=100)
    importance: Optional[int] = Field(None, description="重要度 0-100（别名）", ge=0, le=100)
    tags: Optional[list[str]] = Field(None, description="标签列表")
    phone: Optional[str] = Field(None, description="电话", max_length=50)
    email: Optional[str] = Field(None, description="邮箱", max_length=100)
    note: Optional[str] = Field(None, description="备注")


# ---------------------------------------------------------------------------
# 交往记录相关模型
# ---------------------------------------------------------------------------


class InteractionCreateRequest(BaseModel):
    """创建交往记录请求体."""

    contact_id: int = Field(..., description="联系人 ID", gt=0)
    contact_name: str = Field("", description="联系人姓名快照", max_length=100)
    type: str = Field("聊天", description="交往类型", max_length=50)
    content: str = Field("", description="交往内容")
    emotion: str = Field("neutral", description="心情：positive/neutral/negative", max_length=20)
    duration_minutes: int = Field(0, description="时长（分钟）", ge=0)
    location: str = Field("", description="地点", max_length=100)


# ---------------------------------------------------------------------------
# 社交提醒相关模型
# ---------------------------------------------------------------------------


class ReminderCreateRequest(BaseModel):
    """创建提醒请求体."""

    type: str = Field("contact", description="提醒类型", max_length=50)
    title: str = Field("", description="提醒标题", max_length=200)
    description: str = Field("", description="提醒描述")
    date: str = Field("", description="提醒日期字符串")
    priority: str = Field("medium", description="优先级：high/medium/low", max_length=20)


class ReminderUpdateRequest(BaseModel):
    """更新提醒请求体."""

    status: Optional[str] = Field(None, description="状态：pending/done/cancelled", max_length=20)


# ---------------------------------------------------------------------------
# 通用响应模型
# ---------------------------------------------------------------------------


class SocialStatsData(BaseModel):
    """社交统计数据."""

    total_contacts: int = Field(0, description="联系人总数")
    total_interactions: int = Field(0, description="交往记录总数")
    avg_closeness: int = Field(0, description="平均亲密度")
    eq_score: int = Field(0, description="情商得分")
    week_interactions: int = Field(0, description="本周交往次数")
    streak_days: int = Field(0, description="连续打卡天数")


class RelationGraphData(BaseModel):
    """关系图谱数据."""

    nodes: list[dict[str, Any]] = Field(default_factory=list, description="节点列表")
    links: list[dict[str, Any]] = Field(default_factory=list, description="连线列表")


class EqScoreData(BaseModel):
    """情商得分数据."""

    score: int = Field(0, description="总分")
    level: str = Field("", description="等级")
    dimensions: list[dict[str, Any]] = Field(default_factory=list, description="各维度得分")
