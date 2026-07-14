"""
学业规划模式 API
数据存储：SQLite 数据库（从内存迁移而来）
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from ..models import (
    get_db,
    StudyGoal,
    StudyPlan,
    StudyNote,
    StudyKnowledgeCategory,
    StudyExam,
    StudyProgress,
    StudyMeta,
)

router = APIRouter()

# 默认用户 ID（单用户模式）
DEFAULT_USER_ID = 1


# ==================== 工具函数 ====================

def _get_user_id() -> int:
    """获取用户ID（单用户模式默认 1）"""
    return DEFAULT_USER_ID


def _calc_duration(start: str, end: str) -> float:
    """计算时长（小时）"""
    sh, sm = map(int, start.split(":"))
    eh, em = map(int, end.split(":"))
    return round((eh * 60 + em - sh * 60 - sm) / 60, 1)


# ==================== 数据初始化 ====================

def _ensure_data_initialized(db: Session, user_id: int = DEFAULT_USER_ID):
    """确保学业规划数据已初始化（表为空时自动插入示例数据）"""

    # ---- 学习目标 ----
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

    # ---- 学习计划 ----
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

    # ---- 学习笔记 ----
    if db.query(StudyNote).filter_by(user_id=user_id).count() == 0:
        default_notes = [
            {"note_id": 1, "title": "微积分基本定理笔记", "category": "数学",
             "date_label": "昨天", "content": "微积分基本定理揭示了微分与积分的内在联系，是整个微积分学的核心..."},
            {"note_id": 2, "title": "英语高频词汇整理", "category": "英语",
             "date_label": "3天前", "content": "整理了四六级高频词汇 500 个，按词根词缀分类记忆..."},
            {"note_id": 3, "title": "数据结构 - 树与图", "category": "计算机",
             "date_label": "5天前", "content": "二叉树、平衡树、B树、图的遍历算法整理..."},
        ]
        for n in default_notes:
            db.add(StudyNote(user_id=user_id, **n))
        db.commit()

    # ---- 知识分类 ----
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

    # ---- 科目进度 ----
    if db.query(StudyProgress).filter_by(user_id=user_id).count() == 0:
        default_progress = [
            {"subject": "高等数学", "progress": 65, "color": "blue", "total_hours": 48, "mastered_topics": 85, "total_topics": 128},
            {"subject": "英语", "progress": 78, "color": "green", "total_hours": 62, "mastered_topics": 2800, "total_topics": 3500},
            {"subject": "数据结构", "progress": 42, "color": "amber", "total_hours": 28, "mastered_topics": 24, "total_topics": 56},
            {"subject": "线性代数", "progress": 55, "color": "purple", "total_hours": 35, "mastered_topics": 30, "total_topics": 52},
            {"subject": "概率统计", "progress": 38, "color": "red", "total_hours": 22, "mastered_topics": 28, "total_topics": 72},
        ]
        for p in default_progress:
            db.add(StudyProgress(user_id=user_id, **p))
        db.commit()

    # ---- 考试计划 ----
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

    # ---- 元数据（JSON存储的杂项） ----
    _init_study_meta(db, user_id)


def _init_study_meta(db: Session, user_id: int):
    """初始化学业规划元数据（周目标、风险矩阵、场景库、甘特图、统计等）"""

    meta_keys = {m.meta_key for m in db.query(StudyMeta).filter_by(user_id=user_id).all()}

    # 周目标
    if "weekly_goals" not in meta_keys:
        db.add(StudyMeta(
            meta_key="weekly_goals",
            user_id=user_id,
            meta_value=[
                {"id": 1, "category": "数学章节", "current": 3, "total": 5, "unit": "个", "progress": 60, "completed": False},
                {"id": 2, "category": "单词量", "current": 250, "total": 350, "unit": "词", "progress": 71, "completed": False},
                {"id": 3, "category": "编程题", "current": 12, "total": 20, "unit": "道", "progress": 60, "completed": False},
            ],
        ))

    # 风险矩阵
    if "risk_matrix" not in meta_keys:
        db.add(StudyMeta(
            meta_key="risk_matrix",
            user_id=user_id,
            meta_value=[
                {"probability": "high", "impact": "high", "level": "high", "label": "高危"},
                {"probability": "medium", "impact": "high", "level": "high", "label": "高危"},
                {"probability": "low", "impact": "high", "level": "medium", "label": "中等"},
                {"probability": "high", "impact": "medium", "level": "high", "label": "高危"},
                {"probability": "medium", "impact": "medium", "level": "medium", "label": "中等"},
                {"probability": "low", "impact": "medium", "level": "low", "label": "低"},
                {"probability": "high", "impact": "low", "level": "medium", "label": "中等"},
                {"probability": "medium", "impact": "low", "level": "low", "label": "低"},
                {"probability": "low", "impact": "low", "level": "low", "label": "低"},
            ],
        ))

    # 风险项
    if "risk_items" not in meta_keys:
        db.add(StudyMeta(
            meta_key="risk_items",
            user_id=user_id,
            meta_value=[
                {"id": 1, "name": "数学复习进度滞后", "probability": "high", "impact": "high", "level": "high", "description": "高数内容多，进度可能跟不上"},
                {"id": 2, "name": "论文数据不足", "probability": "medium", "impact": "high", "level": "high", "description": "实验数据收集困难可能影响论文质量"},
                {"id": 3, "name": "英语听力薄弱", "probability": "medium", "impact": "medium", "level": "medium", "description": "听力部分失分较多"},
                {"id": 4, "name": "时间冲突", "probability": "low", "impact": "medium", "level": "low", "description": "多门考试集中导致复习时间紧张"},
            ],
        ))

    # 方案对比（场景库）
    if "scenarios" not in meta_keys:
        db.add(StudyMeta(
            meta_key="scenarios",
            user_id=user_id,
            meta_value=[
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
            ],
        ))

    # 甘特图阶段
    if "gantt_phases" not in meta_keys:
        db.add(StudyMeta(
            meta_key="gantt_phases",
            user_id=user_id,
            meta_value=[
                {"id": 1, "label": "基础复习", "start_week": 1, "end_week": 4, "phase_type": 1},
                {"id": 2, "label": "强化训练", "start_week": 5, "end_week": 8, "phase_type": 2},
                {"id": 3, "label": "冲刺模拟", "start_week": 9, "end_week": 12, "phase_type": 3},
                {"id": 4, "label": "考试周", "start_week": 13, "end_week": 13, "phase_type": 4},
            ],
        ))

    # 学习统计
    if "study_stats" not in meta_keys:
        db.add(StudyMeta(
            meta_key="study_stats",
            user_id=user_id,
            meta_value={
                "today_hours": 5.5,
                "week_hours": 32,
                "streak_days": 12,
                "total_hours": 256,
                "avg_hours_per_day": 4.2,
            },
        ))

    # 进度横幅
    if "progress_banner" not in meta_keys:
        db.add(StudyMeta(
            meta_key="progress_banner",
            user_id=user_id,
            meta_value={
                "exam_name": "期末考试",
                "days_left": 47,
                "semester_progress": 62,
                "today_tasks_done": 2,
                "today_tasks_total": 3,
                "today_completion_rate": 67,
            },
        ))

    db.commit()


def _get_meta(db: Session, key: str, user_id: int = DEFAULT_USER_ID):
    """获取元数据值"""
    meta = db.query(StudyMeta).filter_by(meta_key=key, user_id=user_id).first()
    return meta.meta_value if meta else None


# ==================== 模型转换 ====================

def _goal_to_dict(goal: StudyGoal) -> dict:
    """将目标对象转为前端格式"""
    return {
        "id": goal.goal_id,
        "label": goal.title,
        "icon": goal.icon,
        "progress": goal.progress,
        "status": goal.status,
        "expanded": goal.expanded,
        "parent_id": goal.parent_id,
        "level": goal.level,
    }


def _plan_to_dict(plan: StudyPlan) -> dict:
    """将计划对象转为前端格式"""
    return {
        "id": plan.plan_id,
        "title": plan.title,
        "start_time": plan.start_time,
        "end_time": plan.end_time,
        "duration": plan.duration,
        "priority": plan.priority,
        "completed": plan.completed,
        "subject": plan.subject,
        "date": plan.date,
    }


def _note_to_dict(note: StudyNote) -> dict:
    """将笔记对象转为前端格式"""
    return {
        "id": note.note_id,
        "title": note.title,
        "subject": note.category,
        "date": note.date_label,
        "content": note.content,
        "created_at": note.created_at.strftime("%Y-%m-%d %H:%M") if note.created_at else "",
        "updated_at": note.updated_at.strftime("%Y-%m-%d %H:%M") if note.updated_at else "",
    }


def _knowledge_cat_to_dict(cat: StudyKnowledgeCategory) -> dict:
    """将知识分类对象转为前端格式"""
    return {
        "id": cat.category_id,
        "name": cat.name,
        "icon": cat.icon,
        "item_count": cat.note_count,
        "unit": cat.unit,
    }


def _exam_to_dict(exam: StudyExam) -> dict:
    """将考试对象转为前端格式（动态计算 days_left）"""
    try:
        exam_date = datetime.strptime(exam.exam_date, "%Y-%m-%d %H:%M")
        days_left = max(0, (exam_date - datetime.now()).days)
    except Exception:
        days_left = 0
    return {
        "id": exam.exam_id,
        "name": exam.name,
        "exam_date": exam.exam_date,
        "location": exam.location,
        "days_left": days_left,
        "urgency": exam.urgency,
        "color_theme": exam.color_theme,
    }


def _progress_to_dict(prog: StudyProgress) -> dict:
    """将科目进度对象转为前端格式"""
    return {
        "id": prog.id,
        "subject": prog.subject,
        "progress": prog.progress,
        "color": prog.color,
    }


# ==================== 请求模型 ====================

class GoalCreateRequest(BaseModel):
    label: str
    icon: str = "📚"
    parent_id: Optional[int] = None


class GoalUpdateRequest(BaseModel):
    label: Optional[str] = None
    progress: Optional[int] = None
    status: Optional[str] = None
    expanded: Optional[bool] = None


class PlanCreateRequest(BaseModel):
    title: str
    start_time: str
    end_time: str
    priority: str = "常规"
    subject: str = ""
    date: Optional[str] = None


class NoteCreateRequest(BaseModel):
    title: str
    subject: str
    content: str = ""


class NoteUpdateRequest(BaseModel):
    title: Optional[str] = None
    subject: Optional[str] = None
    content: Optional[str] = None


class ExamCreateRequest(BaseModel):
    name: str
    exam_date: str
    location: str = ""
    urgency: str = "备考中"


class WeeklyGoalItem(BaseModel):
    id: Optional[int] = None
    category: str
    current: int = 0
    total: int = 0
    unit: str = "个"
    progress: int = 0
    completed: bool = False


class WeeklyGoalsUpdateRequest(BaseModel):
    goals: List[WeeklyGoalItem]


# ==================== 概览 ====================

@router.get("/overview")
async def get_overview(db: Session = Depends(get_db)):
    """学业规划概览"""
    user_id = _get_user_id()
    _ensure_data_initialized(db, user_id)

    today = datetime.now().strftime("%Y-%m-%d")
    today_plans = db.query(StudyPlan).filter_by(user_id=user_id, date=today).all()
    done_count = sum(1 for p in today_plans if p.completed)

    total_goals = db.query(StudyGoal).filter_by(user_id=user_id).count()
    total_plans = db.query(StudyPlan).filter_by(user_id=user_id).count()
    total_notes = db.query(StudyNote).filter_by(user_id=user_id).count()
    total_exams = db.query(StudyExam).filter_by(user_id=user_id).count()

    study_stats = _get_meta(db, "study_stats", user_id) or {}
    progress_banner = _get_meta(db, "progress_banner", user_id) or {}

    return {
        "code": 0,
        "message": "ok",
        "data": {
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
        },
    }


# ==================== 目标树 ====================

@router.get("/goals/tree")
async def get_goal_tree(db: Session = Depends(get_db)):
    """获取目标树"""
    user_id = _get_user_id()
    _ensure_data_initialized(db, user_id)

    goals = db.query(StudyGoal).filter_by(user_id=user_id).order_by(StudyGoal.order_index).all()
    goal_map = {g.goal_id: _goal_to_dict(g) for g in goals}

    def build_tree(parent_id=None):
        nodes = [g for g in goal_map.values() if g["parent_id"] == parent_id]
        result = []
        for node in nodes:
            children = build_tree(node["id"])
            node_data = {
                **node,
                "has_children": len(children) > 0,
                "children": children,
            }
            result.append(node_data)
        return result

    tree = build_tree(None)
    return {"code": 0, "message": "ok", "data": tree}


@router.post("/goals")
async def create_goal(req: GoalCreateRequest, db: Session = Depends(get_db)):
    """新增目标"""
    user_id = _get_user_id()
    _ensure_data_initialized(db, user_id)

    # 计算下一个 goal_id
    max_id = db.query(StudyGoal).filter_by(user_id=user_id).count()
    # 用最大 goal_id + 1
    all_goals = db.query(StudyGoal).filter_by(user_id=user_id).all()
    nid = max((g.goal_id for g in all_goals), default=0) + 1

    # 查找父节点计算 level
    parent = None
    if req.parent_id:
        parent = db.query(StudyGoal).filter_by(goal_id=req.parent_id, user_id=user_id).first()
    level = parent.level + 1 if parent else 0

    # 同层级下的最大 order_index + 1
    siblings = db.query(StudyGoal).filter_by(user_id=user_id, parent_id=req.parent_id).all()
    order_index = max((s.order_index for s in siblings), default=0) + 1

    goal = StudyGoal(
        goal_id=nid,
        title=req.label,
        icon=req.icon,
        progress=0,
        status="not-started",
        expanded=True,
        parent_id=req.parent_id,
        level=level,
        order_index=order_index,
        user_id=user_id,
    )
    db.add(goal)
    db.commit()
    db.refresh(goal)

    return {"code": 0, "message": "目标创建成功", "data": _goal_to_dict(goal)}


@router.put("/goals/{goal_id}")
async def update_goal(goal_id: int, req: GoalUpdateRequest, db: Session = Depends(get_db)):
    """更新目标"""
    user_id = _get_user_id()
    _ensure_data_initialized(db, user_id)

    goal = db.query(StudyGoal).filter_by(goal_id=goal_id, user_id=user_id).first()
    if not goal:
        return {"code": 404, "message": "目标不存在", "data": None}

    if req.label is not None:
        goal.title = req.label
    if req.progress is not None:
        goal.progress = max(0, min(100, req.progress))
        if goal.progress >= 100:
            goal.status = "complete"
        elif goal.progress > 0:
            goal.status = "in-progress"
    if req.status is not None:
        goal.status = req.status
    if req.expanded is not None:
        goal.expanded = req.expanded

    db.commit()
    db.refresh(goal)
    return {"code": 0, "message": "更新成功", "data": _goal_to_dict(goal)}


@router.delete("/goals/{goal_id}")
async def delete_goal(goal_id: int, db: Session = Depends(get_db)):
    """删除目标（递归删除子节点）"""
    user_id = _get_user_id()
    _ensure_data_initialized(db, user_id)

    goal = db.query(StudyGoal).filter_by(goal_id=goal_id, user_id=user_id).first()
    if not goal:
        return {"code": 404, "message": "目标不存在", "data": None}

    # 递归收集所有子节点 ID
    def get_children_ids(pid):
        children = db.query(StudyGoal).filter_by(parent_id=pid, user_id=user_id).all()
        ids = []
        for child in children:
            ids.append(child.goal_id)
            ids.extend(get_children_ids(child.goal_id))
        return ids

    all_ids = [goal_id] + get_children_ids(goal_id)

    # 批量删除
    db.query(StudyGoal).filter(StudyGoal.goal_id.in_(all_ids), StudyGoal.user_id == user_id).delete(
        synchronize_session=False
    )
    db.commit()

    return {"code": 0, "message": "删除成功", "data": None}


# ==================== 学习计划 ====================

@router.get("/plans")
async def get_plans(date: Optional[str] = None, db: Session = Depends(get_db)):
    """获取学习计划"""
    user_id = _get_user_id()
    _ensure_data_initialized(db, user_id)

    target_date = date or datetime.now().strftime("%Y-%m-%d")
    plans = db.query(StudyPlan).filter_by(user_id=user_id, date=target_date).order_by(StudyPlan.start_time).all()
    result = [_plan_to_dict(p) for p in plans]
    return {"code": 0, "message": "ok", "data": result}


@router.post("/plans")
async def create_plan(req: PlanCreateRequest, db: Session = Depends(get_db)):
    """创建学习计划"""
    user_id = _get_user_id()
    _ensure_data_initialized(db, user_id)

    all_plans = db.query(StudyPlan).filter_by(user_id=user_id).all()
    pid = max((p.plan_id for p in all_plans), default=0) + 1

    plan = StudyPlan(
        plan_id=pid,
        title=req.title,
        start_time=req.start_time,
        end_time=req.end_time,
        duration=_calc_duration(req.start_time, req.end_time),
        priority=req.priority,
        completed=False,
        subject=req.subject,
        date=req.date or datetime.now().strftime("%Y-%m-%d"),
        user_id=user_id,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)

    return {"code": 0, "message": "计划创建成功", "data": _plan_to_dict(plan)}


@router.put("/plans/{plan_id}/toggle")
async def toggle_plan(plan_id: int, db: Session = Depends(get_db)):
    """切换计划完成状态"""
    user_id = _get_user_id()
    _ensure_data_initialized(db, user_id)

    plan = db.query(StudyPlan).filter_by(plan_id=plan_id, user_id=user_id).first()
    if not plan:
        return {"code": 404, "message": "计划不存在", "data": None}

    plan.completed = not plan.completed
    db.commit()
    db.refresh(plan)
    return {"code": 0, "message": "状态已更新", "data": _plan_to_dict(plan)}


@router.delete("/plans/{plan_id}")
async def delete_plan(plan_id: int, db: Session = Depends(get_db)):
    """删除学习计划"""
    user_id = _get_user_id()
    _ensure_data_initialized(db, user_id)

    plan = db.query(StudyPlan).filter_by(plan_id=plan_id, user_id=user_id).first()
    if not plan:
        return {"code": 404, "message": "计划不存在", "data": None}

    db.delete(plan)
    db.commit()
    return {"code": 0, "message": "删除成功", "data": None}


@router.get("/weekly-goals")
async def get_weekly_goals(db: Session = Depends(get_db)):
    """获取本周目标"""
    user_id = _get_user_id()
    _ensure_data_initialized(db, user_id)

    data = _get_meta(db, "weekly_goals", user_id) or []
    return {"code": 0, "message": "ok", "data": data}


@router.put("/weekly-goals")
async def update_weekly_goals(req: WeeklyGoalsUpdateRequest, db: Session = Depends(get_db)):
    """更新本周目标列表（支持增删改）"""
    user_id = _get_user_id()
    _ensure_data_initialized(db, user_id)

    goals = []
    next_id = 1
    for g in req.goals:
        goal_dict = g.model_dump()
        # 如果没有 id 或 id 为 None，分配新 id
        if goal_dict.get("id") is None:
            goal_dict["id"] = max(
                (gg["id"] for gg in req.goals if gg.id is not None),
                default=0,
            ) + next_id
            next_id += 1
        # 重新计算 progress（防止不一致）
        if goal_dict.get("total", 0) > 0:
            goal_dict["progress"] = min(
                100, int(goal_dict["current"] / goal_dict["total"] * 100)
            )
        else:
            goal_dict["progress"] = 0
        # current >= total 时标记完成
        if goal_dict["current"] >= goal_dict["total"] and goal_dict["total"] > 0:
            goal_dict["completed"] = True
        goals.append(goal_dict)

    meta = db.query(StudyMeta).filter_by(meta_key="weekly_goals", user_id=user_id).first()
    if meta:
        meta.meta_value = goals
    else:
        db.add(StudyMeta(meta_key="weekly_goals", user_id=user_id, meta_value=goals))
    db.commit()

    return {"code": 0, "message": "周目标已更新", "data": goals}


@router.post("/weekly-goals/{goal_id}/toggle")
async def toggle_weekly_goal(goal_id: int, db: Session = Depends(get_db)):
    """切换某个周目标的完成状态"""
    user_id = _get_user_id()
    _ensure_data_initialized(db, user_id)

    goals = _get_meta(db, "weekly_goals", user_id) or []
    found = False
    for g in goals:
        if g.get("id") == goal_id:
            g["completed"] = not g.get("completed", False)
            # 如果勾选完成，自动把 current 设为 total；取消完成则回退
            if g["completed"] and g.get("total", 0) > 0:
                g["current"] = g["total"]
                g["progress"] = 100
            found = True
            break

    if not found:
        return {"code": 404, "message": "周目标不存在", "data": None}

    meta = db.query(StudyMeta).filter_by(meta_key="weekly_goals", user_id=user_id).first()
    if meta:
        meta.meta_value = goals
    db.commit()

    return {"code": 0, "message": "状态已更新", "data": goals}


# ==================== 知识库 ====================

@router.get("/knowledge/categories")
async def get_knowledge_categories(db: Session = Depends(get_db)):
    """获取知识分类"""
    user_id = _get_user_id()
    _ensure_data_initialized(db, user_id)

    cats = db.query(StudyKnowledgeCategory).filter_by(user_id=user_id).order_by(StudyKnowledgeCategory.category_id).all()
    result = [_knowledge_cat_to_dict(c) for c in cats]
    return {"code": 0, "message": "ok", "data": result}


@router.get("/knowledge/notes")
async def get_notes(subject: Optional[str] = None, db: Session = Depends(get_db)):
    """获取学习笔记"""
    user_id = _get_user_id()
    _ensure_data_initialized(db, user_id)

    query = db.query(StudyNote).filter_by(user_id=user_id)
    if subject:
        query = query.filter_by(category=subject)
    notes = query.order_by(StudyNote.created_at.desc()).all()
    result = [_note_to_dict(n) for n in notes]
    return {"code": 0, "message": "ok", "data": result}


@router.post("/knowledge/notes")
async def create_note(req: NoteCreateRequest, db: Session = Depends(get_db)):
    """创建学习笔记"""
    user_id = _get_user_id()
    _ensure_data_initialized(db, user_id)

    all_notes = db.query(StudyNote).filter_by(user_id=user_id).all()
    nid = max((n.note_id for n in all_notes), default=0) + 1

    note = StudyNote(
        note_id=nid,
        title=req.title,
        category=req.subject,
        date_label="刚刚",
        content=req.content,
        user_id=user_id,
    )
    db.add(note)
    db.commit()
    db.refresh(note)

    return {"code": 0, "message": "笔记创建成功", "data": _note_to_dict(note)}


@router.get("/knowledge/notes/{note_id}")
async def get_note_detail(note_id: int, db: Session = Depends(get_db)):
    """获取笔记详情"""
    user_id = _get_user_id()
    _ensure_data_initialized(db, user_id)

    note = db.query(StudyNote).filter_by(note_id=note_id, user_id=user_id).first()
    if not note:
        return {"code": 404, "message": "笔记不存在", "data": None}

    return {"code": 0, "message": "ok", "data": _note_to_dict(note)}


@router.put("/knowledge/notes/{note_id}")
async def update_note(note_id: int, req: NoteUpdateRequest, db: Session = Depends(get_db)):
    """更新笔记"""
    user_id = _get_user_id()
    _ensure_data_initialized(db, user_id)

    note = db.query(StudyNote).filter_by(note_id=note_id, user_id=user_id).first()
    if not note:
        return {"code": 404, "message": "笔记不存在", "data": None}

    if req.title is not None:
        note.title = req.title
    if req.subject is not None:
        note.category = req.subject
    if req.content is not None:
        note.content = req.content

    note.date_label = "刚刚"
    note.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(note)
    return {"code": 0, "message": "笔记更新成功", "data": _note_to_dict(note)}


@router.delete("/knowledge/notes/{note_id}")
async def delete_note(note_id: int, db: Session = Depends(get_db)):
    """删除笔记"""
    user_id = _get_user_id()
    _ensure_data_initialized(db, user_id)

    note = db.query(StudyNote).filter_by(note_id=note_id, user_id=user_id).first()
    if not note:
        return {"code": 404, "message": "笔记不存在", "data": None}

    db.delete(note)
    db.commit()
    return {"code": 0, "message": "删除成功", "data": None}


# ==================== 进度追踪 ====================

@router.get("/progress/subjects")
async def get_subject_progress(db: Session = Depends(get_db)):
    """获取科目进度"""
    user_id = _get_user_id()
    _ensure_data_initialized(db, user_id)

    progs = db.query(StudyProgress).filter_by(user_id=user_id).all()
    result = [_progress_to_dict(p) for p in progs]
    return {"code": 0, "message": "ok", "data": result}


@router.get("/progress/stats")
async def get_study_stats(db: Session = Depends(get_db)):
    """获取学习统计"""
    user_id = _get_user_id()
    _ensure_data_initialized(db, user_id)

    today = datetime.now().strftime("%Y-%m-%d")
    today_plans = db.query(StudyPlan).filter_by(user_id=user_id, date=today).all()
    done_count = sum(1 for p in today_plans if p.completed)
    total_count = len(today_plans)

    study_stats = _get_meta(db, "study_stats", user_id) or {}

    return {
        "code": 0,
        "message": "ok",
        "data": {
            **study_stats,
            "today_tasks_done": done_count,
            "today_tasks_total": total_count,
        },
    }


# ==================== 考试提醒 ====================

@router.get("/exams")
async def get_exams(db: Session = Depends(get_db)):
    """获取考试列表"""
    user_id = _get_user_id()
    _ensure_data_initialized(db, user_id)

    exams = db.query(StudyExam).filter_by(user_id=user_id).order_by(StudyExam.exam_date).all()
    result = [_exam_to_dict(e) for e in exams]
    return {"code": 0, "message": "ok", "data": result}


@router.post("/exams")
async def create_exam(req: ExamCreateRequest, db: Session = Depends(get_db)):
    """创建考试提醒"""
    user_id = _get_user_id()
    _ensure_data_initialized(db, user_id)

    all_exams = db.query(StudyExam).filter_by(user_id=user_id).all()
    eid = max((e.exam_id for e in all_exams), default=0) + 1

    exam = StudyExam(
        exam_id=eid,
        name=req.name,
        exam_date=req.exam_date,
        location=req.location,
        urgency=req.urgency,
        color_theme="blue",
        user_id=user_id,
    )
    db.add(exam)
    db.commit()
    db.refresh(exam)

    return {"code": 0, "message": "考试提醒创建成功", "data": _exam_to_dict(exam)}


@router.delete("/exams/{exam_id}")
async def delete_exam(exam_id: int, db: Session = Depends(get_db)):
    """删除考试提醒"""
    user_id = _get_user_id()
    _ensure_data_initialized(db, user_id)

    exam = db.query(StudyExam).filter_by(exam_id=exam_id, user_id=user_id).first()
    if not exam:
        return {"code": 404, "message": "考试不存在", "data": None}

    db.delete(exam)
    db.commit()
    return {"code": 0, "message": "删除成功", "data": None}


# ==================== 风险矩阵 ====================

@router.get("/risks/matrix")
async def get_risk_matrix(db: Session = Depends(get_db)):
    """获取风险矩阵"""
    user_id = _get_user_id()
    _ensure_data_initialized(db, user_id)

    matrix = _get_meta(db, "risk_matrix", user_id) or []
    items = _get_meta(db, "risk_items", user_id) or []
    return {"code": 0, "message": "ok", "data": {"matrix": matrix, "items": items}}


# ==================== 方案对比 ====================

@router.get("/scenarios")
async def get_scenarios(db: Session = Depends(get_db)):
    """获取方案对比"""
    user_id = _get_user_id()
    _ensure_data_initialized(db, user_id)

    data = _get_meta(db, "scenarios", user_id) or []
    return {"code": 0, "message": "ok", "data": data}


# ==================== 甘特图 ====================

@router.get("/gantt/phases")
async def get_gantt_phases(db: Session = Depends(get_db)):
    """获取甘特图阶段"""
    user_id = _get_user_id()
    _ensure_data_initialized(db, user_id)

    phases = _get_meta(db, "gantt_phases", user_id) or []
    return {"code": 0, "message": "ok", "data": {"phases": phases, "total_weeks": 13}}
