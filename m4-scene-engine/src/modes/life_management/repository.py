"""生活管理模式 - 数据访问层.

封装日程、待办、习惯、场景、财务、规则的数据库 CRUD 操作。
首次使用时自动初始化种子数据，确保开箱即用。
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from src.common.db_transaction import transactional_scope
from src.models.db import (
    LifeFinanceCategoryDB,
    LifeFinanceRecordDB,
    LifeHabitDB,
    LifeHabitRecordDB,
    LifeMetaDB,
    LifeRuleDB,
    LifeScheduleDB,
    LifeSceneDB,
    LifeTodoDB,
)

import structlog

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 种子数据
# ---------------------------------------------------------------------------


def _get_default_schedules(user_id: str = "default") -> list[LifeScheduleDB]:
    """获取默认日程种子数据.

    Args:
        user_id: 用户 ID

    Returns:
        默认日程列表
    """
    today = datetime.now().strftime("%Y-%m-%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    return [
        LifeScheduleDB(schedule_id=1, title="晨间复盘", time_range="09:00 - 10:30",
                       start_time="09:00", end_time="10:30", category="固定",
                       tag_color="green", date=today, user_id=user_id),
        LifeScheduleDB(schedule_id=2, title="团队站会", time_range="14:00 - 15:00",
                       start_time="14:00", end_time="15:00", category="协作",
                       tag_color="blue", date=today, user_id=user_id),
        LifeScheduleDB(schedule_id=3, title="运动时间", time_range="19:00 - 20:00",
                       start_time="19:00", end_time="20:00", category="健康",
                       tag_color="orange", date=today, user_id=user_id),
        LifeScheduleDB(schedule_id=4, title="项目评审", time_range="10:00 - 11:30",
                       start_time="10:00", end_time="11:30", category="协作",
                       tag_color="blue", date=tomorrow, user_id=user_id),
        LifeScheduleDB(schedule_id=5, title="阅读时间", time_range="20:00 - 21:00",
                       start_time="20:00", end_time="21:00", category="固定",
                       tag_color="green", date=tomorrow, user_id=user_id),
    ]


def _get_default_todos(user_id: str = "default") -> list[LifeTodoDB]:
    """获取默认待办种子数据.

    Args:
        user_id: 用户 ID

    Returns:
        默认待办列表
    """
    return [
        LifeTodoDB(todo_id=1, title="晨跑30分钟", status="done", progress=100,
                   category="今日待办", priority="high", user_id=user_id),
        LifeTodoDB(todo_id=2, title="整理工作邮件", status="done", progress=100,
                   category="今日待办", priority="medium", user_id=user_id),
        LifeTodoDB(todo_id=3, title="准备项目文档", status="in-progress", progress=60,
                   category="进行中", priority="high", user_id=user_id),
        LifeTodoDB(todo_id=4, title="学习新技能", status="in-progress", progress=40,
                   category="进行中", priority="medium", user_id=user_id),
        LifeTodoDB(todo_id=5, title="购物清单采购", status="todo", progress=0,
                   category="今日待办", priority="low", user_id=user_id),
        LifeTodoDB(todo_id=6, title="预约牙医", status="todo", progress=0,
                   category="今日待办", priority="medium", user_id=user_id),
        LifeTodoDB(todo_id=7, title="整理房间", status="todo", progress=0,
                   category="今日待办", priority="low", user_id=user_id),
        LifeTodoDB(todo_id=8, title="写周总结", status="todo", progress=0,
                   category="今日待办", priority="medium", user_id=user_id),
    ]


def _get_default_habits(user_id: str = "default") -> list[LifeHabitDB]:
    """获取默认习惯种子数据.

    Args:
        user_id: 用户 ID

    Returns:
        默认习惯列表
    """
    return [
        LifeHabitDB(habit_id=1, name="早起", icon="🌅", streak=15, longest_streak=20,
                    done=True, category="健康", frequency="daily", user_id=user_id),
        LifeHabitDB(habit_id=2, name="阅读30分钟", icon="📚", streak=8, longest_streak=12,
                    done=True, category="学习", frequency="daily", user_id=user_id),
        LifeHabitDB(habit_id=3, name="运动", icon="🏃", streak=12, longest_streak=15,
                    done=False, category="健康", frequency="daily", user_id=user_id),
        LifeHabitDB(habit_id=4, name="喝8杯水", icon="💧", streak=20, longest_streak=30,
                    done=True, category="健康", frequency="daily", user_id=user_id),
        LifeHabitDB(habit_id=5, name="冥想", icon="🧘", streak=5, longest_streak=7,
                    done=False, category="健康", frequency="daily", user_id=user_id),
    ]


def _get_default_habit_records(user_id: str = "default") -> list[LifeHabitRecordDB]:
    """获取默认习惯打卡记录（最近7天）.

    Args:
        user_id: 用户 ID

    Returns:
        默认打卡记录列表
    """
    records: list[LifeHabitRecordDB] = []
    today = datetime.now().date()
    habit_pairs = [(1, "早起"), (2, "阅读30分钟"), (3, "运动"), (4, "喝8杯水"), (5, "冥想")]
    random.seed(42)
    for i in range(7):
        date_str = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        for hid, _ in habit_pairs:
            completed = random.random() > (i * 0.1)
            records.append(LifeHabitRecordDB(
                habit_id=hid,
                date=date_str,
                completed=completed,
                note="" if completed else "今日未完成",
                user_id=user_id,
            ))
    return records


def _get_default_scenes(user_id: str = "default") -> list[LifeSceneDB]:
    """获取默认场景种子数据.

    Args:
        user_id: 用户 ID

    Returns:
        默认场景列表
    """
    return [
        LifeSceneDB(scene_id="home", name="居家模式", icon="🏠", active=True,
                    description="放松舒适的居家环境",
                    settings_json={"lighting": "warm", "volume": 50, "do_not_disturb": False},
                    user_id=user_id),
        LifeSceneDB(scene_id="work", name="工作模式", icon="💼", active=False,
                    description="专注高效的工作环境",
                    settings_json={"lighting": "cool", "volume": 20, "do_not_disturb": True},
                    user_id=user_id),
        LifeSceneDB(scene_id="sport", name="运动模式", icon="🏃", active=False,
                    description="活力四射的运动状态",
                    settings_json={"lighting": "bright", "volume": 80, "do_not_disturb": False},
                    user_id=user_id),
        LifeSceneDB(scene_id="sleep", name="睡眠模式", icon="🌙", active=False,
                    description="安静舒适的睡眠环境",
                    settings_json={"lighting": "off", "volume": 0, "do_not_disturb": True},
                    user_id=user_id),
        LifeSceneDB(scene_id="focus", name="专注模式", icon="🎯", active=False,
                    description="深度专注的工作状态",
                    settings_json={"lighting": "cool", "volume": 10, "do_not_disturb": True},
                    user_id=user_id),
    ]


def _get_default_rules(user_id: str = "default") -> list[LifeRuleDB]:
    """获取默认自动化规则种子数据.

    Args:
        user_id: 用户 ID

    Returns:
        默认规则列表
    """
    return [
        LifeRuleDB(rule_id=1, condition="到达23:00", action="启用勿扰模式",
                   enabled=True, category="时间", user_id=user_id),
        LifeRuleDB(rule_id=2, condition="检测到运动状态", action="切换至运动模式",
                   enabled=True, category="设备", user_id=user_id),
        LifeRuleDB(rule_id=3, condition="设备电量低于20%", action="低电量提醒",
                   enabled=True, category="设备", user_id=user_id),
        LifeRuleDB(rule_id=4, condition="离开家超过500米", action="启动安防模式",
                   enabled=False, category="位置", user_id=user_id),
    ]


def _get_default_finance_categories(user_id: str = "default") -> list[LifeFinanceCategoryDB]:
    """获取默认财务分类种子数据.

    Args:
        user_id: 用户 ID

    Returns:
        默认财务分类列表
    """
    return [
        LifeFinanceCategoryDB(category_id=1, name="餐饮美食", type="expense",
                              spent=1280, percentage=39, color="#FAAD14",
                              budget=2000, user_id=user_id),
        LifeFinanceCategoryDB(category_id=2, name="交通出行", type="expense",
                              spent=680, percentage=21, color="#1890FF",
                              budget=1000, user_id=user_id),
        LifeFinanceCategoryDB(category_id=3, name="购物消费", type="expense",
                              spent=560, percentage=17, color="#722ED1",
                              budget=800, user_id=user_id),
        LifeFinanceCategoryDB(category_id=4, name="休闲娱乐", type="expense",
                              spent=420, percentage=13, color="#52C41A",
                              budget=600, user_id=user_id),
        LifeFinanceCategoryDB(category_id=5, name="其他支出", type="expense",
                              spent=340, percentage=10, color="#8C8C8C",
                              budget=600, user_id=user_id),
    ]


def _get_default_finance_records(user_id: str = "default") -> list[LifeFinanceRecordDB]:
    """获取默认财务记录种子数据（最近30天随机生成）.

    Args:
        user_id: 用户 ID

    Returns:
        默认财务记录列表
    """
    records: list[LifeFinanceRecordDB] = []
    today = datetime.now().date()
    categories_expense = ["餐饮美食", "交通出行", "购物消费", "休闲娱乐", "其他支出"]
    amounts = {
        "餐饮美食": [35, 50, 80, 120, 200],
        "交通出行": [10, 20, 30, 50, 100],
        "购物消费": [50, 100, 200, 300, 500],
        "休闲娱乐": [30, 80, 150, 200, 300],
        "其他支出": [20, 50, 100, 150, 200],
    }
    descriptions = {
        "餐饮美食": ["午餐", "晚餐", "早餐", "下午茶", "聚餐"],
        "交通出行": ["地铁", "打车", "公交", "加油", "停车费"],
        "购物消费": ["日用品", "衣服", "电子产品", "书籍", "家居"],
        "休闲娱乐": ["电影", "游戏", "运动", "KTV", "旅游"],
        "其他支出": ["医疗", "教育", "礼物", "水电煤", "通讯"],
    }
    random.seed(42)
    for i in range(30):
        date_str = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        daily_count = random.randint(1, 3)
        for _ in range(daily_count):
            cat = random.choice(categories_expense)
            amount = random.choice(amounts[cat])
            desc = random.choice(descriptions[cat])
            records.append(LifeFinanceRecordDB(
                type="expense",
                amount=float(amount),
                category=cat,
                description=desc,
                transaction_date=date_str,
                user_id=user_id,
            ))
    # 添加几笔收入
    income_records = [
        ("工资收入", 15000, "月薪", (today - timedelta(days=5)).strftime("%Y-%m-%d")),
        ("理财收益", 500, "基金分红", (today - timedelta(days=10)).strftime("%Y-%m-%d")),
        ("兼职收入", 2000, "项目外包", (today - timedelta(days=15)).strftime("%Y-%m-%d")),
    ]
    for name, amount, desc, date_str in income_records:
        records.append(LifeFinanceRecordDB(
            type="income",
            amount=float(amount),
            category=name,
            description=desc,
            transaction_date=date_str,
            user_id=user_id,
        ))
    return records


def _get_default_meta_entries(user_id: str = "default") -> list[LifeMetaDB]:
    """获取默认元数据种子数据.

    Args:
        user_id: 用户 ID

    Returns:
        默认元数据列表
    """
    return [
        LifeMetaDB(meta_key="energy_data", user_id=user_id, meta_value=[
            {"id": 1, "label": "桌面终端", "value": "1.2kWh", "percentage": 50, "color": "green"},
            {"id": 2, "label": "智能设备", "value": "0.6kWh", "percentage": 25, "color": "blue"},
            {"id": 3, "label": "网络设备", "value": "0.4kWh", "percentage": 17, "color": "orange"},
            {"id": 4, "label": "其他", "value": "0.2kWh", "percentage": 8, "color": "gray"},
        ]),
        LifeMetaDB(meta_key="energy_total", user_id=user_id, meta_value={
            "total": "2.4kWh", "today": "2.4kWh", "week": "15.6kWh", "month": "68.2kWh",
        }),
        LifeMetaDB(meta_key="finance_overview", user_id=user_id, meta_value={
            "total_expense": 3280, "budget": 5000, "today_spending": 128,
            "month_progress": 65.6,
        }),
        LifeMetaDB(meta_key="assistant_tools", user_id=user_id, meta_value=[
            {"type": "weather", "title": "天气查询", "desc": "今日 26°C 晴", "icon": "☀️"},
            {"type": "cook", "title": "营养配餐", "desc": "推荐健康食谱", "icon": "🍳"},
            {"type": "travel", "title": "出行建议", "desc": "路况良好", "icon": "🚗"},
            {"type": "health", "title": "健康助手", "desc": "步数 6,842", "icon": "💊"},
        ]),
        LifeMetaDB(meta_key="life_stats", user_id=user_id, meta_value={
            "todo_completed": "2/8", "habit_checked": "3/5",
            "today_spending": "¥128", "steps": "6,842",
        }),
    ]


def seed_life_data(db: Session, user_id: str = "default") -> bool:
    """初始化生活管理模块的默认种子数据（幂等）.

    仅在日程表为空时执行初始化。

    Args:
        db: 数据库会话
        user_id: 用户 ID

    Returns:
        True 表示执行了初始化，False 表示已有数据跳过
    """
    schedule_count = (
        db.query(LifeScheduleDB)
        .filter(LifeScheduleDB.user_id == user_id)
        .count()
    )
    if schedule_count > 0:
        return False

    with transactional_scope(db):
        # 插入日程
        for s in _get_default_schedules(user_id):
            db.add(s)

        # 插入待办
        for t in _get_default_todos(user_id):
            db.add(t)

        # 插入习惯
        for h in _get_default_habits(user_id):
            db.add(h)

        # 插入习惯打卡记录
        for hr in _get_default_habit_records(user_id):
            db.add(hr)

        # 插入场景
        for s in _get_default_scenes(user_id):
            db.add(s)

        # 插入规则
        for r in _get_default_rules(user_id):
            db.add(r)

        # 插入财务分类
        for fc in _get_default_finance_categories(user_id):
            db.add(fc)

        # 插入财务记录
        for fr in _get_default_finance_records(user_id):
            db.add(fr)

        # 插入元数据
        for m in _get_default_meta_entries(user_id):
            db.add(m)

    logger.info("生活管理模式默认数据初始化完成 (user_id={user_id})", user_id=user_id)
    return True


# ---------------------------------------------------------------------------
# Repository 类
# ---------------------------------------------------------------------------


class LifeRepository:
    """生活管理数据仓库.

    提供日程、待办、习惯、场景、财务、规则的数据库操作。
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
            seed_life_data(self.db, self.user_id)
        except Exception as e:
            logger.warning("生活管理数据初始化跳过", error=str(e), error_type=type(e).__name__)

    # -----------------------------------------------------------------------
    # 日程相关方法
    # -----------------------------------------------------------------------

    def list_schedules(self, date: Optional[str] = None) -> list[LifeScheduleDB]:
        """获取日程列表（可按日期筛选）.

        Args:
            date: 按日期筛选（YYYY-MM-DD）

        Returns:
            日程列表，按开始时间升序
        """
        query = (
            self.db.query(LifeScheduleDB)
            .filter(LifeScheduleDB.user_id == self.user_id)
        )
        if date:
            query = query.filter(LifeScheduleDB.date == date)
        return query.order_by(LifeScheduleDB.start_time).all()

    def get_schedule(self, schedule_id: int) -> Optional[LifeScheduleDB]:
        """按业务 ID 获取日程.

        Args:
            schedule_id: 日程业务 ID

        Returns:
            日程对象，不存在返回 None
        """
        return (
            self.db.query(LifeScheduleDB)
            .filter(
                LifeScheduleDB.schedule_id == schedule_id,
                LifeScheduleDB.user_id == self.user_id,
            )
            .first()
        )

    def create_schedule(
        self,
        title: str,
        time_range: str,
        start_time: str,
        end_time: str,
        category: str = "固定",
        tag_color: str = "green",
        date: Optional[str] = None,
        description: str = "",
        all_day: bool = False,
        priority: str = "normal",
    ) -> LifeScheduleDB:
        """创建日程.

        Args:
            title: 标题
            time_range: 时间范围显示文本
            start_time: 开始时间
            end_time: 结束时间
            category: 分类
            tag_color: 标签颜色
            date: 日期
            description: 描述
            all_day: 是否全天
            priority: 优先级

        Returns:
            创建后的日程对象
        """
        all_schedules = (
            self.db.query(LifeScheduleDB)
            .filter(LifeScheduleDB.user_id == self.user_id)
            .all()
        )
        sid = max((s.schedule_id for s in all_schedules), default=0) + 1

        schedule = LifeScheduleDB(
            schedule_id=sid,
            title=title,
            description=description,
            time_range=time_range,
            start_time=start_time,
            end_time=end_time,
            date=date or datetime.now().strftime("%Y-%m-%d"),
            repeat_type="none",
            category=category,
            tag_color=tag_color,
            all_day=all_day,
            priority=priority,
            status="active",
            user_id=self.user_id,
        )
        with transactional_scope(self.db):
            self.db.add(schedule)
        self.db.refresh(schedule)
        return schedule

    def delete_schedule(self, schedule_id: int) -> bool:
        """删除日程.

        Args:
            schedule_id: 日程业务 ID

        Returns:
            True 表示删除成功，False 表示不存在
        """
        schedule = self.get_schedule(schedule_id)
        if not schedule:
            return False
        with transactional_scope(self.db):
            self.db.delete(schedule)
        return True

    def count_schedules(self, date: Optional[str] = None) -> int:
        """统计日程数量.

        Args:
            date: 按日期筛选

        Returns:
            日程数量
        """
        query = (
            self.db.query(LifeScheduleDB)
            .filter(LifeScheduleDB.user_id == self.user_id)
        )
        if date:
            query = query.filter(LifeScheduleDB.date == date)
        return query.count()

    # -----------------------------------------------------------------------
    # 待办相关方法
    # -----------------------------------------------------------------------

    def list_todos(
        self,
        status: Optional[str] = None,
        category: Optional[str] = None,
    ) -> list[LifeTodoDB]:
        """获取待办列表（可按状态/分类筛选）.

        Args:
            status: 按状态筛选
            category: 按分类筛选

        Returns:
            待办列表，按 todo_id 升序
        """
        query = (
            self.db.query(LifeTodoDB)
            .filter(LifeTodoDB.user_id == self.user_id)
        )
        if status:
            query = query.filter(LifeTodoDB.status == status)
        if category:
            query = query.filter(LifeTodoDB.category == category)
        return query.order_by(LifeTodoDB.todo_id).all()

    def get_todo(self, todo_id: int) -> Optional[LifeTodoDB]:
        """按业务 ID 获取待办.

        Args:
            todo_id: 待办业务 ID

        Returns:
            待办对象，不存在返回 None
        """
        return (
            self.db.query(LifeTodoDB)
            .filter(
                LifeTodoDB.todo_id == todo_id,
                LifeTodoDB.user_id == self.user_id,
            )
            .first()
        )

    def create_todo(
        self,
        title: str,
        status: str = "todo",
        category: str = "今日待办",
        priority: str = "normal",
        description: str = "",
        due_date: Optional[str] = None,
    ) -> LifeTodoDB:
        """创建待办.

        Args:
            title: 标题
            status: 状态
            category: 分类
            priority: 优先级
            description: 描述
            due_date: 截止日期

        Returns:
            创建后的待办对象
        """
        all_todos = (
            self.db.query(LifeTodoDB)
            .filter(LifeTodoDB.user_id == self.user_id)
            .all()
        )
        tid = max((t.todo_id for t in all_todos), default=0) + 1

        todo = LifeTodoDB(
            todo_id=tid,
            title=title,
            description=description,
            status=status,
            progress=100 if status == "done" else 0,
            category=category,
            priority=priority,
            due_date=due_date,
            user_id=self.user_id,
        )
        with transactional_scope(self.db):
            self.db.add(todo)
        self.db.refresh(todo)
        return todo

    def update_todo_status(
        self, todo_id: int, status: str,
    ) -> Optional[LifeTodoDB]:
        """更新待办状态.

        Args:
            todo_id: 待办业务 ID
            status: 新状态

        Returns:
            更新后的待办对象，不存在返回 None
        """
        todo = self.get_todo(todo_id)
        if not todo:
            return None

        with transactional_scope(self.db):
            todo.status = status
            if status == "done":
                todo.progress = 100
                todo.completed_at = datetime.utcnow()
            elif status == "in-progress":
                todo.progress = todo.progress if todo.progress and todo.progress > 0 else 50
                todo.completed_at = None
            else:
                todo.progress = 0
                todo.completed_at = None

            # 更新 category
            cat_map = {"todo": "今日待办", "in-progress": "进行中", "done": "已完成"}
            todo.category = cat_map.get(status, todo.category)

        self.db.refresh(todo)
        return todo

    def delete_todo(self, todo_id: int) -> bool:
        """删除待办.

        Args:
            todo_id: 待办业务 ID

        Returns:
            True 表示删除成功，False 表示不存在
        """
        todo = self.get_todo(todo_id)
        if not todo:
            return False
        with transactional_scope(self.db):
            self.db.delete(todo)
        return True

    def count_todos(self, status: Optional[str] = None) -> int:
        """统计待办数量.

        Args:
            status: 按状态筛选

        Returns:
            待办数量
        """
        query = (
            self.db.query(LifeTodoDB)
            .filter(LifeTodoDB.user_id == self.user_id)
        )
        if status:
            query = query.filter(LifeTodoDB.status == status)
        return query.count()

    # -----------------------------------------------------------------------
    # 习惯相关方法
    # -----------------------------------------------------------------------

    def list_habits(self) -> list[LifeHabitDB]:
        """获取习惯列表.

        Returns:
            习惯列表，按 habit_id 升序
        """
        return (
            self.db.query(LifeHabitDB)
            .filter(LifeHabitDB.user_id == self.user_id)
            .order_by(LifeHabitDB.habit_id)
            .all()
        )

    def get_habit(self, habit_id: int) -> Optional[LifeHabitDB]:
        """按业务 ID 获取习惯.

        Args:
            habit_id: 习惯业务 ID

        Returns:
            习惯对象，不存在返回 None
        """
        return (
            self.db.query(LifeHabitDB)
            .filter(
                LifeHabitDB.habit_id == habit_id,
                LifeHabitDB.user_id == self.user_id,
            )
            .first()
        )

    def create_habit(
        self,
        name: str,
        icon: str = "✅",
        category: str = "",
        frequency: str = "daily",
        description: str = "",
    ) -> LifeHabitDB:
        """创建习惯.

        Args:
            name: 习惯名称
            icon: 图标
            category: 分类
            frequency: 频率
            description: 描述

        Returns:
            创建后的习惯对象
        """
        all_habits = (
            self.db.query(LifeHabitDB)
            .filter(LifeHabitDB.user_id == self.user_id)
            .all()
        )
        hid = max((h.habit_id for h in all_habits), default=0) + 1

        habit = LifeHabitDB(
            habit_id=hid,
            name=name,
            description=description,
            category=category,
            icon=icon,
            streak=0,
            longest_streak=0,
            target_count=1,
            current_count=0,
            done=False,
            frequency=frequency,
            status="active",
            user_id=self.user_id,
        )
        with transactional_scope(self.db):
            self.db.add(habit)
        self.db.refresh(habit)
        return habit

    def checkin_habit(self, habit_id: int) -> Optional[LifeHabitDB]:
        """习惯打卡.

        Args:
            habit_id: 习惯业务 ID

        Returns:
            更新后的习惯对象，不存在返回 None
        """
        habit = self.get_habit(habit_id)
        if not habit:
            return None

        if not habit.done:
            with transactional_scope(self.db):
                habit.done = True
                habit.streak += 1
                if habit.streak > habit.longest_streak:
                    habit.longest_streak = habit.streak

                # 创建打卡记录（习惯更新+打卡记录在同一事务中）
                today_str = datetime.now().strftime("%Y-%m-%d")
                record = LifeHabitRecordDB(
                    habit_id=habit_id,
                    date=today_str,
                    completed=True,
                    note="",
                    user_id=self.user_id,
                )
                self.db.add(record)

            self.db.refresh(habit)

        return habit

    def delete_habit(self, habit_id: int) -> bool:
        """删除习惯.

        Args:
            habit_id: 习惯业务 ID

        Returns:
            True 表示删除成功，False 表示不存在
        """
        habit = self.get_habit(habit_id)
        if not habit:
            return False

        with transactional_scope(self.db):
            # 删除相关打卡记录
            self.db.query(LifeHabitRecordDB).filter(
                LifeHabitRecordDB.user_id == self.user_id,
                LifeHabitRecordDB.habit_id == habit_id,
            ).delete(synchronize_session=False)

            self.db.delete(habit)

        return True

    def count_habits(self, done: Optional[bool] = None) -> int:
        """统计习惯数量.

        Args:
            done: 按是否完成筛选

        Returns:
            习惯数量
        """
        query = (
            self.db.query(LifeHabitDB)
            .filter(LifeHabitDB.user_id == self.user_id)
        )
        if done is not None:
            query = query.filter(LifeHabitDB.done == done)
        return query.count()

    # -----------------------------------------------------------------------
    # 习惯打卡记录相关方法
    # -----------------------------------------------------------------------

    def list_habit_records(
        self,
        habit_id: Optional[int] = None,
        date: Optional[str] = None,
        limit: int = 30,
    ) -> list[LifeHabitRecordDB]:
        """获取习惯打卡记录列表.

        Args:
            habit_id: 按习惯筛选
            date: 按日期筛选
            limit: 返回条数限制

        Returns:
            打卡记录列表，按日期倒序
        """
        query = (
            self.db.query(LifeHabitRecordDB)
            .filter(LifeHabitRecordDB.user_id == self.user_id)
        )
        if habit_id:
            query = query.filter(LifeHabitRecordDB.habit_id == habit_id)
        if date:
            query = query.filter(LifeHabitRecordDB.date == date)
        return (
            query.order_by(desc(LifeHabitRecordDB.date))
            .limit(limit)
            .all()
        )

    # -----------------------------------------------------------------------
    # 场景相关方法
    # -----------------------------------------------------------------------

    def list_scenes(self) -> list[LifeSceneDB]:
        """获取场景列表.

        Returns:
            场景列表
        """
        return (
            self.db.query(LifeSceneDB)
            .filter(LifeSceneDB.user_id == self.user_id)
            .all()
        )

    def get_scene(self, scene_id: str) -> Optional[LifeSceneDB]:
        """按场景 ID 获取场景.

        Args:
            scene_id: 场景 ID（字符串 key）

        Returns:
            场景对象，不存在返回 None
        """
        return (
            self.db.query(LifeSceneDB)
            .filter(
                LifeSceneDB.scene_id == scene_id,
                LifeSceneDB.user_id == self.user_id,
            )
            .first()
        )

    def get_active_scene(self) -> Optional[LifeSceneDB]:
        """获取当前激活的场景.

        Returns:
            当前激活的场景对象，没有则返回第一个
        """
        scene = (
            self.db.query(LifeSceneDB)
            .filter(
                LifeSceneDB.user_id == self.user_id,
                LifeSceneDB.active is True,
            )
            .first()
        )
        if not scene:
            scene = (
                self.db.query(LifeSceneDB)
                .filter(LifeSceneDB.user_id == self.user_id)
                .first()
            )
        return scene

    def switch_scene(self, scene_key: str) -> Optional[LifeSceneDB]:
        """切换场景.

        Args:
            scene_key: 目标场景 key

        Returns:
            切换后的场景对象，不存在返回 None
        """
        scenes = (
            self.db.query(LifeSceneDB)
            .filter(LifeSceneDB.user_id == self.user_id)
            .all()
        )
        target = None
        with transactional_scope(self.db):
            for s in scenes:
                if s.scene_id == scene_key:
                    s.active = True
                    s.is_active = True
                    target = s
                else:
                    s.active = False
                    s.is_active = False

        if target:
            self.db.refresh(target)
            return target

        # 如果没找到目标场景，返回第一个
        if scenes:
            return scenes[0]
        return None

    # -----------------------------------------------------------------------
    # 自动化规则相关方法
    # -----------------------------------------------------------------------

    def list_rules(self) -> list[LifeRuleDB]:
        """获取自动化规则列表.

        Returns:
            规则列表，按 rule_id 升序
        """
        return (
            self.db.query(LifeRuleDB)
            .filter(LifeRuleDB.user_id == self.user_id)
            .order_by(LifeRuleDB.rule_id)
            .all()
        )

    def get_rule(self, rule_id: int) -> Optional[LifeRuleDB]:
        """按业务 ID 获取规则.

        Args:
            rule_id: 规则业务 ID

        Returns:
            规则对象，不存在返回 None
        """
        return (
            self.db.query(LifeRuleDB)
            .filter(
                LifeRuleDB.rule_id == rule_id,
                LifeRuleDB.user_id == self.user_id,
            )
            .first()
        )

    def create_rule(
        self,
        condition: str,
        action: str,
        title: str = "",
        category: str = "",
    ) -> LifeRuleDB:
        """创建自动化规则.

        Args:
            condition: 触发条件
            action: 执行动作
            title: 规则标题
            category: 分类

        Returns:
            创建后的规则对象
        """
        all_rules = (
            self.db.query(LifeRuleDB)
            .filter(LifeRuleDB.user_id == self.user_id)
            .all()
        )
        rid = max((r.rule_id for r in all_rules), default=0) + 1

        rule = LifeRuleDB(
            rule_id=rid,
            title=title,
            condition=condition,
            action=action,
            category=category,
            enabled=True,
            user_id=self.user_id,
        )
        with transactional_scope(self.db):
            self.db.add(rule)
        self.db.refresh(rule)
        return rule

    def toggle_rule(self, rule_id: int) -> Optional[LifeRuleDB]:
        """切换规则开关.

        Args:
            rule_id: 规则业务 ID

        Returns:
            更新后的规则对象，不存在返回 None
        """
        rule = self.get_rule(rule_id)
        if not rule:
            return None

        with transactional_scope(self.db):
            rule.enabled = not rule.enabled
        self.db.refresh(rule)
        return rule

    def delete_rule(self, rule_id: int) -> bool:
        """删除规则.

        Args:
            rule_id: 规则业务 ID

        Returns:
            True 表示删除成功，False 表示不存在
        """
        rule = self.get_rule(rule_id)
        if not rule:
            return False
        with transactional_scope(self.db):
            self.db.delete(rule)
        return True

    # -----------------------------------------------------------------------
    # 财务分类相关方法
    # -----------------------------------------------------------------------

    def list_finance_categories(
        self, type: Optional[str] = None,
    ) -> list[LifeFinanceCategoryDB]:
        """获取财务分类列表.

        Args:
            type: 按类型筛选（income/expense）

        Returns:
            财务分类列表，按 category_id 升序
        """
        query = (
            self.db.query(LifeFinanceCategoryDB)
            .filter(LifeFinanceCategoryDB.user_id == self.user_id)
        )
        if type:
            query = query.filter(LifeFinanceCategoryDB.type == type)
        return query.order_by(LifeFinanceCategoryDB.category_id).all()

    # -----------------------------------------------------------------------
    # 财务记录相关方法
    # -----------------------------------------------------------------------

    def list_finance_records(
        self,
        type: Optional[str] = None,
        category: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 50,
    ) -> list[LifeFinanceRecordDB]:
        """获取财务记录列表（支持筛选）.

        Args:
            type: 按类型筛选
            category: 按分类筛选
            start_date: 起始日期
            end_date: 结束日期
            limit: 返回条数限制

        Returns:
            财务记录列表，按交易日期倒序
        """
        query = (
            self.db.query(LifeFinanceRecordDB)
            .filter(LifeFinanceRecordDB.user_id == self.user_id)
        )
        if type:
            query = query.filter(LifeFinanceRecordDB.type == type)
        if category:
            query = query.filter(LifeFinanceRecordDB.category == category)
        if start_date:
            query = query.filter(LifeFinanceRecordDB.transaction_date >= start_date)
        if end_date:
            query = query.filter(LifeFinanceRecordDB.transaction_date <= end_date)
        return (
            query.order_by(desc(LifeFinanceRecordDB.transaction_date))
            .limit(limit)
            .all()
        )

    def create_finance_record(
        self,
        type: str,
        amount: float,
        category: str,
        description: str = "",
        transaction_date: Optional[str] = None,
    ) -> LifeFinanceRecordDB:
        """创建财务记录.

        Args:
            type: 类型（income/expense）
            amount: 金额
            category: 分类
            description: 描述
            transaction_date: 交易日期

        Returns:
            创建后的财务记录对象
        """
        record = LifeFinanceRecordDB(
            type=type,
            amount=amount,
            category=category,
            description=description,
            transaction_date=transaction_date or datetime.now().strftime("%Y-%m-%d"),
            user_id=self.user_id,
        )
        with transactional_scope(self.db):
            self.db.add(record)
        self.db.refresh(record)
        return record

    def get_finance_summary(self) -> dict[str, Any]:
        """获取财务汇总.

        Returns:
            财务汇总字典
        """
        today = datetime.now()
        month_start = today.strftime("%Y-%m-01")

        expense_total = (
            self.db.query(func.sum(LifeFinanceRecordDB.amount))
            .filter(
                LifeFinanceRecordDB.user_id == self.user_id,
                LifeFinanceRecordDB.type == "expense",
                LifeFinanceRecordDB.transaction_date >= month_start,
            )
            .scalar()
        ) or 0.0

        income_total = (
            self.db.query(func.sum(LifeFinanceRecordDB.amount))
            .filter(
                LifeFinanceRecordDB.user_id == self.user_id,
                LifeFinanceRecordDB.type == "income",
                LifeFinanceRecordDB.transaction_date >= month_start,
            )
            .scalar()
        ) or 0.0

        # 今日支出
        today_str = today.strftime("%Y-%m-%d")
        today_expense = (
            self.db.query(func.sum(LifeFinanceRecordDB.amount))
            .filter(
                LifeFinanceRecordDB.user_id == self.user_id,
                LifeFinanceRecordDB.type == "expense",
                LifeFinanceRecordDB.transaction_date == today_str,
            )
            .scalar()
        ) or 0.0

        # 预算总额
        budget_total = (
            self.db.query(func.sum(LifeFinanceCategoryDB.budget))
            .filter(
                LifeFinanceCategoryDB.user_id == self.user_id,
                LifeFinanceCategoryDB.type == "expense",
            )
            .scalar()
        ) or 0.0

        month_progress = (
            round((expense_total / budget_total * 100), 1)
            if budget_total > 0 else 0
        )

        return {
            "total_expense": round(expense_total, 2),
            "total_income": round(income_total, 2),
            "budget": round(budget_total, 2),
            "today_spending": round(today_expense, 2),
            "month_progress": month_progress,
        }

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
            self.db.query(LifeMetaDB)
            .filter(
                LifeMetaDB.meta_key == key,
                LifeMetaDB.user_id == self.user_id,
            )
            .first()
        )
        return meta.meta_value if meta else None

    def set_meta(self, key: str, value: Any) -> LifeMetaDB:
        """设置元数据值.

        Args:
            key: 元数据键名
            value: 元数据值

        Returns:
            更新或创建后的元数据对象
        """
        meta = (
            self.db.query(LifeMetaDB)
            .filter(
                LifeMetaDB.meta_key == key,
                LifeMetaDB.user_id == self.user_id,
            )
            .first()
        )
        with transactional_scope(self.db):
            if meta:
                meta.meta_value = value
            else:
                meta = LifeMetaDB(
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
        """获取生活管理概览统计.

        Returns:
            概览统计字典
        """
        todos = self.list_todos()
        done_count = sum(1 for t in todos if t.status == "done")

        habits = self.list_habits()
        habit_done = sum(1 for h in habits if h.done)

        today = datetime.now().strftime("%Y-%m-%d")
        schedule_count = self.count_schedules(date=today)

        finance_summary = self.get_finance_summary()
        current_scene = self.get_active_scene()

        return {
            "todo_total": len(todos),
            "todo_done": done_count,
            "habit_total": len(habits),
            "habit_done": habit_done,
            "schedule_total": schedule_count,
            "finance": finance_summary,
            "current_scene": current_scene,
        }
