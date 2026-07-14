"""
M8 管理工作台 - 生活管理模型

包含 LifeSchedule, LifeRule, LifeTodo, LifeHabit, LifeScene,
LifeFinanceCategory, LifeMeta, LifeHabitRecord, LifeFinanceRecord。
"""

from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, JSON, Float
from datetime import datetime

from .base import Base


class LifeSchedule(Base):
    """生活管理 - 日程表"""
    __tablename__ = "life_schedules"

    id = Column(Integer, primary_key=True, index=True)
    schedule_id = Column(Integer, index=True, comment="日程ID（业务ID）")
    title = Column(String(200), comment="日程标题")
    description = Column(Text, default="", comment="描述")
    start_time = Column(String(10), default="09:00", comment="开始时间")
    end_time = Column(String(10), default="10:00", comment="结束时间")
    time_range = Column(String(30), default="", comment="时间范围显示文本")
    date = Column(String(20), comment="日期 YYYY-MM-DD")
    repeat_type = Column(String(20), default="none", comment="重复类型")
    category = Column(String(20), default="", comment="分类/标签")
    tag_color = Column(String(20), default="green", comment="标签颜色")
    user_id = Column(Integer, default=1, index=True, comment="用户ID")
    all_day = Column(Boolean, default=False, comment="是否全天")
    priority = Column(String(20), default="normal", comment="优先级")
    status = Column(String(20), default="active", comment="状态")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")


class LifeRule(Base):
    """生活管理 - 自动化规则表"""
    __tablename__ = "life_rules"

    id = Column(Integer, primary_key=True, index=True)
    rule_id = Column(Integer, index=True, comment="规则ID（业务ID）")
    title = Column(String(200), default="", comment="规则标题")
    description = Column(Text, default="", comment="规则描述")
    condition = Column(Text, default="", comment="触发条件")
    action = Column(Text, default="", comment="执行动作")
    category = Column(String(50), default="", comment="分类")
    enabled = Column(Boolean, default=True, comment="是否启用")
    user_id = Column(Integer, default=1, index=True, comment="用户ID")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")


class LifeTodo(Base):
    """生活管理 - 待办事项表"""
    __tablename__ = "life_todos"

    id = Column(Integer, primary_key=True, index=True)
    todo_id = Column(Integer, index=True, comment="待办ID（业务ID）")
    title = Column(String(200), comment="待办标题")
    description = Column(Text, default="", comment="描述")
    priority = Column(String(20), default="normal", comment="优先级")
    status = Column(String(20), default="todo", comment="状态：todo/in-progress/done")
    progress = Column(Integer, default=0, comment="进度 0-100")
    due_date = Column(String(20), nullable=True, comment="截止日期")
    category = Column(String(50), default="", comment="分类")
    user_id = Column(Integer, default=1, index=True, comment="用户ID")
    completed_at = Column(DateTime, nullable=True, comment="完成时间")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")


class LifeHabit(Base):
    """生活管理 - 习惯打卡表"""
    __tablename__ = "life_habits"

    id = Column(Integer, primary_key=True, index=True)
    habit_id = Column(Integer, index=True, comment="习惯ID（业务ID）")
    name = Column(String(100), comment="习惯名称")
    description = Column(Text, default="", comment="描述")
    category = Column(String(50), default="", comment="分类")
    icon = Column(String(20), default="", comment="图标")
    streak = Column(Integer, default=0, comment="连续打卡天数")
    target_count = Column(Integer, default=1, comment="目标次数")
    current_count = Column(Integer, default=0, comment="当前次数")
    done = Column(Boolean, default=False, comment="今日是否已完成")
    user_id = Column(Integer, default=1, index=True, comment="用户ID")
    frequency = Column(String(20), default="daily", comment="频率：daily/weekly/monthly")
    longest_streak = Column(Integer, default=0, comment="最长连续天数")
    status = Column(String(20), default="active", comment="状态")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")


class LifeScene(Base):
    """生活管理 - 场景模式表"""
    __tablename__ = "life_scenes"

    id = Column(Integer, primary_key=True, index=True)
    scene_id = Column(String(50), index=True, comment="场景ID（业务key）")
    name = Column(String(100), comment="场景名称")
    description = Column(Text, default="", comment="描述")
    icon = Column(String(20), default="", comment="图标")
    active = Column(Boolean, default=False, comment="是否当前激活")
    user_id = Column(Integer, default=1, index=True, comment="用户ID")
    settings_json = Column(JSON, default=dict, comment="场景配置（JSON）")
    is_active = Column(Boolean, default=False, comment="是否激活（兼容字段）")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")


class LifeFinanceCategory(Base):
    """生活管理 - 财务分类表"""
    __tablename__ = "life_finance_categories"

    id = Column(Integer, primary_key=True, index=True)
    category_id = Column(Integer, index=True, comment="分类ID（业务ID）")
    name = Column(String(100), comment="分类名称")
    type = Column(String(20), default="expense", comment="类型：income/expense")
    budget = Column(Float, default=0.0, comment="预算金额")
    spent = Column(Float, default=0.0, comment="已支出金额")
    percentage = Column(Float, default=0.0, comment="占比")
    color = Column(String(20), default="#1890FF", comment="颜色")
    user_id = Column(Integer, default=1, index=True, comment="用户ID")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")


class LifeMeta(Base):
    """生活管理 - 元数据表（key-value JSON 存储）"""
    __tablename__ = "life_meta"

    id = Column(Integer, primary_key=True, index=True)
    meta_key = Column(String(50), unique=True, index=True, comment="键名")
    meta_value = Column(JSON, default=dict, comment="值（JSON）")
    user_id = Column(Integer, default=1, index=True, comment="用户ID")


class LifeHabitRecord(Base):
    """生活管理 - 习惯打卡记录表"""
    __tablename__ = "life_habit_records"

    id = Column(Integer, primary_key=True, index=True)
    habit_id = Column(Integer, index=True, comment="习惯ID")
    date = Column(String(20), index=True, comment="打卡日期 YYYY-MM-DD")
    completed = Column(Boolean, default=True, comment="是否完成")
    note = Column(Text, default="", comment="打卡备注")
    user_id = Column(Integer, default=1, index=True, comment="用户ID")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")


class LifeFinanceRecord(Base):
    """生活管理 - 财务记录表"""
    __tablename__ = "life_finance_records"

    id = Column(Integer, primary_key=True, index=True)
    type = Column(String(20), default="expense", comment="类型：income/expense")
    amount = Column(Float, default=0.0, comment="金额")
    category = Column(String(50), default="", comment="分类")
    description = Column(Text, default="", comment="描述")
    transaction_date = Column(String(20), index=True, comment="交易日期 YYYY-MM-DD")
    user_id = Column(Integer, default=1, index=True, comment="用户ID")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
