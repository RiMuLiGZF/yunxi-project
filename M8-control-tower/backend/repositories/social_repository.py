"""
M8 人际关系 - 数据仓库层

封装联系人、交往记录、社交提醒、情商课程的数据库 CRUD。
迁移过渡期：优先读 DB，DB 为空时自动从内存默认数据初始化。
"""

from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import desc

from ..models import SocialContact, SocialInteraction, SocialReminder, SocialEQLesson


# ========== 默认种子数据 ==========

def _get_default_contacts(user_id: int = 1) -> List[SocialContact]:
    """获取默认联系人数据"""
    now = datetime.utcnow()
    return [
        SocialContact(name="张小明", avatar="👨‍💼", relationship_type="同事", importance=85,
                      tags=["工作", "朋友"], user_id=user_id, contact_count=12,
                      last_contact_at=now - timedelta(days=1)),
        SocialContact(name="李雨晴", avatar="👩‍🎓", relationship_type="同学", importance=92,
                      tags=["同学", "挚友"], user_id=user_id, contact_count=28,
                      last_contact_at=now - timedelta(days=3)),
        SocialContact(name="王大伟", avatar="👨‍🏫", relationship_type="导师", importance=70,
                      tags=["学业", "导师"], user_id=user_id, contact_count=8,
                      last_contact_at=now - timedelta(days=7)),
        SocialContact(name="陈思琪", avatar="👩‍💻", relationship_type="同事", importance=78,
                      tags=["工作", "项目组"], user_id=user_id, contact_count=15,
                      last_contact_at=now - timedelta(hours=2)),
        SocialContact(name="刘子豪", avatar="🧑‍🎨", relationship_type="朋友", importance=88,
                      tags=["朋友", "兴趣"], user_id=user_id, contact_count=35,
                      last_contact_at=now - timedelta(days=2)),
        SocialContact(name="赵雅婷", avatar="👩‍⚕️", relationship_type="家人", importance=95,
                      tags=["家人", "姐姐"], user_id=user_id, contact_count=50,
                      last_contact_at=now - timedelta(days=1)),
        SocialContact(name="孙浩然", avatar="👨‍🔬", relationship_type="合作伙伴", importance=65,
                      tags=["工作", "合作"], user_id=user_id, contact_count=6,
                      last_contact_at=now - timedelta(days=14)),
        SocialContact(name="周雨萱", avatar="👩‍🎨", relationship_type="朋友", importance=80,
                      tags=["朋友", "兴趣"], user_id=user_id, contact_count=20,
                      last_contact_at=now - timedelta(days=5)),
    ]


def _get_default_interactions(user_id: int = 1) -> List[SocialInteraction]:
    """获取默认交往记录数据"""
    now = datetime.utcnow()
    return [
        SocialInteraction(contact_id=4, contact_name="陈思琪", type="聊天",
                          content="讨论了项目进度，确认了下一阶段目标",
                          mood="positive", user_id=user_id,
                          created_at=now - timedelta(hours=6, minutes=30)),
        SocialInteraction(contact_id=6, contact_name="赵雅婷", type="电话",
                          content="聊了聊最近的生活，姐姐说周末回家吃饭",
                          mood="positive", user_id=user_id,
                          created_at=now - timedelta(days=1, hours=4)),
        SocialInteraction(contact_id=1, contact_name="张小明", type="会议",
                          content="项目周会，同步各模块进展",
                          mood="neutral", user_id=user_id,
                          created_at=now - timedelta(days=1, hours=18)),
        SocialInteraction(contact_id=2, contact_name="李雨晴", type="微信",
                          content="约了周末一起看电影",
                          mood="positive", user_id=user_id,
                          created_at=now - timedelta(days=3)),
        SocialInteraction(contact_id=5, contact_name="刘子豪", type="聚餐",
                          content="和朋友们一起吃了火锅，聊得很开心",
                          mood="positive", user_id=user_id,
                          created_at=now - timedelta(days=5)),
        SocialInteraction(contact_id=7, contact_name="孙浩然", type="邮件",
                          content="确认了合作项目的合同细节",
                          mood="neutral", user_id=user_id,
                          created_at=now - timedelta(days=14)),
    ]


