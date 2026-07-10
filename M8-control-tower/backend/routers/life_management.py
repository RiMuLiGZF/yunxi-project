"""
生活管理模式 API
数据存储：SQLite 数据库（Repository 模式，数据库优先 + 内存 fallback）
设备接口：保持对接 M6 代理的逻辑不变
认证：所有接口需要 Bearer Token 认证
"""

import sys
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import Optional, List
from sqlalchemy.orm import Session

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from shared.module_client import get_module_registry
from shared.logger import get_logger
from ..models import get_db
from ..auth import get_current_user
from ..repositories.life_repository import LifeRepository

logger = get_logger("m8.life_management")

router = APIRouter()
registry = get_module_registry()

# 默认用户 ID（单用户模式）
DEFAULT_USER_ID = 1

# 设备列表（保留内存 mock 数据，用于 M6 不可用时的降级）
_devices = [
    {"id": 1, "name": "智能手表", "status": "online", "battery": 78, "icon_type": "watch", "position": {"x": 50, "y": 30}},
    {"id": 2, "name": "智能戒指", "status": "online", "battery": 92, "icon_type": "ring", "position": {"x": 20, "y": 50}},
    {"id": 3, "name": "桌面终端", "status": "online", "battery": 100, "icon_type": "monitor", "position": {"x": 80, "y": 30}},
    {"id": 4, "name": "AR眼镜", "status": "warning", "battery": 35, "icon_type": "glasses", "position": {"x": 50, "y": 60}},
    {"id": 5, "name": "改装无人机", "status": "offline", "battery": None, "icon_type": "drone", "position": {"x": 20, "y": 20}},
    {"id": 6, "name": "笔记本电脑", "status": "online", "battery": 65, "icon_type": "laptop", "position": {"x": 80, "y": 70}},
]


# ==================== 工具函数 ====================

def _get_repo(db: Session, current_user: dict) -> LifeRepository:
    """获取 LifeRepository 实例（根据当前用户）"""
    # 单用户模式下使用默认 user_id，后续可根据 current_user["username"] 映射
    return LifeRepository(db, user_id=DEFAULT_USER_ID)


def _generate_week_days():
    """生成周视图数据"""
    today = datetime.now()
    weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    result = []
    for i in range(7):
        d = today - timedelta(days=today.weekday()) + timedelta(days=i)
        is_active = d.date() == today.date()
        dots = []
        if i % 2 == 0:
            dots.append("green")
        if i % 3 == 0:
            dots.append("blue")
        if i == 2:
            dots.append("orange")
        result.append({
            "label": weekdays[i],
            "day_num": d.day,
            "date": d.strftime("%Y-%m-%d"),
            "event_dots": dots,
            "active": is_active,
        })
    return result


# ==================== 模型转换 ====================

def _schedule_to_dict(s) -> dict:
    """将日程对象转为前端格式"""
    return {
        "id": s.schedule_id,
        "time": s.time_range or f"{s.start_time} - {s.end_time}",
        "title": s.title,
        "tag": s.category,
        "tag_color": s.tag_color,
        "date": s.date,
        "all_day": s.all_day if hasattr(s, 'all_day') else False,
        "priority": s.priority if hasattr(s, 'priority') else "normal",
    }


def _rule_to_dict(r) -> dict:
    """将规则对象转为前端格式"""
    return {
        "id": r.rule_id,
        "condition": r.condition,
        "action": r.action,
        "enabled": r.enabled,
    }


def _todo_to_dict(t) -> dict:
    """将待办对象转为前端格式"""
    return {
        "id": t.todo_id,
        "title": t.title,
        "status": t.status,
        "progress": t.progress,
        "category": t.category,
        "priority": t.priority if hasattr(t, 'priority') else "normal",
    }


