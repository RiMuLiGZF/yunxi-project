"""
M8 管理工作台 - 复盘总结模型

包含 ReviewReview, ReviewDiary, ReviewDecision, ReviewEmotion, ReviewBias。
"""

from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, JSON, Float
from datetime import datetime

from .base import Base


class ReviewReview(Base):
    """复盘总结 - 复盘记录表"""
    __tablename__ = "review_reviews"

    id = Column(Integer, primary_key=True, index=True)
    review_id = Column(Integer, index=True, comment="复盘ID（业务ID）")
    title = Column(String(255), comment="复盘标题")
    content = Column(Text, default="", comment="复盘内容")
    type = Column(String(20), default="daily", comment="类型：daily/weekly/monthly")
    rating = Column(Integer, default=0, comment="评分")
    quality = Column(String(20), default="medium", comment="质量：low/medium/high")
    insights = Column(JSON, default=list, comment="洞察列表")
    actions = Column(JSON, default=list, comment="行动项列表")
    date = Column(String(20), default="", comment="复盘日期")
    word_count = Column(Integer, default=0, comment="字数")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")
    user_id = Column(Integer, default=1, index=True, comment="用户ID")


class ReviewDiary(Base):
    """复盘总结 - 日记表"""
    __tablename__ = "review_diaries"

    id = Column(Integer, primary_key=True, index=True)
    diary_id = Column(Integer, index=True, comment="日记ID（业务ID）")
    title = Column(String(255), comment="日记标题")
    content = Column(Text, default="", comment="日记内容")
    mood = Column(String(50), default="neutral", comment="心情")
    weather = Column(String(50), default="", comment="天气")
    tags = Column(JSON, default=list, comment="标签列表")
    word_count = Column(Integer, default=0, comment="字数")
    encrypted = Column(Boolean, default=True, comment="是否加密")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")
    user_id = Column(Integer, default=1, index=True, comment="用户ID")


class ReviewDecision(Base):
    """复盘总结 - 决策记录表"""
    __tablename__ = "review_decisions"

    id = Column(Integer, primary_key=True, index=True)
    decision_id = Column(Integer, index=True, comment="决策ID（业务ID）")
    title = Column(String(255), comment="决策标题")
    description = Column(Text, default="", comment="决策描述")
    alternatives = Column(JSON, default=list, comment="备选方案列表")
    outcome = Column(Text, default="", comment="结果")
    lessons = Column(Text, default="", comment="经验教训")
    status = Column(String(20), default="pending", comment="状态：pending/executing/completed")
    final_choice = Column(String(255), default="", comment="最终选择")
    result = Column(Text, default="", comment="结果描述")
    emotion_level = Column(Integer, default=5, comment="情绪强度 1-10")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")
    user_id = Column(Integer, default=1, index=True, comment="用户ID")


class ReviewEmotion(Base):
    """复盘总结 - 情绪记录表"""
    __tablename__ = "review_emotions"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(String(20), index=True, comment="日期 YYYY-MM-DD")
    emotion = Column(String(50), default="neutral", comment="情绪类型")
    intensity = Column(Integer, default=5, comment="情绪强度 1-10")
    trigger = Column(String(500), default="", comment="触发因素")
    note = Column(Text, default="", comment="备注")
    created_at = Column(DateTime, default=datetime.utcnow, comment="记录时间")
    user_id = Column(Integer, default=1, index=True, comment="用户ID")


class ReviewBias(Base):
    """复盘总结 - 认知偏差表"""
    __tablename__ = "review_biases"

    id = Column(Integer, primary_key=True, index=True)
    bias_id = Column(Integer, index=True, comment="偏差ID（业务ID）")
    name = Column(String(100), comment="偏差名称")
    description = Column(Text, default="", comment="偏差描述")
    category = Column(String(50), default="", comment="分类")
    level = Column(String(20), default="low", comment="风险等级：low/medium/high")
    detected_count = Column(Integer, default=0, comment="检测次数")
    last_detected = Column(DateTime, nullable=True, comment="最近检测时间")
    suggestions = Column(JSON, default=list, comment="建议列表")
    user_id = Column(Integer, default=1, index=True, comment="用户ID")
