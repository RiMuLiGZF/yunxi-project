"""形象工坊 - Pydantic 数据模型.

定义形象工坊模式相关的请求和响应模型。
"""

from __future__ import annotations

from typing import Optional, List, Any
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------


class ConfigUpdateRequest(BaseModel):
    """形象配置更新请求体."""

    theme: Optional[str] = Field(None, description="主题ID")
    primary_color: Optional[str] = Field(None, description="主色")
    secondary_color: Optional[str] = Field(None, description="辅色")
    accent_color: Optional[str] = Field(None, description="强调色")
    particle_count: Optional[int] = Field(None, description="粒子数量")
    particle_speed: Optional[float] = Field(None, description="粒子速度")
    glow_intensity: Optional[float] = Field(None, description="光晕强度")
    mood: Optional[str] = Field(None, description="当前心情")
    personality_tags: Optional[List[str]] = Field(None, description="性格标签列表")
    voice_type: Optional[str] = Field(None, description="声音类型")
    voice_speed: Optional[float] = Field(None, description="语速")
    voice_pitch: Optional[float] = Field(None, description="音调")
    quality: Optional[str] = Field(None, description="画质")
    model: Optional[str] = Field(None, description="模型")
    sync_enabled: Optional[bool] = Field(None, description="是否同步")


class MoodUpdateRequest(BaseModel):
    """心情切换请求体."""

    mood: str = Field(..., description="心情类型ID")


class PersonalityTagsUpdateRequest(BaseModel):
    """性格标签更新请求体."""

    tags: List[str] = Field(..., description="选中的标签名称列表")


class SnapshotSaveRequest(BaseModel):
    """保存快照请求体."""

    name: str = Field(..., description="快照名称")


# ---------------------------------------------------------------------------
# 响应模型
# ---------------------------------------------------------------------------


class ThemeInfo(BaseModel):
    """主题信息."""

    id: str = Field(..., description="主题ID")
    name: str = Field(..., description="主题名称")
    colors: dict[str, str] = Field(default_factory=dict, description="颜色配置")
    description: str = Field("", description="主题描述")


class MoodStateInfo(BaseModel):
    """心情状态信息."""

    id: str = Field(..., description="心情ID")
    name: str = Field(..., description="心情名称")
    emoji: str = Field("", description="表情符号")
    color: str = Field("", description="主题色")
    particle_effect: str = Field("", description="粒子特效")


class RelationshipLevelInfo(BaseModel):
    """关系等级信息."""

    level: int = Field(..., description="等级")
    name: str = Field(..., description="等级名称")
    intimacy_required: int = Field(..., description="所需亲密度")
    description: str = Field("", description="等级描述")


class RelationshipStatus(BaseModel):
    """关系状态."""

    current_level: int = Field(..., description="当前等级")
    level_name: str = Field(..., description="等级名称")
    level_description: str = Field("", description="等级描述")
    intimacy: int = Field(..., description="当前亲密度")
    progress: int = Field(..., description="升级进度百分比")
    next_level: Optional[dict[str, Any]] = Field(None, description="下一等级信息")
    all_levels: List[dict[str, Any]] = Field(default_factory=list, description="所有等级列表")