def _get_default_reminders(user_id: int = 1) -> List[SocialReminder]:
    """获取默认社交提醒数据"""
    now = datetime.utcnow()
    return [
        SocialReminder(contact_id=2, reminder_type="birthday",
                       title="李雨晴生日",
                       description="下周三是李雨晴的生日，记得准备礼物",
                       reminder_date=now + timedelta(days=3),
                       priority="high", user_id=user_id),
        SocialReminder(contact_id=3, reminder_type="contact",
                       title="久未联系",
                       description="和王大伟导师已经1周没联系了，有空问候一下",
                       reminder_date=now - timedelta(days=7),
                       priority="medium", user_id=user_id),
        SocialReminder(contact_id=1, reminder_type="anniversary",
                       title="入职纪念日",
                       description="和张小明共事一周年纪念日",
                       reminder_date=now + timedelta(days=5),
                       priority="low", user_id=user_id),
        SocialReminder(reminder_type="event",
                       title="同学聚会",
                       description="高中同学聚会，记得参加",
                       reminder_date=now + timedelta(days=10),
                       priority="medium", user_id=user_id),
    ]


def _get_default_eq_lessons(user_id: int = 1) -> List[SocialEQLesson]:
    """获取默认情商课程数据"""
    return [
        SocialEQLesson(title="情绪识别与表达", category="情绪管理",
                       description="学习识别自己和他人的情绪，掌握有效表达方法",
                       progress=80, total_lessons=10, completed_lessons=8,
                       difficulty="intermediate", duration_minutes=300,
                       user_id=user_id),
        SocialEQLesson(title="有效沟通技巧", category="沟通能力",
                       description="提升沟通效率，建立良好的人际关系",
                       progress=50, total_lessons=12, completed_lessons=6,
                       difficulty="beginner", duration_minutes=360,
                       user_id=user_id),
        SocialEQLesson(title="冲突管理与解决", category="冲突处理",
                       description="学会以积极的方式处理人际冲突",
                       progress=20, total_lessons=8, completed_lessons=2,
                       difficulty="advanced", duration_minutes=240,
                       user_id=user_id),
        SocialEQLesson(title="同理心培养", category="社交技能",
                       description="站在他人角度思考，增进理解与信任",
                       progress=65, total_lessons=6, completed_lessons=4,
                       difficulty="intermediate", duration_minutes=180,
                       user_id=user_id),
    ]


# ========== 初始化种子数据 ==========

def seed_social_data(db: Session, user_id: int = 1) -> bool:
    """初始化社交模块的默认数据（幂等）

    Returns:
        True 表示执行了初始化，False 表示已有数据跳过
    """
    # 检查联系人表是否为空
    contact_count = db.query(SocialContact).filter(SocialContact.user_id == user_id).count()
    if contact_count > 0:
        return False

    # 插入默认联系人
    for contact in _get_default_contacts(user_id):
        db.add(contact)
    db.flush()  # 获取生成的 ID

    # 重新获取联系人以获取 ID（用于交往记录和提醒）
    contacts = db.query(SocialContact).filter(SocialContact.user_id == user_id).all()
    name_to_id = {c.name: c.id for c in contacts}

    # 插入默认交往记录（更新 contact_id）
    for interaction in _get_default_interactions(user_id):
        if interaction.contact_id and interaction.contact_name in name_to_id:
            interaction.contact_id = name_to_id[interaction.contact_name]
        db.add(interaction)

    # 插入默认提醒（根据联系人姓名更新 contact_id）
    reminder_defaults = _get_default_reminders(user_id)
    for reminder in reminder_defaults:
        if reminder.contact_id:
            # 根据默认数据的索引映射到实际 ID
            contact_names = ["张小明", "李雨晴", "王大伟", "陈思琪", "刘子豪", "赵雅婷", "孙浩然", "周雨萱"]
            idx = reminder.contact_id - 1
            if idx < len(contact_names) and contact_names[idx] in name_to_id:
                reminder.contact_id = name_to_id[contact_names[idx]]
        db.add(reminder)

    # 插入默认情商课程
    for lesson in _get_default_eq_lessons(user_id):
        db.add(lesson)

    db.commit()
    print(f"[Seed] 社交模块默认数据初始化完成 (user_id={user_id})")
    return True


