"""学业规划模式 - API 路由.

提供学业规划模式的 RESTful API 接口，包括概览、目标树、
学习计划、学习笔记、知识库、进度追踪、考试提醒、
风险矩阵、方案对比、甘特图等功能。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query

from src.database import get_session
from src.models import make_response
from src.modes.study_plan.models import (
    ExamCreateRequest,
    GoalCreateRequest,
    GoalUpdateRequest,
    NoteCreateRequest,
    NoteUpdateRequest,
    PlanCreateRequest,
    WeeklyGoalsUpdateRequest,
)
from src.modes.study_plan.service import StudyService

router = APIRouter(
    prefix="/api/v1/study-plan",
    tags=["学业规划模式"],
)


def _get_service(x_user_id: str = "default") -> StudyService:
    """获取 StudyService 实例.

    Args:
        x_user_id: 用户 ID（从请求头获取）

    Returns:
        StudyService 实例
    """
    db = get_session()
    return StudyService(db, user_id=x_user_id)


# ---------------------------------------------------------------------------
# 概览统计
# ---------------------------------------------------------------------------


@router.get("/overview")
async def get_overview(
    x_user_id: str = Header("default"),
) -> dict:
    """获取学业规划概览统计.

    返回目标总数、计划总数、笔记总数、考试总数、今日任务完成情况等。
    """
    service = _get_service(x_user_id)
    overview = service.get_overview()
    return make_response(data=overview, message="获取概览成功")


# ---------------------------------------------------------------------------
# 目标树
# ---------------------------------------------------------------------------


@router.get("/goals/tree")
async def get_goal_tree(
    x_user_id: str = Header("default"),
) -> dict:
    """获取学习目标树.

    返回层级嵌套的目标树结构，支持父子关系。
    """
    service = _get_service(x_user_id)
    tree = service.get_goal_tree()
    return make_response(data=tree, message="获取目标树成功")


@router.post("/goals")
async def create_goal(
    req: GoalCreateRequest,
    x_user_id: str = Header("default"),
) -> dict:
    """创建学习目标.

    支持在任意层级创建子目标。
    """
    service = _get_service(x_user_id)
    goal = service.create_goal(
        label=req.label,
        icon=req.icon,
        parent_id=req.parent_id,
    )
    return make_response(data=goal, message="创建目标成功")


@router.put("/goals/{goal_id}")
async def update_goal(
    goal_id: int,
    req: GoalUpdateRequest,
    x_user_id: str = Header("default"),
) -> dict:
    """更新学习目标.

    可更新标题、进度、状态、展开状态等字段。
    """
    service = _get_service(x_user_id)
    goal = service.update_goal(
        goal_id=goal_id,
        label=req.label,
        progress=req.progress,
        status=req.status,
        expanded=req.expanded,
    )
    if not goal:
        raise HTTPException(status_code=404, detail="目标不存在")
    return make_response(data=goal, message="更新目标成功")


@router.delete("/goals/{goal_id}")
async def delete_goal(
    goal_id: int,
    x_user_id: str = Header("default"),
) -> dict:
    """删除学习目标.

    会递归删除所有子目标。
    """
    service = _get_service(x_user_id)
    success = service.delete_goal(goal_id)
    if not success:
        raise HTTPException(status_code=404, detail="目标不存在")
    return make_response(data={"deleted": True}, message="删除目标成功")


# ---------------------------------------------------------------------------
# 学习计划
# ---------------------------------------------------------------------------


@router.get("/plans")
async def list_plans(
    date: Optional[str] = Query(None, description="按日期筛选 YYYY-MM-DD"),
    x_user_id: str = Header("default"),
) -> dict:
    """获取学习计划列表.

    支持按日期筛选，默认返回今日计划。
    """
    service = _get_service(x_user_id)
    plans = service.list_plans(date=date)
    return make_response(data=plans, message="获取计划列表成功")


@router.post("/plans")
async def create_plan(
    req: PlanCreateRequest,
    x_user_id: str = Header("default"),
) -> dict:
    """创建学习计划.

    设置学习时间、科目、优先级等。
    """
    service = _get_service(x_user_id)
    plan = service.create_plan(
        title=req.title,
        start_time=req.start_time,
        end_time=req.end_time,
        priority=req.priority,
        subject=req.subject,
        date=req.date,
    )
    return make_response(data=plan, message="创建计划成功")


@router.post("/plans/{plan_id}/toggle")
async def toggle_plan(
    plan_id: int,
    x_user_id: str = Header("default"),
) -> dict:
    """切换计划完成状态.

    在完成/未完成之间切换。
    """
    service = _get_service(x_user_id)
    plan = service.toggle_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="计划不存在")
    return make_response(data=plan, message="切换计划状态成功")


@router.delete("/plans/{plan_id}")
async def delete_plan(
    plan_id: int,
    x_user_id: str = Header("default"),
) -> dict:
    """删除学习计划."""
    service = _get_service(x_user_id)
    success = service.delete_plan(plan_id)
    if not success:
        raise HTTPException(status_code=404, detail="计划不存在")
    return make_response(data={"deleted": True}, message="删除计划成功")


# ---------------------------------------------------------------------------
# 周目标
# ---------------------------------------------------------------------------


@router.get("/weekly-goals")
async def get_weekly_goals(
    x_user_id: str = Header("default"),
) -> dict:
    """获取本周目标列表."""
    service = _get_service(x_user_id)
    goals = service.get_weekly_goals()
    return make_response(data=goals, message="获取周目标成功")


@router.put("/weekly-goals")
async def update_weekly_goals(
    req: WeeklyGoalsUpdateRequest,
    x_user_id: str = Header("default"),
) -> dict:
    """更新周目标列表.

    批量更新所有周目标。
    """
    service = _get_service(x_user_id)
    goals_list = [g.model_dump() for g in req.goals]
    result = service.update_weekly_goals(goals_list)
    return make_response(data=result, message="更新周目标成功")


@router.post("/weekly-goals/{goal_id}/toggle")
async def toggle_weekly_goal(
    goal_id: int,
    x_user_id: str = Header("default"),
) -> dict:
    """切换周目标完成状态."""
    service = _get_service(x_user_id)
    result = service.toggle_weekly_goal(goal_id)
    if result is None:
        raise HTTPException(status_code=404, detail="周目标不存在")
    return make_response(data=result, message="切换周目标成功")


# ---------------------------------------------------------------------------
# 知识库
# ---------------------------------------------------------------------------


@router.get("/knowledge/categories")
async def list_knowledge_categories(
    x_user_id: str = Header("default"),
) -> dict:
    """获取知识分类列表."""
    service = _get_service(x_user_id)
    categories = service.list_knowledge_categories()
    return make_response(data=categories, message="获取知识分类成功")


@router.get("/notes")
async def list_notes(
    subject: Optional[str] = Query(None, description="按科目筛选"),
    x_user_id: str = Header("default"),
) -> dict:
    """获取学习笔记列表.

    支持按科目筛选。
    """
    service = _get_service(x_user_id)
    notes = service.list_notes(subject=subject)
    return make_response(data=notes, message="获取笔记列表成功")


@router.get("/notes/{note_id}")
async def get_note_detail(
    note_id: int,
    x_user_id: str = Header("default"),
) -> dict:
    """获取笔记详情."""
    service = _get_service(x_user_id)
    note = service.get_note_detail(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="笔记不存在")
    return make_response(data=note, message="获取笔记详情成功")


@router.post("/notes")
async def create_note(
    req: NoteCreateRequest,
    x_user_id: str = Header("default"),
) -> dict:
    """创建学习笔记."""
    service = _get_service(x_user_id)
    note = service.create_note(
        title=req.title,
        subject=req.subject,
        content=req.content,
    )
    return make_response(data=note, message="创建笔记成功")


@router.put("/notes/{note_id}")
async def update_note(
    note_id: int,
    req: NoteUpdateRequest,
    x_user_id: str = Header("default"),
) -> dict:
    """更新学习笔记."""
    service = _get_service(x_user_id)
    note = service.update_note(
        note_id=note_id,
        title=req.title,
        subject=req.subject,
        content=req.content,
    )
    if not note:
        raise HTTPException(status_code=404, detail="笔记不存在")
    return make_response(data=note, message="更新笔记成功")


@router.delete("/notes/{note_id}")
async def delete_note(
    note_id: int,
    x_user_id: str = Header("default"),
) -> dict:
    """删除学习笔记."""
    service = _get_service(x_user_id)
    success = service.delete_note(note_id)
    if not success:
        raise HTTPException(status_code=404, detail="笔记不存在")
    return make_response(data={"deleted": True}, message="删除笔记成功")


# ---------------------------------------------------------------------------
# 进度追踪
# ---------------------------------------------------------------------------


@router.get("/progress/subjects")
async def get_subject_progress(
    x_user_id: str = Header("default"),
) -> dict:
    """获取各科学习进度."""
    service = _get_service(x_user_id)
    progress = service.get_subject_progress()
    return make_response(data=progress, message="获取科目进度成功")


@router.get("/progress/stats")
async def get_study_stats(
    x_user_id: str = Header("default"),
) -> dict:
    """获取学习统计数据.

    返回今日学习时长、本周时长、连续学习天数等统计信息。
    """
    service = _get_service(x_user_id)
    stats = service.get_study_stats()
    return make_response(data=stats, message="获取学习统计成功")


# ---------------------------------------------------------------------------
# 考试提醒
# ---------------------------------------------------------------------------


@router.get("/exams")
async def list_exams(
    x_user_id: str = Header("default"),
) -> dict:
    """获取考试提醒列表.

    按考试日期升序排列。
    """
    service = _get_service(x_user_id)
    exams = service.list_exams()
    return make_response(data=exams, message="获取考试列表成功")


@router.post("/exams")
async def create_exam(
    req: ExamCreateRequest,
    x_user_id: str = Header("default"),
) -> dict:
    """创建考试提醒."""
    service = _get_service(x_user_id)
    exam = service.create_exam(
        name=req.name,
        exam_date=req.exam_date,
        location=req.location,
        urgency=req.urgency,
    )
    return make_response(data=exam, message="创建考试提醒成功")


@router.delete("/exams/{exam_id}")
async def delete_exam(
    exam_id: int,
    x_user_id: str = Header("default"),
) -> dict:
    """删除考试提醒."""
    service = _get_service(x_user_id)
    success = service.delete_exam(exam_id)
    if not success:
        raise HTTPException(status_code=404, detail="考试不存在")
    return make_response(data={"deleted": True}, message="删除考试提醒成功")


# ---------------------------------------------------------------------------
# 风险矩阵
# ---------------------------------------------------------------------------


@router.get("/risk-matrix")
async def get_risk_matrix(
    x_user_id: str = Header("default"),
) -> dict:
    """获取风险矩阵.

    返回 3x3 风险矩阵和风险项列表。
    """
    service = _get_service(x_user_id)
    matrix = service.get_risk_matrix()
    return make_response(data=matrix, message="获取风险矩阵成功")


# ---------------------------------------------------------------------------
# 方案对比
# ---------------------------------------------------------------------------


@router.get("/scenarios")
async def get_scenarios(
    x_user_id: str = Header("default"),
) -> dict:
    """获取方案对比.

    返回多种学习方案及各阶段进度。
    """
    service = _get_service(x_user_id)
    scenarios = service.get_scenarios()
    return make_response(data=scenarios, message="获取方案对比成功")


# ---------------------------------------------------------------------------
# 甘特图
# ---------------------------------------------------------------------------


@router.get("/gantt")
async def get_gantt(
    x_user_id: str = Header("default"),
) -> dict:
    """获取学习计划甘特图.

    返回各学习阶段时间线。
    """
    service = _get_service(x_user_id)
    gantt = service.get_gantt_phases()
    return make_response(data=gantt, message="获取甘特图成功")
