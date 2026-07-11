"""
M8 管理工作台 - 数据库模型
"""

from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, Boolean, Float, JSON, inspect, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import os
from pathlib import Path

Base = declarative_base()

# 从 config 读取数据库 URL
from .config import settings

SQLALCHEMY_DATABASE_URL = settings.database_url

# 确保 data 目录存在
_db_path = SQLALCHEMY_DATABASE_URL.replace("sqlite:///", "")
os.makedirs(os.path.dirname(_db_path) if os.path.dirname(_db_path) else "./data", exist_ok=True)

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class User(Base):
    """用户表

    P2-21: 扩展字段以对齐 users.json 数据结构，
    支持 nickname/email/status 等完整用户属性。
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), default="viewer", index=True)  # owner/admin/operator/viewer
    nickname = Column(String(100), default="")  # P2-21: 昵称
    email = Column(String(255), default="")     # P2-21: 邮箱
    status = Column(String(20), default="active", index=True)  # P2-21: active/disabled
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "username": self.username,
            "role": self.role,
            "nickname": self.nickname,
            "email": self.email,
            "status": self.status,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "last_login": self.last_login.strftime("%Y-%m-%d %H:%M:%S") if self.last_login else None,
        }


class ModuleRecord(Base):
    """模块记录表"""
    __tablename__ = "modules"

    id = Column(Integer, primary_key=True, index=True)
    module_key = Column(String(20), unique=True, index=True)
    name = Column(String(100))
    version = Column(String(50))
    status = Column(String(20), default="stopped")  # running/stopped/error
    port = Column(Integer)
    base_url = Column(String(255))
    description = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TaskRecord(Base):
    """任务记录表"""
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(String(64), unique=True, index=True)
    title = Column(String(255))
    status = Column(String(20), default="pending")  # pending/running/completed/failed
    module = Column(String(20))  # 提交到的模块
    input_data = Column(Text)
    output_data = Column(Text, nullable=True)
    error_msg = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)


class AlertRecord(Base):
    """告警记录表"""
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True)
    level = Column(String(20))  # info/warning/error/critical
    title = Column(String(255))
    content = Column(Text)  # 告警详情内容
    source = Column(String(50))  # 来源模块（system/m1/m2/...）
    status = Column(String(20), default="active")  # active/acknowledged/resolved
    created_at = Column(DateTime, default=datetime.utcnow)
    acknowledged_at = Column(DateTime, nullable=True)  # 确认时间
    acknowledged_by = Column(String(50), nullable=True)  # 确认人
    resolved_at = Column(DateTime, nullable=True)  # 解决时间
    resolved_by = Column(String(50), nullable=True)  # 解决人


# ═══════════════════════════════════════════════════════
# 成长中心 - 成就表
# ═══════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════
# 成长中心 - 天赋树表
# ═══════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════
# 成长中心 - 赛季表
# ═══════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════
# 成长中心 - 记忆回响表
# ═══════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════
# 成长中心 - 成长纪事表
# ═══════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════
# 成长中心 - 潮汐日历/打卡表
# ═══════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════
# 工作开发模式 - 项目表
# ═══════════════════════════════════════════════════════

class WorkProject(Base):
    """工作开发 - 项目表"""
    __tablename__ = "work_projects"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, index=True, comment="项目ID（业务ID）")
    name = Column(String(200), comment="项目名称")
    description = Column(Text, default="", comment="项目描述")
    status = Column(String(20), default="planning", comment="状态：planning/active/completed")
    progress = Column(Integer, default=0, comment="进度百分比")
    repo_url = Column(String(500), default="", comment="仓库地址")
    language = Column(String(50), default="python", comment="主要语言")
    file_count = Column(Integer, default=0, comment="文件数量")
    line_count = Column(Integer, default=0, comment="代码行数")
    commit_count = Column(Integer, default=0, comment="提交次数")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")
    user_id = Column(Integer, default=1, index=True, comment="用户ID")


# ═══════════════════════════════════════════════════════
# 工作开发模式 - 任务表
# ═══════════════════════════════════════════════════════

class WorkTask(Base):
    """工作开发 - 任务表"""
    __tablename__ = "work_tasks"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, index=True, comment="任务ID（业务ID）")
    title = C