# ========== Repository 类 ==========

class SocialRepository:
    """人际关系数据仓库"""

    def __init__(self, db: Session, user_id: int = 1):
        self.db = db
        self.user_id = user_id
        self._ensure_seeded()

    def _ensure_seeded(self):
        """确保种子数据已初始化"""
        try:
            seed_social_data(self.db, self.user_id)
        except Exception as e:
            print(f"[Seed] 社交数据初始化跳过: {e}")

    # ---------- 联系人 ----------

    def list_contacts(self, relation: Optional[str] = None,
                      tag: Optional[str] = None) -> List[SocialContact]:
        """获取联系人列表（支持筛选）"""
        query = self.db.query(SocialContact).filter(SocialContact.user_id == self.user_id)
        if relation:
            query = query.filter(SocialContact.relationship_type == relation)
        contacts = query.order_by(desc(SocialContact.importance)).all()
        if tag:
            contacts = [c for c in contacts if tag in (c.tags or [])]
        return contacts

    def get_contact(self, contact_id: int) -> Optional[SocialContact]:
        """按 ID 获取联系人"""
        return (
            self.db.query(SocialContact)
            .filter(SocialContact.id == contact_id, SocialContact.user_id == self.user_id)
            .first()
        )

    def create_contact(self, name: str, avatar: str = "👤",
                       relation: str = "朋友", tags: Optional[List[str]] = None) -> SocialContact:
        """创建联系人"""
        contact = SocialContact(
            name=name,
            avatar=avatar,
            relationship_type=relation,
            importance=50,
            tags=tags or [],
            contact_count=0,
            last_contact_at=None,
            user_id=self.user_id,
        )
        self.db.add(contact)
        self.db.commit()
        self.db.refresh(contact)
        return contact

    def update_contact(self, contact_id: int, **kwargs) -> Optional[SocialContact]:
        """更新联系人信息

        支持字段: name, avatar, relationship_type/relation, importance/closeness,
        tags, phone, email, note
        """
        contact = self.get_contact(contact_id)
        if not contact:
            return None

        # 字段映射（兼容前端字段名）
        field_map = {
            "name": "name",
            "avatar": "avatar",
            "relation": "relationship_type",
            "relationship_type": "relationship_type",
            "closeness": "importance",
            "importance": "importance",
            "tags": "tags",
            "phone": "phone",
            "email": "email",
            "note": "note",
        }

        for key, value in kwargs.items():
            if value is None:
                continue
            attr = field_map.get(key)
            if attr and hasattr(contact, attr):
                setattr(contact, attr, value)

        self.db.commit()
        self.db.refresh(contact)
        return contact

    def delete_contact(self, contact_id: int) -> bool:
        """删除联系人（同时删除相关的交往记录和提醒）"""
        contact = self.get_contact(contact_id)
        if not contact:
            return False

        # 删除相关交往记录
        self.db.query(SocialInteraction).filter(
            SocialInteraction.user_id == self.user_id,
            SocialInteraction.contact_id == contact_id,
        ).delete(synchronize_session=False)

        # 删除相关提醒
        self.db.query(SocialReminder).filter(
            SocialReminder.user_id == self.user_id,
            SocialReminder.contact_id == contact_id,
        ).delete(synchronize_session=False)

        self.db.delete(contact)
        self.db.commit()
        return True

    def update_contact_stats(self, contact_id: int):
        """更新联系人的联系统计（新增交往后调用）"""
        contact = self.get_contact(contact_id)
        if contact:
            contact.last_contact_at = datetime.utcnow()
            contact.contact_count += 1
            self.db.commit()

    def search_contacts(self, keyword: str) -> List[SocialContact]:
        """搜索联系人（按姓名模糊匹配）"""
        if not keyword:
            return []
        return (
            self.db.query(SocialContact)
            .filter(
                SocialContact.user_id == self.user_id,
                SocialContact.name.like(f"%{keyword}%"),
            )
            .order_by(desc(SocialContact.importance))
            .all()
        )

    def count_contacts(self) -> int:
        """联系人总数"""
        return (
            self.db.query(SocialContact)
            .filter(SocialContact.user_id == self.user_id)
            .count()
        )

    def avg_importance(self) -> float:
        """平均重要度"""
        from sqlalchemy import func
        result = (
            self.db.query(func.avg(SocialContact.importance))
            .filter(SocialContact.user_id == self.user_id)
            .scalar()
        )
        return float(result or 0)

    # ---------- 交往记录 ----------

    def list_interactions(self, contact_id: Optional[int] = None,
                          limit: int = 20) -> List[SocialInteraction]:
        """获取交往记录列表"""
        query = self.db.query(SocialInteraction).filter(SocialInteraction.user_id == self.user_id)
        if contact_id:
            query = query.filter(SocialInteraction.contact_id == contact_id)
        return query.order_by(desc(SocialInteraction.created_at)).limit(limit).all()

    def create_interaction(self, contact_id: int, contact_name: str,
                           type: str, content: str,
                           emotion: str = "neutral",
                           duration_minutes: int = 0,
                           location: str = "") -> SocialInteraction:
        """创建交往记录"""
        interaction = SocialInteraction(
            contact_id=contact_id,
            contact_name=contact_name,
            type=type,
            content=content,
            mood=emotion,
            duration_minutes=duration_minutes,
            location=location,
            user_id=self.user_id,
        )
        self.db.add(interaction)
        self.db.commit()
        self.db.refresh(interaction)
        return interaction

    def get_interaction(self, interaction_id: int) -> Optional[SocialInteraction]:
        """按 ID 获取交往记录"""
        return (
            self.db.query(SocialInteraction)
            .filter(SocialInteraction.id == interaction_id, SocialInteraction.user_id == self.user_id)
            .first()
        )

    def update_interaction(self, interaction_id: int, **kwargs) -> Optional[SocialInteraction]:
        """更新交往记录

        支持字段: type, content, mood/emotion, duration_minutes, location, contact_id, contact_name
        """
        interaction = self.get_interaction(interaction_id)
        if not interaction:
            return None

        # 字段映射（兼容前端字段名）
        field_map = {
            "type": "type",
            "content": "content",
            "emotion": "mood",
            "mood": "mood",
            "duration_minutes": "duration_minutes",
            "location": "location",
            "contact_id": "contact_id",
            "contact_name": "contact_name",
        }

        for key, value in kwargs.items():
            if value is None:
                continue
            attr = field_map.get(key)
            if attr and hasattr(interaction, attr):
                setattr(interaction, attr, value)

        self.db.commit()
        self.db.refresh(interaction)
        return interaction

    def delete_interaction(self, interaction_id: int) -> bool:
        """删除交往记录"""
        interaction = (
            self.db.query(SocialInteraction)
            .filter(SocialInteraction.id == interaction_id, SocialInteraction.user_id == self.user_id)
            .first()
        )
        if interaction:
            self.db.delete(interaction)
            self.db.commit()
            return True
        return False

    def count_interactions(self) -> int:
        """交往记录总数"""
        return (
            self.db.query(SocialInteraction)
            .filter(SocialInteraction.user_id == self.user_id)
            .count()
        )

    def count_week_interactions(self) -> int:
        """本周交往次数"""
        week_ago = datetime.utcnow() - timedelta(days=7)
        return (
            self.db.query(SocialInteraction)
            .filter(
                SocialInteraction.user_id == self.user_id,
                SocialInteraction.created_at >= week_ago,
            )
            .count()
        )

    # ---------- 社交提醒 ----------

    def list_reminders(self, status: Optional[str] = None,
                       reminder_type: Optional[str] = None,
                       priority: Optional[str] = None) -> List[SocialReminder]:
        """获取所有提醒（支持按状态、类型、优先级筛选）"""
        query = self.db.query(SocialReminder).filter(SocialReminder.user_id == self.user_id)
        if status:
            query = query.filter(SocialReminder.status == status)
        if reminder_type:
            query = query.filter(SocialReminder.reminder_type == reminder_type)
        if priority:
            query = query.filter(SocialReminder.priority == priority)
        return query.order_by(SocialReminder.reminder_date.asc().nullslast()).all()

    def create_reminder(self, type: str, title: str,
                        description: str = "", date: str = "",
                        priority: str = "medium") -> SocialReminder:
        """创建提醒"""
        # 尝试解析日期
        reminder_date = None
        if date:
            try:
                reminder_date = datetime.strptime(date, "%Y-%m-%d")
            except ValueError:
                try:
                    reminder_date = datetime.strptime(date, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    pass

        reminder = SocialReminder(
            reminder_type=type,
            title=title,
            description=description,
            reminder_date=reminder_date,
            priority=priority,
            user_id=self.user_id,
        )
        self.db.add(reminder)
        self.db.commit()
        self.db.refresh(reminder)
        return reminder

    def get_reminder(self, reminder_id: int) -> Optional[SocialReminder]:
        """按 ID 获取提醒"""
        return (
            self.db.query(SocialReminder)
            .filter(SocialReminder.id == reminder_id, SocialReminder.user_id == self.user_id)
            .first()
        )

    def update_reminder_status(self, reminder_id: int, status: str) -> Optional[SocialReminder]:
        """更新提醒状态

        Args:
            status: pending / done / cancelled
        """
        reminder = self.get_reminder(reminder_id)
        if not reminder:
            return None

        if status in ("pending", "done", "cancelled"):
            reminder.status = status
            self.db.commit()
            self.db.refresh(reminder)
        return reminder

    def delete_reminder(self, reminder_id: int) -> bool:
        """删除提醒"""
        reminder = (
            self.db.query(SocialReminder)
            .filter(SocialReminder.id == reminder_id, SocialReminder.user_id == self.user_id)
            .first()
        )
        if reminder:
            self.db.delete(reminder)
            self.db.commit()
            return True
        return False

    # ---------- 情商课程 ----------

    def list_eq_lessons(self) -> List[SocialEQLesson]:
        """获取情商课程列表"""
        return (
            self.db.query(SocialEQLesson)
            .filter(SocialEQLesson.user_id == self.user_id)
            .order_by(SocialEQLesson.id.asc())
            .all()
        )

    def get_eq_lesson(self, lesson_id: int) -> Optional[SocialEQLesson]:
        """按 ID 获取情商课程"""
        return (
            self.db.query(SocialEQLesson)
            .filter(SocialEQLesson.id == lesson_id, SocialEQLesson.user_id == self.user_id)
            .first()
        )

    def update_eq_lesson_progress(self, lesson_id: int, progress: int,
                                  completed_lessons: Optional[int] = None) -> Optional[SocialEQLesson]:
        """更新情商课程进度"""
        lesson = self.get_eq_lesson(lesson_id)
        if not lesson:
            return None

        # 限制进度在 0-100 范围内
        lesson.progress = max(0, min(100, progress))
        if completed_lessons is not None:
            lesson.completed_lessons = max(0, completed_lessons)

        self.db.commit()
        self.db.refresh(lesson)
        return lesson

    def get_eq_score(self) -> Dict[str, Any]:
        """获取情商评分及维度数据"""
        lessons = self.list_eq_lessons()
        total_progress = sum(l.progress for l in lessons) / len(lessons) if lessons else 0
        # 基础分 + 课程进度加成
        base_score = 60
        eq_score = min(99, int(base_score + total_progress * 0.35))

        # 等级
        if eq_score >= 90:
            level = "优秀"
        elif eq_score >= 75:
            level = "良好"
        elif eq_score >= 60:
            level = "一般"
        else:
            level = "待提升"

        return {
            "score": eq_score,
            "level": level,
            "dimensions": [
                {"name": "自我认知", "score": min(95, eq_score + 4)},
                {"name": "情绪管理", "score": min(95, eq_score - 3)},
                {"name": "自我激励", "score": min(95, eq_score + 2)},
                {"name": "同理心", "score": eq_score},
                {"name": "社交技能", "score": min(95, eq_score - 2)},
            ],
        }
