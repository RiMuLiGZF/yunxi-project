"""M7 积木平台 - 触发器管理路由.

提供触发器的 CRUD API 和 Webhook 端点。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ..models import ApiResponse
from ..services.trigger_manager import (
    TriggerType,
    get_trigger_manager,
)
from ..m8_api.m8_auth_middleware import get_current_user


router = APIRouter(tags=["触发器"])

_trigger_mgr = get_trigger_manager()


# ============================================================
# 请求/响应模型
# ============================================================

class TriggerCreateRequest(BaseModel):
    """创建触发器请求."""
    name: str
    workflow_id: str
    trigger_type: str = Field(default="schedule", description="触发器类型: schedule/webhook/event")
    description: str = ""
    config: dict = Field(default_factory=dict, description="触发器配置")
    input_mapping: dict = Field(default_factory=dict, description="输入映射")
    filter_config: dict = Field(default_factory=dict, description="事件过滤配置")
    enabled: bool = False
    timezone: str = "Asia/Shanghai"


class TriggerUpdateRequest(BaseModel):
    """更新触发器请求."""
    name: Optional[str] = None
    description: Optional[str] = None
    config: Optional[dict] = None
    input_mapping: Optional[dict] = None
    filter_config: Optional[dict] = None
    enabled: Optional[bool] = None
    timezone: Optional[str] = None


# ============================================================
# 触发器 CRUD
# ============================================================

@router.get("/api/v1/triggers")
async def list_triggers(
    request: Request,
    workflow_id: Optional[str] = Query(default=None, description="工作流 ID 过滤"),
    trigger_type: Optional[str] = Query(default=None, description="触发器类型过滤"),
    enabled: Optional[bool] = Query(default=None, description="启用状态过滤"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
    current_user: dict = Depends(get_current_user),
):
    """获取触发器列表."""
    result = _trigger_mgr.repo.list_triggers(
        workflow_id=workflow_id,
        trigger_type=trigger_type,
        enabled=enabled,
        page=page,
        page_size=page_size,
    )
    return ApiResponse.success(
        data=result,
        request_id=request.headers.get("X-Request-ID", ""),
    )


@router.post("/api/v1/triggers")
async def create_trigger(
    request: Request,
    body: TriggerCreateRequest,
    current_user: dict = Depends(get_current_user),
):
    """创建触发器."""
    # 验证触发器类型
    if body.trigger_type not in TriggerType.ALL:
        return ApiResponse.error(
            code=400,
            message=f"不支持的触发器类型: {body.trigger_type}，支持: {', '.join(TriggerType.ALL)}",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    # 验证配置
    valid, msg = _validate_trigger_config(body.trigger_type, body.config)
    if not valid:
        return ApiResponse.error(
            code=400,
            message=msg,
            request_id=request.headers.get("X-Request-ID", ""),
        )

    try:
        trigger = _trigger_mgr.create_trigger(
            name=body.name,
            workflow_id=body.workflow_id,
            trigger_type=body.trigger_type,
            description=body.description,
            config=body.config,
            input_mapping=body.input_mapping,
            filter_config=body.filter_config,
            enabled=body.enabled,
            timezone=body.timezone,
            created_by=current_user.get("user_id", ""),
        )
        return ApiResponse.success(
            data=trigger,
            message="触发器创建成功",
            request_id=request.headers.get("X-Request-ID", ""),
        )
    except Exception as e:
        return ApiResponse.error(
            code=500,
            message=f"创建触发器失败: {e}",
            request_id=request.headers.get("X-Request-ID", ""),
        )


@router.get("/api/v1/triggers/{trigger_id}")
async def get_trigger(
    request: Request,
    trigger_id: str,
    current_user: dict = Depends(get_current_user),
):
    """获取触发器详情."""
    trigger = _trigger_mgr.repo.get_trigger(trigger_id)
    if not trigger:
        return ApiResponse.error(
            code=404,
            message=f"触发器 {trigger_id} 不存在",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    # 补充调度信息
    if trigger.get("trigger_type") == TriggerType.SCHEDULE:
        schedule_info = _trigger_mgr.scheduler.get_schedule_info(trigger_id)
        trigger["next_run_time"] = schedule_info.get("next_run_time")

    return ApiResponse.success(
        data=trigger,
        request_id=request.headers.get("X-Request-ID", ""),
    )


@router.put("/api/v1/triggers/{trigger_id}")
async def update_trigger(
    request: Request,
    trigger_id: str,
    body: TriggerUpdateRequest,
    current_user: dict = Depends(get_current_user),
):
    """更新触发器."""
    trigger = _trigger_mgr.repo.get_trigger(trigger_id)
    if not trigger:
        return ApiResponse.error(
            code=404,
            message=f"触发器 {trigger_id} 不存在",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    # 构建更新字段
    update_data = {k: v for k, v in body.model_dump().items() if v is not None}

    # 验证配置（如果有更新）
    if "config" in update_data:
        valid, msg = _validate_trigger_config(trigger["trigger_type"], update_data["config"])
        if not valid:
            return ApiResponse.error(
                code=400,
                message=msg,
                request_id=request.headers.get("X-Request-ID", ""),
            )

    success = _trigger_mgr.update_trigger(trigger_id, **update_data)
    if success:
        updated = _trigger_mgr.repo.get_trigger(trigger_id)
        return ApiResponse.success(
            data=updated,
            message="触发器更新成功",
            request_id=request.headers.get("X-Request-ID", ""),
        )
    else:
        return ApiResponse.error(
            code=500,
            message="更新触发器失败",
            request_id=request.headers.get("X-Request-ID", ""),
        )


@router.delete("/api/v1/triggers/{trigger_id}")
async def delete_trigger(
    request: Request,
    trigger_id: str,
    current_user: dict = Depends(get_current_user),
):
    """删除触发器."""
    success = _trigger_mgr.delete_trigger(trigger_id)
    if success:
        return ApiResponse.success(
            message="触发器删除成功",
            data={"trigger_id": trigger_id},
            request_id=request.headers.get("X-Request-ID", ""),
        )
    else:
        return ApiResponse.error(
            code=404,
            message=f"触发器 {trigger_id} 不存在",
            request_id=request.headers.get("X-Request-ID", ""),
        )


# ============================================================
# 启用/禁用
# ============================================================

@router.post("/api/v1/triggers/{trigger_id}/enable")
async def enable_trigger(
    request: Request,
    trigger_id: str,
    current_user: dict = Depends(get_current_user),
):
    """启用触发器."""
    trigger = _trigger_mgr.repo.get_trigger(trigger_id)
    if not trigger:
        return ApiResponse.error(
            code=404,
            message=f"触发器 {trigger_id} 不存在",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    success = _trigger_mgr.enable_trigger(trigger_id)
    if success:
        return ApiResponse.success(
            message="触发器已启用",
            data={"trigger_id": trigger_id, "enabled": True},
            request_id=request.headers.get("X-Request-ID", ""),
        )
    else:
        return ApiResponse.error(
            code=500,
            message="启用触发器失败",
            request_id=request.headers.get("X-Request-ID", ""),
        )


@router.post("/api/v1/triggers/{trigger_id}/disable")
async def disable_trigger(
    request: Request,
    trigger_id: str,
    current_user: dict = Depends(get_current_user),
):
    """禁用触发器."""
    trigger = _trigger_mgr.repo.get_trigger(trigger_id)
    if not trigger:
        return ApiResponse.error(
            code=404,
            message=f"触发器 {trigger_id} 不存在",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    success = _trigger_mgr.disable_trigger(trigger_id)
    if success:
        return ApiResponse.success(
            message="触发器已禁用",
            data={"trigger_id": trigger_id, "enabled": False},
            request_id=request.headers.get("X-Request-ID", ""),
        )
    else:
        return ApiResponse.error(
            code=500,
            message="禁用触发器失败",
            request_id=request.headers.get("X-Request-ID", ""),
        )


# ============================================================
# 触发历史
# ============================================================

@router.get("/api/v1/triggers/{trigger_id}/history")
async def get_trigger_history(
    request: Request,
    trigger_id: str,
    status: Optional[str] = Query(default=None, description="状态过滤"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
    current_user: dict = Depends(get_current_user),
):
    """获取触发器的触发历史."""
    trigger = _trigger_mgr.repo.get_trigger(trigger_id)
    if not trigger:
        return ApiResponse.error(
            code=404,
            message=f"触发器 {trigger_id} 不存在",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    result = _trigger_mgr.repo.list_history(
        trigger_id=trigger_id,
        status=status,
        page=page,
        page_size=page_size,
    )
    return ApiResponse.success(
        data=result,
        request_id=request.headers.get("X-Request-ID", ""),
    )


# ============================================================
# Webhook 端点
# ============================================================

@router.post("/api/v1/webhook/{trigger_path}")
async def webhook_endpoint(
    request: Request,
    trigger_path: str,
):
    """Webhook 触发端点.

    公开端点，通过路径和签名验证识别触发器。
    不需要认证中间件（外部系统调用）。
    """
    body = await request.body()
    headers = dict(request.headers)

    # 构建完整路径
    full_path = f"/webhook/trig_{trigger_path}" if not trigger_path.startswith("trig_") else f"/webhook/{trigger_path}"

    # 处理 webhook
    result = _trigger_mgr.handle_webhook(full_path, body, headers)

    if result.get("success"):
        return {
            "code": 0,
            "message": result.get("message", "Webhook 已接收"),
            "data": {
                "trigger_id": result.get("trigger_id"),
                "workflow_id": result.get("workflow_id"),
            },
        }
    else:
        raise HTTPException(
            status_code=400,
            detail=result.get("error", "Webhook 处理失败"),
        )


# ============================================================
# 触发器统计
# ============================================================

@router.get("/api/v1/triggers/stats/summary")
async def trigger_stats(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """获取触发器统计概览."""
    all_triggers = _trigger_mgr.repo.list_triggers(page=1, page_size=1000)

    total = all_triggers["total"]
    by_type = {}
    by_status = {"enabled": 0, "disabled": 0}

    for t in all_triggers["items"]:
        ttype = t.get("trigger_type", "unknown")
        by_type[ttype] = by_type.get(ttype, 0) + 1
        if t.get("enabled"):
            by_status["enabled"] += 1
        else:
            by_status["disabled"] += 1

    return ApiResponse.success(
        data={
            "total": total,
            "by_type": by_type,
            "by_status": by_status,
            "scheduler_running": _trigger_mgr.scheduler.running,
        },
        request_id=request.headers.get("X-Request-ID", ""),
    )


# ============================================================
# 辅助函数
# ============================================================

def _validate_trigger_config(trigger_type: str, config: dict) -> tuple[bool, str]:
    """验证触发器配置.

    Returns:
        (是否有效, 错误信息)
    """
    if trigger_type == TriggerType.SCHEDULE:
        schedule_type = config.get("schedule_type", "cron")
        if schedule_type == "cron":
            cron_expr = config.get("cron_expression", "")
            if not cron_expr:
                return False, "缺少 cron_expression 配置"
            from ..services.trigger_manager import SimpleCronParser
            if not SimpleCronParser.is_valid(cron_expr):
                return False, f"无效的 Cron 表达式: {cron_expr}"
        elif schedule_type == "interval":
            interval = config.get("interval_seconds", 0)
            if interval <= 0:
                return False, "interval_seconds 必须大于 0"
        elif schedule_type == "one_time":
            if not config.get("run_at"):
                return False, "one_time 类型需要配置 run_at"
        else:
            return False, f"不支持的 schedule_type: {schedule_type}"

    elif trigger_type == TriggerType.EVENT:
        if not config.get("event_type"):
            return False, "Event 触发器需要配置 event_type"

    return True, ""
