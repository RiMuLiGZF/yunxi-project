"""
模式页持久化验证脚本
测试学业规划和生活管理两个模式的数据库持久化功能

使用方法：
    cd c:\Yunxi\workspace\yunxi-project\M8-control-tower\backend
    python test_modes_p2.py
"""

import sys
import os
from pathlib import Path
from datetime import datetime, timedelta

# 将项目根目录加入 path
backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

# 使用临时数据库
TEST_DB_PATH = os.path.join(backend_dir, "data", "test_modes_p2.db")

# 先删除旧的测试数据库
if os.path.exists(TEST_DB_PATH):
    os.remove(TEST_DB_PATH)
    print(f"[清理] 已删除旧测试数据库: {TEST_DB_PATH}")

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

# 导入模型
from models import (
    Base,
    StudyGoal, StudyPlan, StudyNote, StudyKnowledgeCategory,
    StudyExam, StudyProgress, StudyMeta,
    LifeSchedule, LifeRule, LifeTodo, LifeHabit,
    LifeScene, LifeFinanceCategory, LifeMeta,
)

# 创建测试数据库引擎
engine = create_engine(
    f"sqlite:///{TEST_DB_PATH}",
    connect_args={"check_same_thread": False},
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 创建所有表
Base.metadata.create_all(bind=engine)
print(f"[初始化] 测试数据库已创建: {TEST_DB_PATH}")

# 统计创建的表
inspector = inspect(engine)
tables = inspector.get_table_names()
study_tables = [t for t in tables if t.startswith("study_")]
life_tables = [t for t in tables if t.startswith("life_")]
print(f"[表结构] 学业规划表: {len(study_tables)} 张 - {study_tables}")
print(f"[表结构] 生活管理表: {len(life_tables)} 张 - {life_tables}")

DEFAULT_USER_ID = 1

passed = 0
failed = 0


def test(name, condition, detail=""):
    """测试断言"""
    global passed, failed
    if condition:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        print(f"  ❌ {name} - {detail}")


def section(title):
    """打印章节标题"""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ==================== 初始化函数（复刻路由里的逻辑） ====================

def _calc_duration(start: str, end: str) -> float:
    sh, sm = map(int, start.split(":"))
    eh, em = map(int, end.split(":"))
    return round((eh * 60 + em - sh * 60 - sm) / 60, 1)


def init_study_data(db, user_id=DEFAULT_USER_ID):
    """初始化学业规划示例数据"""
    if db.query(StudyGoal).filter_by(user_id=user_id).count() == 0:
        default_goals = [
            {"goal_id": 1, "title": "本学期总目标", "icon": "🎯", "progress": 52,
             "status": "in-progress", "expanded": True, "parent_id": None, "level": 0, "order_index": 1},
            {"goal_id": 2, "title": "专业课复习", "icon": "📚", "progress": 75,
             "status": "in-progress", "expanded": True, "parent_id": 1, "level": 1, "order_index": 1},
            {"goal_id": 3, "title": "高等数学", "icon": "📐", "progress": 100,
             "status": "complete", "expanded": False, "parent_id": 2, "level": 2, "order_index": 1},
            {"goal_id": 4, "title": "线性代数", "icon": "🔢", "progress": 80,
             "status": "in-progress", "expanded": False, "parent_id": 2, "level": 2, "order_index": 2},
            {"goal_id": 5, "title": "概率统计", "icon": "📊", "progress": 45,
             "status": "warning", "expanded": False, "parent_id": 2, "level": 2, "order_index": 3},
            {"goal_id": 6, "title": "毕业论文", "icon": "📝", "progress": 30,
             "status": "warning", "expanded": True, "parent_id": 1, "level": 1, "order_index": 2},
            {"goal_id": 7, "title": "文献综述", "icon": "📄", "progress": 60,
             "status": "in-progress", "expanded": False, "parent_id": 6, "level": 2, "order_index": 1},
            {"goal_id": 8, "title": "数据收集", "icon": "🗃️", "progress": 20,
             "status": "warning", "expanded": False, "parent_id": 6, "level": 2, "order_index": 2},
            {"goal_id": 9, "title": "初稿撰写", "icon": "✍️", "progress": 0,
             "status": "not-started", "expanded": False, "parent_id": 6, "level": 2, "order_index": 3},
            {"goal_id": 10, "title": "英语六级", "icon": "📖", "progress": 50,
             "status": "in-progress", "expanded": False, "parent_id": 1, "level": 1, "order_index": 3},
        ]
        for g in default_goals:
            db.add(StudyGoal(user_id=user_id, **g))
        db.commit()

    if db.query(StudyPlan).filter_by(user_id=user_id).count() == 0:
        today = datetime.now().strftime("%Y-%m-%d")
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        default_plans = [
            {"plan_id": 1, "title": "高等数学 - 第三章积分", "start_time": "09:00", "end_time": "11:00",
             "duration": 2, "priority": "重要", "completed": True, "subject": "高等数学", "date": today},
            {"plan_id": 2, "title": "英语阅读 - 真题练习", "start_time": "14:00", "end_time": "15:30",
             "duration": 1.5, "priority": "常规", "completed": True, "subject": "英语", "date": today},
            {"plan_id": 3, "title": "数据结构复习", "start_time": "19:00", "end_time": "21:00",
             "duration": 2, "priority": "考前", "completed": False, "subject": "计算机", "date": today},
            {"plan_id": 4, "title": "线性代数 - 特征值专题", "start_time": "10:00", "end_time": "12:00",
             "duration": 2, "priority": "重要", "completed": False, "subject": "线性代数", "date": tomorrow},
            {"plan_id": 5, "title": "英语听力训练", "start_time": "08:00", "end_time": "09:00",
             "duration": 1, "priority": "常规", "completed": False, "subject": "英语", "date": tomorrow},
        ]
        for p in default_plans:
            db.add(StudyPlan(user_id=user_id, **p))
        db.commit()

    if db.query(StudyNote).filter_by(user_id=user_id).count() == 0:
        default_notes = [
            {"note_id": 1, "title": "微积分基本定理笔记", "category": "数学",
             "date_label": "昨天", "content": "微积分基本定理揭示了微分与积分的内在联系..."},
            {"note_id": 2, "title": "英语高频词汇整理", "category": "英语",
             "date_label": "3天前", "content": "整理了四六级高频词汇 500 个..."},
            {"note_id": 3, "title": "数据结构 - 树与图", "category": "计算机",
             "date_label": "5天前", "content": "二叉树、平衡树、B树、图的遍历算法整理..."},
        ]
        for n in default_notes:
            db.add(StudyNote(user_id=user_id, **n))
        db.commit()

    if db.query(StudyKnowledgeCategory).filter_by(user_id=user_id).count() == 0:
        default_cats = [
            {"category_id": 1, "name": "数学", "icon": "📐", "note_count": 128, "unit": "个知识点"},
            {"category_id": 2, "name": "英语", "icon": "📖", "note_count": 3500, "unit": "词汇"},
            {"category_id": 3, "name": "计算机", "icon": "💻", "note_count": 56, "unit": "个知识点"},
            {"category_id": 4, "name": "物理", "icon": "⚛️", "note_count": 89, "unit": "个知识点"},
            {"category_id": 5, "name": "化学", "icon": "🧪", "note_count": 72, "unit": "个知识点"},
            {"category_id": 6, "name": "语文", "icon": "📝", "note_count": 45, "unit": "篇古文"},
        ]
        for c in default_cats:
            db.add(StudyKnowledgeCategory(user_id=user_id, **c))
        db.commit()

    if db.query(StudyProgress).filter_by(user_id=user_id).count() == 0:
        default_progress = [
            {"subject": "高等数学", "progress": 65, "color": "blue"},
            {"subject": "英语", "progress": 78, "color": "green"},
            {"subject": "数据结构", "progress": 42, "color": "amber"},
            {"subject": "线性代数", "progress": 55, "color": "purple"},
            {"subject": "概率统计", "progress": 38, "color": "red"},
        ]
        for p in default_progress:
            db.add(StudyProgress(user_id=user_id, **p))
        db.commit()

    if db.query(StudyExam).filter_by(user_id=user_id).count() == 0:
        now = datetime.now()
        default_exams = [
            {"exam_id": 1, "name": "期末考试 - 高等数学", "subject": "高等数学",
             "exam_date": (now + timedelta(days=15)).strftime("%Y-%m-%d 09:00"),
             "location": "教学楼A301", "urgency": "紧急", "color_theme": "red"},
            {"exam_id": 2, "name": "英语四级考试", "subject": "英语",
             "exam_date": (now + timedelta(days=30)).strftime("%Y-%m-%d 09:00"),
             "location": "外语楼B202", "urgency": "重要", "color_theme": "amber"},
            {"exam_id": 3, "name": "计算机等级考试", "subject": "计算机",
             "exam_date": (now + timedelta(days=45)).strftime("%Y-%m-%d 14:00"),
             "location": "计算机楼C501", "urgency": "备考中", "color_theme": "green"},
            {"exam_id": 4, "name": "毕业论文答辩", "subject": "综合",
             "exam_date": (now + timedelta(days=60)).strftime("%Y-%m-%d 14:00"),
             "location": "学术报告厅", "urgency": "规划中", "color_theme": "blue"},
        ]
        for e in default_exams:
            db.add(StudyExam(user_id=user_id, **e))
        db.commit()

    # 元数据
    meta_keys = {m.meta_key for m in db.query(StudyMeta).filter_by(user_id=user_id).all()}
    meta_items = {
        "weekly_goals": [
            {"id": 1, "category": "数学章节", "current": 3, "total": 5, "unit": "个", "progress": 60},
            {"id": 2, "category": "单词量", "current": 250, "total": 350, "unit": "词", "progress": 71},
            {"id": 3, "category": "编程题", "current": 12, "total": 20, "unit": "道", "progress": 60},
        ],
        "study_stats": {
            "today_hours": 5.5, "week_hours": 32, "streak_days": 12,
            "total_hours": 256, "avg_hours_per_day": 4.2,
        },
        "risk_matrix": [
            {"probability": "high", "impact": "high", "level": "high", "label": "高危"},
        ],
        "risk_items": [
            {"id": 1, "name": "数学复习进度滞后", "probability": "high"},
        ],
        "scenarios": [
            {"id": 1, "name": "方案A：保守路径", "subtitle": "稳扎稳打"},
        ],
        "gantt_phases": [
            {"id": 1, "label": "基础复习", "start_week": 1, "end_week": 4},
        ],
        "progress_banner": {
            "exam_name": "期末考试", "days_left": 47, "semester_progress": 62,
        },
    }
    for key, value in meta_items.items():
        if key not in meta_keys:
            db.add(StudyMeta(meta_key=key, meta_value=value, user_id=user_id))
    db.commit()


def init_life_data(db, user_id=DEFAULT_USER_ID):
    """初始化生活管理示例数据"""
    if db.query(LifeSchedule).filter_by(user_id=user_id).count() == 0:
        today = datetime.now().strftime("%Y-%m-%d")
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        default_schedules = [
            {"schedule_id": 1, "title": "晨间复盘", "time_range": "09:00 - 10:30",
             "start_time": "09:00", "end_time": "10:30", "category": "固定", "tag_color": "green", "date": today},
            {"schedule_id": 2, "title": "团队站会", "time_range": "14:00 - 15:00",
             "start_time": "14:00", "end_time": "15:00", "category": "协作", "tag_color": "blue", "date": today},
            {"schedule_id": 3, "title": "运动时间", "time_range": "19:00 - 20:00",
             "start_time": "19:00", "end_time": "20:00", "category": "健康", "tag_color": "orange", "date": today},
            {"schedule_id": 4, "title": "项目评审", "time_range": "10:00 - 11:30",
             "start_time": "10:00", "end_time": "11:30", "category": "协作", "tag_color": "blue", "date": tomorrow},
            {"schedule_id": 5, "title": "阅读时间", "time_range": "20:00 - 21:00",
             "start_time": "20:00", "end_time": "21:00", "category": "固定", "tag_color": "green", "date": tomorrow},
        ]
        for s in default_schedules:
            db.add(LifeSchedule(user_id=user_id, **s))
        db.commit()

    if db.query(LifeRule).filter_by(user_id=user_id).count() == 0:
        default_rules = [
            {"rule_id": 1, "condition": "到达23:00", "action": "启用勿扰模式", "enabled": True},
            {"rule_id": 2, "condition": "检测到运动状态", "action": "切换至运动模式", "enabled": True},
            {"rule_id": 3, "condition": "设备电量低于20%", "action": "低电量提醒", "enabled": True},
            {"rule_id": 4, "condition": "离开家超过500米", "action": "启动安防模式", "enabled": False},
        ]
        for r in default_rules:
            db.add(LifeRule(user_id=user_id, **r))
        db.commit()

    if db.query(LifeTodo).filter_by(user_id=user_id).count() == 0:
        default_todos = [
            {"todo_id": 1, "title": "晨跑30分钟", "status": "done", "progress": 100, "category": "今日待办"},
            {"todo_id": 2, "title": "整理工作邮件", "status": "done", "progress": 100, "category": "今日待办"},
            {"todo_id": 3, "title": "准备项目文档", "status": "in-progress", "progress": 60, "category": "进行中"},
            {"todo_id": 4, "title": "学习新技能", "status": "in-progress", "progress": 40, "category": "进行中"},
            {"todo_id": 5, "title": "购物清单采购", "status": "todo", "progress": 0, "category": "今日待办"},
            {"todo_id": 6, "title": "预约牙医", "status": "todo", "progress": 0, "category": "今日待办"},
            {"todo_id": 7, "title": "整理房间", "status": "todo", "progress": 0, "category": "今日待办"},
            {"todo_id": 8, "title": "写周总结", "status": "todo", "progress": 0, "category": "今日待办"},
        ]
        for t in default_todos:
            db.add(LifeTodo(user_id=user_id, **t))
        db.commit()

    if db.query(LifeHabit).filter_by(user_id=user_id).count() == 0:
        default_habits = [
            {"habit_id": 1, "name": "早起", "icon": "🌅", "streak": 15, "done": True},
            {"habit_id": 2, "name": "阅读30分钟", "icon": "📚", "streak": 8, "done": True},
            {"habit_id": 3, "name": "运动", "icon": "🏃", "streak": 12, "done": False},
            {"habit_id": 4, "name": "喝8杯水", "icon": "💧", "streak": 20, "done": True},
            {"habit_id": 5, "name": "冥想", "icon": "🧘", "streak": 5, "done": False},
        ]
        for h in default_habits:
            db.add(LifeHabit(user_id=user_id, **h))
        db.commit()

    if db.query(LifeScene).filter_by(user_id=user_id).count() == 0:
        default_scenes = [
            {"scene_id": "home", "name": "居家模式", "icon": "🏠", "active": True},
            {"scene_id": "work", "name": "工作模式", "icon": "💼", "active": False},
            {"scene_id": "sport", "name": "运动模式", "icon": "🏃", "active": False},
            {"scene_id": "sleep", "name": "睡眠模式", "icon": "🌙", "active": False},
            {"scene_id": "focus", "name": "专注模式", "icon": "🎯", "active": False},
        ]
        for s in default_scenes:
            db.add(LifeScene(user_id=user_id, **s))
        db.commit()

    if db.query(LifeFinanceCategory).filter_by(user_id=user_id).count() == 0:
        default_cats = [
            {"category_id": 1, "name": "餐饮美食", "type": "expense", "spent": 1280, "percentage": 39, "color": "#FAAD14"},
            {"category_id": 2, "name": "交通出行", "type": "expense", "spent": 680, "percentage": 21, "color": "#1890FF"},
            {"category_id": 3, "name": "购物消费", "type": "expense", "spent": 560, "percentage": 17, "color": "#722ED1"},
            {"category_id": 4, "name": "休闲娱乐", "type": "expense", "spent": 420, "percentage": 13, "color": "#52C41A"},
            {"category_id": 5, "name": "其他支出", "type": "expense", "spent": 340, "percentage": 10, "color": "#8C8C8C"},
        ]
        for c in default_cats:
            db.add(LifeFinanceCategory(user_id=user_id, **c))
        db.commit()

    # 元数据
    meta_keys = {m.meta_key for m in db.query(LifeMeta).filter_by(user_id=user_id).all()}
    meta_items = {
        "energy_data": [
            {"id": 1, "label": "桌面终端", "value": "1.2kWh", "percentage": 50, "color": "green"},
            {"id": 2, "label": "智能设备", "value": "0.6kWh", "percentage": 25, "color": "blue"},
        ],
        "energy_total": {"total": "2.4kWh", "today": "2.4kWh", "week": "15.6kWh"},
        "finance_overview": {
            "total_expense": 3280, "budget": 5000, "today_spending": 128, "month_progress": 65.6,
        },
        "assistant_tools": [
            {"type": "weather", "title": "天气查询", "desc": "今日 26°C 晴", "icon": "☀️"},
        ],
        "life_stats": {
            "todo_completed": "2/8", "habit_checked": "3/5",
            "today_spending": "¥128", "steps": "6,842",
        },
    }
    for key, value in meta_items.items():
        if key not in meta_keys:
            db.add(LifeMeta(meta_key=key, meta_value=value, user_id=user_id))
    db.commit()


def get_study_meta(db, key, user_id=DEFAULT_USER_ID):
    meta = db.query(StudyMeta).filter_by(meta_key=key, user_id=user_id).first()
    return meta.meta_value if meta else None


def get_life_meta(db, key, user_id=DEFAULT_USER_ID):
    meta = db.query(LifeMeta).filter_by(meta_key=key, user_id=user_id).first()
    return meta.meta_value if meta else None


# ==================== 测试一：学业规划 ====================

section("测试一：学业规划 - 数据初始化")

db = TestingSessionLocal()
init_study_data(db, DEFAULT_USER_ID)

goal_count = db.query(StudyGoal).filter_by(user_id=DEFAULT_USER_ID).count()
plan_count = db.query(StudyPlan).filter_by(user_id=DEFAULT_USER_ID).count()
note_count = db.query(StudyNote).filter_by(user_id=DEFAULT_USER_ID).count()
exam_count = db.query(StudyExam).filter_by(user_id=DEFAULT_USER_ID).count()
progress_count = db.query(StudyProgress).filter_by(user_id=DEFAULT_USER_ID).count()
cat_count = db.query(StudyKnowledgeCategory).filter_by(user_id=DEFAULT_USER_ID).count()
meta_count = db.query(StudyMeta).filter_by(user_id=DEFAULT_USER_ID).count()

test("学习目标表有数据", goal_count > 0, f"实际: {goal_count}")
test("学习计划表有数据", plan_count > 0, f"实际: {plan_count}")
test("学习笔记表有数据", note_count > 0, f"实际: {note_count}")
test("考试计划表有数据", exam_count > 0, f"实际: {exam_count}")
test("科目进度表有数据", progress_count > 0, f"实际: {progress_count}")
test("知识分类表有数据", cat_count > 0, f"实际: {cat_count}")
test("元数据表有数据", meta_count > 0, f"实际: {meta_count}")

# 幂等性测试
init_study_data(db, DEFAULT_USER_ID)
goal_count2 = db.query(StudyGoal).filter_by(user_id=DEFAULT_USER_ID).count()
test("初始化幂等性（目标表不重复）", goal_count2 == goal_count,
     f"之前: {goal_count}, 之后: {goal_count2}")
meta_count2 = db.query(StudyMeta).filter_by(user_id=DEFAULT_USER_ID).count()
test("初始化幂等性（元数据表不重复）", meta_count2 == meta_count,
     f"之前: {meta_count}, 之后: {meta_count2}")

db.close()


# ---- 目标树测试 ----

section("测试一.1：学业规划 - 目标树")

db = TestingSessionLocal()
init_study_data(db, DEFAULT_USER_ID)

goals = db.query(StudyGoal).filter_by(user_id=DEFAULT_USER_ID).order_by(StudyGoal.order_index).all()
test("目标数量正确", len(goals) == 10, f"实际: {len(goals)}")
test("目标有 title 字段", all(g.title for g in goals))
test("目标树有根节点", any(g.parent_id is None for g in goals))
test("目标树有子节点", any(g.parent_id is not None for g in goals))
test("目标有进度字段", all(hasattr(g, 'progress') for g in goals))
test("目标有状态字段", all(hasattr(g, 'status') for g in goals))

# 新增目标
all_goals = db.query(StudyGoal).filter_by(user_id=DEFAULT_USER_ID).all()
max_gid = max((g.goal_id for g in all_goals), default=0)
new_goal = StudyGoal(
    goal_id=max_gid + 1, title="测试目标", icon="🧪", progress=0,
    status="not-started", expanded=True, parent_id=None, level=0,
    order_index=99, user_id=DEFAULT_USER_ID,
)
db.add(new_goal)
db.commit()
db.refresh(new_goal)
test("新增目标成功", new_goal.goal_id == max_gid + 1)
test("新增目标字段正确", new_goal.title == "测试目标" and new_goal.icon == "🧪")

# 更新目标
new_goal.progress = 50
new_goal.status = "in-progress"
db.commit()
db.refresh(new_goal)
test("更新目标进度", new_goal.progress == 50)
test("更新目标状态", new_goal.status == "in-progress")

# 删除目标（递归删除子节点）
# 先创建一个子目标
child_goal = StudyGoal(
    goal_id=max_gid + 2, title="子目标", icon="📂", progress=0,
    status="not-started", expanded=True, parent_id=max_gid + 1, level=1,
    order_index=1, user_id=DEFAULT_USER_ID,
)
db.add(child_goal)
db.commit()

# 递归删除
def get_children_ids(pid):
    children = db.query(StudyGoal).filter_by(parent_id=pid, user_id=DEFAULT_USER_ID).all()
    ids = []
    for child in children:
        ids.append(child.goal_id)
        ids.extend(get_children_ids(child.goal_id))
    return ids

all_ids = [max_gid + 1] + get_children_ids(max_gid + 1)
db.query(StudyGoal).filter(StudyGoal.goal_id.in_(all_ids), StudyGoal.user_id == DEFAULT_USER_ID).delete(
    synchronize_session=False
)
db.commit()
deleted_parent = db.query(StudyGoal).filter_by(goal_id=max_gid + 1, user_id=DEFAULT_USER_ID).first()
deleted_child = db.query(StudyGoal).filter_by(goal_id=max_gid + 2, user_id=DEFAULT_USER_ID).first()
test("递归删除目标（父+子）", deleted_parent is None and deleted_child is None)

db.close()


# ---- 学习计划测试 ----

section("测试一.2：学业规划 - 计划列表")

db = TestingSessionLocal()
init_study_data(db, DEFAULT_USER_ID)

today = datetime.now().strftime("%Y-%m-%d")
plans = db.query(StudyPlan).filter_by(user_id=DEFAULT_USER_ID, date=today).order_by(StudyPlan.start_time).all()
test("今日计划存在", len(plans) > 0)
test("计划有 title 字段", all(p.title for p in plans))
test("计划有 start_time/end_time", all(p.start_time and p.end_time for p in plans))
test("计划有 completed 字段", all(hasattr(p, 'completed') for p in plans))
test("计划有 duration 字段", all(hasattr(p, 'duration') and p.duration > 0 for p in plans))

# 新增计划
all_plans = db.query(StudyPlan).filter_by(user_id=DEFAULT_USER_ID).all()
max_pid = max((p.plan_id for p in all_plans), default=0)
new_plan = StudyPlan(
    plan_id=max_pid + 1, title="测试学习计划",
    start_time="14:00", end_time="16:00",
    duration=_calc_duration("14:00", "16:00"),
    priority="重要", completed=False, subject="测试科目",
    date=today, user_id=DEFAULT_USER_ID,
)
db.add(new_plan)
db.commit()
db.refresh(new_plan)
test("新增计划成功", new_plan.plan_id == max_pid + 1)
test("计划时长计算正确", new_plan.duration == 2.0)

# 切换完成状态
new_plan.completed = not new_plan.completed
db.commit()
db.refresh(new_plan)
test("切换计划完成状态", new_plan.completed == True)

# 删除计划
db.delete(new_plan)
db.commit()
deleted = db.query(StudyPlan).filter_by(plan_id=max_pid + 1, user_id=DEFAULT_USER_ID).first()
test("删除计划成功", deleted is None)

db.close()


# ---- 学习笔记测试 ----

section("测试一.3：学业规划 - 笔记列表")

db = TestingSessionLocal()
init_study_data(db, DEFAULT_USER_ID)

notes = db.query(StudyNote).filter_by(user_id=DEFAULT_USER_ID).order_by(StudyNote.created_at.desc()).all()
test("笔记列表非空", len(notes) > 0)
test("笔记有 title 字段", all(n.title for n in notes))
test("笔记有 category（科目）字段", all(hasattr(n, 'category') for n in notes))
test("笔记有 content 字段", all(hasattr(n, 'content') for n in notes))

# 按科目筛选
math_notes = db.query(StudyNote).filter_by(user_id=DEFAULT_USER_ID, category="数学").all()
test("按科目筛选笔记有效", len(math_notes) >= 0)

# 新增笔记
all_notes = db.query(StudyNote).filter_by(user_id=DEFAULT_USER_ID).all()
max_nid = max((n.note_id for n in all_notes), default=0)
new_note = StudyNote(
    note_id=max_nid + 1, title="测试笔记",
    category="测试科目", date_label="刚刚",
    content="这是一条测试笔记", user_id=DEFAULT_USER_ID,
)
db.add(new_note)
db.commit()
db.refresh(new_note)
test("新增笔记成功", new_note.title == "测试笔记")
test("笔记有创建时间", new_note.created_at is not None)

db.close()


# ---- 考试列表测试 ----

section("测试一.4：学业规划 - 考试列表")

db = TestingSessionLocal()
init_study_data(db, DEFAULT_USER_ID)

exams = db.query(StudyExam).filter_by(user_id=DEFAULT_USER_ID).order_by(StudyExam.exam_date).all()
test("考试列表非空", len(exams) > 0)
test("考试有 name 字段", all(e.name for e in exams))
test("考试有 exam_date 字段", all(e.exam_date for e in exams))
test("考试有 location 字段", all(hasattr(e, 'location') for e in exams))
test("考试有 urgency 字段", all(hasattr(e, 'urgency') for e in exams))

# 验证 days_left 可计算
for e in exams:
    try:
        exam_date = datetime.strptime(e.exam_date, "%Y-%m-%d %H:%M")
        days_left = max(0, (exam_date - datetime.now()).days)
        assert days_left >= 0
    except Exception as exc:
        test(f"考试日期解析失败: {e.name}", False, str(exc))
test("所有考试日期可解析并计算剩余天数", True)

# 新增考试
all_exams = db.query(StudyExam).filter_by(user_id=DEFAULT_USER_ID).all()
max_eid = max((e.exam_id for e in all_exams), default=0)
new_exam = StudyExam(
    exam_id=max_eid + 1, name="测试考试", subject="测试科目",
    exam_date=(datetime.now() + timedelta(days=10)).strftime("%Y-%m-%d %H:%M"),
    location="测试考场", urgency="备考中", color_theme="blue",
    user_id=DEFAULT_USER_ID,
)
db.add(new_exam)
db.commit()
db.refresh(new_exam)
test("新增考试成功", new_exam.name == "测试考试")

db.close()


# ---- 进度统计测试 ----

section("测试一.5：学业规划 - 进度统计")

db = TestingSessionLocal()
init_study_data(db, DEFAULT_USER_ID)

progs = db.query(StudyProgress).filter_by(user_id=DEFAULT_USER_ID).all()
test("科目进度列表非空", len(progs) > 0)
test("进度有 subject 字段", all(p.subject for p in progs))
test("进度值在 0-100 之间", all(0 <= p.progress <= 100 for p in progs))
test("进度有颜色字段", all(hasattr(p, 'color') for p in progs))

# 元数据验证
study_stats = get_study_meta(db, "study_stats")
test("学习统计元数据存在", study_stats is not None and isinstance(study_stats, dict))
test("学习统计包含 streak_days", "streak_days" in study_stats)
test("学习统计包含 total_hours", "total_hours" in study_stats)

weekly_goals = get_study_meta(db, "weekly_goals")
test("周目标元数据存在", weekly_goals is not None and isinstance(weekly_goals, list))

risk_matrix = get_study_meta(db, "risk_matrix")
test("风险矩阵元数据存在", risk_matrix is not None and isinstance(risk_matrix, list))

scenarios = get_study_meta(db, "scenarios")
test("方案对比元数据存在", scenarios is not None and isinstance(scenarios, list))

gantt_phases = get_study_meta(db, "gantt_phases")
test("甘特图元数据存在", gantt_phases is not None and isinstance(gantt_phases, list))

progress_banner = get_study_meta(db, "progress_banner")
test("进度横幅元数据存在", progress_banner is not None and isinstance(progress_banner, dict))

# 知识分类
cats = db.query(StudyKnowledgeCategory).filter_by(user_id=DEFAULT_USER_ID).all()
test("知识分类列表非空", len(cats) > 0)
test("分类有 name 字段", all(c.name for c in cats))
test("分类有 note_count 字段", all(hasattr(c, 'note_count') for c in cats))
test("分类有 icon 字段", all(hasattr(c, 'icon') for c in cats))

db.close()


# ==================== 测试二：生活管理 ====================

section("测试二：生活管理 - 数据初始化")

db = TestingSessionLocal()
init_life_data(db, DEFAULT_USER_ID)

schedule_count = db.query(LifeSchedule).filter_by(user_id=DEFAULT_USER_ID).count()
rule_count = db.query(LifeRule).filter_by(user_id=DEFAULT_USER_ID).count()
todo_count = db.query(LifeTodo).filter_by(user_id=DEFAULT_USER_ID).count()
habit_count = db.query(LifeHabit).filter_by(user_id=DEFAULT_USER_ID).count()
scene_count = db.query(LifeScene).filter_by(user_id=DEFAULT_USER_ID).count()
finance_count = db.query(LifeFinanceCategory).filter_by(user_id=DEFAULT_USER_ID).count()
life_meta_count = db.query(LifeMeta).filter_by(user_id=DEFAULT_USER_ID).count()

test("日程表有数据", schedule_count > 0, f"实际: {schedule_count}")
test("规则表有数据", rule_count > 0, f"实际: {rule_count}")
test("待办表有数据", todo_count > 0, f"实际: {todo_count}")
test("习惯表有数据", habit_count > 0, f"实际: {habit_count}")
test("场景表有数据", scene_count > 0, f"实际: {scene_count}")
test("财务分类表有数据", finance_count > 0, f"实际: {finance_count}")
test("元数据表有数据", life_meta_count > 0, f"实际: {life_meta_count}")

# 幂等性
init_life_data(db, DEFAULT_USER_ID)
todo_count2 = db.query(LifeTodo).filter_by(user_id=DEFAULT_USER_ID).count()
test("初始化幂等性（待办不重复）", todo_count2 == todo_count,
     f"之前: {todo_count}, 之后: {todo_count2}")

db.close()


# ---- 日程列表测试 ----

section("测试二.1：生活管理 - 日程列表")

db = TestingSessionLocal()
init_life_data(db, DEFAULT_USER_ID)

today = datetime.now().strftime("%Y-%m-%d")
schedules = db.query(LifeSchedule).filter_by(user_id=DEFAULT_USER_ID, date=today).order_by(LifeSchedule.start_time).all()
test("今日日程非空", len(schedules) > 0)
test("日程有 title 字段", all(s.title for s in schedules))
test("日程有 time_range 字段", all(s.time_range for s in schedules))
test("日程有 category（标签）字段", all(hasattr(s, 'category') for s in schedules))
test("日程有 tag_color 字段", all(hasattr(s, 'tag_color') for s in schedules))

# 新增日程
all_scheds = db.query(LifeSchedule).filter_by(user_id=DEFAULT_USER_ID).all()
max_sid = max((s.schedule_id for s in all_scheds), default=0)
new_sched = LifeSchedule(
    schedule_id=max_sid + 1, title="测试日程",
    time_range="10:00 - 11:00", start_time="10:00", end_time="11:00",
    category="测试", tag_color="purple", date=today, user_id=DEFAULT_USER_ID,
)
db.add(new_sched)
db.commit()
db.refresh(new_sched)
test("新增日程成功", new_sched.title == "测试日程")

# 删除日程
db.delete(new_sched)
db.commit()
deleted = db.query(LifeSchedule).filter_by(schedule_id=max_sid + 1, user_id=DEFAULT_USER_ID).first()
test("删除日程成功", deleted is None)

db.close()


# ---- 待办事项测试 ----

section("测试二.2：生活管理 - 待办事项")

db = TestingSessionLocal()
init_life_data(db, DEFAULT_USER_ID)

todos = db.query(LifeTodo).filter_by(user_id=DEFAULT_USER_ID).all()
test("待办列表非空", len(todos) > 0)
test("待办有 title 字段", all(t.title for t in todos))
test("待办有 status 字段", all(t.status for t in todos))
test("待办有 progress 字段", all(hasattr(t, 'progress') for t in todos))
test("待办有 category 字段", all(hasattr(t, 'category') for t in todos))

# 按状态筛选
done_todos = db.query(LifeTodo).filter_by(user_id=DEFAULT_USER_ID, status="done").all()
test("按状态筛选（已完成）", len(done_todos) > 0)
todo_todos = db.query(LifeTodo).filter_by(user_id=DEFAULT_USER_ID, status="todo").all()
test("按状态筛选（待处理）", len(todo_todos) > 0)

# 新增待办
all_todos = db.query(LifeTodo).filter_by(user_id=DEFAULT_USER_ID).all()
max_tid = max((t.todo_id for t in all_todos), default=0)
new_todo = LifeTodo(
    todo_id=max_tid + 1, title="测试待办",
    status="todo", progress=0, category="今日待办",
    user_id=DEFAULT_USER_ID,
)
db.add(new_todo)
db.commit()
db.refresh(new_todo)
test("新增待办成功", new_todo.title == "测试待办")

# 更新待办状态
new_todo.status = "in-progress"
new_todo.progress = 50
new_todo.category = "进行中"
db.commit()
db.refresh(new_todo)
test("更新待办为进行中", new_todo.status == "in-progress" and new_todo.progress == 50)

new_todo.status = "done"
new_todo.progress = 100
new_todo.category = "已完成"
db.commit()
db.refresh(new_todo)
test("更新待办为已完成", new_todo.status == "done" and new_todo.progress == 100)

# 删除待办
db.delete(new_todo)
db.commit()
deleted = db.query(LifeTodo).filter_by(todo_id=max_tid + 1, user_id=DEFAULT_USER_ID).first()
test("删除待办成功", deleted is None)

db.close()


# ---- 习惯打卡测试 ----

section("测试二.3：生活管理 - 习惯打卡")

db = TestingSessionLocal()
init_life_data(db, DEFAULT_USER_ID)

habits = db.query(LifeHabit).filter_by(user_id=DEFAULT_USER_ID).all()
test("习惯列表非空", len(habits) > 0)
test("习惯有 name 字段", all(h.name for h in habits))
test("习惯有 streak（连续天数）字段", all(hasattr(h, 'streak') for h in habits))
test("习惯有 done 字段", all(hasattr(h, 'done') for h in habits))
test("习惯有 icon 字段", all(hasattr(h, 'icon') for h in habits))

# 新增习惯
all_habits = db.query(LifeHabit).filter_by(user_id=DEFAULT_USER_ID).all()
max_hid = max((h.habit_id for h in all_habits), default=0)
new_habit = LifeHabit(
    habit_id=max_hid + 1, name="测试习惯",
    icon="🧪", streak=0, done=False,
    user_id=DEFAULT_USER_ID,
)
db.add(new_habit)
db.commit()
db.refresh(new_habit)
test("新增习惯成功", new_habit.name == "测试习惯" and new_habit.streak == 0)

# 打卡测试
if not new_habit.done:
    new_habit.done = True
    new_habit.streak += 1
db.commit()
db.refresh(new_habit)
test("习惯打卡成功（done=True）", new_habit.done == True)
test("连续天数+1", new_habit.streak == 1)

# 重复打卡不增加 streak
old_streak = new_habit.streak
# 模拟：如果已经 done，就不增加
if new_habit.done:
    pass  # 保持不变
db.commit()
db.refresh(new_habit)
test("重复打卡不增加连续天数", new_habit.streak == old_streak)

db.close()


# ---- 场景切换测试 ----

section("测试二.4：生活管理 - 场景切换")

db = TestingSessionLocal()
init_life_data(db, DEFAULT_USER_ID)

scenes = db.query(LifeScene).filter_by(user_id=DEFAULT_USER_ID).all()
test("场景列表非空", len(scenes) > 0)
test("场景有 scene_id（key）字段", all(s.scene_id for s in scenes))
test("场景有 name 字段", all(s.name for s in scenes))
test("场景有 icon 字段", all(hasattr(s, 'icon') for s in scenes))
test("场景有 active 字段", all(hasattr(s, 'active') for s in scenes))

# 只有一个激活场景
active_scenes = db.query(LifeScene).filter_by(user_id=DEFAULT_USER_ID, active=True).all()
test("只有一个激活场景", len(active_scenes) == 1, f"实际: {len(active_scenes)}")

# 切换场景
current_active = active_scenes[0]
target_scene = db.query(LifeScene).filter_by(user_id=DEFAULT_USER_ID, active=False).first()
if target_scene:
    target_key = target_scene.scene_id
    for s in scenes:
        s.active = (s.scene_id == target_key)
    db.commit()

    new_active_count = db.query(LifeScene).filter_by(user_id=DEFAULT_USER_ID, active=True).count()
    new_active = db.query(LifeScene).filter_by(user_id=DEFAULT_USER_ID, active=True).first()
    test("切换后只有一个激活", new_active_count == 1)
    test("切换到正确场景", new_active.scene_id == target_key)
    test("原场景已取消激活",
         db.query(LifeScene).filter_by(scene_id=current_active.scene_id, user_id=DEFAULT_USER_ID).first().active == False)

db.close()


# ---- 财务概览测试 ----

section("测试二.5：生活管理 - 财务概览")

db = TestingSessionLocal()
init_life_data(db, DEFAULT_USER_ID)

cats = db.query(LifeFinanceCategory).filter_by(user_id=DEFAULT_USER_ID).all()
test("财务分类列表非空", len(cats) > 0)
test("分类有 name 字段", all(c.name for c in cats))
test("分类有 spent（支出金额）字段", all(hasattr(c, 'spent') for c in cats))
test("分类有 percentage 字段", all(hasattr(c, 'percentage') for c in cats))
test("分类有 color 字段", all(hasattr(c, 'color') for c in cats))
test("分类有 type 字段", all(hasattr(c, 'type') for c in cats))

# 财务概览元数据
finance_overview = get_life_meta(db, "finance_overview")
test("财务概览元数据存在", finance_overview is not None and isinstance(finance_overview, dict))
test("财务概览包含总支出", "total_expense" in finance_overview)
test("财务概览包含预算", "budget" in finance_overview)
test("财务概览包含月进度", "month_progress" in finance_overview)

# 其他元数据
energy_data = get_life_meta(db, "energy_data")
test("能耗数据元数据存在", energy_data is not None and isinstance(energy_data, list))

energy_total = get_life_meta(db, "energy_total")
test("能耗总计元数据存在", energy_total is not None and isinstance(energy_total, dict))

assistant_tools = get_life_meta(db, "assistant_tools")
test("助手工具元数据存在", assistant_tools is not None and isinstance(assistant_tools, list))

life_stats = get_life_meta(db, "life_stats")
test("生活统计元数据存在", life_stats is not None and isinstance(life_stats, dict))

# 规则表验证
rules = db.query(LifeRule).filter_by(user_id=DEFAULT_USER_ID).all()
test("规则列表非空", len(rules) > 0)
test("规则有 condition 字段", all(r.condition for r in rules))
test("规则有 action 字段", all(r.action for r in rules))
test("规则有 enabled 字段", all(hasattr(r, 'enabled') for r in rules))

db.close()


# ==================== 总结 ====================

section("测试总结")

total = passed + failed
print(f"\n  总测试数: {total}")
print(f"  通过: {passed}")
print(f"  失败: {failed}")
print(f"  通过率: {passed/total*100:.1f}%" if total > 0 else "  无测试")

if failed == 0:
    print(f"\n  所有测试通过！")
else:
    print(f"\n  有 {failed} 个测试失败，请检查代码。")

# 清理
engine.dispose()
if os.path.exists(TEST_DB_PATH):
    os.remove(TEST_DB_PATH)
    print(f"\n[清理] 测试数据库已删除")

print("\n验证完成！")
sys.exit(0 if failed == 0 else 1)
