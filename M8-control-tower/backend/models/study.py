"""
M8 管理工作台 - 学业规划模型

包含 StudyGoal, StudyPlan, StudyNote, StudyKnowledgeCategory, StudyExam, StudyProgress, StudyMeta。
"""

from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, JSON, Float
from datetime import datetime

from .base import Base


class StudyGoal(Base):
    """学业规划 - 学习目标表（树形结构）"""
    __tablename__ = "study_goals"

    id = Column(Integer, primary_key=True, index=True)
    goal_id = Column(Integer, index=True, comment="目标ID（业务ID）")
    title = Column(String(200), comment="目标标题")
    description = Column(Text, default="", comment="目标描述")
    parent_id = Column(Integer, nullable=True, comment="父目标ID")
    status = Column(String(20), default="not-started", comment="状态：not-started/in-progress/complete/warning")
    progress = Column(Integer, default=0, comment="进度 0-100")
    priority = Column(String(20), default="normal", comment="优先级")
    deadline = Column(String(20), nullable=True, comment="截止日期")
    order_index = Column(Integer, default=0, comment="排序")
    icon = Column(String(20), default="", comment="图标")
    expanded = Column(Boolean, default=True, comment="是否展开")
    level = Column(Integer, default=0, comment="层级")
    extra = Column(JSON, default=dict, comment="扩展字段（JSON）")
    user_id = Column(Integer, default=1, index=True, comment="用户ID")


class StudyPlan(Base):
    """学业规划 - 学习计划表"""
    __tablename__ = "study_plans"

    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(Integer, index=True, comment="计划ID（业务ID）")
    title = Column(String(200), comment="计划标题")
    content = Column(Text, default="", comment="计划内容")
    subject = Column(String(50), default="", comment="科目")
    status = Column(String(20), default="pending", comment="状态")
    start_time = Column(String(10), default="09:00", comment="开始时间 HH:MM")
    end_time = Column(String(10), default="10:00", comment="结束时间 HH:MM")
    date = Column(String(20), comment="日期 YYYY-MM-DD")
    duration = Column(Float, default=1.0, comment="时长（小时）")
    priority = Column(String(20), default="", comment="优先级")
    completed = Column(Boolean, default=False, comment="是否完成")
    user_id = Column(Integer, default=1, index=True, comment="用户ID")


class StudyNote(Base):
    """学业规划 - 学习笔记表"""
    __tablename__ = "study_notes"

    id = Column(Integer, primary_key=True, index=True)
    note_id = Column(Integer, index=True, comment="笔记ID（业务ID）")
    title = Column(String(200), comment="笔记标题")
    content = Column(Text, default="", comment="笔记内容")
    category = Column(String(50), default="", comment="分类/科目")
    tags = Column(JSON, default=list, comment="标签列表")
    important = Column(Boolean, default=False, comment="是否重要")
    date_label = Column(String(20), default="", comment="显示用日期标签")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")
    user_id = Column(Integer, default=1, index=True, comment="用户ID")


class StudyKnowledgeCategory(Base):
    """学业规划 - 知识分类表"""
    __tablename__ = "study_knowledge_categories"

    id = Column(Integer, primary_key=True, index=True)
    category_id = Column(Integer, index=True, comment="分类ID（业务ID）")
    name = Column(String(100), comment="分类名称")
    description = Column(Text, default="", comment="分类描述")
    parent_id = Column(Integer, nullable=True, comment="父分类ID")
    note_count = Column(Integer, default=0, comment="笔记/知识点数量")
    icon = Column(String(20), default="", comment="图标")
    unit = Column(String(20), default="", comment="数量单位")
    user_id = Column(Integer, default=1, index=True, comment="用户ID")


class StudyExam(Base):
    """学业规划 - 考试计划表"""
    __tablename__ = "study_exams"

    id = Column(Integer, primary_key=True, index=True)
    exam_id = Column(Integer, index=True, comment="考试ID（业务ID）")
    name = Column(String(200), comment="考试名称")
    subject = Column(String(50), default="", comment="科目")
    exam_date = Column(String(30), comment="考试日期时间 YYYY-MM-DD HH:MM")
    location = Column(String(200), default="", comment="考试地点")
    score = Column(Float, nullable=True, comment="分数")
    status = Column(String(20), default="upcoming", comment="状态：upcoming/completed")
    urgency = Column(String(20), default="", comment="紧急程度")
    color_theme = Column(String(20), default="blue", comment="颜色主题")
    user_id = Column(Integer, default=1, index=True, comment="用户ID")


class StudyProgress(Base):
    """学业规划 - 科目进度表"""
    __tablename__ = "study_progress"

    id = Column(Integer, primary_key=True, index=True)
    subject = Column(String(50), index=True, comment="科目名称")
    progress = Column(Integer, default=0, comment="进度百分比 0-100")
    total_hours = Column(Float, default=0.0, comment="总学习时长（小时）")
    mastered_topics = Column(Integer, default=0, comment="已掌握知识点数")
    total_topics = Column(Integer, default=0, comment="总知识点数")
    color = Column(String(20), default="blue", comment="进度条颜色")
    user_id = Column(Integer, default=1, index=True, comment="用户ID")


class StudyMeta(Base):
    """学业规划 - 元数据表（key-value JSON 存储）"""
    __tablename__ = "study_meta"

    id = Column(Integer, primary_key=True, index=True)
    meta_key = Column(String(50), unique=True, index=True, comment="键名")
    meta_value = Column(JSON, default=dict, comment="值（JSON）")
    user_id = Column(Integer, default=1, index=True, comment="用户ID")