def _habit_to_dict(h) -> dict:
    """将习惯对象转为前端格式"""
    return {
        "id": h.habit_id,
        "name": h.name,
        "icon": h.icon,
        "streak": h.streak,
        "longest_streak": h.longest_streak if hasattr(h, 'longest_streak') else h.streak,
        "done": h.done,
        "frequency": h.frequency if hasattr(h, 'frequency') else "daily",
    }


def _scene_to_dict(s) -> dict:
    """将场景对象转为前端格式"""
    return {
        "key": s.scene_id,
        "label": s.name,
        "icon": s.icon,
        "active": s.active,
        "description": s.description or "",
    }


def _finance_cat_to_dict(c) -> dict:
    """将财务分类对象转为前端格式"""
    return {
        "id": c.category_id,
        "name": c.name,
        "amount": c.spent,
        "percentage": c.percentage,
        "color": c.color,
        "budget": c.budget,
    }


def _finance_record_to_dict(r) -> dict:
    """将财务记录对象转为前端格式"""
    return {
        "id": r.id,
        "type": r.type,
        "amount": r.amount,
        "category": r.category,
        "description": r.description,
        "transaction_date": r.transaction_date,
        "created_at": r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else None,
    }


# ==================== 请求模型 ====================

class ScheduleCreateRequest(BaseModel):
    title: str
    time: str
    tag: str = "固定"
    tag_color: str = "green"
    date: Optional[str] = None
    description: str = ""
    all_day: bool = False
    priority: str = "normal"


class TodoCreateRequest(BaseModel):
    title: str
    status: str = "todo"
    category: str = "今日待办"
    priority: str = "normal"
    description: str = ""
    due_date: Optional[str] = None


class HabitCreateRequest(BaseModel):
    name: str
    icon: str = "✅"
    category: str = ""
    frequency: str = "daily"
    description: str = ""


class RuleCreateRequest(BaseModel):
    condition: str
    action: str
    title: str = ""
    category: str = ""


class SceneSwitchRequest(BaseModel):
    scene_key: str


class FinanceRecordCreateRequest(BaseModel):
    type: str = "expense"
    amount: float
    category: str
    description: str = ""
    transaction_date: Optional[str] = None


# ==================== 概览 ====================

