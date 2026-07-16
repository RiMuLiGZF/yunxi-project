"""
主动提醒管理 API
"""

import sys
import time
from pathlib import Path
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from ..schemas import ApiResponse
from ..auth import get_current_user
from shared.context_aware import (
    get_context_aware_engine,
    ReminderType,
    ReminderPriority,
    ReminderStatus,
)

router = APIRouter()
context_engine = get_context_aware_engine()


# ==================== Pydantic 模型 ====================

class ReminderCreate(BaseModel):
    """创建提醒请求"""
    title: str
    description: str = ""
    type: str = ReminderType.ONCE.value
    priority: str = ReminderPriority.NORMAL.value
    trigger_time: Optional[float] = None  # 一次性提醒用
    repeat_time: Optional[str] = None  # 重复提醒时间 "HH:MM"
    repeat_days: List[int] = Field(default_factory=list)  # 每周重复 0-6
    notify_methods: List[str] = Field(default_factory=lambda: ["voice", "notification"])
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ReminderUpdate(BaseModel):
    """更新提醒请求"""
    title: Optional[str] = None
    description: Optional[str] = None
    type: Optional[str] = None
    priority: Optional[str] = None
    trigger_time: Optional[float] = None
    repeat_time: Optional[str] = None
    repeat_days: Optional[List[int]] = None
    status: Optional[str] = None


class SnoozeRequest(BaseModel):
    """延后提醒请求"""
    minutes: int = 10


# ==================== 提醒管理接口 ====================

@router.post("/reminders")
async def create_reminder(
    reminder: ReminderCreate,
    current_user: dict = Depends(get_current_user)
):
    """创建提醒"""
    new_reminder = context_engine.add_reminder(
        title=reminder.title,
        description=reminder.description,
        reminder_type=reminder.type,
        priority=reminder.priority,
        trigger_time=reminder.trigger_time,
        repeat_time=reminder.repeat_time,
        repeat_days=reminder.repeat_days,
        notify_methods=reminder.notify_methods,
        tags=reminder.tags,
        metadata=reminder.metadata,
    )
    return ApiResponse.success(
        message="提醒创建成功",
        data=new_reminder.to_dict()
    )


@router.get("/reminders")
async def list_reminders(
    status: Optional[str] = None,
    reminder_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    current_user: dict = Depends(get_current_user)
):
    """获取提醒列表"""
    reminders = context_engine.list_reminders(
        status=status,
        reminder_type=reminder_type,
        limit=limit,
        offset=offset,
    )
    return ApiResponse.success(data={
        "total": len(reminders),
        "items": [r.to_dict() for r in reminders],
        "limit": limit,
        "offset": offset,
    })


@router.get("/reminders/{reminder_id}")
async def get_reminder(
    reminder_id: str,
    current_user: dict = Depends(get_current_user)
):
    """获取单个提醒详情"""
    reminder = context_engine.get_reminder(reminder_id)
    if not reminder:
        return ApiResponse.error(code=404, message="提醒不存在")
    return ApiResponse.success(data=reminder.to_dict())


@router.put("/reminders/{reminder_id}")
async def update_reminder(
    reminder_id: str,
    update: ReminderUpdate,
    current_user: dict = Depends(get_current_user)
):
    """更新提醒"""
    update_data = update.model_dump(exclude_unset=True)
    reminder = context_engine.update_reminder(reminder_id, **update_data)
    if not reminder:
        return ApiResponse.error(code=404, message="提醒不存在")
    return ApiResponse.success(
        message="提醒更新成功",
        data=reminder.to_dict()
    )


@router.delete("/reminders/{reminder_id}")
async def delete_reminder(
    reminder_id: str,
    current_user: dict = Depends(get_current_user)
):
    """删除提醒"""
    success = context_engine.delete_reminder(reminder_id)
    if not success:
        return ApiResponse.error(code=404, message="提醒不存在")
    return ApiResponse.success(message="提醒删除成功")


@router.post("/reminders/{reminder_id}/complete")
async def complete_reminder(
    reminder_id: str,
    current_user: dict = Depends(get_current_user)
):
    """标记提醒为已完成"""
    success = context_engine.complete_reminder(reminder_id)
    if not success:
        return ApiResponse.error(code=404, message="提醒不存在")
    return ApiResponse.success(message="提醒已完成")


@router.post("/reminders/{reminder_id}/snooze")
async def snooze_reminder(
    reminder_id: str,
    request: SnoozeRequest,
    current_user: dict = Depends(get_current_user)
):
    """延后提醒"""
    success = context_engine.snooze_reminder(reminder_id, request.minutes)
    if not success:
        return ApiResponse.error(code=404, message="提醒不存在")
    return ApiResponse.success(message=f"提醒已延后 {request.minutes} 分钟")


@router.post("/reminders/{reminder_id}/cancel")
async def cancel_reminder(
    reminder_id: str,
    current_user: dict = Depends(get_current_user)
):
    """取消提醒"""
    success = context_engine.cancel_reminder(reminder_id)
    if not success:
        return ApiResponse.error(code=404, message="提醒不存在")
    return ApiResponse.success(message="提醒已取消")


# ==================== 情景感知接口 ====================

