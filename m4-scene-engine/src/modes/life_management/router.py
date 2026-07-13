"""生活管理模式 - API 路由.

提供生活管理模式的 RESTful API 接口，包括概览、日程管理、
待办事项、习惯打卡、场景模式、自动化规则、财务管理等功能。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header, Query

from src.database import get_session
from src.models import make_response
from src.modes.life_management.models import (
    FinanceRecordCreateRequest,
    HabitCreateRequest,
    RuleCreateRequest,
    SceneSwitchRequest,
    ScheduleCreateRequest,
    TodoCreateRequest,
)
from src.modes.life_management.service import LifeService

import structlog

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# 路由配置
# ---------------------------------------------------------------------------

router = APIRouter(
    prefix="/api/v1/life-management",
    tags=["生活管理模式"],
)


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _get_service(x_user_id: str = "default") -> LifeService:
    """获取 LifeService 实例.

    Args:
        x_user_id: 用户 ID（从请求头获取）

    Returns:
        LifeService 实例
    """
    db = get_session()
    return LifeService(db, user_id=x_user_id)


# ---------------------------------------------------------------------------
# 概览接口
# ---------------------------------------------------------------------------


@router.get("/overview", summary="获取生活管理概览")
async def get_overview(
    x_user_id: str = Header("default", description="用户 ID"),
):
    """获取生活管理概览数据，包含统计数据和当前场景."""
    try:
        service = _get_service(x_user_id)
        data = service.get_overview()
        return make_response(data=data)
    except Exception as e:
        logger.error("overview 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50001,
            message=f"获取概览失败: {e}",
            data={},
        )


# ---------------------------------------------------------------------------
# 日程管理接口
# ---------------------------------------------------------------------------


@router.get("/schedules", summary="获取日程列表")
async def get_schedules(
    date: Optional[str] = Query(None, description="按日期筛选 YYYY-MM-DD"),
    x_user_id: str = Header("default", description="用户 ID"),
):
    """获取日程列表，支持按日期筛选."""
    try:
        service = _get_service(x_user_id)
        data = service.list_schedules(date=date)
        return make_response(data=data)
    except Exception as e:
        logger.error("schedules 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50002,
            message=f"获取日程列表失败: {e}",
            data=[],
        )


@router.get("/schedules/week", summary="获取周视图")
async def get_week_schedules(
    x_user_id: str = Header("default", description="用户 ID"),
):
    """获取周视图数据."""
    try:
        service = _get_service(x_user_id)
        data = service.get_week_view()
        return make_response(data=data)
    except Exception as e:
        logger.error("week schedules 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50003,
            message=f"获取周视图失败: {e}",
            data={"week_days": []},
        )


@router.post("/schedules", summary="创建日程")
async def create_schedule(
    req: ScheduleCreateRequest,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """创建一个新日程."""
    try:
        service = _get_service(x_user_id)
        data = service.create_schedule(
            title=req.title,
            time=req.time,
            tag=req.tag,
            tag_color=req.tag_color,
            date=req.date,
            description=req.description,
            all_day=req.all_day,
            priority=req.priority,
        )
        return make_response(message="日程创建成功", data=data)
    except Exception as e:
        logger.error("create schedule 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50004,
            message=f"创建日程失败: {e}",
            data={},
        )


@router.delete("/schedules/{schedule_id}", summary="删除日程")
async def delete_schedule(
    schedule_id: int,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """删除指定日程."""
    try:
        service = _get_service(x_user_id)
        success = service.delete_schedule(schedule_id)
        if not success:
            return make_response(
                code=40401,
                message="日程不存在",
                data={},
            )
        return make_response(message="删除成功", data={})
    except Exception as e:
        logger.error("delete schedule 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50005,
            message=f"删除日程失败: {e}",
            data={},
        )


# ---------------------------------------------------------------------------
# 待办事项接口
# ---------------------------------------------------------------------------


@router.get("/todos", summary="获取待办列表")
async def get_todos(
    status: Optional[str] = Query(None, description="按状态筛选"),
    x_user_id: str = Header("default", description="用户 ID"),
):
    """获取待办事项列表，支持按状态筛选."""
    try:
        service = _get_service(x_user_id)
        data = service.list_todos(status=status)
        return make_response(data=data)
    except Exception as e:
        logger.error("todos 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50006,
            message=f"获取待办列表失败: {e}",
            data=[],
        )


@router.post("/todos", summary="创建待办")
async def create_todo(
    req: TodoCreateRequest,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """创建一个新待办事项."""
    try:
        service = _get_service(x_user_id)
        data = service.create_todo(
            title=req.title,
            status=req.status,
            category=req.category,
            priority=req.priority,
            description=req.description,
            due_date=req.due_date,
        )
        return make_response(message="待办创建成功", data=data)
    except Exception as e:
        logger.error("create todo 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50007,
            message=f"创建待办失败: {e}",
            data={},
        )


@router.put("/todos/{todo_id}/status", summary="更新待办状态")
async def update_todo_status(
    todo_id: int,
    status: str = Query(..., description="新状态：todo/in-progress/done"),
    x_user_id: str = Header("default", description="用户 ID"),
):
    """更新待办事项状态."""
    try:
        service = _get_service(x_user_id)
        data = service.update_todo_status(todo_id, status)
        if data is None:
            return make_response(
                code=40402,
                message="待办不存在",
                data={},
            )
        return make_response(message="状态已更新", data=data)
    except Exception as e:
        logger.error("update todo status 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50008,
            message=f"更新待办状态失败: {e}",
            data={},
        )


@router.delete("/todos/{todo_id}", summary="删除待办")
async def delete_todo(
    todo_id: int,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """删除指定待办事项."""
    try:
        service = _get_service(x_user_id)
        success = service.delete_todo(todo_id)
        if not success:
            return make_response(
                code=40402,
                message="待办不存在",
                data={},
            )
        return make_response(message="删除成功", data={})
    except Exception as e:
        logger.error("delete todo 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50009,
            message=f"删除待办失败: {e}",
            data={},
        )


# ---------------------------------------------------------------------------
# 习惯打卡接口
# ---------------------------------------------------------------------------


@router.get("/habits", summary="获取习惯列表")
async def get_habits(
    x_user_id: str = Header("default", description="用户 ID"),
):
    """获取习惯打卡列表."""
    try:
        service = _get_service(x_user_id)
        data = service.list_habits()
        return make_response(data=data)
    except Exception as e:
        logger.error("habits 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50010,
            message=f"获取习惯列表失败: {e}",
            data=[],
        )


@router.post("/habits", summary="创建习惯")
async def create_habit(
    req: HabitCreateRequest,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """创建一个新习惯."""
    try:
        service = _get_service(x_user_id)
        data = service.create_habit(
            name=req.name,
            icon=req.icon,
            category=req.category,
            frequency=req.frequency,
            description=req.description,
        )
        return make_response(message="习惯创建成功", data=data)
    except Exception as e:
        logger.error("create habit 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50011,
            message=f"创建习惯失败: {e}",
            data={},
        )


@router.post("/habits/{habit_id}/checkin", summary="习惯打卡")
async def checkin_habit(
    habit_id: int,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """对指定习惯进行打卡."""
    try:
        service = _get_service(x_user_id)
        data = service.checkin_habit(habit_id)
        if data is None:
            return make_response(
                code=40403,
                message="习惯不存在",
                data={},
            )
        return make_response(message="打卡成功", data=data)
    except Exception as e:
        logger.error("checkin habit 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50012,
            message=f"打卡失败: {e}",
            data={},
        )


@router.delete("/habits/{habit_id}", summary="删除习惯")
async def delete_habit(
    habit_id: int,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """删除指定习惯."""
    try:
        service = _get_service(x_user_id)
        success = service.delete_habit(habit_id)
        if not success:
            return make_response(
                code=40403,
                message="习惯不存在",
                data={},
            )
        return make_response(message="删除成功", data={})
    except Exception as e:
        logger.error("delete habit 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50013,
            message=f"删除习惯失败: {e}",
            data={},
        )


# ---------------------------------------------------------------------------
# 习惯打卡记录接口
# ---------------------------------------------------------------------------


@router.get("/habits/records", summary="获取习惯打卡记录")
async def get_habit_records(
    habit_id: Optional[int] = Query(None, description="按习惯 ID 筛选"),
    date: Optional[str] = Query(None, description="按日期筛选"),
    limit: int = Query(30, description="返回条数限制", ge=1, le=100),
    x_user_id: str = Header("default", description="用户 ID"),
):
    """获取习惯打卡记录列表."""
    try:
        service = _get_service(x_user_id)
        data = service.list_habit_records(
            habit_id=habit_id, date=date, limit=limit,
        )
        return make_response(data=data)
    except Exception as e:
        logger.error("habit records 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50014,
            message=f"获取打卡记录失败: {e}",
            data=[],
        )


# ---------------------------------------------------------------------------
# 场景模式接口
# ---------------------------------------------------------------------------


@router.get("/scenes", summary="获取场景列表")
async def get_scenes(
    x_user_id: str = Header("default", description="用户 ID"),
):
    """获取生活场景列表."""
    try:
        service = _get_service(x_user_id)
        data = service.list_scenes()
        return make_response(data=data)
    except Exception as e:
        logger.error("scenes 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50015,
            message=f"获取场景列表失败: {e}",
            data=[],
        )


@router.post("/scenes/switch", summary="切换场景")
async def switch_scene(
    req: SceneSwitchRequest,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """切换当前生活场景."""
    try:
        service = _get_service(x_user_id)
        data = service.switch_scene(req.scene_key)
        if data is None:
            return make_response(
                code=40404,
                message="场景不存在",
                data={},
            )
        return make_response(message=f"已切换至{data.get('name', '')}", data=data)
    except Exception as e:
        logger.error("switch scene 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50016,
            message=f"切换场景失败: {e}",
            data={},
        )


# ---------------------------------------------------------------------------
# 自动化规则接口
# ---------------------------------------------------------------------------


@router.get("/rules", summary="获取自动化规则")
async def get_rules(
    x_user_id: str = Header("default", description="用户 ID"),
):
    """获取自动化规则列表."""
    try:
        service = _get_service(x_user_id)
        data = service.list_rules()
        return make_response(data=data)
    except Exception as e:
        logger.error("rules 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50017,
            message=f"获取规则列表失败: {e}",
            data=[],
        )


@router.post("/rules", summary="创建自动化规则")
async def create_rule(
    req: RuleCreateRequest,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """创建一条新的自动化规则."""
    try:
        service = _get_service(x_user_id)
        data = service.create_rule(
            condition=req.condition,
            action=req.action,
            title=req.title,
            category=req.category,
        )
        return make_response(message="规则创建成功", data=data)
    except Exception as e:
        logger.error("create rule 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50018,
            message=f"创建规则失败: {e}",
            data={},
        )


@router.put("/rules/{rule_id}/toggle", summary="切换规则开关")
async def toggle_rule(
    rule_id: int,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """切换自动化规则的启用/禁用状态."""
    try:
        service = _get_service(x_user_id)
        data = service.toggle_rule(rule_id)
        if data is None:
            return make_response(
                code=40405,
                message="规则不存在",
                data={},
            )
        return make_response(message="状态已更新", data=data)
    except Exception as e:
        logger.error("toggle rule 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50019,
            message=f"切换规则状态失败: {e}",
            data={},
        )


@router.delete("/rules/{rule_id}", summary="删除规则")
async def delete_rule(
    rule_id: int,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """删除指定自动化规则."""
    try:
        service = _get_service(x_user_id)
        success = service.delete_rule(rule_id)
        if not success:
            return make_response(
                code=40405,
                message="规则不存在",
                data={},
            )
        return make_response(message="删除成功", data={})
    except Exception as e:
        logger.error("delete rule 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50020,
            message=f"删除规则失败: {e}",
            data={},
        )


# ---------------------------------------------------------------------------
# 财务管理接口
# ---------------------------------------------------------------------------


@router.get("/finance/overview", summary="获取财务概览")
async def get_finance_overview(
    x_user_id: str = Header("default", description="用户 ID"),
):
    """获取财务概览数据."""
    try:
        service = _get_service(x_user_id)
        data = service.get_finance_overview()
        return make_response(data=data)
    except Exception as e:
        logger.error("finance overview 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50021,
            message=f"获取财务概览失败: {e}",
            data={},
        )


@router.get("/finance/categories", summary="获取财务分类")
async def get_finance_categories(
    x_user_id: str = Header("default", description="用户 ID"),
):
    """获取支出分类列表."""
    try:
        service = _get_service(x_user_id)
        data = service.list_finance_categories(type="expense")
        return make_response(data=data)
    except Exception as e:
        logger.error("finance categories 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50022,
            message=f"获取财务分类失败: {e}",
            data=[],
        )


@router.get("/finance/records", summary="获取财务记录")
async def get_finance_records(
    type: Optional[str] = Query(None, description="按类型筛选"),
    category: Optional[str] = Query(None, description="按分类筛选"),
    start_date: Optional[str] = Query(None, description="起始日期"),
    end_date: Optional[str] = Query(None, description="结束日期"),
    limit: int = Query(50, description="返回条数限制", ge=1, le=200),
    x_user_id: str = Header("default", description="用户 ID"),
):
    """获取财务记录列表，支持多条件筛选."""
    try:
        service = _get_service(x_user_id)
        data = service.list_finance_records(
            type=type,
            category=category,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
        )
        return make_response(data=data)
    except Exception as e:
        logger.error("finance records 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50023,
            message=f"获取财务记录失败: {e}",
            data=[],
        )


@router.post("/finance/records", summary="创建财务记录")
async def create_finance_record(
    req: FinanceRecordCreateRequest,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """创建一条财务记录（收入或支出）."""
    try:
        service = _get_service(x_user_id)
        data = service.create_finance_record(
            type=req.type,
            amount=req.amount,
            category=req.category,
            description=req.description,
            transaction_date=req.transaction_date,
        )
        return make_response(message="记录创建成功", data=data)
    except Exception as e:
        logger.error("create finance record 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50024,
            message=f"创建财务记录失败: {e}",
            data={},
        )


# ---------------------------------------------------------------------------
# 生活助手接口
# ---------------------------------------------------------------------------


@router.get("/assistant/tools", summary="获取助手工具列表")
async def get_assistant_tools(
    x_user_id: str = Header("default", description="用户 ID"),
):
    """获取生活助手工具列表."""
    try:
        service = _get_service(x_user_id)
        data = service.get_assistant_tools()
        return make_response(data=data)
    except Exception as e:
        logger.error("assistant tools 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50025,
            message=f"获取助手工具失败: {e}",
            data=[],
        )


# ---------------------------------------------------------------------------
# 能耗监控接口
# ---------------------------------------------------------------------------


@router.get("/energy", summary="获取能耗数据")
async def get_energy_data(
    x_user_id: str = Header("default", description="用户 ID"),
):
    """获取能耗监控数据."""
    try:
        service = _get_service(x_user_id)
        data = service.get_energy_data()
        return make_response(data=data)
    except Exception as e:
        logger.error("energy 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50026,
            message=f"获取能耗数据失败: {e}",
            data={"categories": [], "total": {}},
        )
