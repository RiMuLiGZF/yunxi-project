"""
M8 管理工作台 - 成长中心模型

包含 GrowthAchievement, GrowthTalent, GrowthTalentMeta, GrowthSeason,
GrowthSeasonTask, GrowthMemory, GrowthChronicle, GrowthCalendar。
"""

from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, JSON, Float
from datetime import datetime

from .base import Base


class GrowthAchievement(Base):
    """成长中心 - 成就表"""
    __tablename__ = "growth_achievements"

    id = Column(Integer, primary_key=True, index=True)
    achievement_id = Column(String(64), index=True, comment="成就ID")
    name = Column(String(100), comment="成就名称")
    description = Column(Text, default="", comment="成就描述")
    category = Column(String(50), default="exploration", comment="分类：exploration/conversation/growth/memory/season/special")
    rarity = Column(String(20), default="common", comment="稀有度：common/uncommon/rare/epic/legendary")
    points = Column(Integer, default=0, comment="成就点数")
    icon = Column(String(20), default="", comment="图标")
    unlocked = Column(Boolean, default=False, comment="是否解锁")
    unlocked_at = Column(DateTime, nullable=True, comment="解锁时间")
    user_id = Column(Integer, default=1, index=True, comment="用户ID")


class GrowthTalent(Base):
    """成长中心 - 天赋节点表"""
    __tablename__ = "growth_talents"

    id = Column(Integer, primary_key=True, index=True)
    talent_id = Column(String(64), index=True, comment="天赋节点ID")
    name = Column(String(100), comment="天赋名称")
    description = Column(Text, default="", comment="天赋描述")
    branch = Column(String(50), default="core", comment="分支：core/cognition/memory/emotion/utility/social")
    tier = Column(Integer, default=1, comment="层级")
    cost = Column(JSON, default=list, comment="升级所需点数数组")
    unlocked = Column(Boolean, default=False, comment="是否已解锁（等级>0）")
    current_level = Column(Integer, default=0, comment="当前等级")
    max_level = Column(Integer, default=1, comment="最大等级")
    position_x = Column(Integer, default=0, comment="位置X坐标")
    position_y = Column(Integer, default=0, comment="位置Y坐标")
    prerequisites = Column(JSON, default=list, comment="前置天赋ID列表")
    effects = Column(JSON, default=list, comment="效果列表")
    icon = Column(String(20), default="", comment="图标")
    user_id = Column(Integer, default=1, index=True, comment="用户ID")


class GrowthTalentMeta(Base):
    """成长中心 - 天赋树元数据表（总点数等）"""
    __tablename__ = "growth_talent_meta"

    id = Column(Integer, primary_key=True, index=True)
    total_points = Column(Integer, default=0, comment="总天赋点")
    used_points = Column(Integer, default=0, comment="已用天赋点")
    user_id = Column(Integer, default=1, index=True, comment="用户ID")


class GrowthSeason(Base):
    """成长中心 - 赛季表"""
    __tablename__ = "growth_seasons"

    id = Column(Integer, primary_key=True, index=True)
    season_id = Column(String(64), index=True, comment="赛季ID")
    name = Column(String(100), comment="赛季名称")
    theme = Column(String(100), default="", comment="赛季主题")
    description = Column(Text, default="", comment="赛季描述")
    start_date = Column(String(20), comment="开始日期")
    end_date = Column(String(20), comment="结束日期")
    current = Column(Boolean, default=False, comment="是否为当前赛季")
    status = Column(String(20), default="active", comment="状态：active/completed")
    rank = Column(String(20), nullable=True, comment="评级：bronze/silver/gold")
    reward_preview = Column(JSON, default=dict, comment="奖励预览")
    user_id = Column(Integer, default=1, index=True, comment="用户ID")


class GrowthSeasonTask(Base):
    """成长中心 - 赛季任务表"""
    __tablename__ = "growth_season_tasks"

    id = Column(Integer, primary_key=True, index=True)
    season_id = Column(String(64), index=True, comment="所属赛季ID")
    task_id = Column(String(64), index=True, comment="任务ID")
    name = Column(String(100), comment="任务名称")
    description = Column(Text, default="", comment="任务描述")
    type = Column(String(20), default="daily", comment="类型：daily/weekly/monthly")
    points = Column(Integer, default=0, comment="奖励点数")
    target = Column(Integer, default=1, comment="目标数量")
    current = Column(Integer, default=0, comment="当前进度")
    completed = Column(Boolean, default=False, comment="是否完成")
    completed_at = Column(DateTime, nullable=True, comment="完成时间")
    claimed = Column(Boolean, default=False, comment="是否已领取奖励")
    user_id = Column(Integer, default=1, index=True, comment="用户ID")


class GrowthMemory(Base):
    """成长中心 - 记忆回响表"""
    __tablename__ = "growth_memories"

    id = Column(Integer, primary_key=True, index=True)
    memory_id = Column(String(64), index=True, comment="记忆/回响ID")
    title = Column(String(200), comment="标题")
    content = Column(Text, default="", comment="内容摘要")
    content_summary = Column(Text, default="", comment="内容摘要（兼容字段）")
    tags = Column(JSON, default=list, comment="标签列表")
    emotion = Column(String(50), default="", comment="情绪标签")
    emotion_tags = Column(JSON, default=list, comment="情绪标签列表")
    importance = Column(Integer, default=1, comment="重要程度 1-5")
    echo_type = Column(String(20), default="reflection", comment="回响类型：reflection/insight/poem/story")
    original_memory_id = Column(String(64), nullable=True, comment="原始记忆ID")
    favorite = Column(Boolean, default=False, comment="是否收藏")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
    generated_at = Column(DateTime, nullable=True, comment="生成时间")
    user_id = Column(Integer, default=1, index=True, comment="用户ID")


class GrowthChronicle(Base):
    """成长中心 - 成长纪事表"""
    __tablename__ = "growth_chronicles"

    id = Column(Integer, primary_key=True, index=True)
    chronicle_id = Column(String(64), index=True, comment="纪事ID")
    title = Column(String(200), comment="标题")
    content = Column(Text, default="", comment="内容")
    category = Column(String(50), default="daily", comment="分类：milestone/discovery/achievement/daily/reflection")
    tags = Column(JSON, default=list, comment="标签列表")
    mood = Column(String(50), nullable=True, comment="心情标签")
    important = Column(Boolean, default=False, comment="是否重要")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")
    user_id = Column(Integer, default=1, index=True, comment="用户ID")


class GrowthCalendar(Base):
    """成长中心 - 潮汐日历/打卡表"""
    __tablename__ = "growth_calendar"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(String(20), index=True, comment="日期 YYYY-MM-DD")
    checked_in = Column(Boolean, default=False, comment="是否打卡")
    mood = Column(String(50), nullable=True, comment="当日心情")
    note = Column(Text, default="", comment="打卡备注")
    streak = Column(Integer, default=0, comment="截至当日的连续打卡天数")
    user_id = Column(Integer, default=1, index=True, comment="用户ID")