@router.get("/context")
async def get_context(current_user: dict = Depends(get_current_user)):
    """获取当前情景"""
    ctx = context_engine.get_context()
    return ApiResponse.success(data={
        "timestamp": ctx.timestamp,
        "hour": ctx.hour,
        "weekday": ctx.weekday,
        "is_weekend": ctx.is_weekend,
        "time_of_day": ctx.time_of_day,
        "time_of_day_name": _get_time_of_day_name(ctx.time_of_day),
        "device_active": ctx.device_active,
        "battery_level": ctx.battery_level,
        "is_charging": ctx.is_charging,
        "user_active": ctx.user_active,
        "location": ctx.location,
    })


@router.get("/upcoming")
async def get_upcoming_reminders(
    limit: int = 10,
    current_user: dict = Depends(get_current_user)
):
    """获取即将到来的提醒"""
    upcoming = context_engine.get_upcoming_reminders(limit)
    return ApiResponse.success(data={
        "total": len(upcoming),
        "items": upcoming,
    })


@router.get("/daily-summary")
async def get_daily_summary(current_user: dict = Depends(get_current_user)):
    """获取今日提醒摘要"""
    summary = context_engine.get_daily_summary()
    return ApiResponse.success(data=summary)


@router.get("/stats")
async def get_reminder_stats(current_user: dict = Depends(get_current_user)):
    """获取提醒统计"""
    stats = context_engine.get_stats()
    return ApiResponse.success(data=stats)


# ==================== 快捷创建接口 ====================

@router.post("/quick/once")
async def create_once_reminder(
    title: str,
    trigger_time: float,
    description: str = "",
    priority: str = ReminderPriority.NORMAL.value,
    current_user: dict = Depends(get_current_user)
):
    """快捷创建一次性提醒"""
    reminder = context_engine.add_reminder(
        title=title,
        description=description,
        reminder_type=ReminderType.ONCE.value,
        priority=priority,
        trigger_time=trigger_time,
    )
    return ApiResponse.success(
        message="提醒创建成功",
        data=reminder.to_dict()
    )


@router.post("/quick/daily")
async def create_daily_reminder(
    title: str,
    time: str,  # "HH:MM" 格式
    description: str = "",
    priority: str = ReminderPriority.NORMAL.value,
    current_user: dict = Depends(get_current_user)
):
    """快捷创建每日提醒"""
    reminder = context_engine.add_reminder(
        title=title,
        description=description,
        reminder_type=ReminderType.DAILY.value,
        priority=priority,
        repeat_time=time,
    )
    return ApiResponse.success(
        message="每日提醒创建成功",
        data=reminder.to_dict()
    )


@router.post("/quick/weekly")
async def create_weekly_reminder(
    title: str,
    time: str,  # "HH:MM" 格式
    days: List[int],  # 0-6 周一到周日
    description: str = "",
    priority: str = ReminderPriority.NORMAL.value,
    current_user: dict = Depends(get_current_user)
):
    """快捷创建每周提醒"""
    reminder = context_engine.add_reminder(
        title=title,
        description=description,
        reminder_type=ReminderType.WEEKLY.value,
        priority=priority,
        repeat_time=time,
        repeat_days=days,
    )
    return ApiResponse.success(
        message="每周提醒创建成功",
        data=reminder.to_dict()
    )


# ==================== 枚举接口 ====================

@router.get("/meta/types")
async def get_reminder_types(current_user: dict = Depends(get_current_user)):
    """获取提醒类型列表"""
    types = [
        {"id": t.value, "name": _get_type_name(t.value), "description": _get_type_desc(t.value)}
        for t in ReminderType
    ]
    return ApiResponse.success(data=types)


@router.get("/meta/priorities")
async def get_priorities(current_user: dict = Depends(get_current_user)):
    """获取优先级列表"""
    priorities = [
        {"id": p.value, "name": _get_priority_name(p.value), "level": i}
        for i, p in enumerate(ReminderPriority)
    ]
    return ApiResponse.success(data=priorities)


@router.get("/meta/statuses")
async def get_statuses(current_user: dict = Depends(get_current_user)):
    """获取状态列表"""
    statuses = [
        {"id": s.value, "name": _get_status_name(s.value)}
        for s in ReminderStatus
    ]
    return ApiResponse.success(data=statuses)


# ==================== 辅助函数 ====================

def _get_time_of_day_name(time_of_day: str) -> str:
    """获取时段中文名"""
    names = {
        "morning": "早晨",
        "afternoon": "下午",
        "evening": "傍晚",
        "night": "深夜",
    }
    return names.get(time_of_day, time_of_day)


def _get_type_name(rtype: str) -> str:
    """获取类型中文名"""
    names = {
        "once": "一次性",
        "daily": "每日",
        "weekly": "每周",
        "monthly": "每月",
        "conditional": "条件触发",
    }
    return names.get(rtype, rtype)


def _get_type_desc(rtype: str) -> str:
    """获取类型描述"""
    descs = {
        "once": "只提醒一次，指定具体时间",
        "daily": "每天同一时间提醒",
        "weekly": "每周选定日期同一时间提醒",
        "monthly": "每月同一天同一时间提醒",
        "conditional": "满足特定条件时触发提醒",
    }
    return descs.get(rtype, "")


def _get_priority_name(priority: str) -> str:
    """获取优先级中文名"""
    names = {
        "low": "低",
        "normal": "普通",
        "high": "高",
        "urgent": "紧急",
    }
    return names.get(priority, priority)


def _get_status_name(status: str) -> str:
    """获取状态中文名"""
    names = {
        "pending": "待触发",
        "triggered": "已触发",
        "snoozed": "已延后",
        "completed": "已完成",
        "cancelled": "已取消",
    }
    return names.get(status, status)
