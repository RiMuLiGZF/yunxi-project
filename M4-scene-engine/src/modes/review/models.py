"""复盘总结模式 - Pydantic 数据模型.

定义复盘总结模式相关的请求/响应数据模型，
用于 API 接口的数据校验和类型提示。
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 复盘记录相关模型
# ---------------------------------------------------------------------------


class ReviewCreateRequest(BaseModel):
    """创建复盘请求体."""

    type: str = Field("daily", description="复盘类型：daily/weekly/monthly",
                      max_length=20)
    date: Optional[str] = Field(None, description="复盘日期 YYYY-MM-DD",
                                max_length=20)
    content: Optional[str] = Field("", description="复盘内容")


class ReviewGenerateRequest(BaseModel):
    """AI 生成复盘请求体."""

    type: str = Field("daily", description="复盘类型：daily/weekly/monthly",
                      max_length=20)
    date: Optional[str] = Field(None, description="复盘日期 YYYY-MM-DD",
                                max_length=20)


# ---------------------------------------------------------------------------
# 日记相关模型
# ---------------------------------------------------------------------------


class DiaryCreateRequest(BaseModel):
    """创建日记请求体."""

    title: str = Field(..., description="日记标题", min_length=1, max_length=255)
    content: str = Field("", description="日记内容")
    mood: Optional[str] = Field("neutral", description="心情", max_length=50)
    tags: Optional[list[str]] = Field(default_factory=list, description="标签列表")


# ---------------------------------------------------------------------------
# 决策记录相关模型
# ---------------------------------------------------------------------------


class DecisionCreateRequest(BaseModel):
    """创建决策请求体."""

    title: str = Field(..., description="决策标题", min_length=1, max_length=255)
    description: str = Field("", description="决策描述")
    options: list[str] = Field(default_factory=list, description="备选方案列表")
    final_choice: Optional[str] = Field("", description="最终选择", max_length=255)
    result: Optional[str] = Field("", description="结果描述")
    emotion_level: Optional[int] = Field(5, description="情绪强度 1-10", ge=1, le=10)


class DecisionUpdateRequest(BaseModel):
    """更新决策请求体（所有字段可选）."""

    title: Optional[str] = Field(None, description="决策标题", max_length=255)
    description: Optional[str] = Field(None, description="决策描述")
    status: Optional[str] = Field(None,
                                  description="状态：pending/executing/completed",
                                  max_length=20)
    final_choice: Optional[str] = Field(None, description="最终选择",
                                        max_length=255)
    result: Optional[str] = Field(None, description="结果描述")
    emotion_level: Optional[int] = Field(None, description="情绪强度 1-10",
                                         ge=1, le=10)
    alternatives: Optional[list[str]] = Field(None, description="备选方案列表")


# ---------------------------------------------------------------------------
# 情绪记录相关模型
# ---------------------------------------------------------------------------


class EmotionRecordRequest(BaseModel):
    """记录情绪请求体."""

    emotion: str = Field("neutral", description="情绪类型", max_length=50)
    level: int = Field(5, description="情绪强度 1-10", ge=1, le=10)
    trigger: Optional[str] = Field("", description="触发因素", max_length=500)
    note: Optional[str] = Field("", description="备注")


# ---------------------------------------------------------------------------
# 认知偏差相关模型
# ---------------------------------------------------------------------------


class BiasAnalyzeRequest(BaseModel):
    """认知偏差分析请求体."""

    text: str = Field("", description="待分析的文本")


# ---------------------------------------------------------------------------
# 通用响应模型
# ---------------------------------------------------------------------------


class ReviewStatsData(BaseModel):
    """复盘统计数据."""

    total_reviews: int = Field(0, description="复盘总数")
    total_diaries: int = Field(0, description="日记总数")
    total_decisions: int = Field(0, description="决策总数")
    total_emotions: int = Field(0, description="情绪记录总数")
    week_reviews: int = Field(0, description="本周复盘数")
    streak_days: int = Field(0, description="连续打卡天数")


class EmotionStatsData(BaseModel):
    """情绪统计数据."""

    total_records: int = Field(0, description="总记录数")
    emotion_distribution: dict[str, Any] = Field(default_factory=dict,
                                                 description="情绪分布")
    dominant_emotion: str = Field("", description="主导情绪")
    daily_trend: list[dict[str, Any]] = Field(default_factory=list,
                                              description="每日趋势")
    avg_level: float = Field(0.0, description="平均情绪强度")
