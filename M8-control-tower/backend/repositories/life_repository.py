"""
M8 生活管理 - 数据仓库层

封装日程、待办、习惯、场景、财务、规则的数据库 CRUD。
迁移过渡期：优先读 DB，DB 为空时自动从内存默认数据初始化。
"""

from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import desc

from ..models import (
    LifeSchedule,
    LifeTodo,
    LifeHabit,
    LifeHabitRecord,
    LifeScene,
    LifeFinanceCategory,
    LifeFinanceRecord,
    LifeRule,
    LifeMeta,
)


# ========== 默认种子数据 ==========

def _get_default_schedules(user_id: int = 1) -> List[LifeSchedule]:
    """获取默认日程数据"""
    today = datetime.now().strftime("%Y-%m-%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    return [
        LifeSchedule(schedule_id=1, title="晨间复盘", time_range="09:00 - 10:30",
                     start_time="09:00", end_time="10:30", category="固定",
                     tag_color="green", date=today, user_id=user_id),
        LifeSchedule(schedule_id=2, title="团队站会", time_range="14:00 - 15:00",
                     start_time="14:00", end_time="15:00", category="协作",
                     tag_color="blue", date=today, user_id=user_id),
        LifeSchedule(schedule_id=3, title="运动时间", time_range="19:00 - 20:00",
                     start_time="19:00", end_time="20:00", category="健康",
                     tag_color="orange", date=today, user_id=user_id),
        LifeSchedule(schedule_id=4, title="项目评审", time_range="10:00 - 11:30",
                     start_time="10:00", end_time="11:30", category="协作",
                     tag_color="blue", date=tomorrow, user_id=user_id),
        LifeSchedule(schedule_id=5, title="阅读时间", time_range="20:00 - 21:00",
                     start_time="20:00", end_time="21:00", category="固定",
                     tag_color="green", date=tomorrow, user_id=user_id),
    ]


def _get_default_todos(user_id: int = 1) -> List[LifeTodo]:
    """获取默认待办数据"""
    return [
        LifeTodo(todo_id=1, title="晨跑30分钟", status="done", progress=100,
                 category="今日待办", priority="high", user_id=user_id),
        LifeTodo(todo_id=2, title="整理工作邮件", status="done", progress=100,
                 category="今日待办", priority="medium", user_id=user_id),
        LifeTodo(todo_id=3, title="准备项目文档", status="in-progress", progress=60,
                 category="进行中", priority="high", user_id=user_id),
        LifeTodo(todo_id=4, title="学习新技能", status="in-progress", progress=40,
                 category="进行中", priority="medium", user_id=user_id),
        LifeTodo(todo_id=5, title="购物清单采购", status="todo", progress=0,
                 category="今日待办", priority="low", user_id=user_id),
        LifeTodo(todo_id=6, title="预约牙医", status="todo", progress=0,
                 category="今日待办", priority="medium", user_id=user_id),
        LifeTodo(todo_id=7, title="整理房间", status="todo", progress=0,
                 category="今日待办", priority="low", user_id=user_id),
        LifeTodo(todo_id=8, title="写周总结", status="todo", progress=0,
                 category="今日待办", priority="medium", user_id=user_id),
    ]


def _get_default_habits(user_id: int = 1) -> List[LifeHabit]:
    """获取默认习惯数据"""
    return [
        LifeHabit(habit_id=1, name="早起", icon="🌅", streak=15, longest_streak=20,
                  done=True, category="健康", frequency="daily", user_id=user_id),
        LifeHabit(habit_id=2, name="阅读30分钟", icon="📚", streak=8, longest_streak=12,
                  done=True, category="学习", frequency="daily", user_id=user_id),
        LifeHabit(habit_id=3, name="运动", icon="🏃", streak=12, longest_streak=15,
                  done=False, category="健康", frequency="daily", user_id=user_id),
        LifeHabit(habit_id=4, name="喝8杯水", icon="💧", streak=20, longest_streak=30,
                  done=True, category="健康", frequency="daily", user_id=user_id),
        LifeHabit(habit_id=5, name="冥想", icon="🧘", streak=5, longest_streak=7,
                  done=False, category="健康", frequency="daily", user_id=user_id),
    ]


