"""
成长系统数据模型定义

包含成就、天赋、日历、编年史、记忆回响、赛季征程六大模块的数据结构定义。
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ============================================================
# 成就勋章殿堂
# ============================================================

class AchievementCategory(str, Enum):
    """成就分类"""
    GROWTH = "growth"      # 成长类
    SKILL = "skill"        # 技能类
    SOCIAL = "social"      # 社交类
    SPECIAL = "special"    # 特殊类


class AchievementRarity(str, Enum):
    """成就稀有度"""
    COMMON = "common"          # 普通 - 铁
    RARE = "rare"              # 稀有 - 银
    EPIC = "epic"              # 史诗 - 金
    LEGENDARY = "legendary"    # 传奇 - 传奇


RARITY_TEXT_MAP = {
    AchievementRarity.COMMON: "普通",
    AchievementRarity.RARE: "稀有",
    AchievementRarity.EPIC: "史诗",
    AchievementRarity.LEGENDARY: "传奇",
}

# 成就解锁奖励的天赋点数
RARITY_POINT_REWARD = {
    AchievementRarity.COMMON: 1,
    AchievementRarity.RARE: 2,
    AchievementRarity.EPIC: 3,
    AchievementRarity.LEGENDARY: 5,
}


class Achievement(BaseModel):
    """成就数据模型"""
    id: str
    name: str
    category: str
    rarity: str
    rarity_text: str
    unlocked: bool = False
    unlock_date: str = ""
    condition: str
    description: str
    point_reward: int = 1


class AchievementStats(BaseModel):
    """成就统计"""
    total: int = 0
    unlocked: int = 0
    locked: int = 0
    by_category: Dict[str, Dict[str, int]] = Field(default_factory=dict)
    by_rarity: Dict[str, int] = Field(default_factory=dict)
    unlock_rate: float = 0.0


# ============================================================
# 心智天赋树
# ============================================================

class TalentBranch(str, Enum):
    """天赋分支"""
    MIND = "mind"              # 心智分支
    EMOTION = "emotion"        # 稳态分支
    CREATIVITY = "creativity"  # 创造分支
    EXPERIENCE = "experience"  # 阅历分支


BRANCH_TEXT_MAP = {
    TalentBranch.MIND: "心智",
    TalentBranch.EMOTION: "稳态",
    TalentBranch.CREATIVITY: "创造",
    TalentBranch.EXPERIENCE: "阅历",
}


class TalentNode(BaseModel):
    """天赋节点数据模型"""
    id: str
    name: str
    branch: str
    description: str
    status: str = "locked"  # unlocked / locked
    level: int = 0
    max_level: int = 1
    parent_id: Optional[str] = None
    children_ids: List[str] = Field(default_factory=list)
    tree: str  # mind / emotion / creativity / experience
    point_cost: int = 1
    layer: int = 1  # 所在层级 1-3


class TalentTreeData(BaseModel):
    """天赋树完整数据"""
    nodes: List[TalentNode] = Field(default_factory=list)
    connections: List[Dict[str, str]] = Field(default_factory=list)
    available_points: int = 0
    total_points: int = 0
    spent_points: int = 0
    stats: Dict[str, Any] = Field(default_factory=dict)


class TalentStats(BaseModel):
    """天赋统计"""
    total_nodes: int = 0
    unlocked_nodes: int = 0
    max_level_nodes: int = 0
    available_points: int = 0
    total_points_earned: int = 0
    by_branch: Dict[str, Dict[str, int]] = Field(default_factory=dict)


# ============================================================
# 潮汐专属历法
# ============================================================

class TidePhase(str, Enum):
    """潮汐相位"""
    NEAP = "小潮"          # 小潮
    SPRING = "大潮"        # 大潮
    ASTRONOMICAL = "天文潮"  # 天文潮


class DayData(BaseModel):
    """单日日历数据"""
    date: str  # YYYY-MM-DD
    mood: int = 0  # 心情值 1-10，0表示未打卡
    energy: int = 0  # 精力值 1-10，0表示未打卡
    checked_in: bool = False
    summary: str = ""
    tags: List[str] = Field(default_factory=list)
    tide_phase: str = "小潮"


class CalendarStats(BaseModel):
    """日历统计"""
    total_days: int = 0
    checked_days: int = 0
    streak: int = 0
    avg_mood: float = 0.0
    avg_energy: float = 0.0
    checkin_rate: float = 0.0


class CheckinRequest(BaseModel):
    """打卡请求"""
    date: Optional[str] = None  # 默认为今天
    mood: int = Field(default=7, ge=1, le=10)
    energy: int = Field(default=7, ge=1, le=10)
    summary: str = ""
    tags: List[str] = Field(default_factory=list)


class MonthCalendarData(BaseModel):
    """月历数据"""
    year: int
    month: int
    days: List[DayData] = Field(default_factory=list)
    stats: CalendarStats = Field(default_factory=CalendarStats)


# ============================================================
# 地球Online编年史
# ============================================================

class ChronicleBase(BaseModel):
    """编年史基础字段"""
    date: str = Field(..., description="日期 YYYY.MM.DD")
    title: str = Field(..., description="标题")
    category: str = Field(default="main-quest", description="类型：main-quest/side-quest/achievement/critical-decision")
    category_text: str = Field(default="主线任务", description="类型中文")
    difficulty: str = Field(default="普通", description="难度：入门/普通/困难/史诗")
    content: str = Field(default="", description="详细内容")
    tags: List[str] = Field(default_factory=list, description="标签数组")
    has_git: bool = Field(default=False, description="是否关联 Git 提交")
    git_commits: List[Dict[str, Any]] = Field(default_factory=list, description="Git 提交信息数组")


class ChronicleCreate(ChronicleBase):
    """创建纪事请求"""
    pass


class ChronicleUpdate(BaseModel):
    """更新纪事请求"""
    date: Optional[str] = None
    title: Optional[str] = None
    category: Optional[str] = None
    category_text: Optional[str] = None
    difficulty: Optional[str] = None
    content: Optional[str] = None
    tags: Optional[List[str]] = None
    has_git: Optional[bool] = None
    git_commits: Optional[List[Dict[str, Any]]] = None


class Chronicle(ChronicleBase):
    """完整纪事数据"""
    id: str = Field(..., description="纪事ID")
    created_at: str = Field(..., description="创建时间")
    updated_at: str = Field(..., description="更新时间")


# ============================================================
# 记忆回响对比
# ============================================================

class MemoryEchoState(BaseModel):
    """记忆状态（过去/现在）"""
    date: str = Field(default="", description="日期")
    title: str = Field(default="", description="标题")
    desc: str = Field(default="", description="描述")
    emotion: str = Field(default="", description="情绪")
    pattern: str = Field(default="", description="行为模式")
    tags: List[str] = Field(default_factory=list, description="标签")


class MemoryEchoBase(BaseModel):
    """记忆回响基础字段"""
    title: str = Field(..., description="标题")
    category: str = Field(default="growth", description="分类：emotion/decision/social/growth/work/life")
    category_text: str = Field(default="成长", description="分类中文")
    before: MemoryEchoState = Field(default_factory=MemoryEchoState, description="过去状态")
    after: MemoryEchoState = Field(default_factory=MemoryEchoState, description="现在状态")
    growth: str = Field(default="", description="成长感悟/回响洞察")
    content: str = Field(default="", description="补充内容")


class MemoryEchoGenerateRequest(BaseModel):
    """生成回响请求"""
    type: str = Field(default="growth", description="回响类型")
    memory_id: Optional[str] = Field(default=None, description="关联记忆ID（可选）")
    before: Optional[MemoryEchoState] = Field(default=None, description="过去状态")
    after: Optional[MemoryEchoState] = Field(default=None, description="现在状态")


class MemoryEcho(MemoryEchoBase):
    """完整记忆回响数据"""
    id: str = Field(..., description="回响ID")
    created_at: str = Field(..., description="创建时间")


# ============================================================
# 赛季征程系统
# ============================================================

class SeasonPhase(BaseModel):
    """赛季阶段"""
    id: str = Field(..., description="阶段ID")
    name: str = Field(..., description="阶段名称")
    status: str = Field(default="locked", description="状态：completed/active/locked")
    tasks_total: int = Field(default=0, description="任务总数")
    tasks_completed: int = Field(default=0, description="已完成任务数")
    reward: str = Field(default="", description="阶段奖励名称")
    reward_points: int = Field(default=0, description="奖励天赋点数")
    reward_claimed: bool = Field(default=False, description="是否已领取")


class Season(BaseModel):
    """赛季数据"""
    id: str = Field(..., description="赛季ID")
    name: str = Field(..., description="赛季名称")
    period: str = Field(default="", description="赛季周期描述")
    start_date: str = Field(..., description="开始日期")
    end_date: str = Field(..., description="结束日期")
    status: str = Field(default="locked", description="状态：active/completed/locked")
    progress: int = Field(default=0, description="进度百分比 0-100")
    days_left: int = Field(default=0, description="剩余天数")
    phases: List[SeasonPhase] = Field(default_factory=list, description="阶段数组")


class SeasonTask(BaseModel):
    """赛季任务"""
    id: str = Field(..., description="任务ID")
    phase_id: str = Field(..., description="所属阶段ID")
    title: str = Field(..., description="任务标题")
    description: str = Field(default="", description="任务描述")
    type: str = Field(default="seasonal", description="类型：daily/weekly/seasonal")
    status: str = Field(default="pending", description="状态：pending/completed/claimed")
    points: int = Field(default=0, description="奖励天赋点数")
    completed_at: Optional[str] = Field(default=None, description="完成时间")


# vim: set et ts=4 sw=4:
