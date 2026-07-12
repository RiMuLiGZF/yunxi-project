"""成长中心模式 - Pydantic 数据模型.

定义成长中心模式相关的请求/响应数据模型，
用于 API 接口的数据校验和类型提示。
涵盖成就、天赋、历法、编年史、回响、赛季六大模块。
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 打卡请求模型
# ---------------------------------------------------------------------------


class CheckinRequest(BaseModel):
    """打卡请求体."""

    date: Optional[str] = Field(None, description="日期 YYYY-MM-DD，默认今天")
    mood: int = Field(7, description="心情值 1-10", ge=1, le=10)
    energy: int = Field(7, description="精力值 1-10", ge=1, le=10)
    summary: str = Field("", description="当日总结")
    tags: list[str] = Field(default_factory=list, description="标签列表")


# ---------------------------------------------------------------------------
# 编年史请求模型
# ---------------------------------------------------------------------------


class ChronicleCreateRequest(BaseModel):
    """创建纪事请求体."""

    date: str = Field(..., description="日期 YYYY.MM.DD", min_length=1)
    title: str = Field(..., description="标题", min_length=1, max_length=200)
    category: str = Field("main-quest", description="类型：main-quest/side-quest/achievement/critical-decision")
    category_text: str = Field("主线任务", description="类型中文")
    difficulty: str = Field("普通", description="难度：入门/普通/困难/史诗")
    content: str = Field("", description="详细内容")
    tags: list[str] = Field(default_factory=list, description="标签数组")
    has_git: bool = Field(False, description="是否关联 Git")
    git_commits: list[dict[str, Any]] = Field(default_factory=list, description="Git 提交数组")


class ChronicleUpdateRequest(BaseModel):
    """更新纪事请求体."""

    date: Optional[str] = Field(None, description="日期 YYYY.MM.DD")
    title: Optional[str] = Field(None, description="标题", max_length=200)
    category: Optional[str] = Field(None, description="类型")
    category_text: Optional[str] = Field(None, description="类型中文")
    difficulty: Optional[str] = Field(None, description="难度")
    content: Optional[str] = Field(None, description="详细内容")
    tags: Optional[list[str]] = Field(None, description="标签数组")
    has_git: Optional[bool] = Field(None, description="是否关联 Git")
    git_commits: Optional[list[dict[str, Any]]] = Field(None, description="Git 提交数组")


# ---------------------------------------------------------------------------
# 回响请求模型
# ---------------------------------------------------------------------------


class MemoryEchoState(BaseModel):
    """记忆状态（过去/现在）."""

    date: str = Field("", description="日期")
    title: str = Field("", description="标题")
    desc: str = Field("", description="描述")
    emotion: str = Field("", description="情绪")
    pattern: str = Field("", description="行为模式")
    tags: list[str] = Field(default_factory=list, description="标签")


class EchoGenerateRequest(BaseModel):
    """生成回响请求体."""

    type: str = Field("growth", description="回响类型")
    memory_id: Optional[str] = Field(None, description="关联记忆ID（可选）")
    before: Optional[MemoryEchoState] = Field(None, description="过去状态")
    after: Optional[MemoryEchoState] = Field(None, description="现在状态")


# ---------------------------------------------------------------------------
# 成长概览响应模型
# ---------------------------------------------------------------------------


class GrowthOverview(BaseModel):
    """成长中心概览数据.

    聚合成就、天赋、历法、赛季等多个模块的核心数据，
    用于成长中心首页展示。
    """

    achievement_stats: dict[str, Any] = Field(
        default_factory=dict, description="成就统计"
    )
    talent_points: dict[str, Any] = Field(
        default_factory=dict, description="天赋点数信息"
    )
    calendar_stats: dict[str, Any] = Field(
        default_factory=dict, description="日历/打卡统计"
    )
    current_season: dict[str, Any] = Field(
        default_factory=dict, description="当前赛季信息"
    )
    today_checked_in: bool = Field(False, description="今日是否已打卡")
    recent_achievements: list[dict[str, Any]] = Field(
        default_factory=list, description="最近解锁的成就"
    )
    quick_actions: list[dict[str, Any]] = Field(
        default_factory=list, description="快捷操作列表"
    )


# ---------------------------------------------------------------------------
# 成长中心配置模型
# ---------------------------------------------------------------------------


class GrowthConfig(BaseModel):
    """成长中心配置项."""

    daily_checkin_reminder: bool = Field(True, description="每日打卡提醒")
    achievement_notification: bool = Field(True, description="成就解锁通知")
    season_task_reminder: bool = Field(True, description="赛季任务提醒")
    default_view: str = Field("overview", description="默认视图：overview/achievements/talents/calendar/season")
    calendar_start_day: str = Field("monday", description="日历起始日：monday/sunday")