@router.get("/overview")
async def get_overview(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """生活管理概览"""
    repo = _get_repo(db, current_user)
    stats = repo.get_overview_stats()

    life_stats = repo.get_meta("life_stats") or {}
    finance_overview = repo.get_meta("finance_overview") or {}

    current_scene_obj = stats["current_scene"]
    current_scene = _scene_to_dict(current_scene_obj) if current_scene_obj else {}

    # 设备统计：优先从 M6 获取
    device_total = len(_devices)
    device_online = sum(1 for d in _devices if d["status"] == "online")
    try:
        m6_client = registry.get_client("m6")
        is_healthy = await m6_client.health_check()
        if is_healthy:
            result = await m6_client.get("/api/v1/devices/stats")
            m6_stats = result.get("data", {})
            device_total = m6_stats.get("total", device_total)
            device_online = m6_stats.get("online", device_online)
    except Exception:
        pass

    return {
        "code": 0,
        "message": "ok",
        "data": {
            "stats": {
                "todo_total": stats["todo_total"],
                "todo_done": stats["todo_done"],
                "habit_total": stats["habit_total"],
                "habit_done": stats["habit_done"],
                "device_total": device_total,
                "device_online": device_online,
                "today_spending": finance_overview.get("today_spending", stats["finance"]["today_spending"]),
            },
            "life_stats": life_stats,
            "current_scene": current_scene,
        },
    }


# ==================== 日程管理 ====================

@router.get("/schedules")
async def get_schedules(
    date: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取日程列表"""
    repo = _get_repo(db, current_user)
    target_date = date or datetime.now().strftime("%Y-%m-%d")
    schedules = repo.list_schedules(date=target_date)
    result = [_schedule_to_dict(s) for s in schedules]
    return {"code": 0, "message": "ok", "data": result}


@router.get("/schedules/week")
async def get_week_schedules(
    current_user: dict = Depends(get_current_user),
):
    """获取周视图"""
    week_days = _generate_week_days()
    return {"code": 0, "message": "ok", "data": {"week_days": week_days}}


@router.post("/schedules")
async def create_schedule(
    req: ScheduleCreateRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """创建日程"""
    repo = _get_repo(db, current_user)

    # 解析时间范围 "09:00 - 10:30"
    time_range = req.time
    start_time = "09:00"
    end_time = "10:00"
    try:
        parts = time_range.replace(" ", "").split("-")
        if len(parts) == 2:
            start_time = parts[0]
            end_time = parts[1]
    except Exception:
        pass

    schedule = repo.create_schedule(
        title=req.title,
        time_range=time_range,
        start_time=start_time,
        end_time=end_time,
        category=req.tag,
        tag_color=req.tag_color,
        date=req.date,
        description=req.description,
        all_day=req.all_day,
        priority=req.priority,
    )

    return {"code": 0, "message": "日程创建成功", "data": _schedule_to_dict(schedule)}


@router.delete("/schedules/{schedule_id}")
async def delete_schedule(
    schedule_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """删除日程"""
    repo = _get_repo(db, current_user)
    success = repo.delete_schedule(schedule_id)
    if not success:
        return {"code": 404, "message": "日程不存在", "data": None}
    return {"code": 0, "message": "删除成功", "data": None}


# ==================== 自动化规则 ====================

@router.get("/rules")
async def get_rules(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取自动化规则"""
    repo = _get_repo(db, current_user)
    rules = repo.list_rules()
    result = [_rule_to_dict(r) for r in rules]
    return {"code": 0, "message": "ok", "data": result}


@router.post("/rules")
async def create_rule(
    req: RuleCreateRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """创建自动化规则"""
    repo = _get_repo(db, current_user)
    rule = repo.create_rule(
        condition=req.condition,
        action=req.action,
        title=req.title,
        category=req.category,
    )
    return {"code": 0, "message": "规则创建成功", "data": _rule_to_dict(rule)}


@router.put("/rules/{rule_id}/toggle")
async def toggle_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """切换规则开关"""
    repo = _get_repo(db, current_user)
    rule = repo.toggle_rule(rule_id)
    if not rule:
        return {"code": 404, "message": "规则不存在", "data": None}
    return {"code": 0, "message": "状态已更新", "data": _rule_to_dict(rule)}


@router.delete("/rules/{rule_id}")
async def delete_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """删除规则"""
    repo = _get_repo(db, current_user)
    success = repo.delete_rule(rule_id)
    if not success:
        return {"code": 404, "message": "规则不存在", "data": None}
    return {"code": 0, "message": "删除成功", "data": None}


# ==================== 设备中心（保持 M6 对接逻辑不变） ====================

@router.get("/devices")
async def get_devices(
    current_user: dict = Depends(get_current_user),
):
    """获取设备列表（优先从 M6 获取，不可用时使用本地 mock 数据）"""
    try:
        m6_client = registry.get_client("m6")
        is_healthy = await m6_client.health_check()
        if is_healthy:
            result = await m6_client.get("/api/v1/devices")
            m6_devices = result.get("data", {}).get("devices", [])
            # 转换为 life_management 格式以保持向后兼容
            items = []
            for i, dev in enumerate(m6_devices):
                items.append({
                    "id": i + 1,
                    "name": dev.get("name", dev.get("device_id", "设备")),
                    "status": dev.get("status", "offline"),
                    "battery": dev.get("battery"),
                    "icon_type": dev.get("device_type", "device"),
                    "position": dev.get("position", {"x": 50, "y": 50}),
                })
            return {"code": 0, "message": "ok", "data": items, "source": "m6"}
    except Exception as exc:
        logger.debug(f"M6 设备列表获取失败，使用本地数据: {exc}")

    return {"code": 0, "message": "ok", "data": _devices, "source": "local"}


@router.get("/devices/stats")
async def get_device_stats(
    current_user: dict = Depends(get_current_user),
):
    """设备统计（优先从 M6 获取，不可用时使用本地 mock 数据）"""
    try:
        m6_client = registry.get_client("m6")
        is_healthy = await m6_client.health_check()
        if is_healthy:
            result = await m6_client.get("/api/v1/devices/stats")
            m6_stats = result.get("data", {})
            # 兼容旧格式
            return {
                "code": 0,
                "message": "ok",
                "data": {
                    "total": m6_stats.get("total", 0),
                    "online": m6_stats.get("online", 0),
                    "offline": m6_stats.get("offline", 0),
                    "warning": m6_stats.get("warning", 0),
                },
                "source": "m6",
            }
    except Exception as exc:
        logger.debug(f"M6 设备统计获取失败，使用本地数据: {exc}")

    online = sum(1 for d in _devices if d["status"] == "online")
    offline = sum(1 for d in _devices if d["status"] == "offline")
    warning = sum(1 for d in _devices if d["status"] == "warning")
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "total": len(_devices),
            "online": online,
            "offline": offline,
            "warning": warning,
        },
        "source": "local",
    }


# ==================== 能耗监控 ====================

@router.get("/energy")
async def get_energy_data(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取能耗数据"""
    repo = _get_repo(db, current_user)
    categories = repo.get_meta("energy_data") or []
    total = repo.get_meta("energy_total") or {}
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "categories": categories,
            "total": total,
        },
    }


# ==================== 场景模式 ====================

@router.get("/scenes")
async def get_scenes(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取场景列表"""
    repo = _get_repo(db, current_user)
    scenes = repo.list_scenes()
    result = [_scene_to_dict(s) for s in scenes]
    return {"code": 0, "message": "ok", "data": result}


@router.post("/scenes/switch")
async def switch_scene(
    req: SceneSwitchRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """切换场景"""
    repo = _get_repo(db, current_user)
    current = repo.switch_scene(req.scene_key)
    if not current:
        return {"code": 404, "message": "场景不存在", "data": None}
    return {"code": 0, "message": f"已切换至{current.name}", "data": _scene_to_dict(current)}


# ==================== 待办事项 ====================

@router.get("/todos")
async def get_todos(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取待办列表"""
    repo = _get_repo(db, current_user)
    todos = repo.list_todos(status=status)
    result = [_todo_to_dict(t) for t in todos]
    return {"code": 0, "message": "ok", "data": result}


@router.post("/todos")
async def create_todo(
    req: TodoCreateRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """创建待办"""
    repo = _get_repo(db, current_user)
    todo = repo.create_todo(
        title=req.title,
        status=req.status,
        category=req.category,
        priority=req.priority,
        description=req.description,
        due_date=req.due_date,
    )
    return {"code": 0, "message": "待办创建成功", "data": _todo_to_dict(todo)}


@router.put("/todos/{todo_id}/status")
async def update_todo_status(
    todo_id: int,
    status: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """更新待办状态"""
    repo = _get_repo(db, current_user)
    todo = repo.update_todo_status(todo_id, status)
    if not todo:
        return {"code": 404, "message": "待办不存在", "data": None}
    return {"code": 0, "message": "状态已更新", "data": _todo_to_dict(todo)}


@router.delete("/todos/{todo_id}")
async def delete_todo(
    todo_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """删除待办"""
    repo = _get_repo(db, current_user)
    success = repo.delete_todo(todo_id)
    if not success:
        return {"code": 404, "message": "待办不存在", "data": None}
    return {"code": 0, "message": "删除成功", "data": None}


# ==================== 习惯打卡 ====================

@router.get("/habits")
async def get_habits(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取习惯列表"""
    repo = _get_repo(db, current_user)
    habits = repo.list_habits()
    result = [_habit_to_dict(h) for h in habits]
    return {"code": 0, "message": "ok", "data": result}


@router.post("/habits")
async def create_habit(
    req: HabitCreateRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """创建习惯"""
    repo = _get_repo(db, current_user)
    habit = repo.create_habit(
        name=req.name,
        icon=req.icon,
        category=req.category,
        frequency=req.frequency,
        description=req.description,
    )
    return {"code": 0, "message": "习惯创建成功", "data": _habit_to_dict(habit)}


@router.post("/habits/{habit_id}/checkin")
async def checkin_habit(
    habit_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """习惯打卡"""
    repo = _get_repo(db, current_user)
    habit = repo.checkin_habit(habit_id)
    if not habit:
        return {"code": 404, "message": "习惯不存在", "data": None}
    return {"code": 0, "message": "打卡成功", "data": _habit_to_dict(habit)}


@router.delete("/habits/{habit_id}")
async def delete_habit(
    habit_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """删除习惯"""
    repo = _get_repo(db, current_user)
    success = repo.delete_habit(habit_id)
    if not success:
        return {"code": 404, "message": "习惯不存在", "data": None}
    return {"code": 0, "message": "删除成功", "data": None}


# ==================== 习惯打卡记录 ====================

@router.get("/habits/records")
async def get_habit_records(
    habit_id: Optional[int] = None,
    date: Optional[str] = None,
    limit: int = 30,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取习惯打卡记录"""
    repo = _get_repo(db, current_user)
    records = repo.list_habit_records(habit_id=habit_id, date=date, limit=limit)
    result = [
        {
            "id": r.id,
            "habit_id": r.habit_id,
            "date": r.date,
            "completed": r.completed,
            "note": r.note,
        }
        for r in records
    ]
    return {"code": 0, "message": "ok", "data": result}


# ==================== 财务管理 ====================

@router.get("/finance/overview")
async def get_finance_overview(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取财务概览"""
    repo = _get_repo(db, current_user)
    # 优先从实际记录计算，meta 作为 fallback
    summary = repo.get_finance_summary()
    meta_overview = repo.get_meta("finance_overview") or {}

    # 合并数据，实际记录优先
    data = {
        "total_expense": summary.get("total_expense", meta_overview.get("total_expense", 0)),
        "total_income": summary.get("total_income", 0),
        "budget": summary.get("budget", meta_overview.get("budget", 0)),
        "today_spending": summary.get("today_spending", meta_overview.get("today_spending", 0)),
        "month_progress": summary.get("month_progress", meta_overview.get("month_progress", 0)),
    }
    return {"code": 0, "message": "ok", "data": data}


@router.get("/finance/categories")
async def get_finance_categories(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取支出分类"""
    repo = _get_repo(db, current_user)
    cats = repo.list_finance_categories(type="expense")
    result = [_finance_cat_to_dict(c) for c in cats]
    return {"code": 0, "message": "ok", "data": result}


@router.get("/finance/records")
async def get_finance_records(
    type: Optional[str] = None,
    category: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取财务记录列表"""
    repo = _get_repo(db, current_user)
    records = repo.list_finance_records(
        type=type, category=category,
        start_date=start_date, end_date=end_date,
        limit=limit,
    )
    result = [_finance_record_to_dict(r) for r in records]
    return {"code": 0, "message": "ok", "data": result}


@router.post("/finance/records")
async def create_finance_record(
    req: FinanceRecordCreateRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """创建财务记录"""
    repo = _get_repo(db, current_user)
    record = repo.create_finance_record(
        type=req.type,
        amount=req.amount,
        category=req.category,
        description=req.description,
        transaction_date=req.transaction_date,
    )
    return {"code": 0, "message": "记录创建成功", "data": _finance_record_to_dict(record)}


# ==================== 生活助手 ====================

@router.get("/assistant/tools")
async def get_assistant_tools(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取助手工具列表"""
    repo = _get_repo(db, current_user)
    data = repo.get_meta("assistant_tools") or []
    return {"code": 0, "message": "ok", "data": data}
