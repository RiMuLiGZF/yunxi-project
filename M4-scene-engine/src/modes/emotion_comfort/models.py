"""情绪陪伴 - Pydantic 数据模型.

定义情绪陪伴模式相关的请求和响应模型。
"""

from __future__ import annotations

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------


class EmotionRecordRequest(BaseModel):
    """情绪记录请求体."""

    emotion: str = Field(..., description="情绪类型")
    level: int = Field(..., ge=1, le=10, description="情绪强度 1-10")
    trigger: str = Field("", description="触发因素")
    note: str = Field("", description="备注")


class AssessmentSubmitRequest(BaseModel):
    """测评提交请求体."""

    assessment_id: int = Field(..., description="测评ID")
    answers: Dict[str, int] = Field(..., description="答题记录 {question_id: option_index}")


class MoodEntryRequest(BaseModel):
    """心情日记创建请求体."""

    emotion: str = Field(..., description="心情类型")
    content: str = Field(..., description="日记内容")
    tags: List[str] = Field(default_factory=list, description="标签列表")


# ---------------------------------------------------------------------------
# 响应模型
# ---------------------------------------------------------------------------


class EmotionStats(BaseModel):
    """情绪统计数据."""

    total_records: int = Field(0, description="总记录数")
    distribution: Dict[str, int] = Field(default_factory=dict, description="情绪分布")
    daily_trend: List[Dict[str, Any]] = Field(default_factory=list, description="日趋势数据")
    triggers: Dict[str, int] = Field(default_factory=dict, description="触发因素统计")
    dominant_emotion: str = Field("", description="主导情绪")


class EmotionOverview(BaseModel):
    """情绪概览数据."""

    stats: Dict[str, Any] = Field(default_factory=dict, description="统计数据")
    current_mood: Optional[Dict[str, Any]] = Field(None, description="当前心情记录")
