"""学业规划模式 - 数据访问层.

封装学习目标、学习计划、学习笔记、知识分类、考试计划、
科目进度等的数据库 CRUD 操作。
首次使用时自动初始化种子数据，确保开箱即用。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from src.common.db_transaction import transactional_scope
from src.models.db import (
    StudyExamDB,
    StudyGoalDB,
    StudyKnowledgeCategoryDB,
    StudyMetaDB,
    StudyNoteDB,
    StudyPlanDB,
    StudyProgressDB,
)

import structlog

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 种子数据
# ---------------------------------------------------------------------------


def _get_default_goals(user_id: str = "default") -> list[StudyGoalDB]:
    """获取默认学习目标种子数据.

    Args:
        user_id: 用户 ID

    Returns:
        默认目标列表
    """
    return [
        StudyGoalDB(goal_id=1, title="本学期总目标", icon="🎯", progress=52,
                    status="in-progress", expanded=True, parent_id=None, level=0, order_index=1,
                    user_id=user_id),
        StudyGoalDB(goal_id=2, title="专业课复习", icon="📚", progress=75,
                    status="in-progress", expanded=True, parent_id=1, level=1, order_index=1,
                    user_id=user_id),
        StudyGoalDB(goal_id=3, title="高等数学", icon="📐", progress=100,
                    status="complete", expanded=False, parent_id=2, level=2, order_index=1,
                    user_id=user_id),
        StudyGoalDB(goal_id=4, title="线性代数", icon="🔢", progress=80,
                    status="in-progress", expanded=False, parent_id=2, level=2, order_index=2,
                    user_id=user_id),
        StudyGoalDB(goal_id=5, title="概率统计", icon="📊", progress=45,
                    status="warning", expanded=False, parent_id=2, level=2, order_index=3,
                    user_id=user_id),
        StudyGoalDB(goal_id=6, title="毕业论文", icon="📝", progress=30,
                    status="warning", expanded=True, parent_id=1, level=1, order_index=2,
                    user_id=user_id),
        StudyGoalDB(goal_id=7, title="文献综述", icon="📄", progress=60,
                    status="in-progress", expanded=False, parent_id=6, level=2, order_index=1,
                    user_id=user_id),
        StudyGoalDB(goal_id=8, title="数据收集", icon="🗃️", progress=20,
                    status="warning", expanded=False, parent_id=6, level=2, order_index=2,
                    user_id=user_id),
        StudyGoalDB(goal_id=9, title="初稿撰写", icon="✍️", progress=0,
                    status="not-started", expanded=False, parent_id=6, level=2, order_index=3,
                    user_id=user_id),
        StudyGoalDB(goal_id=10, title="英语六级", icon="📖", progress=50,
                    status="in-progress", expanded=False, parent_id=1, level=1, order_index=3,
                    user_id=user_id),
    ]


def _get_default_plans(user_id: str = "default") -> list[StudyPlanDB]:
    """获取默认学习计划种子数据.

    Args:
        user_id: 用户 ID

    Returns:
        默认计划列表
    """
    today = datetime.now().strftime("%Y-%m-%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    return [
        StudyPlanDB(plan_id=1, title="高等数学 - 第三章积分", start_time="09:00",
                    end_time="11:00", duration=2, priority="重要", completed=True,
                    subject="高等数学", date=today, user_id=user_id),
        StudyPlanDB(plan_id=2, title="英语阅读 - 真题练习", start_time="14:00",
                    end_time="15:30", duration=1.5, priority="常规", completed=True,
                    subject="英语", date=today, user_id=user_id),
        StudyPlanDB(plan_id=3, title="数据结构复习", start_time="19:00",
                    end_time="21:00", duration=2, priority="考前", completed=False,
                    subject="计算机", date=today, user_id=user_id),
        StudyPlanDB(plan_id=4, title="线性代数 - 特征值专题", start_time="10:00",
                    end_time="12:00", duration=2, priority="重要", completed=False,
                    subject="线性代数", date=tomorrow, user_id=user_id),
        StudyPlanDB(plan_id=5, title="英语听力训练", start_time="08:00",
                    end_time="09:00", duration=1, priority="常规", completed=False,
                    subject="英语", date=tomorrow, user_id=user_id),
    ]


def _get_default_notes(user_id: str = "default") -> list[StudyNoteDB]:
    """获取默认学习笔记种子数据.

    Args:
        user_id: 用户 ID

    Returns:
        默认笔记列表
    """
    return [
        StudyNoteDB(note_id=1, title="微积分基本定理笔记", category="数学",
                    date_label="昨天",
                    content="微积分基本定理揭示了微分与积分的内在联系，是整个微积分学的核心...",
                    user_id=user_id),
        StudyNoteDB(note_id=2, title="英语高频词汇整理", category="英语",
                    date_label="3天前",
                    content="整理了四六级高频词汇 500 个，按词根词缀分类记忆...",
                    user_id=user_id),
        StudyNoteDB(note_id=3, title="数据结构 - 树与图", category="计算机",
                    date_label="5天前",
                    content="二叉树、平衡树、B树、图的遍历算法整理...",
                    user_id=user_id),
    ]


def _get_default_knowledge_categories(user_id: str = "default") -> list[StudyKnowledgeCategoryDB]:
    """获取默认知识分类种子数据.

    Args:
        user_id: 用户 ID

    Returns:
        默认知识分类列表
    """
    return [
        StudyKnowledgeCategoryDB(category_id=1, name="数学", icon="📐",
                                 note_count=128, unit="个知识点", user_id=user_id),
        StudyKnowledgeCategoryDB(category_id=2, name="英语", icon="📖",
                                 note_count=3500, unit="词汇", user_id=user_id),
        StudyKnowledgeCategoryDB(category_id=3, name="计算机", icon="💻",
                                 note_count=56, unit="个知识点", user_id=user_id),
        StudyKnowledgeCategoryDB(category_id=4, name="物理", icon="⚛️",
                                 note_count=89, unit="个知识点", user_id=user_id),
        StudyKnowledgeCategoryDB(category_id=5, name="化学", icon="🧪",
                                 note_count=72, unit="个知识点", user_id=user_id),
        StudyKnowledgeCategoryDB(category_id=6, name="语文", icon="📝",
                                 note_count=45, unit="篇古文", user_id=user_id),
    ]


def _get_default_progress(user_id: str = "default") -> list[StudyProgressDB]:
    """获取默认科目进度种子数据.

    Args:
        user_id: 用户 ID

    Returns:
        默认科目进度列表
    """
    return [
        StudyProgressDB(subject="高等数学", progress=65, color="blue",
                        total_hours=48, mastered_topics=85, total_topics=128,
                        user_id=user_id),
        StudyProgressDB(subject="英语", progress=78, color="green",
                        total_hours=62, mastered_topics=2800, total_topics=3500,
                        user_id=user_id),
        StudyProgressDB(subject="数据结构", progress=42, color="amber",
                        total_hours=28, mastered_topics=24, total_topics=56,
                        user_id=user_id),
        StudyProgressDB(subject="线性代数", progress=55, color="purple",
                        total_hours=35, mastered_topics=30, total_topics=52,
                        user_id=user_id),
        StudyProgressDB(subject="概率统计", progress=38, color="red",
                        total_hours=22, mastered_topics=28, total_topics=72,
                        user_id=user_id),
    ]


def _get_default_exams(user_id: str = "default") -> list[StudyExamDB]:
    """获取默认考试计划种子数据.

    Args:
        user_id: 用户 ID

    Returns:
        默认考试列表
    """
    now = datetime.now()
    return [
        StudyExamDB(exam_id=1, name="期末考试 - 高等数学", subject="高等数学",
                    exam_date=(now + timedelta(days=15)).strftime("%Y-%m-%d 09:00"),
                    location="教学楼A301", urgency="紧急", color_theme="red",
                    user_id=user_id),
        StudyExamDB(exam_id=2, name="英语四级考试", subject="英语",
                    exam_date=(now + timedelta(days=30)).strftime("%Y-%m-%d 09:00"),
                    location="外语楼B202", urgency="重要", color_theme="amber",
                    user_id=user_id),
        StudyExamDB(exam_id=3, name="计算机等级考试", subject="计算机",
                    exam_date=(now + timedelta(days=45)).strftime("%Y-%m-%d 14:00"),
                    location="计算机楼C501", urgency="备考中", color_theme="green",
                    user_id=user_id),
        StudyExamDB(exam_id=4, name="毕业论文答辩", subject="综合",
                    exam_date=(now + timedelta(days=60)).strftime("%Y-%m-%d 14:00"),
                    location="学术报告厅", urgency="规划中", color_theme="blue",
                    user_id=user_id),
    ]


def _get_default_meta_entries(user_id: str = "default") -> list[StudyMetaDB]:
    """获取默认元数据种子数据.

    Args:
        user_id: 用户 ID

    Returns:
        默认元数据列表
    """
    return [
        StudyMetaDB(meta_key="weekly_goals", user_id=user_id, meta_value=[
            {"id": 1, "category": "数学章节", "current": 3, "total": 5, "unit": "个",
             "progress": 60, "completed": False},
            {"id": 2, "category": "单词量", "current": 250, "total": 350, "unit": "词",
             "progress": 71, "completed": False},
            {"id": 3, "category": "编程题", "current": 12, "total": 20, "unit": "道",
             "progress": 60, "completed": False},
        ]),
        StudyMetaDB(meta_key="risk_matrix", user_id=user_id, meta_value=[
            {"probability": "high", "impact": "high", "level": "high", "label": "高危"},
            {"probability": "medium", "impact": "high", "level": "high", "label": "高危"},
            {"probability": "low", "impact": "high", "level": "medium", "label": "中等"},
            {"probability": "high", "impact": "medium", "level": "high", "label": "高危"},
            {"probability": "medium", "impact": "medium", "level": "medium", "label": "中等"},
            {"probability": "low", "impact": "medium", "level": "low", "label": "低"},
            {"probability": "high", "impact": "low", "level": "medium", "label": "中等"},
            {"probability": "medium", "impact": "low", "level": "low", "label": "低"},
            {"probability": "low", "impact": "low", "level": "low", "label": "低"},
        ]),
        StudyMetaDB(meta_key="risk_items", user_id=user_id, meta_value=[
            {"id": 1, "name": "数学复习进度滞后", "probability": "high", "impact": "high",
             "level": "high", "description": "高数内容多，进度可能跟不上"},
            {"id": 2, "name": "论文数据不足", "probability": "medium", "impact": "high",
             "level": "high", "description": "实验数据收集困难可能影响论文质量"},
            {"id": 3, "name": "英语听力薄弱", "probability": "medium", "impact": "medium",
             "level": "medium", "description": "听力部分失分较多"},
            {"id": 4, "name": "时间冲突", "probability": "low", "impact": "medium",
             "level": "low", "description": "多门考试集中导致复习时间紧张"},
        ]),
        StudyMetaDB(meta_key="scenarios", user_id=user_id, meta_value=[
            {
                "id": 1,
                "name": "方案A：保守路径",
                "subtitle": "稳扎稳打，确保通过",
                "is_recommended": True,
                "phases": [
                    {"name": "基础复习", "progress": 85, "color": "green"},
                    {"name": "强化训练", "progress": 60, "color": "blue"},
                    {"name": "冲刺模拟", "progress": 40, "color": "amber"},
                ],
            },
            {
                "id": 2,
                "name": "方案B：激进路径",
                "subtitle": "高强度冲刺，冲击高分",
                "is_recommended": False,
                "phases": [
                    {"name": "基础复习", "progress": 60, "color": "green"},
                    {"name": "强化训练", "progress": 80, "color": "blue"},
                    {"name": "冲刺模拟", "progress": 70, "color": "amber"},
                ],
            },
        ]),
        StudyMetaDB(meta_key="gantt_phases", user_id=user_id, meta_value=[
            {"id": 1, "label": "基础复习", "start_week": 1, "end_week": 4, "phase_type": 1},
            {"id": 2, "label": "强化训练", "start_week": 5, "end_week": 8, "phase_type": 2},
            {"id": 3, "label": "冲刺模拟", "start_week": 9, "end_week": 12, "phase_type": 3},
            {"id": 4, "label": "考试周", "start_week": 13, "end_week": 13, "phase_type": 4},
        ]),
        StudyMetaDB(meta_key="study_stats", user_id=user_id, meta_value={
            "today_hours": 5.5,
            "week_hours": 32,
            "streak_days": 12,
            "total_hours": 256,
            "avg_hours_per_day": 4.2,
        }),
        StudyMetaDB(meta_key="progress_banner", user_id=user_id, meta_value={
            "exam_name": "期末考试",
            "days_left": 47,
            "semester_progress": 62,
            "today_tasks_done": 2,
            "today_tasks_total": 3,
            "today_completion_rate": 67,
        }),
    ]


def seed_study_data(db: Session, user_id: str = "default") -> bool:
    """初始化学业规划模块的默认种子数据（幂等）.

    仅在目标表为空时执行初始化。

    Args:
        db: 数据库会话
        user_id: 用户 ID

    Returns:
        True 表示执行了初始化，False 表示已有数据跳过
    """
    goal_count = (
        db.query(StudyGoalDB)
        .filter(StudyGoalDB.user_id == user_id)
        .count()
    )
    if goal_count > 0:
        return False

    with transactional_scope(db):
        # 插入学习目标
        for g in _get_default_goals(user_id):
            db.add(g)

        # 插入学习计划
        for p in _get_default_plans(user_id):
            db.add(p)

        # 插入学习笔记
        for n in _get_default_notes(user_id):
            db.add(n)

        # 插入知识分类
        for c in _get_default_knowledge_categories(user_id):
            db.add(c)

        # 插入科目进度
        for p in _get_default_progress(user_id):
            db.add(p)

        # 插入考试计划
        for e in _get_default_exams(user_id):
            db.add(e)

        # 插入元数据
        for m in _get_default_meta_entries(user_id):
            db.add(m)

    logger.info("学业规划模式默认数据初始化完成 (user_id={user_id})", user_id=user_id)
    return True


# ---------------------------------------------------------------------------
# Repository 类
# ---------------------------------------------------------------------------


class StudyRepository:
    """学业规划数据仓库.

    提供学习目标、学习计划、学习笔记、知识分类、考试计划、
    科目进度的数据库操作。
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
            seed_study_data(self.db, self.user_id)
        except Exception as e:
            logger.warning("学业规划数据初始化跳过", error=str(e), error_type=type(e).__name__)

    # -----------------------------------------------------------------------
    # 学习目标相关方法
    # -----------------------------------------------------------------------

    def list_goals(self) -> list[StudyGoalDB]:
        """获取所有目标列表.

        Returns:
            目标列表，按 order_index 升序
        """
        return (
            self.db.query(StudyGoalDB)
            .filter(StudyGoalDB.user_id == self.user_id)
            .order_by(StudyGoalDB.order_index)
            .all()
        )

    def get_goal(self, goal_id: int) -> Optional[StudyGoalDB]:
        """按业务 ID 获取目标.

        Args:
            goal_id: 目标业务 ID

        Returns:
            目标对象，不存在返回 None
        """
        return (
            self.db.query(StudyGoalDB)
            .filter(
                StudyGoalDB.goal_id == goal_id,
                StudyGoalDB.user_id == self.user_id,
            )
            .first()
        )

    def create_goal(
        self,
        title: str,
        icon: str = "📚",
        parent_id: Optional[int] = None,
    ) -> StudyGoalDB:
        """创建目标.

        Args:
            title: 目标标题
            icon: 图标
            parent_id: 父目标 ID

        Returns:
            创建后的目标对象
        """
        all_goals = (
            self.db.query(StudyGoalDB)
            .filter(StudyGoalDB.user_id == self.user_id)
            .all()
        )
        nid = max((g.goal_id for g in all_goals), default=0) + 1

        # 查找父节点计算 level
        parent = None
        if parent_id:
            parent = (
                self.db.query(StudyGoalDB)
                .filter(
                    StudyGoalDB.goal_id == parent_id,
                    StudyGoalDB.user_id == self.user_id,
                )
                .first()
            )
        level = parent.level + 1 if parent else 0

        # 同层级下的最大 order_index + 1
        siblings = (
            self.db.query(StudyGoalDB)
            .filter(
                StudyGoalDB.user_id == self.user_id,
                StudyGoalDB.parent_id == parent_id,
            )
            .all()
        )
        order_index = max((s.order_index for s in siblings), default=0) + 1

        goal = StudyGoalDB(
            goal_id=nid,
            title=title,
            icon=icon,
            progress=0,
            status="not-started",
            expanded=True,
            parent_id=parent_id,
            level=level,
            order_index=order_index,
            user_id=self.user_id,
        )
        with transactional_scope(self.db):
            self.db.add(goal)
        self.db.refresh(goal)
        return goal

    def update_goal(
        self,
        goal_id: int,
        **kwargs: Any,
    ) -> Optional[StudyGoalDB]:
        """更新目标.

        Args:
            goal_id: 目标业务 ID
            **kwargs: 待更新的字段

        Returns:
            更新后的目标对象，不存在返回 None
        """
        goal = self.get_goal(goal_id)
        if not goal:
            return None

        field_map = {
            "label": "title",
            "title": "title",
            "progress": "progress",
            "status": "status",
            "expanded": "expanded",
            "icon": "icon",
            "description": "description",
            "priority": "priority",
            "deadline": "deadline",
        }

        with transactional_scope(self.db):
            for key, value in kwargs.items():
                if value is None:
                    continue
                attr = field_map.get(key)
                if attr and hasattr(goal, attr):
                    setattr(goal, attr, value)

            # 根据进度自动更新状态
            if "progress" in kwargs and kwargs["progress"] is not None:
                if goal.progress >= 100:
                    goal.status = "complete"
                elif goal.progress > 0:
                    if goal.status == "not-started":
                        goal.status = "in-progress"
        self.db.refresh(goal)
        return goal

    def delete_goal(self, goal_id: int) -> bool:
        """删除目标（递归删除子节点）.

        Args:
            goal_id: 目标业务 ID

        Returns:
            True 表示删除成功，False 表示不存在
        """
        goal = self.get_goal(goal_id)
        if not goal:
            return False

        # 递归收集所有子节点 ID
        def get_children_ids(pid: int) -> list[int]:
            children = (
                self.db.query(StudyGoalDB)
                .filter(
                    StudyGoalDB.parent_id == pid,
                    StudyGoalDB.user_id == self.user_id,
                )
                .all()
            )
            ids: list[int] = []
            for child in children:
                ids.append(child.goal_id)
                ids.extend(get_children_ids(child.goal_id))
            return ids

        all_ids = [goal_id] + get_children_ids(goal_id)

        # 批量删除（原子操作）
        with transactional_scope(self.db):
            self.db.query(StudyGoalDB).filter(
                StudyGoalDB.goal_id.in_(all_ids),
                StudyGoalDB.user_id == self.user_id,
            ).delete(synchronize_session=False)

        return True

    def count_goals(self) -> int:
        """统计目标总数.

        Returns:
            目标总数
        """
        return (
            self.db.query(StudyGoalDB)
            .filter(StudyGoalDB.user_id == self.user_id)
            .count()
        )

    # -----------------------------------------------------------------------
    # 学习计划相关方法
    # -----------------------------------------------------------------------

    def list_plans(self, date: Optional[str] = None) -> list[StudyPlanDB]:
        """获取学习计划列表.

        Args:
            date: 按日期筛选

        Returns:
            计划列表，按开始时间升序
        """
        query = (
            self.db.query(StudyPlanDB)
            .filter(StudyPlanDB.user_id == self.user_id)
        )
        if date:
            query = query.filter(StudyPlanDB.date == date)
        return query.order_by(StudyPlanDB.start_time).all()

    def get_plan(self, plan_id: int) -> Optional[StudyPlanDB]:
        """按业务 ID 获取计划.

        Args:
            plan_id: 计划业务 ID

        Returns:
            计划对象，不存在返回 None
        """
        return (
            self.db.query(StudyPlanDB)
            .filter(
                StudyPlanDB.plan_id == plan_id,
                StudyPlanDB.user_id == self.user_id,
            )
            .first()
        )

    def create_plan(
        self,
        title: str,
        start_time: str,
        end_time: str,
        duration: float,
        priority: str = "常规",
        subject: str = "",
        date: Optional[str] = None,
    ) -> StudyPlanDB:
        """创建学习计划.

        Args:
            title: 标题
            start_time: 开始时间
            end_time: 结束时间
            duration: 时长（小时）
            priority: 优先级
            subject: 科目
            date: 日期

        Returns:
            创建后的计划对象
        """
        all_plans = (
            self.db.query(StudyPlanDB)
            .filter(StudyPlanDB.user_id == self.user_id)
            .all()
        )
        pid = max((p.plan_id for p in all_plans), default=0) + 1

        plan = StudyPlanDB(
            plan_id=pid,
            title=title,
            start_time=start_time,
            end_time=end_time,
            duration=duration,
            priority=priority,
            completed=False,
            subject=subject,
            date=date or datetime.now().strftime("%Y-%m-%d"),
            user_id=self.user_id,
        )
        with transactional_scope(self.db):
            self.db.add(plan)
        self.db.refresh(plan)
        return plan

    def toggle_plan(self, plan_id: int) -> Optional[StudyPlanDB]:
        """切换计划完成状态.

        Args:
            plan_id: 计划业务 ID

        Returns:
            更新后的计划对象，不存在返回 None
        """
        plan = self.get_plan(plan_id)
        if not plan:
            return None

        with transactional_scope(self.db):
            plan.completed = not plan.completed
        self.db.refresh(plan)
        return plan

    def delete_plan(self, plan_id: int) -> bool:
        """删除学习计划.

        Args:
            plan_id: 计划业务 ID

        Returns:
            True 表示删除成功，False 表示不存在
        """
        plan = self.get_plan(plan_id)
        if not plan:
            return False
        with transactional_scope(self.db):
            self.db.delete(plan)
        return True

    def count_plans(self, date: Optional[str] = None) -> int:
        """统计计划数量.

        Args:
            date: 按日期筛选

        Returns:
            计划数量
        """
        query = (
            self.db.query(StudyPlanDB)
            .filter(StudyPlanDB.user_id == self.user_id)
        )
        if date:
            query = query.filter(StudyPlanDB.date == date)
        return query.count()

    # -----------------------------------------------------------------------
    # 学习笔记相关方法
    # -----------------------------------------------------------------------

    def list_notes(
        self, subject: Optional[str] = None,
    ) -> list[StudyNoteDB]:
        """获取学习笔记列表.

        Args:
            subject: 按科目/分类筛选

        Returns:
            笔记列表，按创建时间倒序
        """
        query = (
            self.db.query(StudyNoteDB)
            .filter(StudyNoteDB.user_id == self.user_id)
        )
        if subject:
            query = query.filter(StudyNoteDB.category == subject)
        return query.order_by(desc(StudyNoteDB.created_at)).all()

    def get_note(self, note_id: int) -> Optional[StudyNoteDB]:
        """按业务 ID 获取笔记.

        Args:
            note_id: 笔记业务 ID

        Returns:
            笔记对象，不存在返回 None
        """
        return (
            self.db.query(StudyNoteDB)
            .filter(
                StudyNoteDB.note_id == note_id,
                StudyNoteDB.user_id == self.user_id,
            )
            .first()
        )

    def create_note(
        self,
        title: str,
        category: str,
        content: str = "",
    ) -> StudyNoteDB:
        """创建学习笔记.

        Args:
            title: 标题
            category: 分类/科目
            content: 内容

        Returns:
            创建后的笔记对象
        """
        all_notes = (
            self.db.query(StudyNoteDB)
            .filter(StudyNoteDB.user_id == self.user_id)
            .all()
        )
        nid = max((n.note_id for n in all_notes), default=0) + 1

        note = StudyNoteDB(
            note_id=nid,
            title=title,
            category=category,
            date_label="刚刚",
            content=content,
            user_id=self.user_id,
        )
        with transactional_scope(self.db):
            self.db.add(note)
        self.db.refresh(note)
        return note

    def update_note(
        self,
        note_id: int,
        **kwargs: Any,
    ) -> Optional[StudyNoteDB]:
        """更新笔记.

        Args:
            note_id: 笔记业务 ID
            **kwargs: 待更新的字段

        Returns:
            更新后的笔记对象，不存在返回 None
        """
        note = self.get_note(note_id)
        if not note:
            return None

        field_map = {
            "title": "title",
            "subject": "category",
            "category": "category",
            "content": "content",
            "important": "important",
            "tags": "tags",
        }

        with transactional_scope(self.db):
            for key, value in kwargs.items():
                if value is None:
                    continue
                attr = field_map.get(key)
                if attr and hasattr(note, attr):
                    setattr(note, attr, value)

            note.date_label = "刚刚"
            note.updated_at = datetime.utcnow()
        self.db.refresh(note)
        return note

    def delete_note(self, note_id: int) -> bool:
        """删除笔记.

        Args:
            note_id: 笔记业务 ID

        Returns:
            True 表示删除成功，False 表示不存在
        """
        note = self.get_note(note_id)
        if not note:
            return False
        with transactional_scope(self.db):
            self.db.delete(note)
        return True

    def count_notes(self) -> int:
        """统计笔记总数.

        Returns:
            笔记总数
        """
        return (
            self.db.query(StudyNoteDB)
            .filter(StudyNoteDB.user_id == self.user_id)
            .count()
        )

    # -----------------------------------------------------------------------
    # 知识分类相关方法
    # -----------------------------------------------------------------------

    def list_knowledge_categories(self) -> list[StudyKnowledgeCategoryDB]:
        """获取知识分类列表.

        Returns:
            知识分类列表，按 category_id 升序
        """
        return (
            self.db.query(StudyKnowledgeCategoryDB)
            .filter(StudyKnowledgeCategoryDB.user_id == self.user_id)
            .order_by(StudyKnowledgeCategoryDB.category_id)
            .all()
        )

    # -----------------------------------------------------------------------
    # 科目进度相关方法
    # -----------------------------------------------------------------------

    def list_progress(self) -> list[StudyProgressDB]:
        """获取科目进度列表.

        Returns:
            科目进度列表
        """
        return (
            self.db.query(StudyProgressDB)
            .filter(StudyProgressDB.user_id == self.user_id)
            .all()
        )

    # -----------------------------------------------------------------------
    # 考试计划相关方法
    # -----------------------------------------------------------------------

    def list_exams(self) -> list[StudyExamDB]:
        """获取考试列表.

        Returns:
            考试列表，按考试日期升序
        """
        return (
            self.db.query(StudyExamDB)
            .filter(StudyExamDB.user_id == self.user_id)
            .order_by(StudyExamDB.exam_date)
            .all()
        )

    def get_exam(self, exam_id: int) -> Optional[StudyExamDB]:
        """按业务 ID 获取考试.

        Args:
            exam_id: 考试业务 ID

        Returns:
            考试对象，不存在返回 None
        """
        return (
            self.db.query(StudyExamDB)
            .filter(
                StudyExamDB.exam_id == exam_id,
                StudyExamDB.user_id == self.user_id,
            )
            .first()
        )

    def create_exam(
        self,
        name: str,
        exam_date: str,
        location: str = "",
        urgency: str = "备考中",
    ) -> StudyExamDB:
        """创建考试提醒.

        Args:
            name: 考试名称
            exam_date: 考试日期时间
            location: 考试地点
            urgency: 紧急程度

        Returns:
            创建后的考试对象
        """
        all_exams = (
            self.db.query(StudyExamDB)
            .filter(StudyExamDB.user_id == self.user_id)
            .all()
        )
        eid = max((e.exam_id for e in all_exams), default=0) + 1

        exam = StudyExamDB(
            exam_id=eid,
            name=name,
            exam_date=exam_date,
            location=location,
            urgency=urgency,
            color_theme="blue",
            user_id=self.user_id,
        )
        with transactional_scope(self.db):
            self.db.add(exam)
        self.db.refresh(exam)
        return exam

    def delete_exam(self, exam_id: int) -> bool:
        """删除考试提醒.

        Args:
            exam_id: 考试业务 ID

        Returns:
            True 表示删除成功，False 表示不存在
        """
        exam = self.get_exam(exam_id)
        if not exam:
            return False
        with transactional_scope(self.db):
            self.db.delete(exam)
        return True

    def count_exams(self) -> int:
        """统计考试总数.

        Returns:
            考试总数
        """
        return (
            self.db.query(StudyExamDB)
            .filter(StudyExamDB.user_id == self.user_id)
            .count()
        )

    # -----------------------------------------------------------------------
    # 元数据相关方法
    # -----------------------------------------------------------------------

    def get_meta(self, key: str) -> Any:
        """获取元数据值.

        Args:
            key: 元数据键名

        Returns:
            元数据值，不存在返回 None
        """
        meta = (
            self.db.query(StudyMetaDB)
            .filter(
                StudyMetaDB.meta_key == key,
                StudyMetaDB.user_id == self.user_id,
            )
            .first()
        )
        return meta.meta_value if meta else None

    def set_meta(self, key: str, value: Any) -> StudyMetaDB:
        """设置元数据值.

        Args:
            key: 元数据键名
            value: 元数据值

        Returns:
            更新或创建后的元数据对象
        """
        meta = (
            self.db.query(StudyMetaDB)
            .filter(
                StudyMetaDB.meta_key == key,
                StudyMetaDB.user_id == self.user_id,
            )
            .first()
        )
        with transactional_scope(self.db):
            if meta:
                meta.meta_value = value
            else:
                meta = StudyMetaDB(
                    meta_key=key,
                    meta_value=value,
                    user_id=self.user_id,
                )
                self.db.add(meta)
        self.db.refresh(meta)
        return meta

    # -----------------------------------------------------------------------
    # 概览统计方法
    # -----------------------------------------------------------------------

    def get_overview_stats(self) -> dict[str, Any]:
        """获取学业规划概览统计.

        Returns:
            概览统计字典
        """
        today = datetime.now().strftime("%Y-%m-%d")
        today_plans = self.list_plans(date=today)
        done_count = sum(1 for p in today_plans if p.completed)

        total_goals = self.count_goals()
        total_plans = self.count_plans()
        total_notes = self.count_notes()
        total_exams = self.count_exams()

        study_stats = self.get_meta("study_stats") or {}
        progress_banner = self.get_meta("progress_banner") or {}

        return {
            "stats": {
                "total_goals": total_goals,
                "total_plans": total_plans,
                "total_notes": total_notes,
                "total_exams": total_exams,
                "today_tasks": len(today_plans),
                "today_done": done_count,
                "streak_days": study_stats.get("streak_days", 0),
            },
            "banner": progress_banner,
            "study_stats": study_stats,
        }
