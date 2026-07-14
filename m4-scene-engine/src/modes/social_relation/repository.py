"""人际关系模式 - 数据访问层.

封装联系人、交往记录、社交提醒、情商课程的数据库 CRUD 操作。
首次使用时自动初始化种子数据，确保开箱即用。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from src.common.db_transaction import transactional_scope
from src.models.db import (
    SocialContactDB,
    SocialEqLessonDB,
    SocialInteractionDB,
    SocialReminderDB,
)

import structlog

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 种子数据
# ---------------------------------------------------------------------------


def _get_default_contacts(user_id: str = "default") -> list[SocialContactDB]:
    """获取默认联系人种子数据.

    Args:
        user_id: 用户 ID

    Returns:
        默认联系人列表
    """
    now = datetime.utcnow()
    return [
        SocialContactDB(name="张小明", avatar="👨‍💼", relationship_type="同事",
                        importance=85, tags=["工作", "朋友"], user_id=user_id,
                        contact_count=12, last_contact_at=now - timedelta(days=1)),
        SocialContactDB(name="李雨晴", avatar="👩‍🎓", relationship_type="同学",
                        importance=92, tags=["同学", "挚友"], user_id=user_id,
                        contact_count=28, last_contact_at=now - timedelta(days=3)),
        SocialContactDB(name="王大伟", avatar="👨‍🏫", relationship_type="导师",
                        importance=70, tags=["学业", "导师"], user_id=user_id,
                        contact_count=8, last_contact_at=now - timedelta(days=7)),
        SocialContactDB(name="陈思琪", avatar="👩‍💻", relationship_type="同事",
                        importance=78, tags=["工作", "项目组"], user_id=user_id,
                        contact_count=15, last_contact_at=now - timedelta(hours=2)),
        SocialContactDB(name="刘子豪", avatar="🧑‍🎨", relationship_type="朋友",
                        importance=88, tags=["朋友", "兴趣"], user_id=user_id,
                        contact_count=35, last_contact_at=now - timedelta(days=2)),
        SocialContactDB(name="赵雅婷", avatar="👩‍⚕️", relationship_type="家人",
                        importance=95, tags=["家人", "姐姐"], user_id=user_id,
                        contact_count=50, last_contact_at=now - timedelta(days=1)),
        SocialContactDB(name="孙浩然", avatar="👨‍🔬", relationship_type="合作伙伴",
                        importance=65, tags=["工作", "合作"], user_id=user_id,
                        contact_count=6, last_contact_at=now - timedelta(days=14)),
        SocialContactDB(name="周雨萱", avatar="👩‍🎨", relationship_type="朋友",
                        importance=80, tags=["朋友", "兴趣"], user_id=user_id,
                        contact_count=20, last_contact_at=now - timedelta(days=5)),
    ]


def _get_default_interactions(user_id: str = "default") -> list[SocialInteractionDB]:
    """获取默认交往记录种子数据.

    Args:
        user_id: 用户 ID

    Returns:
        默认交往记录列表
    """
    now = datetime.utcnow()
    return [
        SocialInteractionDB(contact_id=4, contact_name="陈思琪", type="聊天",
                            content="讨论了项目进度，确认了下一阶段目标",
                            mood="positive", user_id=user_id,
                            created_at=now - timedelta(hours=6, minutes=30)),
        SocialInteractionDB(contact_id=6, contact_name="赵雅婷", type="电话",
                            content="聊了聊最近的生活，姐姐说周末回家吃饭",
                            mood="positive", user_id=user_id,
                            created_at=now - timedelta(days=1, hours=4)),
        SocialInteractionDB(contact_id=1, contact_name="张小明", type="会议",
                            content="项目周会，同步各模块进展",
                            mood="neutral", user_id=user_id,
                            created_at=now - timedelta(days=1, hours=18)),
        SocialInteractionDB(contact_id=2, contact_name="李雨晴", type="微信",
                            content="约了周末一起看电影",
                            mood="positive", user_id=user_id,
                            created_at=now - timedelta(days=3)),
        SocialInteractionDB(contact_id=5, contact_name="刘子豪", type="聚餐",
                            content="和朋友们一起吃了火锅，聊得很开心",
                            mood="positive", user_id=user_id,
                            created_at=now - timedelta(days=5)),
        SocialInteractionDB(contact_id=7, contact_name="孙浩然", type="邮件",
                            content="确认了合作项目的合同细节",
                            mood="neutral", user_id=user_id,
                            created_at=now - timedelta(days=14)),
    ]


def _get_default_reminders(user_id: str = "default") -> list[SocialReminderDB]:
    """获取默认社交提醒种子数据.

    Args:
        user_id: 用户 ID

    Returns:
        默认提醒列表
    """
    now = datetime.utcnow()
    return [
        SocialReminderDB(contact_id=2, reminder_type="birthday",
                         title="李雨晴生日",
                         description="下周三是李雨晴的生日，记得准备礼物",
                         reminder_date=now + timedelta(days=3),
                         priority="high", user_id=user_id),
        SocialReminderDB(contact_id=3, reminder_type="contact",
                         title="久未联系",
                         description="和王大伟导师已经1周没联系了，有空问候一下",
                         reminder_date=now - timedelta(days=7),
                         priority="medium", user_id=user_id),
        SocialReminderDB(contact_id=1, reminder_type="anniversary",
                         title="入职纪念日",
                         description="和张小明共事一周年纪念日",
                         reminder_date=now + timedelta(days=5),
                         priority="low", user_id=user_id),
        SocialReminderDB(reminder_type="event",
                         title="同学聚会",
                         description="高中同学聚会，记得参加",
                         reminder_date=now + timedelta(days=10),
                         priority="medium", user_id=user_id),
    ]


def _get_default_eq_lessons(user_id: str = "default") -> list[SocialEqLessonDB]:
    """获取默认情商课程种子数据.

    Args:
        user_id: 用户 ID

    Returns:
        默认情商课程列表
    """
    return [
        SocialEqLessonDB(title="情绪识别与表达", category="情绪管理",
                         description="学习识别自己和他人的情绪，掌握有效表达方法",
                         progress=80, total_lessons=10, completed_lessons=8,
                         difficulty="intermediate", duration_minutes=300,
                         user_id=user_id),
        SocialEqLessonDB(title="有效沟通技巧", category="沟通能力",
                         description="提升沟通效率，建立良好的人际关系",
                         progress=50, total_lessons=12, completed_lessons=6,
                         difficulty="beginner", duration_minutes=360,
                         user_id=user_id),
        SocialEqLessonDB(title="冲突管理与解决", category="冲突处理",
                         description="学会以积极的方式处理人际冲突",
                         progress=20, total_lessons=8, completed_lessons=2,
                         difficulty="advanced", duration_minutes=240,
                         user_id=user_id),
        SocialEqLessonDB(title="同理心培养", category="社交技能",
                         description="站在他人角度思考，增进理解与信任",
                         progress=65, total_lessons=6, completed_lessons=4,
                         difficulty="intermediate", duration_minutes=180,
                         user_id=user_id),
    ]


def seed_social_data(db: Session, user_id: str = "default") -> bool:
    """初始化社交模块的默认种子数据（幂等）.

    仅在联系人表为空时执行初始化。

    Args:
        db: 数据库会话
        user_id: 用户 ID

    Returns:
        True 表示执行了初始化，False 表示已有数据跳过
    """
    contact_count = (
        db.query(SocialContactDB)
        .filter(SocialContactDB.user_id == user_id)
        .count()
    )
    if contact_count > 0:
        return False

    with transactional_scope(db):
        # 插入默认联系人
        for contact in _get_default_contacts(user_id):
            db.add(contact)
        db.flush()  # 获取生成的 ID

        # 重新获取联系人以建立姓名到 ID 的映射
        contacts = (
            db.query(SocialContactDB)
            .filter(SocialContactDB.user_id == user_id)
            .all()
        )
        name_to_id = {c.name: c.id for c in contacts}

        # 插入默认交往记录（根据姓名更新 contact_id）
        for interaction in _get_default_interactions(user_id):
            if interaction.contact_id and interaction.contact_name in name_to_id:
                interaction.contact_id = name_to_id[interaction.contact_name]
            db.add(interaction)

        # 插入默认提醒（根据索引映射到实际联系人 ID）
        reminder_defaults = _get_default_reminders(user_id)
        contact_names = [
            "张小明", "李雨晴", "王大伟", "陈思琪",
            "刘子豪", "赵雅婷", "孙浩然", "周雨萱",
        ]
        for reminder in reminder_defaults:
            if reminder.contact_id:
                idx = reminder.contact_id - 1
                if idx < len(contact_names) and contact_names[idx] in name_to_id:
                    reminder.contact_id = name_to_id[contact_names[idx]]
            db.add(reminder)

        # 插入默认情商课程
        for lesson in _get_default_eq_lessons(user_id):
            db.add(lesson)

    logger.info("人际关系模式默认数据初始化完成 (user_id={user_id})", user_id=user_id)
    return True


# ---------------------------------------------------------------------------
# Repository 类
# ---------------------------------------------------------------------------


class SocialRepository:
    """人际关系数据仓库.

    提供联系人、交往记录、社交提醒、情商课程的数据库操作。
    首次实例化时自动初始化种子数据。
    """

    def __init__(self, db: Session, user_id: str = "default") -> None:
        """初始化数据仓库.

        Args:
            db: 数据库会话
            user_id: 用户 ID
        """
        self.db = db
        self.user_id = user_id
        self._ensure_seeded()

    def _ensure_seeded(self) -> None:
        """确保种子数据已初始化."""
        try:
            seed_social_data(self.db, self.user_id)
        except Exception as e:
            logger.warning("人际关系数据初始化跳过", error=str(e), error_type=type(e).__name__)

    # -----------------------------------------------------------------------
    # 联系人相关方法
    # -----------------------------------------------------------------------

    def list_contacts(
        self,
        relation: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> list[SocialContactDB]:
        """获取联系人列表（支持筛选）.

        Args:
            relation: 按关系类型筛选
            tag: 按标签筛选

        Returns:
            联系人列表，按重要度降序排列
        """
        query = (
            self.db.query(SocialContactDB)
            .filter(SocialContactDB.user_id == self.user_id)
        )
        if relation:
            query = query.filter(SocialContactDB.relationship_type == relation)
        contacts = query.order_by(desc(SocialContactDB.importance)).all()
        if tag:
            contacts = [c for c in contacts if tag in (c.tags or [])]
        return contacts

    def get_contact(self, contact_id: int) -> Optional[SocialContactDB]:
        """按 ID 获取联系人.

        Args:
            contact_id: 联系人 ID

        Returns:
            联系人对象，不存在返回 None
        """
        return (
            self.db.query(SocialContactDB)
            .filter(
                SocialContactDB.id == contact_id,
                SocialContactDB.user_id == self.user_id,
            )
            .first()
        )

    def create_contact(
        self,
        name: str,
        avatar: str = "👤",
        relation: str = "朋友",
        tags: Optional[list[str]] = None,
    ) -> SocialContactDB:
        """创建联系人.

        Args:
            name: 姓名
            avatar: 头像 emoji
            relation: 关系类型
            tags: 标签列表

        Returns:
            创建后的联系人对象
        """
        contact = SocialContactDB(
            name=name,
            avatar=avatar,
            relationship_type=relation,
            importance=50,
            tags=tags or [],
            contact_count=0,
            last_contact_at=None,
            user_id=self.user_id,
        )
        with transactional_scope(self.db):
            self.db.add(contact)
        self.db.refresh(contact)
        return contact

    def update_contact(
        self,
        contact_id: int,
        **kwargs: Any,
    ) -> Optional[SocialContactDB]:
        """更新联系人信息.

        支持字段名映射（兼容前端字段）：
        - relation → relationship_type
        - closeness → importance

        Args:
            contact_id: 联系人 ID
            **kwargs: 待更新的字段

        Returns:
            更新后的联系人对象，不存在返回 None
        """
        contact = self.get_contact(contact_id)
        if not contact:
            return None

        # 字段名映射（兼容前端字段名）
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

        with transactional_scope(self.db):
            for key, value in kwargs.items():
                if value is None:
                    continue
                attr = field_map.get(key)
                if attr and hasattr(contact, attr):
                    setattr(contact, attr, value)
        self.db.refresh(contact)
        return contact

    def delete_contact(self, contact_id: int) -> bool:
        """删除联系人（同时删除相关的交往记录和提醒）.

        Args:
            contact_id: 联系人 ID

        Returns:
            True 表示删除成功，False 表示不存在
        """
        contact = self.get_contact(contact_id)
        if not contact:
            return False

        with transactional_scope(self.db):
            # 删除相关交往记录
            self.db.query(SocialInteractionDB).filter(
                SocialInteractionDB.user_id == self.user_id,
                SocialInteractionDB.contact_id == contact_id,
            ).delete(synchronize_session=False)

            # 删除相关提醒
            self.db.query(SocialReminderDB).filter(
                SocialReminderDB.user_id == self.user_id,
                SocialReminderDB.contact_id == contact_id,
            ).delete(synchronize_session=False)

            self.db.delete(contact)

        return True

    def update_contact_stats(self, contact_id: int) -> None:
        """更新联系人的联系统计（新增交往后调用）.

        更新最后联系时间和联系次数。

        Args:
            contact_id: 联系人 ID
        """
        contact = self.get_contact(contact_id)
        if contact:
            with transactional_scope(self.db):
                contact.last_contact_at = datetime.utcnow()
                contact.contact_count += 1

    def count_contacts(self) -> int:
        """统计联系人总数.

        Returns:
            联系人总数
        """
        return (
            self.db.query(SocialContactDB)
            .filter(SocialContactDB.user_id == self.user_id)
            .count()
        )

    def avg_importance(self) -> float:
        """计算平均重要度（亲密度）.

        Returns:
            平均重要度
        """
        result = (
            self.db.query(func.avg(SocialContactDB.importance))
            .filter(SocialContactDB.user_id == self.user_id)
            .scalar()
        )
        return float(result or 0)

    # -----------------------------------------------------------------------
    # 交往记录相关方法
    # -----------------------------------------------------------------------

    def list_interactions(
        self,
        contact_id: Optional[int] = None,
        limit: int = 20,
    ) -> list[SocialInteractionDB]:
        """获取交往记录列表.

        Args:
            contact_id: 按联系人筛选
            limit: 返回条数限制

        Returns:
            交往记录列表，按时间倒序
        """
        query = (
            self.db.query(SocialInteractionDB)
            .filter(SocialInteractionDB.user_id == self.user_id)
        )
        if contact_id:
            query = query.filter(SocialInteractionDB.contact_id == contact_id)
        return (
            query.order_by(desc(SocialInteractionDB.created_at))
            .limit(limit)
            .all()
        )

    def create_interaction(
        self,
        contact_id: int,
        contact_name: str,
        type: str,
        content: str,
        emotion: str = "neutral",
        duration_minutes: int = 0,
        location: str = "",
    ) -> SocialInteractionDB:
        """创建交往记录.

        Args:
            contact_id: 联系人 ID
            contact_name: 联系人姓名快照
            type: 交往类型
            content: 交往内容
            emotion: 心情
            duration_minutes: 时长（分钟）
            location: 地点

        Returns:
            创建后的交往记录对象
        """
        interaction = SocialInteractionDB(
            contact_id=contact_id,
            contact_name=contact_name,
            type=type,
            content=content,
            mood=emotion,
            duration_minutes=duration_minutes,
            location=location,
            user_id=self.user_id,
        )
        with transactional_scope(self.db):
            self.db.add(interaction)
        self.db.refresh(interaction)
        return interaction

    def count_interactions(self) -> int:
        """统计交往记录总数.

        Returns:
            交往记录总数
        """
        return (
            self.db.query(SocialInteractionDB)
            .filter(SocialInteractionDB.user_id == self.user_id)
            .count()
        )

    def count_week_interactions(self) -> int:
        """统计本周交往次数.

        Returns:
            近 7 天的交往次数
        """
        week_ago = datetime.utcnow() - timedelta(days=7)
        return (
            self.db.query(SocialInteractionDB)
            .filter(
                SocialInteractionDB.user_id == self.user_id,
                SocialInteractionDB.created_at >= week_ago,
            )
            .count()
        )

    # -----------------------------------------------------------------------
    # 社交提醒相关方法
    # -----------------------------------------------------------------------

    def list_reminders(self) -> list[SocialReminderDB]:
        """获取所有提醒列表.

        Returns:
            提醒列表，按提醒日期升序（空日期排在最后）
        """
        return (
            self.db.query(SocialReminderDB)
            .filter(SocialReminderDB.user_id == self.user_id)
            .order_by(SocialReminderDB.reminder_date.asc().nullslast())
            .all()
        )

    def create_reminder(
        self,
        type: str,
        title: str,
        description: str = "",
        date: str = "",
        priority: str = "medium",
    ) -> SocialReminderDB:
        """创建社交提醒.

        Args:
            type: 提醒类型
            title: 提醒标题
            description: 提醒描述
            date: 日期字符串（支持 YYYY-MM-DD 或 YYYY-MM-DD HH:MM:SS）
            priority: 优先级

        Returns:
            创建后的提醒对象
        """
        # 尝试解析日期
        reminder_date: Optional[datetime] = None
        if date:
            for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
                try:
                    reminder_date = datetime.strptime(date, fmt)
                    break
                except ValueError:
                    continue

        reminder = SocialReminderDB(
            reminder_type=type,
            title=title,
            description=description,
            reminder_date=reminder_date,
            priority=priority,
            user_id=self.user_id,
        )
        with transactional_scope(self.db):
            self.db.add(reminder)
        self.db.refresh(reminder)
        return reminder

    def get_reminder(self, reminder_id: int) -> Optional[SocialReminderDB]:
        """按 ID 获取提醒.

        Args:
            reminder_id: 提醒 ID

        Returns:
            提醒对象，不存在返回 None
        """
        return (
            self.db.query(SocialReminderDB)
            .filter(
                SocialReminderDB.id == reminder_id,
                SocialReminderDB.user_id == self.user_id,
            )
            .first()
        )

    def update_reminder_status(
        self,
        reminder_id: int,
        status: str,
    ) -> Optional[SocialReminderDB]:
        """更新提醒状态.

        Args:
            reminder_id: 提醒 ID
            status: 新状态（pending/done/cancelled）

        Returns:
            更新后的提醒对象，不存在返回 None
        """
        reminder = self.get_reminder(reminder_id)
        if not reminder:
            return None

        if status in ("pending", "done", "cancelled"):
            with transactional_scope(self.db):
                reminder.status = status
            self.db.refresh(reminder)
        return reminder

    def delete_reminder(self, reminder_id: int) -> bool:
        """删除提醒.

        Args:
            reminder_id: 提醒 ID

        Returns:
            True 表示删除成功，False 表示不存在
        """
        reminder = self.get_reminder(reminder_id)
        if reminder:
            with transactional_scope(self.db):
                self.db.delete(reminder)
            return True
        return False

    # -----------------------------------------------------------------------
    # 情商课程相关方法
    # -----------------------------------------------------------------------

    def list_eq_lessons(self) -> list[SocialEqLessonDB]:
        """获取情商课程列表.

        Returns:
            情商课程列表，按 ID 升序
        """
        return (
            self.db.query(SocialEqLessonDB)
            .filter(SocialEqLessonDB.user_id == self.user_id)
            .order_by(SocialEqLessonDB.id.asc())
            .all()
        )

    def get_eq_score(self) -> dict[str, Any]:
        """获取情商评分及维度数据.

        根据课程进度计算情商得分和各维度分数。

        Returns:
            情商评分字典，包含 score、level、dimensions
        """
        lessons = self.list_eq_lessons()
        total_progress = (
            sum(l.progress for l in lessons) / len(lessons) if lessons else 0
        )
        # 基础分 + 课程进度加成
        base_score = 60
        eq_score = min(99, int(base_score + total_progress * 0.35))

        # 等级判定
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