def _get_default_habit_records(user_id: int = 1) -> List[LifeHabitRecord]:
    """获取默认习惯打卡记录（最近7天）"""
    records = []
    today = datetime.now().date()
    habit_pairs = [(1, "早起"), (2, "阅读30分钟"), (3, "运动"), (4, "喝8杯水"), (5, "冥想")]
    for i in range(7):
        date_str = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        for hid, hname in habit_pairs:
            # 模拟随机打卡，越近的日期完成率越高
            import random
            random.seed(hid * 100 + i)
            completed = random.random() > (i * 0.1)
            records.append(LifeHabitRecord(
                habit_id=hid,
                date=date_str,
                completed=completed,
                note="" if completed else "今日未完成",
                user_id=user_id,
            ))
    return records


def _get_default_scenes(user_id: int = 1) -> List[LifeScene]:
    """获取默认场景数据"""
    return [
        LifeScene(scene_id="home", name="居家模式", icon="🏠", active=True,
                  description="放松舒适的居家环境",
                  settings_json={"lighting": "warm", "volume": 50, "do_not_disturb": False},
                  user_id=user_id),
        LifeScene(scene_id="work", name="工作模式", icon="💼", active=False,
                  description="专注高效的工作环境",
                  settings_json={"lighting": "cool", "volume": 20, "do_not_disturb": True},
                  user_id=user_id),
        LifeScene(scene_id="sport", name="运动模式", icon="🏃", active=False,
                  description="活力四射的运动状态",
                  settings_json={"lighting": "bright", "volume": 80, "do_not_disturb": False},
                  user_id=user_id),
        LifeScene(scene_id="sleep", name="睡眠模式", icon="🌙", active=False,
                  description="安静舒适的睡眠环境",
                  settings_json={"lighting": "off", "volume": 0, "do_not_disturb": True},
                  user_id=user_id),
        LifeScene(scene_id="focus", name="专注模式", icon="🎯", active=False,
                  description="深度专注的工作状态",
                  settings_json={"lighting": "cool", "volume": 10, "do_not_disturb": True},
                  user_id=user_id),
    ]


def _get_default_rules(user_id: int = 1) -> List[LifeRule]:
    """获取默认自动化规则数据"""
    return [
        LifeRule(rule_id=1, condition="到达23:00", action="启用勿扰模式",
                 enabled=True, category="时间", user_id=user_id),
        LifeRule(rule_id=2, condition="检测到运动状态", action="切换至运动模式",
                 enabled=True, category="设备", user_id=user_id),
        LifeRule(rule_id=3, condition="设备电量低于20%", action="低电量提醒",
                 enabled=True, category="设备", user_id=user_id),
        LifeRule(rule_id=4, condition="离开家超过500米", action="启动安防模式",
                 enabled=False, category="位置", user_id=user_id),
    ]


def _get_default_finance_categories(user_id: int = 1) -> List[LifeFinanceCategory]:
    """获取默认财务分类数据"""
    return [
        LifeFinanceCategory(category_id=1, name="餐饮美食", type="expense",
                            spent=1280, percentage=39, color="#FAAD14",
                            budget=2000, user_id=user_id),
        LifeFinanceCategory(category_id=2, name="交通出行", type="expense",
                            spent=680, percentage=21, color="#1890FF",
                            budget=1000, user_id=user_id),
        LifeFinanceCategory(category_id=3, name="购物消费", type="expense",
                            spent=560, percentage=17, color="#722ED1",
                            budget=800, user_id=user_id),
        LifeFinanceCategory(category_id=4, name="休闲娱乐", type="expense",
                            spent=420, percentage=13, color="#52C41A",
                            budget=600, user_id=user_id),
        LifeFinanceCategory(category_id=5, name="其他支出", type="expense",
                            spent=340, percentage=10, color="#8C8C8C",
                            budget=600, user_id=user_id),
    ]


