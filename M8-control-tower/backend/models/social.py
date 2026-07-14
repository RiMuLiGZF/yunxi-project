"""
M8 管理工作台 - 人际关系模型

包含 SocialContact, SocialInteraction, SocialReminder, SocialEQLesson。
"""

from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, JSON, Float
from datetime import datetime

from .base import Base


class SocialContact(Base):
    """人际关系 - 联系人表"""
    __tablename__ = "social_contacts"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), index=True, comment="姓名")
    avatar = Column(String(20), default="", comment="头像emoji")
    relationship_type = Column(String(50), default="朋友", index=True, comment="关系类型：同事/同学/朋友/家人/导师等")
    importance = Column(Integer, default=50, comment="重要度/亲密度 0-100")
    tags = Column(JSON, default=list, comment="标签列表")
    phone = Column(String(50), default="", comment="电话")
    email = Column(String(100), default="", comment="邮箱")
    note = Column(Text, default="", comment="备注")
    last_contact_at = Column(DateTime, nullable=True, comment="最后联系时间")
    contact_count = Column(Integer, default=0, comment="联系次数")
    user_id = Column(Integer, default=1, index=True, comment="用户ID")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")

    def to_dict(self) -> dict:
        """转换为字典（兼容前端字段名）"""
        last_contact_text = ""
        if self.last_contact_at:
            now = datetime.utcnow()
            diff = now - self.last_contact_at
            days = diff.days
            if days == 0:
                hours = diff.seconds // 3600
                if hours == 0:
                    last_contact_text = "刚刚"
                else:
                    last_contact_text = f"{hours}小时前"
            elif days == 1:
                last_contact_text = "昨天"
            elif days < 7:
                last_contact_text = f"{days}天前"
            elif days < 30:
                weeks = days // 7
                last_contact_text = f"{weeks}周前"
            else:
                last_contact_text = f"{days // 30}个月前"

        return {
            "id": self.id,
            "name": self.name,
            "avatar": self.avatar,
            "relation": self.relationship_type,
            "closeness": self.importance,
            "last_contact": last_contact_text,
            "contact_count": self.contact_count,
            "tags": self.tags or [],
            "phone": self.phone,
            "email": self.email,
            "note": self.note,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }


class SocialInteraction(Base):
    """人际关系 - 交往记录表"""
    __tablename__ = "social_interactions"

    id = Column(Integer, primary_key=True, index=True)
    contact_id = Column(Integer, index=True, comment="联系人ID")
    contact_name = Column(String(100), default="", comment="联系人姓名快照")
    type = Column(String(50), default="聊天", index=True, comment="交往类型：聊天/电话/会议/微信/聚餐/邮件等")
    content = Column(Text, default="", comment="交往内容")
    duration_minutes = Column(Integer, default=0, comment="时长（分钟）")
    mood = Column(String(20), default="neutral", comment="心情：positive/neutral/negative")
    location = Column(String(100), default="", comment="地点")
    user_id = Column(Integer, default=1, index=True, comment="用户ID")
    created_at = Column(DateTime, default=datetime.utcnow, index=True, comment="交往时间")

    def to_dict(self) -> dict:
        """转换为字典（兼容前端字段名）"""
        date_text = "刚刚"
        if self.created_at:
            now = datetime.utcnow()
            diff = now - self.created_at
            days = diff.days
            if days == 0:
                hours = diff.seconds // 3600
                if hours == 0:
                    mins = diff.seconds // 60
                    date_text = f"{mins}分钟前" if mins > 0 else "刚刚"
                else:
                    date_text = f"今天 {self.created_at.strftime('%H:%M')}"
            elif days == 1:
                date_text = f"昨天 {self.created_at.strftime('%H:%M')}"
            elif days < 7:
                date_text = f"{days}天前"
            else:
                date_text = self.created_at.strftime("%Y-%m-%d")

        return {
            "id": self.id,
            "contact_id": self.contact_id,
            "contact_name": self.contact_name,
            "type": self.type,
            "content": self.content,
            "date": date_text,
            "emotion": self.mood,
            "duration_minutes": self.duration_minutes,
            "location": self.location,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


class SocialReminder(Base):
    """人际关系 - 社交提醒表"""
    __tablename__ = "social_reminders"

    id = Column(Integer, primary_key=True, index=True)
    contact_id = Column(Integer, default=0, index=True, comment="关联联系人ID（0表示无）")
    reminder_type = Column(String(50), default="contact", index=True, comment="提醒类型：birthday/contact/anniversary/event等")
    title = Column(String(200), default="", comment="提醒标题")
    description = Column(Text, default="", comment="提醒描述")
    reminder_date = Column(DateTime, nullable=True, comment="提醒日期")
    repeat = Column(String(20), default="none", comment="重复周期：none/daily/weekly/monthly/yearly")
    status = Column(String(20), default="pending", index=True, comment="状态：pending/done/cancelled")
    priority = Column(String(20), default="medium", comment="优先级：high/medium/low")
    user_id = Column(Integer, default=1, index=True, comment="用户ID")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")

    def to_dict(self) -> dict:
        """转换为字典（兼容前端字段名）"""
        date_text = ""
        if self.reminder_date:
            now = datetime.utcnow()
            diff = self.reminder_date - now
            days = diff.days
            if days < 0:
                date_text = f"{abs(days)}天前"
            elif days == 0:
                date_text = "今天"
            elif days == 1:
                date_text = "明天"
            elif days < 7:
                date_text = f"{days}天后"
            else:
                date_text = self.reminder_date.strftime("%Y-%m-%d")

        return {
            "id": self.id,
            "type": self.reminder_type,
            "title": self.title,
            "description": self.description,
            "date": date_text,
            "priority": self.priority,
            "status": self.status,
            "repeat": self.repeat,
            "contact_id": self.contact_id,
            "reminder_date": self.reminder_date.strftime("%Y-%m-%d") if self.reminder_date else None,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


class SocialEQLesson(Base):
    """人际关系 - 情商课程表"""
    __tablename__ = "social_eq_lessons"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), default="", comment="课程标题")
    category = Column(String(50), default="情绪管理", index=True, comment="分类")
    content = Column(Text, default="", comment="课程内容简介")
    difficulty = Column(String(20), default="beginner", comment="难度：beginner/intermediate/advanced")
    duration_minutes = Column(Integer, default=0, comment="预计时长（分钟）")
    completed = Column(Boolean, default=False, comment="是否完成")
    progress = Column(Integer, default=0, comment="进度百分比 0-100")
    total_lessons = Column(Integer, default=1, comment="总课时数")
    completed_lessons = Column(Integer, default=0, comment="已完成课时数")
    description = Column(Text, default="", comment="课程描述")
    user_id = Column(Integer, default=1, index=True, comment="用户ID")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")

    def to_dict(self) -> dict:
        """转换为字典（兼容前端字段名）"""
        return {
            "id": self.id,
            "title": self.title,
            "progress": self.progress,
            "total_lessons": self.total_lessons,
            "completed_lessons": self.completed_lessons,
            "description": self.description,
            "category": self.category,
            "content": self.content,
            "difficulty": self.difficulty,
            "duration_minutes": self.duration_minutes,
            "completed": self.completed,
        }