def _get_default_finance_records(user_id: int = 1) -> List[LifeFinanceRecord]:
    """获取默认财务记录数据（最近30天随机生成）"""
    records = []
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
    import random
    random.seed(42)
    for i in range(30):
        date_str = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        # 每天 1-3 笔支出
        daily_count = random.randint(1, 3)
        for _ in range(daily_count):
            cat = random.choice(categories_expense)
            amount = random.choice(amounts[cat])
            desc = random.choice(descriptions[cat])
            records.append(LifeFinanceRecord(
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
        records.append(LifeFinanceRecord(
            type="income",
            amount=float(amount),
            category=name,
            description=desc,
            transaction_date=date_str,
            user_id=user_id,
        ))
    return records


def _get_default_meta_entries(user_id: int = 1) -> List[LifeMeta]:
    """获取默认元数据"""
    return [
        LifeMeta(meta_key="energy_data", user_id=user_id, meta_value=[
            {"id": 1, "label": "桌面终端", "value": "1.2kWh", "percentage": 50, "color": "green"},
            {"id": 2, "label": "智能设备", "value": "0.6kWh", "percentage": 25, "color": "blue"},
            {"id": 3, "label": "网络设备", "value": "0.4kWh", "percentage": 17, "color": "orange"},
            {"id": 4, "label": "其他", "value": "0.2kWh", "percentage": 8, "color": "gray"},
        ]),
        LifeMeta(meta_key="energy_total", user_id=user_id, meta_value={
            "total": "2.4kWh", "today": "2.4kWh", "week": "15.6kWh", "month": "68.2kWh",
        }),
        LifeMeta(meta_key="finance_overview", user_id=user_id, meta_value={
            "total_expense": 3280, "budget": 5000, "today_spending": 128,
            "month_progress": 65.6,
        }),
        LifeMeta(meta_key="assistant_tools", user_id=user_id, meta_value=[
            {"type": "weather", "title": "天气查询", "desc": "今日 26°C 晴", "icon": "☀️"},
            {"type": "cook", "title": "营养配餐", "desc": "推荐健康食谱", "icon": "🍳"},
            {"type": "travel", "title": "出行建议", "desc": "路况良好", "icon": "🚗"},
            {"type": "health", "title": "健康助手", "desc": "步数 6,842", "icon": "💊"},
        ]),
        LifeMeta(meta_key="life_stats", user_id=user_id, meta_value={
            "todo_completed": "2/8", "habit_checked": "3/5",
            "today_spending": "¥128", "steps": "6,842",
        }),
    ]


# ========== 初始化种子数据 ==========

def seed_life_data(db: Session, user_id: int = 1) -> bool:
    """初始化生活管理模块的默认数据（幂等）

    Returns:
        True 表示执行了初始化，False 表示已有数据跳过
    """
    # 检查日程表是否为空
    schedule_count = db.query(LifeSchedule).filter(LifeSchedule.user_id == user_id).count()
    if schedule_count > 0:
        return False

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

    db.commit()
    print(f"[Seed] 生活管理默认数据初始化完成 (user_id={user_id})")
    return True


# ========== Repository 类 ==========

class LifeRepository:
    """生活管理数据仓库"""

    def __init__(self, db: Session, user_id: int = 1):
        self.db = db
        self.user_id = user_id
        self._ensure_seeded()

    def _ensure_seeded(self):
        """确保种子数据已初始化"""
        try:
            seed_life_data(self.db, self.user_id)
        except Exception as e:
            print(f"[Seed] 生活管理数据初始化跳过: {e}")

    # ---------- 日程 ----------

    def list_schedules(self, date: Optional[str] = None) -> List[LifeSchedule]:
        """获取日程列表（可按日期筛选）"""
        query = self.db.query(LifeSchedule).filter(LifeSchedule.user_id == self.user_id)
        if date:
            query = query.filter(LifeSchedule.date == date)
        return query.order_by(LifeSchedule.start_time).all()

    def get_schedule(self, schedule_id: int) -> Optional[LifeSchedule]:
        """按业务 ID 获取日程"""
        return (
            self.db.query(LifeSchedule)
            .filter(LifeSchedule.schedule_id == schedule_id, LifeSchedule.user_id == self.user_id)
            .first()
        )

    def create_schedule(self, title: str, time_range: str, start_time: str, end_time: str,
                        category: str = "固定", tag_color: str = "green",
                        date: Optional[str] = None, description: str = "",
                        all_day: bool = False, priority: str = "normal") -> LifeSchedule:
        """创建日程"""
        all_schedules = self.db.query(LifeSchedule).filter_by(user_id=self.user_id).all()
        sid = max((s.schedule_id for s in all_schedules), default=0) + 1

        schedule = LifeSchedule(
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
        self.db.add(schedule)
        self.db.commit()
        self.db.refresh(schedule)
        return schedule

    def delete_schedule(self, schedule_id: int) -> bool:
        """删除日程"""
        schedule = self.get_schedule(schedule_id)
        if not schedule:
            return False
        self.db.delete(schedule)
        self.db.commit()
        return True

    def count_schedules(self, date: Optional[str] = None) -> int:
        """日程数量"""
        query = self.db.query(LifeSchedule).filter(LifeSchedule.user_id == self.user_id)
        if date:
            query = query.filter(LifeSchedule.date == date)
        return query.count()

    # ---------- 待办 ----------

    def list_todos(self, status: Optional[str] = None,
                   category: Optional[str] = None) -> List[LifeTodo]:
        """获取待办列表（可按状态/分类筛选）"""
        query = self.db.query(LifeTodo).filter(LifeTodo.user_id == self.user_id)
        if status:
            query = query.filter(LifeTodo.status == status)
        if category:
            query = query.filter(LifeTodo.category == category)
        return query.order_by(LifeTodo.todo_id).all()

    def get_todo(self, todo_id: int) -> Optional[LifeTodo]:
        """按业务 ID 获取待办"""
        return (
            self.db.query(LifeTodo)
            .filter(LifeTodo.todo_id == todo_id, LifeTodo.user_id == self.user_id)
            .first()
        )

    def create_todo(self, title: str, status: str = "todo",
                    category: str = "今日待办", priority: str = "normal",
                    description: str = "", due_date: Optional[str] = None) -> LifeTodo:
        """创建待办"""
        all_todos = self.db.query(LifeTodo).filter_by(user_id=self.user_id).all()
        tid = max((t.todo_id for t in all_todos), default=0) + 1

        todo = LifeTodo(
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
        self.db.add(todo)
        self.db.commit()
        self.db.refresh(todo)
        return todo

    def update_todo_status(self, todo_id: int, status: str) -> Optional[LifeTodo]:
        """更新待办状态"""
        todo = self.get_todo(todo_id)
        if not todo:
            return None

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

        self.db.commit()
        self.db.refresh(todo)
        return todo

    def delete_todo(self, todo_id: int) -> bool:
        """删除待办"""
        todo = self.get_todo(todo_id)
        if not todo:
            return False
        self.db.delete(todo)
        self.db.commit()
        return True

    def count_todos(self, status: Optional[str] = None) -> int:
        """待办数量"""
        query = self.db.query(LifeTodo).filter(LifeTodo.user_id == self.user_id)
        if status:
            query = query.filter(LifeTodo.status == status)
        return query.count()

    # ---------- 习惯 ----------

    def list_habits(self) -> List[LifeHabit]:
        """获取习惯列表"""
        return (
            self.db.query(LifeHabit)
            .filter(LifeHabit.user_id == self.user_id)
            .order_by(LifeHabit.habit_id)
            .all()
        )

    def get_habit(self, habit_id: int) -> Optional[LifeHabit]:
        """按业务 ID 获取习惯"""
        return (
            self.db.query(LifeHabit)
            .filter(LifeHabit.habit_id == habit_id, LifeHabit.user_id == self.user_id)
            .first()
        )

    def create_habit(self, name: str, icon: str = "✅",
                     category: str = "", frequency: str = "daily",
                     target_count: int = 1, description: str = "") -> LifeHabit:
        """创建习惯"""
        all_habits = self.db.query(LifeHabit).filter_by(user_id=self.user_id).all()
        hid = max((h.habit_id for h in all_habits), default=0) + 1

        habit = LifeHabit(
            habit_id=hid,
            name=name,
            description=description,
            category=category,
            icon=icon,
            streak=0,
            longest_streak=0,
            target_count=target_count,
            current_count=0,
            done=False,
            frequency=frequency,
            status="active",
            user_id=self.user_id,
        )
        self.db.add(habit)
        self.db.commit()
        self.db.refresh(habit)
        return habit

    def checkin_habit(self, habit_id: int) -> Optional[LifeHabit]:
        """习惯打卡"""
        habit = self.get_habit(habit_id)
        if not habit:
            return None

        if not habit.done:
            habit.done = True
            habit.streak += 1
            if habit.streak > habit.longest_streak:
                habit.longest_streak = habit.streak

            # 创建打卡记录
            today_str = datetime.now().strftime("%Y-%m-%d")
            record = LifeHabitRecord(
                habit_id=habit_id,
                date=today_str,
                completed=True,
                note="",
                user_id=self.user_id,
            )
            self.db.add(record)

            self.db.commit()
            self.db.refresh(habit)

        return habit

    def delete_habit(self, habit_id: int) -> bool:
        """删除习惯"""
        habit = self.get_habit(habit_id)
        if not habit:
            return False
        self.db.delete(habit)
        self.db.commit()
        return True

    def count_habits(self, done: Optional[bool] = None) -> int:
        """习惯数量"""
        query = self.db.query(LifeHabit).filter(LifeHabit.user_id == self.user_id)
        if done is not None:
            query = query.filter(LifeHabit.done == done)
        return query.count()

    # ---------- 习惯打卡记录 ----------

    def list_habit_records(self, habit_id: Optional[int] = None,
                           date: Optional[str] = None,
                           limit: int = 30) -> List[LifeHabitRecord]:
        """获取习惯打卡记录"""
        query = self.db.query(LifeHabitRecord).filter(LifeHabitRecord.user_id == self.user_id)
        if habit_id:
            query = query.filter(LifeHabitRecord.habit_id == habit_id)
        if date:
            query = query.filter(LifeHabitRecord.date == date)
        return query.order_by(desc(LifeHabitRecord.date)).limit(limit).all()

    # ---------- 场景 ----------

    def list_scenes(self) -> List[LifeScene]:
        """获取场景列表"""
        return (
            self.db.query(LifeScene)
            .filter(LifeScene.user_id == self.user_id)
            .all()
        )

    def get_scene(self, scene_id: str) -> Optional[LifeScene]:
        """按场景 ID 获取场景"""
        return (
            self.db.query(LifeScene)
            .filter(LifeScene.scene_id == scene_id, LifeScene.user_id == self.user_id)
            .first()
        )

    def get_active_scene(self) -> Optional[LifeScene]:
        """获取当前激活的场景"""
        scene = (
            self.db.query(LifeScene)
            .filter(LifeScene.user_id == self.user_id, LifeScene.active == True)
            .first()
        )
        if not scene:
            scene = (
                self.db.query(LifeScene)
                .filter(LifeScene.user_id == self.user_id)
                .first()
            )
        return scene

    def switch_scene(self, scene_key: str) -> Optional[LifeScene]:
        """切换场景"""
        scenes = self.db.query(LifeScene).filter(LifeScene.user_id == self.user_id).all()
        target = None
        for s in scenes:
            if s.scene_id == scene_key:
                s.active = True
                s.is_active = True
                target = s
            else:
                s.active = False
                s.is_active = False

        self.db.commit()

        if target:
            self.db.refresh(target)
            return target

        # 如果没找到目标场景，返回第一个
        if scenes:
            return scenes[0]
        return None

    # ---------- 自动化规则 ----------

    def list_rules(self) -> List[LifeRule]:
        """获取自动化规则列表"""
        return (
            self.db.query(LifeRule)
            .filter(LifeRule.user_id == self.user_id)
            .order_by(LifeRule.rule_id)
            .all()
        )

    def get_rule(self, rule_id: int) -> Optional[LifeRule]:
        """按业务 ID 获取规则"""
        return (
            self.db.query(LifeRule)
            .filter(LifeRule.rule_id == rule_id, LifeRule.user_id == self.user_id)
            .first()
        )

    def create_rule(self, condition: str, action: str,
                    title: str = "", category: str = "") -> LifeRule:
        """创建自动化规则"""
        all_rules = self.db.query(LifeRule).filter_by(user_id=self.user_id).all()
        rid = max((r.rule_id for r in all_rules), default=0) + 1

        rule = LifeRule(
            rule_id=rid,
            title=title,
            condition=condition,
            action=action,
            category=category,
            enabled=True,
            user_id=self.user_id,
        )
        self.db.add(rule)
        self.db.commit()
        self.db.refresh(rule)
        return rule

    def toggle_rule(self, rule_id: int) -> Optional[LifeRule]:
        """切换规则开关"""
        rule = self.get_rule(rule_id)
        if not rule:
            return None

        rule.enabled = not rule.enabled
        self.db.commit()
        self.db.refresh(rule)
        return rule

    def delete_rule(self, rule_id: int) -> bool:
        """删除规则"""
        rule = self.get_rule(rule_id)
        if not rule:
            return False
        self.db.delete(rule)
        self.db.commit()
        return True

    # ---------- 财务分类 ----------

    def list_finance_categories(self, type: Optional[str] = None) -> List[LifeFinanceCategory]:
        """获取财务分类列表"""
        query = self.db.query(LifeFinanceCategory).filter(LifeFinanceCategory.user_id == self.user_id)
        if type:
            query = query.filter(LifeFinanceCategory.type == type)
        return query.order_by(LifeFinanceCategory.category_id).all()

    # ---------- 财务记录 ----------

    def list_finance_records(self, type: Optional[str] = None,
                             category: Optional[str] = None,
                             start_date: Optional[str] = None,
                             end_date: Optional[str] = None,
                             limit: int = 50) -> List[LifeFinanceRecord]:
        """获取财务记录列表（支持筛选）"""
        query = self.db.query(LifeFinanceRecord).filter(LifeFinanceRecord.user_id == self.user_id)
        if type:
            query = query.filter(LifeFinanceRecord.type == type)
        if category:
            query = query.filter(LifeFinanceRecord.category == category)
        if start_date:
            query = query.filter(LifeFinanceRecord.transaction_date >= start_date)
        if end_date:
            query = query.filter(LifeFinanceRecord.transaction_date <= end_date)
        return query.order_by(desc(LifeFinanceRecord.transaction_date)).limit(limit).all()

    def create_finance_record(self, type: str, amount: float,
                              category: str, description: str = "",
                              transaction_date: Optional[str] = None) -> LifeFinanceRecord:
        """创建财务记录"""
        record = LifeFinanceRecord(
            type=type,
            amount=amount,
            category=category,
            description=description,
            transaction_date=transaction_date or datetime.now().strftime("%Y-%m-%d"),
            user_id=self.user_id,
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def get_finance_summary(self) -> Dict[str, Any]:
        """获取财务汇总"""
        from sqlalchemy import func

        # 本月支出
        today = datetime.now()
        month_start = today.strftime("%Y-%m-01")

        expense_total = (
            self.db.query(func.sum(LifeFinanceRecord.amount))
            .filter(
                LifeFinanceRecord.user_id == self.user_id,
                LifeFinanceRecord.type == "expense",
                LifeFinanceRecord.transaction_date >= month_start,
            )
            .scalar()
        ) or 0.0

        income_total = (
            self.db.query(func.sum(LifeFinanceRecord.amount))
            .filter(
                LifeFinanceRecord.user_id == self.user_id,
                LifeFinanceRecord.type == "income",
                LifeFinanceRecord.transaction_date >= month_start,
            )
            .scalar()
        ) or 0.0

        # 今日支出
        today_str = today.strftime("%Y-%m-%d")
        today_expense = (
            self.db.query(func.sum(LifeFinanceRecord.amount))
            .filter(
                LifeFinanceRecord.user_id == self.user_id,
                LifeFinanceRecord.type == "expense",
                LifeFinanceRecord.transaction_date == today_str,
            )
            .scalar()
        ) or 0.0

        # 预算总额
        budget_total = (
            self.db.query(func.sum(LifeFinanceCategory.budget))
            .filter(
                LifeFinanceCategory.user_id == self.user_id,
                LifeFinanceCategory.type == "expense",
            )
            .scalar()
        ) or 0.0

        month_progress = round((expense_total / budget_total * 100), 1) if budget_total > 0 else 0

        return {
            "total_expense": round(expense_total, 2),
            "total_income": round(income_total, 2),
            "budget": round(budget_total, 2),
            "today_spending": round(today_expense, 2),
            "month_progress": month_progress,
        }

    # ---------- 元数据 ----------

    def get_meta(self, key: str) -> Any:
        """获取元数据值"""
        meta = (
            self.db.query(LifeMeta)
            .filter(LifeMeta.meta_key == key, LifeMeta.user_id == self.user_id)
            .first()
        )
        return meta.meta_value if meta else None

    def set_meta(self, key: str, value: Any) -> LifeMeta:
        """设置元数据值"""
        meta = (
            self.db.query(LifeMeta)
            .filter(LifeMeta.meta_key == key, LifeMeta.user_id == self.user_id)
            .first()
        )
        if meta:
            meta.meta_value = value
        else:
            meta = LifeMeta(
                meta_key=key,
                meta_value=value,
                user_id=self.user_id,
            )
            self.db.add(meta)
        self.db.commit()
        self.db.refresh(meta)
        return meta

    # ---------- 概览统计 ----------

    def get_overview_stats(self) -> Dict[str, Any]:
        """获取生活管理概览统计"""
        todos = self.list_todos()
        done_count = sum(1 for t in todos if t.status == "done")

        habits = self.list_habits()
        habit_done = sum(1 for h in habits if h.done)

        finance_summary = self.get_finance_summary()
        current_scene = self.get_active_scene()

        return {
            "todo_total": len(todos),
            "todo_done": done_count,
            "habit_total": len(habits),
            "habit_done": habit_done,
            "finance": finance_summary,
            "current_scene": current_scene,
        }
